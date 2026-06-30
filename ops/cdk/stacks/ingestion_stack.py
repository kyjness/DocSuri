"""ECS Fargate — deploy unit ② (ingestion worker) + SQS + EventBridge schedule.

infra-design.md §2 (worker) + §3 (EventBridge) + §4 (S3)."""

from aws_cdk import (
    Duration,
    RemovalPolicy,
    Stack,
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
    aws_events as events,
)
from aws_cdk import (
    aws_events_targets as targets,
)
from aws_cdk import (
    aws_iam as iam,
)
from aws_cdk import (
    aws_opensearchservice as opensearch,
)
from aws_cdk import (
    aws_s3 as s3,
)
from aws_cdk import (
    aws_secretsmanager as secretsmanager,
)
from aws_cdk import (
    aws_sqs as sqs,
)
from constructs import Construct

# Bedrock text-embedding model for the worker (Cohere Embed v4, 1024-dim — matches the
# discovery/search side). cohere.embed-v4:0 is NOT invokable on-demand by its bare id; it must
# go through the global cross-region inference profile. The adapter pins output_dimension to the
# 1024-dim spec (embed-v4 defaults to 1536). v2 dual-write targets the same profile so the
# backfilled docsuri-corpus-v2 is a clean, uniform v4 rebuild.
_BEDROCK_FOUNDATION_MODEL = "cohere.embed-v4:0"
_BEDROCK_MODEL_ID = "global.cohere.embed-v4:0"  # inference profile id (used for InvokeModel)

# Existing control-plane RDS (created by Docsuri-Compute) referenced by concrete id rather than
# a CFN cross-stack import. Importing compute's L2 construct would force a compute redeploy, which
# regenerates the per-synth X-Origin-Verify secret and briefly 403s the live API during CloudFront
# propagation. RDS is RemovalPolicy.RETAIN so these ids are stable.
# ponytail: hardcoded infra ids; only revisit if the RDS instance or its secret is recreated.
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
# Semantic Scholar API key (x-api-key) for the corpus harvest — created out-of-band in Secrets
# Manager; referenced by full ARN so the worker (and daily tick) authenticate SS. Plain-string
# secret (no JSON field). ponytail: hardcoded id, revisit only if the secret is recreated.
_SS_API_KEY_SECRET_ARN = (
    "arn:aws:secretsmanager:ap-northeast-2:028317349537:secret:"
    "docsuri/semantic-scholar-api-key-ExoKCk"
)


class IngestionStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        vpc: ec2.IVpc,
        opensearch_domain: opensearch.IDomain,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # --- ECR (already created manually; import by name) ---
        self.repo = ecr.Repository.from_repository_name(self, "IngestionRepo", "docsuri-ingestion")

        # --- SQS: ingestion queue + DLQ (infra-design §2.3) ---
        dlq = sqs.Queue(
            self, "IngestionDlq",
            queue_name="docsuri-ingestion-dlq",
            retention_period=Duration.days(14),
            encryption=sqs.QueueEncryption.SQS_MANAGED,
        )
        self.queue = sqs.Queue(
            self, "IngestionQueue",
            queue_name="docsuri-ingestion-queue",
            visibility_timeout=Duration.seconds(300),
            retention_period=Duration.days(14),
            encryption=sqs.QueueEncryption.SQS_MANAGED,
            dead_letter_queue=sqs.DeadLetterQueue(max_receive_count=3, queue=dlq),
        )

        # --- S3: full-text storage (infra-design §4) ---
        self.bucket = s3.Bucket(
            self, "FulltextBucket",
            bucket_name=f"docsuri-papers-fulltext-{Stack.of(self).account}",
            versioned=True,
            encryption=s3.BucketEncryption.S3_MANAGED,
            intelligent_tiering_configurations=[
                s3.IntelligentTieringConfiguration(
                    name="archive-cold",
                    archive_access_tier_time=Duration.days(180),
                    deep_archive_access_tier_time=Duration.days(365),
                ),
            ],
            removal_policy=RemovalPolicy.RETAIN,
        )

        # --- EventBridge: daily arXiv schedule (infra-design §3.1) ---
        events.Rule(
            self, "ArxivDailySchedule",
            rule_name="docsuri-arxiv-daily",
            schedule=events.Schedule.cron(hour="6", minute="0"),  # 06:00 UTC = 15:00 KST
            targets=[
                targets.SqsQueue(
                    self.queue,
                    message=events.RuleTargetInput.from_object(
                        {"type": "schedule_tick"}
                    ),
                )
            ],
        )

        # --- ECS Fargate: ingestion worker (0.5 vCPU / 1 GB, SQS polling) ---
        cluster = ecs.Cluster.from_cluster_attributes(
            self, "Cluster", cluster_name="docsuri", vpc=vpc,
            security_groups=[],
        )
        # grobid/grobid:0.8.0 is the full deep-learning image (~20GB extracted, bundles
        # TensorFlow) — the 20GB Fargate default ephemeral storage overflows on pull
        # (CannotPullContainerError: no space left on device). Bump disk to fit it, and RAM
        # so GROBID has headroom alongside the worker.
        task_def = ecs.FargateTaskDefinition(
            self, "WorkerTaskDef",
            cpu=2048,
            memory_limit_mib=8192,
            ephemeral_storage_gib=80,
        )

        # Control-plane DSN WITHOUT the password — libpq reads PGPASSWORD (injected as a secret
        # below) for any field absent from the conninfo. Keeps the DB credential out of the
        # plaintext task-def env, mirroring how the API injects DB_PASSWORD.
        control_plane_dsn = f"postgresql://docsuri_admin@{_RDS_ENDPOINT}:{_RDS_PORT}/docsuri"
        db_secret = secretsmanager.Secret.from_secret_complete_arn(
            self, "DbSecret", _RDS_SECRET_ARN
        )
        ss_api_key_secret = secretsmanager.Secret.from_secret_complete_arn(
            self, "SsApiKeySecret", _SS_API_KEY_SECRET_ARN
        )

        task_def.add_container(
            "grobid",
            image=ecs.ContainerImage.from_registry("grobid/grobid:0.8.0"),
            logging=ecs.LogDrivers.aws_logs(stream_prefix="grobid"),
            essential=False,
            port_mappings=[ecs.PortMapping(container_port=8070)],
        )

        task_def.add_container(
            "worker",
            image=ecs.ContainerImage.from_ecr_repository(self.repo, tag="latest"),
            logging=ecs.LogDrivers.aws_logs(stream_prefix="ingestion"),
            environment={
                "DOCSURI_ENV": "production",
                "DOCSURI_AWS_REGION": self.region,
                "DOCSURI_S3_BUCKET": self.bucket.bucket_name,
                "DOCSURI_BEDROCK_MODEL_ID": _BEDROCK_MODEL_ID,
                "DOCSURI_OPENSEARCH_ENDPOINT": f"https://{opensearch_domain.domain_endpoint}",
                # Post-v4-cutover: live search reads alias docsuri-corpus -> v2, so the worker
                # must write to v2. v1 is the retired pre-migration index; dual-write scaffolding
                # (bedrock_model_id_v2) stays unset now the migration is done.
                "DOCSURI_OPENSEARCH_INDEX": "docsuri-corpus-v2",
                "DOCSURI_OPENSEARCH_ALIAS": "docsuri-corpus",
                # SS/OpenAlex re-enabled after fixing the SS bulk-search 400 (commit c7bd065d)
                # and adding per-source isolation to on_schedule_tick — a bad source now logs +
                # skips instead of crashing the worker. Watermarks seeded to now(), so the daily
                # tick harvests only forward deltas; a real SS/OpenAlex corpus needs a separate
                # bounded backfill (DOCSURI_BACKFILL_START/END), not enabled here.
                "DOCSURI_CORPUS_SOURCES": "ARXIV,SEMANTIC_SCHOLAR,OPENALEX",
                "DOCSURI_GROBID_URL": "http://127.0.0.1:8070",
                "DOCSURI_OPENSEARCH_INDEX_V2": "docsuri-corpus-v2",
                "DOCSURI_CONTROL_PLANE_DSN": control_plane_dsn,
                "DOCSURI_SQS_QUEUE_URL": self.queue.queue_url,
                "DOCSURI_SQS_DLQ_URL": dlq.queue_url,
                # FR-17 multimodal figure/table assets ON (Pillow/pypdfium2/pdfplumber baked
                # into the image via the [assets] extra).
                "DOCSURI_MULTIMODAL_ASSETS_ENABLED": "true",
            },
            secrets={
                "PGPASSWORD": ecs.Secret.from_secrets_manager(db_secret, "password"),
                # SS API key → x-api-key header (settings.semantic_scholar_api_key). Injecting it
                # here also grants the execution role read on the secret, so the daily tick + any
                # CDK-managed task is authed (the manual :13 revision used for the one-off backfill
                # is outside CDK and superseded once this deploys).
                "DOCSURI_SEMANTIC_SCHOLAR_API_KEY": ecs.Secret.from_secrets_manager(
                    ss_api_key_secret
                ),
            },
        )

        self.service = ecs.FargateService(
            self, "WorkerService",
            service_name="docsuri-ingestion",
            cluster=cluster,
            task_definition=task_def,
            desired_count=0,  # scale-to-zero at rest
            assign_public_ip=True,  # NAT-free: public subnet + IGW
            circuit_breaker=ecs.DeploymentCircuitBreaker(rollback=True),
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
        )

        # Autoscaling: min 0 — max 3 (SQS-driven step scaling)
        from aws_cdk import aws_applicationautoscaling as appscaling

        scaling = self.service.auto_scale_task_count(min_capacity=0, max_capacity=3)
        scaling.scale_on_metric(
            "SqsDepth",
            metric=self.queue.metric_approximate_number_of_messages_visible(),
            scaling_steps=[
                appscaling.ScalingInterval(upper=0, change=0),
                appscaling.ScalingInterval(lower=10, change=1),
                appscaling.ScalingInterval(lower=50, change=2),
            ],
            adjustment_type=appscaling.AdjustmentType.CHANGE_IN_CAPACITY,
        )

        # SG: worker → OpenSearch (HTTPS) + RDS (Postgres). Egress is added on the worker side;
        # the RDS SG is imported by id (mutable) so the ingress rule lands in THIS stack — no
        # change to the compute stack that owns it.
        self.service.connections.allow_to(opensearch_domain.connections, ec2.Port.tcp(443))
        rds_sg = ec2.SecurityGroup.from_security_group_id(
            self, "RdsSg", _RDS_SECURITY_GROUP_ID, mutable=True
        )
        self.service.connections.allow_to(rds_sg, ec2.Port.tcp(_RDS_PORT))

        # Grant SQS consume + S3 read/write + Bedrock embed-model invoke to the task role
        self.queue.grant_consume_messages(task_def.task_role)
        # The worker also PRODUCES to the main queue — on_schedule_tick / backfill_external /
        # trigger_full_rebuild all send_job onto it. grant_consume_messages alone (receive/delete)
        # left SendMessage as an implicitDeny, so every worker-side enqueue failed with a botocore
        # ClientError. Grant send too.
        self.queue.grant_send_messages(task_def.task_role)
        dlq.grant_send_messages(task_def.task_role)
        self.bucket.grant_read_write(task_def.task_role)
        task_def.add_to_task_role_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel"],
                resources=[
                    # Invocation goes through the global inference profile, which can route to
                    # the foundation model in any region — grant both.
                    f"arn:aws:bedrock:{self.region}:{self.account}:inference-profile/{_BEDROCK_MODEL_ID}",
                    f"arn:aws:bedrock:*::foundation-model/{_BEDROCK_FOUNDATION_MODEL}",
                ],
            )
        )
