"""ECS Fargate — deploy unit ④ (summarization worker) + SQS summary-job queue.

infra-design §2.3 (summary queue) + §2.4 (worker, deploy unit ④). Long-input summaries
(map-reduce, BR-S6/BR-S12) run here as a background job: the API enqueues onto
``docsuri-summary-job-queue`` and the worker (this stack) consumes, runs map-reduce inline
(no gateway timeout), and write-throughs the result to ``summaries/`` in the papers bucket so the
client's poll hits the cache. Reuses the ``docsuri-api`` image with the worker entrypoint.

NOTE: code/synth only — deploy is owned by the team. The worker carries the real summarization
config (bucket + map-reduce gate ON + DB) since it IS the summarization deploy unit; the live API
stays unchanged until separately activated.
"""

from aws_cdk import (
    Duration,
    Stack,
)
from aws_cdk import (
    aws_applicationautoscaling as appscaling,
)
from aws_cdk import (
    aws_cloudwatch as cloudwatch,
)
from aws_cdk import (
    aws_cloudwatch_actions as cw_actions,
)
from aws_cdk import (
    aws_ec2 as ec2,
)
from aws_cdk import (
    aws_ecr as ecr,
)
from aws_cdk import (
    aws_ecs as ecs,
)
from aws_cdk import (
    aws_iam as iam,
)
from aws_cdk import (
    aws_logs as logs,
)
from aws_cdk import (
    aws_secretsmanager as secretsmanager,
)
from aws_cdk import (
    aws_sns as sns,
)
from aws_cdk import (
    aws_sns_subscriptions as subs,
)
from aws_cdk import (
    aws_sqs as sqs,
)
from constructs import Construct

# Existing control-plane RDS (created by Docsuri-Compute) referenced by concrete id rather than a
# CFN cross-stack import (RETAIN → stable ids; avoids forcing a compute redeploy). Mirrors
# ingestion_stack — the glossary repo reads PGPASSWORD for the password field absent from the DSN.
_RDS_ENDPOINT = (
    "docsuri-compute-postgres9dc8bb04-7ajkntsj0ouu"
    ".cpegcaqmu01d.ap-northeast-2.rds.amazonaws.com"
)
_RDS_PORT = 5432
_RDS_SECURITY_GROUP_ID = "sg-0633ac0c0b8c7a052"
_RDS_SECRET_ARN = (
    "arn:aws:secretsmanager:ap-northeast-2:028317349537:secret:"
    "DocsuriComputePostgresSecre-9qclXydED0pl-30WA1V"
)


class SummarizationStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        vpc: ec2.IVpc,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        _DEFAULT_OPS_ALERT_EMAIL = "corpseonthemission@icloud.com"
        _ctx_alert_emails = self.node.try_get_context("ops_alert_email")
        _raw_alert_emails = (
            _DEFAULT_OPS_ALERT_EMAIL if _ctx_alert_emails is None else _ctx_alert_emails
        )
        ops_alert_emails = [e.strip() for e in _raw_alert_emails.split(",") if e.strip()]

        account = Stack.of(self).account
        papers_bucket_arn = f"arn:aws:s3:::docsuri-papers-fulltext-{account}"

        # --- SQS: summary-job queue + DLQ (infra-design §2.3) ---
        dlq = sqs.Queue(
            self, "SummaryJobDlq",
            queue_name="docsuri-summary-job-dlq",
            retention_period=Duration.days(14),
            encryption=sqs.QueueEncryption.SQS_MANAGED,
        )
        self.queue = sqs.Queue(
            self, "SummaryJobQueue",
            queue_name="docsuri-summary-job-queue",
            visibility_timeout=Duration.seconds(900),  # 15 min — map-reduce N+1 LLM calls
            retention_period=Duration.days(14),
            encryption=sqs.QueueEncryption.SQS_MANAGED,
            dead_letter_queue=sqs.DeadLetterQueue(max_receive_count=3, queue=dlq),
        )
        ops_alerts = sns.Topic(self, "OpsAlerts", display_name="docsuri-summary-ops-alerts")
        for email in ops_alert_emails:
            ops_alerts.add_subscription(subs.EmailSubscription(email))
        summary_age_alarm = self.queue.metric_approximate_age_of_oldest_message(
            period=Duration.minutes(5),
            statistic="Maximum",
        ).create_alarm(
            self,
            "SummaryQueueAgeAlarm",
            threshold=900,
            evaluation_periods=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
            alarm_description="Summary jobs are waiting more than 15 minutes before processing",
        )
        summary_age_alarm.add_alarm_action(cw_actions.SnsAction(ops_alerts))

        # --- ECS Fargate: summary worker (reuses the docsuri-api image, worker entrypoint) ---
        repo = ecr.Repository.from_repository_name(self, "ApiRepo", "docsuri-api")
        cluster = ecs.Cluster.from_cluster_attributes(
            self, "Cluster", cluster_name="docsuri", vpc=vpc, security_groups=[],
        )
        task_def = ecs.FargateTaskDefinition(self, "WorkerTaskDef", cpu=512, memory_limit_mib=1024)

        # DSN WITHOUT the password — libpq reads PGPASSWORD (secret below) for the absent field.
        database_url = f"postgresql://docsuri_admin@{_RDS_ENDPOINT}:{_RDS_PORT}/docsuri"
        db_secret = secretsmanager.Secret.from_secret_complete_arn(
            self, "DbSecret", _RDS_SECRET_ARN
        )

        task_def.add_container(
            "worker",
            image=ecs.ContainerImage.from_ecr_repository(repo, tag="latest"),
            command=["python", "-m", "summarization.worker"],
            logging=ecs.LogDrivers.aws_logs(stream_prefix="summary-worker"),
            environment={
                "AWS_DEFAULT_REGION": self.region,
                # The worker IS the summarization deploy unit → carries the real config.
                "DOCSURI_SUMMARY_BUCKET": f"docsuri-papers-fulltext-{account}",
                "DOCSURI_SUMMARY_JOB_QUEUE_URL": self.queue.queue_url,
                "DOCSURI_MAP_REDUCE_ENABLED": "true",  # worker must hold the map-reduce summarizer
                # Full-text translation runs on THIS worker and must read the structured doc-model;
                # without this flag the reader is unwired and translation degrades to a plain-text
                # head-only fallback. Mirrors the API service flag (compute stack).
                "DOCSURI_DOCMODEL_VIEWER_ENABLED": "true",
                "DATABASE_URL": database_url,  # personal glossary (no Redis — S3-only store here)
                "CLOUDWATCH_NAMESPACE": "DocSuri/Production",
                "CLOUDWATCH_LOG_GROUP": "/docsuri/ops",
            },
            secrets={"PGPASSWORD": ecs.Secret.from_secrets_manager(db_secret, "password")},
        )
        ops_log_group = logs.LogGroup.from_log_group_name(self, "OpsLogGroup", "/docsuri/ops")
        ops_log_group.grant_write(task_def.task_role)
        task_def.add_to_task_role_policy(
            iam.PolicyStatement(
                actions=["cloudwatch:PutMetricData"],
                resources=["*"],
                conditions={"StringEquals": {"cloudwatch:namespace": "DocSuri/Production"}},
            )
        )

        self.service = ecs.FargateService(
            self, "WorkerService",
            service_name="docsuri-summary-worker",
            cluster=cluster,
            task_definition=task_def,
            desired_count=0,  # scale-to-zero at rest
            assign_public_ip=True,  # NAT-free: public subnet + IGW
            circuit_breaker=ecs.DeploymentCircuitBreaker(rollback=True),
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
        )

        # Autoscaling: min 0 — max 2 (SQS-driven)
        scaling = self.service.auto_scale_task_count(min_capacity=0, max_capacity=2)
        scaling.scale_on_metric(
            "SqsDepth",
            metric=self.queue.metric_approximate_number_of_messages_visible(),
            scaling_steps=[
                appscaling.ScalingInterval(upper=0, change=0),
                appscaling.ScalingInterval(lower=1, change=1),
                appscaling.ScalingInterval(lower=10, change=2),
            ],
            adjustment_type=appscaling.AdjustmentType.CHANGE_IN_CAPACITY,
        )

        # SG: worker → RDS (Postgres). RDS SG imported by id (mutable) so the ingress lands here.
        rds_sg = ec2.SecurityGroup.from_security_group_id(
            self, "RdsSg", _RDS_SECURITY_GROUP_ID, mutable=True
        )
        self.service.connections.allow_to(rds_sg, ec2.Port.tcp(_RDS_PORT))

        # --- IAM: SQS consume + S3 (doc-model read · summary write) + Bedrock ---
        self.queue.grant_consume_messages(task_def.task_role)
        dlq.grant_send_messages(task_def.task_role)
        task_def.add_to_task_role_policy(
            iam.PolicyStatement(
                actions=["s3:GetObject"], resources=[f"{papers_bucket_arn}/doc-model/*"],
            )
        )
        # Full-text source (S3FullTextSource reads full-text/{paperId}/v{n}.txt). The worker payload
        # carries only paperId/version/abstract, so the worker re-reads the body from S3; with the
        # doc-model viewer off here that full-text read is its only real input source. Without this
        # the read hits AccessDenied, which the source-selector swallows into a silent degrade to
        # abstract — long async summaries quietly stop working. Mirrors the API task role.
        task_def.add_to_task_role_policy(
            iam.PolicyStatement(
                actions=["s3:GetObject"], resources=[f"{papers_bucket_arn}/full-text/*"],
            )
        )
        task_def.add_to_task_role_policy(
            iam.PolicyStatement(
                actions=["s3:GetObject", "s3:PutObject"],
                # Store writes under ``summaries/`` (plural — SummaryCacheKey.object_path,
                # infra-design §2.1); grant must match or the worker's cache write-through hits
                # AccessDenied (put is uncaught → async summary fails, nothing cached). Mirror of
                # the API task role in compute_stack. Was ``summary/`` (typo).
                resources=[f"{papers_bucket_arn}/summaries/*"],
            )
        )
        task_def.add_to_task_role_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
                resources=[
                    f"arn:aws:bedrock:{self.region}::foundation-model/anthropic.*",
                    f"arn:aws:bedrock:{self.region}:{account}:inference-profile/*",
                ],
            )
        )
