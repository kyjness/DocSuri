"""U11 evidence formation agent worker infrastructure.

Code/synth only; deploy remains a team-controlled operation.
The unit is activated when DOCSURI_EVIDENCE_ASYNC_ENABLED=true and
DOCSURI_DOCMODEL_BUCKET is configured.
"""

from aws_cdk import Duration, Stack
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


class EvidenceStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        vpc: ec2.IVpc,
        db: rds.DatabaseInstance,
        opensearch_domain: opensearch.IDomain,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        account = Stack.of(self).account
        # NoveltyStack과 동일 패턴 — 팀원별 -c evidence_db_*/evidence_docmodel_bucket 문자열
        # context를 손으로 넘겨야 했던 구조를 db construct 참조로 대체. 이전에는 이 값들이
        # 없으면 app.py 로드 자체가 실패해 Network/Compute 등 다른 스택 배포까지 막았다
        # (PR #338 리뷰 Blocking #8).
        docmodel_bucket = f'docsuri-papers-fulltext-{account}'

        dlq = sqs.Queue(
            self,
            'EvidenceJobDlq',
            queue_name='docsuri-evidence-agent-job-dlq',
            retention_period=Duration.days(14),
            encryption=sqs.QueueEncryption.SQS_MANAGED,
        )
        self.queue = sqs.Queue(
            self,
            'EvidenceJobQueue',
            queue_name='docsuri-evidence-agent-job-queue',
            # 15분: Bedrock 추출 + DocModel 로딩 여유 (NFR-P6)
            visibility_timeout=Duration.seconds(900),
            retention_period=Duration.days(14),
            encryption=sqs.QueueEncryption.SQS_MANAGED,
            dead_letter_queue=sqs.DeadLetterQueue(max_receive_count=3, queue=dlq),
        )

        repo = ecr.Repository.from_repository_name(self, 'ApiRepo', 'docsuri-api')
        cluster = ecs.Cluster.from_cluster_attributes(
            self,
            'Cluster',
            cluster_name='docsuri',
            vpc=vpc,
            security_groups=[],
        )
        task_def = ecs.FargateTaskDefinition(
            self, 'WorkerTaskDef', cpu=512, memory_limit_mib=1024
        )

        assert db.secret is not None
        database_url = (
            f'postgresql://docsuri_admin@{db.db_instance_endpoint_address}:'
            f'{db.db_instance_endpoint_port}/docsuri'
        )

        task_def.add_container(
            'worker',
            image=ecs.ContainerImage.from_ecr_repository(repo, tag='latest'),
            command=['python', '-m', 'backend.modules.evidence.worker'],
            logging=ecs.LogDrivers.aws_logs(stream_prefix='evidence-worker'),
            environment={
                'AWS_DEFAULT_REGION': self.region,
                'DATABASE_URL': database_url,
                'EVIDENCE_AGENT_ENABLED': 'true',
                'DOCSURI_EVIDENCE_ASYNC_ENABLED': 'true',
                'DOCSURI_EVIDENCE_JOB_QUEUE_URL': self.queue.queue_url,
                'DOCSURI_DOCMODEL_BUCKET': docmodel_bucket,
                # U2 discovery 재사용 검색 경로 활성화에 필수 — 없으면 hosts=[None]으로
                # OpenSearch 클라이언트가 만들어져 검색이 전부 실패한다(PR #338 리뷰 Blocking #6).
                'DOCSURI_OPENSEARCH_ENDPOINT': f'https://{opensearch_domain.domain_endpoint}',
                'CLOUDWATCH_NAMESPACE': 'DocSuri/Production',
                'CLOUDWATCH_LOG_GROUP': '/docsuri/ops',
            },
            secrets={'PGPASSWORD': ecs.Secret.from_secrets_manager(db.secret, 'password')},
        )

        self.service = ecs.FargateService(
            self,
            'WorkerService',
            service_name='docsuri-evidence-agent-worker',
            cluster=cluster,
            task_definition=task_def,
            desired_count=0,
            assign_public_ip=True,
            circuit_breaker=ecs.DeploymentCircuitBreaker(rollback=True),
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
        )

        scaling = self.service.auto_scale_task_count(min_capacity=0, max_capacity=2)
        scaling.scale_on_metric(
            'SqsDepth',
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
            'RdsSg',
            db.connections.security_groups[0].security_group_id,
            mutable=True,
        )
        self.service.connections.allow_to(rds_sg, ec2.Port.tcp(5432))
        # worker → OpenSearch 도메인 보안그룹 경로. 없으면 VPC PRIVATE_ISOLATED + SG 제한 하에서
        # TCP 연결 자체가 timeout된다(PR #338 리뷰 Blocking #7).
        self.service.connections.allow_to(opensearch_domain.connections, ec2.Port.tcp(443))

        self.queue.grant_consume_messages(task_def.task_role)
        dlq.grant_send_messages(task_def.task_role)

        # S3 DocModel 읽기 (U1 소유 버킷 — GetObject only)
        task_def.add_to_task_role_policy(
            iam.PolicyStatement(
                actions=['s3:GetObject'],
                resources=[f'arn:aws:s3:::{docmodel_bucket}/doc-model/*'],
            )
        )
        # ListBucket 없이 GetObject만 있으면 미빌드 키가 403(AccessDenied)으로 반환되어
        # S3DocModelReader의 _MISS_CODES(404/NoSuchKey)에 안 걸리고 re-raise된다 — 정상적인
        # "아직 안 만들어진 doc-model" 상황이 job 실패로 처리됨(PR #338 리뷰 Medium #13,
        # compute_stack.py는 이미 동일한 이유로 이 권한을 부여하고 있음).
        task_def.add_to_task_role_policy(
            iam.PolicyStatement(
                actions=['s3:ListBucket'],
                resources=[f'arn:aws:s3:::{docmodel_bucket}'],
            )
        )
        # Bedrock 추론 (claude-sonnet-4-6 inference profile)
        task_def.add_to_task_role_policy(
            iam.PolicyStatement(
                actions=['bedrock:InvokeModel', 'bedrock:InvokeModelWithResponseStream'],
                resources=[
                    f'arn:aws:bedrock:{self.region}::foundation-model/anthropic.*',
                    f'arn:aws:bedrock:{self.region}:{account}:inference-profile/*',
                ],
            )
        )
        # OpenSearch (U2 재사용) — discovery 설정 ENV로 주입됨. 실제 도메인 ARN을 그대로
        # 참조한다 — 하드코딩된 도메인명(docsuri)이 실제 도메인(docsuri-papers)과 달라
        # AccessDenied가 나던 문제를 NoveltyStack과 동일한 패턴으로 수정(PR #338 리뷰 Blocking #5).
        task_def.add_to_task_role_policy(
            iam.PolicyStatement(
                actions=['es:ESHttpGet', 'es:ESHttpPost'],
                resources=[f'{opensearch_domain.domain_arn}/*'],
            )
        )

        dlq.metric_approximate_number_of_messages_visible().create_alarm(
            self,
            'EvidenceDlqAlarm',
            threshold=0,
            evaluation_periods=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
            alarm_description='Evidence agent worker messages are landing in the DLQ',
        )
