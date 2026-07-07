"""U11 novelty-agent worker infrastructure.

Code/synth only; deploy remains a team-controlled operation. The unit is activated by
deployment configuration, not by a later manual toggle: NOVELTY_AGENT_ENABLED is always true.
"""

from aws_cdk import Duration, RemovalPolicy, Stack
from aws_cdk import aws_applicationautoscaling as appscaling
from aws_cdk import aws_cloudwatch as cloudwatch
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecr as ecr
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_iam as iam
from aws_cdk import aws_opensearchservice as opensearch
from aws_cdk import aws_rds as rds
from aws_cdk import aws_sqs as sqs
from constructs import Construct


class NoveltyStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        vpc: ec2.IVpc,
        db: rds.DatabaseInstance,
        queue: sqs.IQueue,
        opensearch_domain: opensearch.IDomain,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        account = Stack.of(self).account
        artifact_bucket_arn = f"arn:aws:s3:::docsuri-papers-fulltext-{account}"
        # ponytail: keep ownership in this stack until a real CDK import migration moves it.
        # Removing these resources from the template makes CloudFormation delete the live queue.
        dlq = sqs.Queue(
            self,
            "NoveltyJobDlq",
            queue_name="docsuri-novelty-agent-job-dlq",
            retention_period=Duration.days(14),
            encryption=sqs.QueueEncryption.SQS_MANAGED,
        )
        dlq.apply_removal_policy(RemovalPolicy.RETAIN)
        self.queue = sqs.Queue(
            self,
            "NoveltyJobQueue",
            queue_name="docsuri-novelty-agent-job-queue",
            visibility_timeout=Duration.seconds(900),
            retention_period=Duration.days(14),
            encryption=sqs.QueueEncryption.SQS_MANAGED,
            dead_letter_queue=sqs.DeadLetterQueue(max_receive_count=3, queue=dlq),
        )
        self.queue.apply_removal_policy(RemovalPolicy.RETAIN)
        dlq.metric_approximate_number_of_messages_visible().create_alarm(
            self,
            "NoveltyDlqAlarm",
            threshold=0,
            evaluation_periods=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
            alarm_description="Novelty agent worker messages are landing in the DLQ",
        )
        queue = self.queue

        repo = ecr.Repository.from_repository_name(self, "ApiRepo", "docsuri-api")
        cluster = ecs.Cluster.from_cluster_attributes(
            self,
            "Cluster",
            cluster_name="docsuri",
            vpc=vpc,
            security_groups=[],
        )
        task_def = ecs.FargateTaskDefinition(self, "WorkerTaskDef", cpu=512, memory_limit_mib=1024)

        database_url = (
            f"postgresql://docsuri_admin@{db.db_instance_endpoint_address}:"
            f"{db.db_instance_endpoint_port}/docsuri"
        )
        assert db.secret is not None

        task_def.add_container(
            "worker",
            image=ecs.ContainerImage.from_ecr_repository(repo, tag="latest"),
            command=["python", "-m", "backend.modules.novelty.worker"],
            logging=ecs.LogDrivers.aws_logs(stream_prefix="novelty-worker"),
            environment={
                "AWS_DEFAULT_REGION": self.region,
                "DATABASE_URL": database_url,
                "NOVELTY_AGENT_ENABLED": "true",
                "DOCSURI_NOVELTY_JOB_QUEUE_URL": queue.queue_url,
                "DOCSURI_NOVELTY_ARTIFACT_BUCKET": f"docsuri-papers-fulltext-{account}",
                "DOCSURI_NOVELTY_ARTIFACT_PREFIX": "novelty/",
                "DOCSURI_DOCMODEL_BUCKET": f"docsuri-papers-fulltext-{account}",
                "DOCSURI_DOCMODEL_BUILD_QUEUE_URL": (
                    f"https://sqs.{self.region}.amazonaws.com/{account}/docsuri-docmodel-queue"
                ),
                # User-PDF (manuscript) doc-model build → GROBID Option B queue, preferred by the
                # coordinator factory over the shared queue above so novelty manuscripts get
                # structured TEI. Referenced by name (Ingestion owns it); SendMessage granted below.
                "DOCSURI_USERDOC_BUILD_QUEUE_URL": (
                    f"https://sqs.{self.region}.amazonaws.com/{account}/docsuri-userdoc-queue"
                ),
                "DOCSURI_OPENSEARCH_ENDPOINT": f"https://{opensearch_domain.domain_endpoint}",
                "DOCSURI_BEDROCK_MODEL_ID": "global.cohere.embed-v4:0",
                "DOCSURI_NOVELTY_LLM_MODEL_ID": "global.anthropic.claude-sonnet-4-6",
                "DOCSURI_AWS_REGION": self.region,
                "CLOUDWATCH_NAMESPACE": "DocSuri/Production",
                "CLOUDWATCH_LOG_GROUP": "/docsuri/ops",
            },
            secrets={"PGPASSWORD": ecs.Secret.from_secrets_manager(db.secret, "password")},
        )

        self.service = ecs.FargateService(
            self,
            "WorkerService",
            service_name="docsuri-novelty-agent-worker",
            cluster=cluster,
            task_definition=task_def,
            desired_count=0,
            assign_public_ip=True,
            circuit_breaker=ecs.DeploymentCircuitBreaker(rollback=True),
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
        )

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

        rds_sg = ec2.SecurityGroup.from_security_group_id(
            self,
            "RdsSg",
            db.connections.security_groups[0].security_group_id,
            mutable=True,
        )
        self.service.connections.allow_to(rds_sg, ec2.Port.tcp(5432))
        self.service.connections.allow_to(opensearch_domain.connections, ec2.Port.tcp(443))

        queue.grant_consume_messages(task_def.task_role)
        queue.grant_send_messages(task_def.task_role)
        task_def.add_to_task_role_policy(
            iam.PolicyStatement(
                actions=["s3:GetObject", "s3:PutObject"],
                resources=[f"{artifact_bucket_arn}/novelty/*"],
            )
        )
        task_def.add_to_task_role_policy(
            iam.PolicyStatement(
                actions=["s3:GetObject"],
                resources=[f"{artifact_bucket_arn}/doc-model/*"],
            )
        )
        # ListBucket 없이 GetObject만 있으면 아직 안 만들어진 doc-model 키가 404가 아니라
        # 403(AccessDenied)으로 반환되어 S3DocModelReader의 _MISS_CODES(404/NoSuchKey)에 안 걸리고
        # re-raise → evidence 파이프라인이 트레이스백 폭풍(프로덕션 novelty 워커 152건/10분 관측).
        # evidence_stack / compute_stack는 이미 동일 이유로 이 권한을 부여 중.
        task_def.add_to_task_role_policy(
            iam.PolicyStatement(
                actions=["s3:ListBucket"],
                resources=[artifact_bucket_arn],
            )
        )
        task_def.add_to_task_role_policy(
            iam.PolicyStatement(
                actions=["sqs:SendMessage"],
                resources=[
                    f"arn:aws:sqs:{self.region}:{account}:docsuri-docmodel-queue",
                    # User-PDF (manuscript) build queue (GROBID Option B), enqueued via
                    # DOCSURI_USERDOC_BUILD_QUEUE_URL above.
                    f"arn:aws:sqs:{self.region}:{account}:docsuri-userdoc-queue",
                ],
            )
        )
        task_def.add_to_task_role_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
                resources=[
                    "arn:aws:bedrock:::foundation-model/anthropic.*",
                    "arn:aws:bedrock:*::foundation-model/anthropic.*",
                    "arn:aws:bedrock:::foundation-model/cohere.embed-v4:0",
                    "arn:aws:bedrock:*::foundation-model/cohere.embed-v4:0",
                    f"arn:aws:bedrock:{self.region}:{account}:inference-profile/*",
                ],
            )
        )
        task_def.add_to_task_role_policy(
            iam.PolicyStatement(
                actions=[
                    "es:ESHttpGet",
                    "es:ESHttpHead",
                    "es:ESHttpPost",
                ],
                resources=[f"{opensearch_domain.domain_arn}/*"],
            )
        )
        ops_log_group_arn = (
            f"arn:aws:logs:{self.region}:{account}:log-group:/docsuri/ops"
        )
        task_def.task_role.add_to_principal_policy(
            iam.PolicyStatement(
                actions=["cloudwatch:PutMetricData"],
                resources=["*"],
                conditions={"StringEquals": {"cloudwatch:namespace": "DocSuri/Production"}},
            )
        )
        task_def.task_role.add_to_principal_policy(
            iam.PolicyStatement(
                actions=["logs:CreateLogGroup"],
                resources=[ops_log_group_arn],
            )
        )
        task_def.task_role.add_to_principal_policy(
            iam.PolicyStatement(
                actions=["logs:CreateLogStream", "logs:DescribeLogStreams", "logs:PutLogEvents"],
                resources=[f"{ops_log_group_arn}:*"],
            )
        )
