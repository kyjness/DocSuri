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
                # U11 실시간 조회(설계 v3 §3.2) — arXiv·Semantic Scholar·OpenAlex. **기본은
                # off다**: 켜면 턴마다 코퍼스 밖으로 나가는 호출이 생기므로 켜는 것은 결정이다.
                # 앞선 `external_search`(arXiv 하나)는 이 자리에도 `.env.example`에도 플래그가
                # 없어 배포에서 한 번도 돈 적이 없다 — 코드에만 있고 아무도 그 사실을 몰랐다.
                'DOCSURI_EVIDENCE_LIVE_LOOKUP_ENABLED': 'false',
                # 실시간 조회로 찾은 논문의 백그라운드 색인(§2.6 4단계) — U1 **본** 큐다.
                # 승격이 쓰는 우선순위 큐가 아니다: 그쪽은 사용자가 기다리는 본문 확보용이라
                # 색인 잡을 섞으면 기다리는 쪽이 밀린다. Ingestion이 큐를 소유하므로 이름으로
                # 참조한다(저장소 패턴 — 크로스 스택 export를 만들지 않는다).
                'DOCSURI_SQS_QUEUE_URL': (
                    f'https://sqs.{self.region}.amazonaws.com/{account}/docsuri-ingestion-queue'
                ),
                # U2 discovery 재사용 검색 경로 활성화에 필수 — 없으면 hosts=[None]으로
                # OpenSearch 클라이언트가 만들어져 검색이 전부 실패한다(PR #338 리뷰 Blocking #6).
                'DOCSURI_OPENSEARCH_ENDPOINT': f'https://{opensearch_domain.domain_endpoint}',
                # **네 값이 한 벌이다.** 엔드포인트만 주고 나머지를 빼 두면 `search_enabled`가
                # False라 코퍼스 검색의 **벡터 leg가 통째로 off**가 된다 — 이 워커가 배포된 내내
                # BM25만으로 코퍼스를 검색하고 있었고, 임베딩 호출 실패가 lexical-only 저하로
                # 흡수돼 어디에도 남지 않았다(2026-10-06 발견). 리더는 writer와 **같은 공간**을
                # 써야 하므로 값은 compute_stack의 리더·ingestion_stack의 writer와 동일해야
                # 한다(vector-spec §4) — 세 자리가 갈리면 질의가 다른 공간에서 채점된다.
                'DOCSURI_BEDROCK_MODEL_ID': 'cohere.embed-multilingual-v3',
                'DOCSURI_OPENSEARCH_INDEX': 'docsuri-corpus-c3ml',
                # v3는 ap-northeast-2(도메인 리전)에 없어 질의 임베딩은 크로스리전이다.
                'DOCSURI_BEDROCK_REGION': 'ap-northeast-1',
                'DOCSURI_AWS_REGION': self.region,
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
        # 백그라운드 색인 enqueue(§2.6 4단계) — Ingestion 소유 큐라 ARN을 이름으로 짓는다
        # (크로스 스택 export를 만들지 않는 저장소 패턴). 이 권한이 없으면 색인 요청이
        # AccessDenied로 조용히 삼켜지고(어댑터가 best-effort다) 코퍼스는 안 자란다.
        task_def.add_to_task_role_policy(
            iam.PolicyStatement(
                actions=['sqs:SendMessage'],
                resources=[f'arn:aws:sqs:{self.region}:{account}:docsuri-ingestion-queue'],
            )
        )

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
        # U2 리더 질의 임베딩 — **위의 anthropic 정책이 이것을 덮지 않는다.** 그쪽은
        # `{self.region}`의 `anthropic.*`이고, 질의 임베딩은 ap-northeast-1의 Cohere다.
        # 이것이 없으면 embed가 AccessDenied → EmbeddingUnavailable → lexical-only 저하로
        # 흡수돼, 벡터 leg가 꺼진 채로도 검색이 "그냥 결과가 적은" 모양으로 돈다.
        # 자원 목록은 compute_stack의 리더 정책과 **같은 벌**이어야 한다(같은 공간·같은 모델).
        task_def.add_to_task_role_policy(
            iam.PolicyStatement(
                actions=['bedrock:InvokeModel'],
                resources=[
                    'arn:aws:bedrock:*::foundation-model/cohere.embed-multilingual-v3',
                    # v4 롤백 대비(compute_stack과 동일) — 모델 id를 v4로 되돌릴 때 쓴다.
                    f'arn:aws:bedrock:{self.region}:{account}:inference-profile/global.cohere.embed-v4:0',
                    'arn:aws:bedrock:*::foundation-model/cohere.embed-v4:0',
                ],
            )
        )
        # U2 리더 cross-encoder 재랭킹(FR-3). 리랭크 모델은 이 리전(서울)에 없어 크로스리전
        # (도쿄)으로 호출하므로 리전 와일드카드다 — compute_stack의 API 태스크와 같은 벌.
        # **활성화는 `DOCSURI_RERANK_MODEL_ARN`(도쿄 ARN) 하나**이고 그 값은 코드가 아니라
        # 운영이 넣는다(compute_stack도 ENV에 두지 않는다). 권한만 있고 ARN이 없으면
        # reranker=None으로 baseline RRF — 안전한 무동작이다.
        task_def.add_to_task_role_policy(
            iam.PolicyStatement(
                actions=['bedrock:Rerank'],
                resources=[
                    'arn:aws:bedrock:*::foundation-model/cohere.rerank-v3-5:0',
                    'arn:aws:bedrock:*::foundation-model/amazon.rerank-v1:0',
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
