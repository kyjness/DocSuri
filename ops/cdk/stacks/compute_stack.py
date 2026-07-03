"""ECS Fargate — deploy unit ① (API modular monolith) + ALB + RDS + Redis.

infra-design.md §6 (API compute) + U3 infrastructure-design (RDS/Redis/ALB)."""

from aws_cdk import (
    CfnOutput,
    Duration,
    Fn,
    RemovalPolicy,
    Stack,
)
from aws_cdk import (
    aws_budgets as budgets,
)
from aws_cdk import (
    aws_certificatemanager as acm,
)
from aws_cdk import (
    aws_cloudfront as cloudfront,
)
from aws_cdk import (
    aws_cloudfront_origins as origins,
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
    aws_ecs_patterns as ecs_patterns,
)
from aws_cdk import (
    aws_elasticache as elasticache,
)
from aws_cdk import (
    aws_elasticloadbalancingv2 as elbv2,
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
    aws_logs as logs,
)
from aws_cdk import (
    aws_opensearchservice as opensearch,
)
from aws_cdk import (
    aws_rds as rds,
)
from aws_cdk import (
    aws_route53 as route53,
)
from aws_cdk import (
    aws_secretsmanager as secretsmanager,
)
from aws_cdk import (
    aws_ses as ses,
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

from ._origin_auth import api_origin_verify_secret, social_origin_verify_secret

# Public DNS for the API origin (zone docsuri.org lives in this account's Route53). CloudFront
# connects to this name over HTTPS so the ACM cert (issued for it) validates — ACM can't issue
# for the ALB's *.elb.amazonaws.com name, so a controlled domain is mandatory for origin TLS.
_ORIGIN_DOMAIN = "origin.docsuri.org"
_ZONE_NAME = "docsuri.org"
_ZONE_ID = "Z0084324NUV4EPLJ7JH9"

class ComputeStack(Stack):
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

        # X-Origin-Verify secrets (api: ApiCdn→ALB; social: shared w/ frontend's /auth/social/*
        # edge). Read from SSM at deploy time so synth is deterministic — see ._origin_auth.
        origin_verify = api_origin_verify_secret(self)
        social_verify = social_origin_verify_secret(self)

        # Ops alert recipients — comma-separated so adding teammates later is a deploy-arg change,
        # not a code change: `cdk deploy -c ops_alert_email=a@x.com,b@y.com` (or cdk.json context).
        # Defaults to the team ops inbox so a context-less deploy can't silently DROP the email
        # subscriptions + budget — a full `cdk deploy --all` without -c did exactly that, tearing
        # down alerting. Pass -c to change recipients; pass `-c ops_alert_email=` (empty) to
        # opt out.
        _DEFAULT_OPS_ALERT_EMAIL = "corpseonthemission@icloud.com"
        _ctx_alert_emails = self.node.try_get_context("ops_alert_email")
        _raw_alert_emails = (
            _DEFAULT_OPS_ALERT_EMAIL if _ctx_alert_emails is None else _ctx_alert_emails
        )
        ops_alert_emails = [e.strip() for e in _raw_alert_emails.split(",") if e.strip()]

        # --- ECR repository (already created manually; import by name) ---
        self.api_repo = ecr.Repository.from_repository_name(self, "ApiRepo", "docsuri-api")

        # --- ECS cluster ---
        cluster = ecs.Cluster(self, "Cluster", cluster_name="docsuri", vpc=vpc)

        # --- RDS PostgreSQL (U3 spec: db.t4g.small Multi-AZ, 20 GB gp3) ---
        self.db = rds.DatabaseInstance(
            self, "Postgres",
            engine=rds.DatabaseInstanceEngine.postgres(version=rds.PostgresEngineVersion.VER_16),
            instance_type=ec2.InstanceType.of(ec2.InstanceClass.T4G, ec2.InstanceSize.SMALL),
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_ISOLATED),
            multi_az=True,
            allocated_storage=20,
            storage_type=rds.StorageType.GP3,
            backup_retention=Duration.days(7),
            deletion_protection=True,
            removal_policy=RemovalPolicy.RETAIN,
            credentials=rds.Credentials.from_generated_secret("docsuri_admin"),
            database_name="docsuri",
        )

        # ponytail: queues already exist in prod; import them until a separate CDK import migrates
        # ownership. Creating same-name queues in this stack would fail the next Compute deploy.
        novelty_dlq = sqs.Queue.from_queue_attributes(
            self,
            "NoveltyJobDlq",
            queue_arn=f"arn:aws:sqs:{self.region}:{self.account}:docsuri-novelty-agent-job-dlq",
            queue_url=f"https://sqs.{self.region}.amazonaws.com/{self.account}/docsuri-novelty-agent-job-dlq",
        )
        self.novelty_queue = sqs.Queue.from_queue_attributes(
            self,
            "NoveltyJobQueue",
            queue_arn=f"arn:aws:sqs:{self.region}:{self.account}:docsuri-novelty-agent-job-queue",
            queue_url=f"https://sqs.{self.region}.amazonaws.com/{self.account}/docsuri-novelty-agent-job-queue",
        )
        novelty_dlq_visible_metric = novelty_dlq.metric_approximate_number_of_messages_visible()
        novelty_dlq_alarm = novelty_dlq_visible_metric.create_alarm(
            self,
            "NoveltyDlqAlarm",
            threshold=0,
            evaluation_periods=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
            alarm_description="Novelty agent worker messages are landing in the DLQ",
        )

        # --- ElastiCache Redis (U3 spec: cache.t4g.micro, 2-node Multi-AZ) ---
        redis_sg = ec2.SecurityGroup(self, "RedisSg", vpc=vpc, allow_all_outbound=False)
        isolated_subnets = vpc.select_subnets(subnet_type=ec2.SubnetType.PRIVATE_ISOLATED)
        redis_subnet_group = elasticache.CfnSubnetGroup(
            self, "RedisSubnetGroup",
            description="Redis isolated subnets",
            subnet_ids=isolated_subnets.subnet_ids,
        )
        self.redis = elasticache.CfnReplicationGroup(
            self, "Redis",
            replication_group_description="docsuri-session-store",
            engine="redis",
            engine_version="7.1",
            cache_node_type="cache.t4g.micro",
            num_cache_clusters=2,  # primary + replica (Multi-AZ)
            multi_az_enabled=True,
            automatic_failover_enabled=True,
            cache_subnet_group_name=redis_subnet_group.ref,
            security_group_ids=[redis_sg.security_group_id],
            at_rest_encryption_enabled=True,
            transit_encryption_enabled=True,
        )

        # --- Environment variables for the API container ---
        # backend/config.py assembles DATABASE_URL from DB_HOST/PORT/NAME/USER + DB_PASSWORD
        # (the password arrives via Secrets Manager — see `secrets=` below, never plain env).
        # The app self-migrates the accounts+library schema on startup (RUN_MIGRATIONS_ON_STARTUP
        # defaults on for Postgres), so a fresh RDS is provisioned on first deploy.
        redis_endpoint = self.redis.attr_primary_end_point_address
        redis_port = self.redis.attr_primary_end_point_port

        container_env = {
            "ENV": "production",
            # Activate CloudWatch observability. backend/app.py _build_observability() ships metrics
            # to CloudWatch only when CLOUDWATCH_NAMESPACE is set — without it the app silently uses
            # the in-memory store and NO prod metrics flow. This one line is what gives the SLO
            # alarms below data to alarm on.
            "CLOUDWATCH_NAMESPACE": "DocSuri/Production",
            "CLOUDWATCH_LOG_GROUP": "/docsuri/ops",
            "DB_HOST": self.db.db_instance_endpoint_address,
            "DB_PORT": self.db.db_instance_endpoint_port,
            "DB_NAME": "docsuri",
            "DB_USER": "docsuri_admin",  # matches rds.Credentials.from_generated_secret above
            "REDIS_HOST": redis_endpoint,
            "REDIS_PORT": redis_port,
            "REDIS_TLS": "1",  # ElastiCache transit_encryption_enabled=True → client TLS required
            # CloudFront -> ALB -> ECS: trust the two controlled proxy hops so gateway
            # rate-limiting keys on the viewer IP instead of collapsing all traffic to a proxy.
            "TRUST_PROXY_HEADERS": "true",
            "TRUSTED_PROXY_COUNT": "2",
            # Blanket gateway backstop. Endpoint-specific account/email limits remain stricter;
            # this cap must not trip the checked-in 20-VU production smoke load test.
            "DOCSURI_GATEWAY_RATE_LIMIT_MAX_REQUESTS": "3000",
            "DOCSURI_GATEWAY_RATE_LIMIT_WINDOW_SECONDS": "60",
            "SES_SENDER_EMAIL": "no-reply@docsuri.org",  # via the SES domain identity below
            # Email provider toggle. "resend" → ResendEmailClient (no SES sandbox review gate;
            # delivers to any recipient once docsuri.org is DNS-verified in Resend). Requires the
            # RESEND_API_KEY secret below. If the key is missing the app falls back to SES.
            "EMAIL_PROVIDER": "resend",
            # Public apex used to build clickable verification links in emails. Behind
            # CloudFront/BFF/ALB the request host is internal, so the link must use this
            # public URL pointing at the frontend verify page (controller._verification_link_base
            # → {PUBLIC_APP_URL}/verify-email), which calls the backend via the BFF. Must match
            # the CloudFront alias.
            "PUBLIC_APP_URL": "https://docsuri.org",
            "OPENSEARCH_ENDPOINT": Fn.join("", [
                "https://", opensearch_domain.domain_endpoint,
            ]),
            # U2 discovery reader real-path wiring. DiscoverySettings.from_env reads the
            # DOCSURI_-prefixed names, and search_enabled requires BOTH the endpoint AND the
            # model — without these the reader silently falls back to the mock orchestrator.
            # The model MUST match the writer's (Cohere v4) so query and corpus share one
            # embedding space (vector-spec §4). Index defaults to the docsuri-corpus alias.
            "DOCSURI_OPENSEARCH_ENDPOINT": Fn.join("", [
                "https://", opensearch_domain.domain_endpoint,
            ]),
            "DOCSURI_BEDROCK_MODEL_ID": "global.cohere.embed-v4:0",
            "DOCSURI_AWS_REGION": self.region,
            # --- U7 summarization + doc-model (피벗) — queue URLs (deploy-ready config) ---
            # The IAM below is provisioned ahead of activation. ACTIVATION is a deploy-time step the
            # team owns: set DOCSURI_SUMMARY_BUCKET (papers bucket) + DATABASE_URL(+PGPASSWORD) [+
            # DOCSURI_REDIS_URL] to mount the real path (summarization_enabled = bool(bucket)); the
            # OA-license + map-reduce gates stay OFF by default. Referenced by name to avoid a
            # cross-stack export coupling deploys (repo pattern).
            "DOCSURI_DOCMODEL_BUILD_QUEUE_URL": (
                # doc-model lazy build (BR-30, boundary B) → dedicated PRIORITY queue, isolated from
                # the bulk ingestion/backfill queue so reader-triggered builds (viewer/citation
                # tree) are not starved behind a large backfill. Worker drains this queue first.
                f"https://sqs.{self.region}.amazonaws.com/{self.account}/docsuri-docmodel-queue"
            ),
            "DOCSURI_SUMMARY_JOB_QUEUE_URL": (  # long-summary async job (BR-S12)
                f"https://sqs.{self.region}.amazonaws.com/{self.account}/docsuri-summary-job-queue"
            ),
            "DOCSURI_NOVELTY_JOB_QUEUE_URL": self.novelty_queue.queue_url,
            # Activation: mounting the U7 read path (summarization_enabled = bool(bucket)). The
            # papers bucket is Ingestion-owned (same name the summary worker carries); the IAM for
            # S3 read/write + Bedrock invoke is already granted to this task role below.
            "DOCSURI_SUMMARY_BUCKET": f"docsuri-papers-fulltext-{self.account}",
            "DOCSURI_NOVELTY_ARTIFACT_BUCKET": f"docsuri-papers-fulltext-{self.account}",
            "DOCSURI_NOVELTY_ARTIFACT_PREFIX": "novelty/",
            # doc-model rich view (본문): on a read miss the API enqueues a BUILD_DOC_MODEL job to
            # the ingestion queue (DOCSURI_DOCMODEL_BUILD_QUEUE_URL above) and returns `building`;
            # the ingestion worker builds + caches it. OFF → license_unavailable.
            "DOCSURI_DOCMODEL_VIEWER_ENABLED": "true",
            # Figure/table images (본문 그림): the API presigns the S3 assets written by ingestion
            # (which already sets this flag) and joins them to the doc-model FigureBlocks by
            # assetId. Only OA papers are stored so rendering is license-safe (BR-SF-11). Without
            # this the /assets manifest returns license_unavailable and figures never render even
            # though the webp objects exist in S3.
            "DOCSURI_MULTIMODAL_ASSETS_ENABLED": "true",
            # Long-input summaries: map-reduce band enqueues to the summary-job queue (async worker)
            # and returns `pending`; without this the MAP_REDUCE band abstains (input_too_long).
            "DOCSURI_MAP_REDUCE_ENABLED": "true",
            "CITATION_GRAPH_ENABLED": "true",
            "PERSONALIZATION_ENABLED": "true",
            # Research is intentionally enabled in prod; keep this aligned with the live flag.
            "RESEARCH_AGENT_ENABLED": "true",
            "NOVELTY_AGENT_ENABLED": "true",
            "PERSONALIZATION_RAW_EVENT_RETENTION_DAYS": "90",
            # --- U3 social login (FR-27, Google OIDC) ---
            # client_id is public (embedded in the auth URL) → plain env. The matching
            # GOOGLE_OIDC_CLIENT_SECRET arrives via Secrets Manager (see secrets= below).
            "GOOGLE_OIDC_CLIENT_ID": (
                # 2026-06-25: 이전 클라이언트(…15equ…)가 Google Console에서 삭제됨 → OAuth가
                # "401 deleted_client"로 실패. 새 OAuth 클라이언트로 교체(시크릿도 함께 회전 필요).
                "505093491210-55npim41bgaujn0udfj342p08vk6g8ne.apps.googleusercontent.com"
            ),
            # The browser must land first-party on docsuri.org for the session cookie to stick,
            # so this callback path is routed to the backend by a CloudFront behavior on the
            # frontend distribution (frontend_stack: /auth/social/* → backend origin — TODO).
            "GOOGLE_OIDC_REDIRECT_URI": "https://docsuri.org/auth/social/google/callback",
            # --- U3 social login (FR-27/BR-A13, ORCID OIDC) ---
            # ORCID OIDC는 이메일을 반환하지 않아 email=NULL 계정을 만든다(BR-A13). client_id는
            # 공개값(plain env); 미설정이면 토큰 교환이 Fail-Closed로 실패해 ORCID 로그인만 비활성
            # (Google/이메일 로그인은 영향 없음). 활성화: `cdk deploy -c orcid_oidc_client_id=APP-…
            # -c orcid_oidc_secret_arn=<완전ARN>` (ORCID Developer Tools에서 클라이언트 등록 후).
            "ORCID_OIDC_CLIENT_ID": self.node.try_get_context("orcid_oidc_client_id") or "",
            "ORCID_OIDC_REDIRECT_URI": "https://docsuri.org/auth/social/orcid/callback",
            "ORCID_OIDC_ENV": self.node.try_get_context("orcid_oidc_env") or "prod",
            # --- U3 account deletion cascade (FR-28/BR-A11) ---
            # AccountDeletedPublisher puts events here; subscribers (U4/U2/U11) attach bus rules.
            # Unset → app falls back to the Logging publisher (no real fan-out).
            "ACCOUNT_EVENTS_BUS": "docsuri-account-events",
        }

        # DB password injected from the RDS-generated secret (JSON key "password"); CDK grants
        # the task EXECUTION role read on the secret automatically for this.
        assert self.db.secret is not None  # from_generated_secret always creates one
        container_secrets = {
            "DB_PASSWORD": ecs.Secret.from_secrets_manager(self.db.secret, "password"),
        }
        # Resend API key for transactional email (EMAIL_PROVIDER=resend). Referenced by name —
        # the secret "docsuri/resend-api-key" (raw key as the secret value) MUST be created in
        # Secrets Manager BEFORE deploying this stack, or the API task fails to start. CDK grants
        # the task execution role read on it automatically via ecs.Secret.from_secrets_manager.
        resend_secret = secretsmanager.Secret.from_secret_name_v2(
            self, "ResendApiKey", "docsuri/resend-api-key",
        )
        container_secrets["RESEND_API_KEY"] = ecs.Secret.from_secrets_manager(resend_secret)
        # Google OIDC client secret (FR-27). Referenced by COMPLETE ARN, not name:
        # from_secret_name_v2 grants on "<name>-??????" but ECS fetches the partial name ARN — they
        # mismatch, so the task gets AccessDenied and the deploy rolls back (observed). The full ARN
        # makes the grant and the container valueFrom identical to the real secret ARN.
        google_oidc_secret = secretsmanager.Secret.from_secret_complete_arn(
            self,
            "GoogleOidcClientSecret",
            "arn:aws:secretsmanager:ap-northeast-2:028317349537:secret:docsuri/google-oidc-client-secret-lihORg",  # noqa: E501
        )
        container_secrets["GOOGLE_OIDC_CLIENT_SECRET"] = ecs.Secret.from_secrets_manager(
            google_oidc_secret
        )
        # ORCID OIDC client secret (FR-27/BR-A13). Context-gated so deploys keep working before
        # ORCID is registered: only wired when `-c orcid_oidc_secret_arn=<COMPLETE ARN>` is passed
        # (the secret MUST exist in Secrets Manager first). Complete ARN (not name) for the same
        # grant/valueFrom reason documented for the Google secret above.
        orcid_oidc_secret_arn = self.node.try_get_context("orcid_oidc_secret_arn")
        if orcid_oidc_secret_arn:
            orcid_oidc_secret = secretsmanager.Secret.from_secret_complete_arn(
                self, "OrcidOidcClientSecret", orcid_oidc_secret_arn,
            )
            container_secrets["ORCID_OIDC_CLIENT_SECRET"] = ecs.Secret.from_secrets_manager(
                orcid_oidc_secret
            )

        # --- TLS for the origin: Route53 zone + ACM cert for origin.docsuri.org ---
        zone = route53.HostedZone.from_hosted_zone_attributes(
            self, "Zone", hosted_zone_id=_ZONE_ID, zone_name=_ZONE_NAME,
        )
        origin_cert = acm.Certificate(
            self, "OriginCert",
            domain_name=_ORIGIN_DOMAIN,
            validation=acm.CertificateValidation.from_dns(zone),  # auto CNAME in the zone
        )

        # --- SES: verify the docsuri.org domain so the app can send no-reply@docsuri.org ---
        # public_hosted_zone(zone) auto-writes the DKIM CNAMEs into Route53 → no mailbox needed.
        # NOTE: the account is still in the SES sandbox (delivers only to verified recipients);
        # arbitrary signup delivery needs production access (separate AWS request — strengthened by
        # the bounce/complaint handling below).

        # Bounce/complaint handling. The config set (1) auto-adds hard-bounced + complained
        # addresses to the account suppression list so we never re-send to them, and (2) publishes
        # bounce/complaint/reject events to an SNS topic for ops visibility (subscribe via console).
        # Set as the identity's DEFAULT config set → every send from docsuri.org uses it, no
        # per-send code change. This is the automated handling SES production-access review expects.
        ses_events_topic = sns.Topic(self, "SesEventsTopic", display_name="docsuri-ses-events")
        email_config_set = ses.ConfigurationSet(
            self, "EmailConfigSet",
            suppression_reasons=ses.SuppressionReasons.BOUNCES_AND_COMPLAINTS,
        )
        email_config_set.add_event_destination(
            "ToSns",
            destination=ses.EventDestination.sns_topic(ses_events_topic),
            events=[
                ses.EmailSendingEvent.BOUNCE,
                ses.EmailSendingEvent.COMPLAINT,
                ses.EmailSendingEvent.REJECT,
            ],
        )
        ses.EmailIdentity(
            self, "DomainIdentity",
            identity=ses.Identity.public_hosted_zone(zone),
            configuration_set=email_config_set,
        )
        CfnOutput(
            self, "SesEventsTopicArn",
            value=ses_events_topic.topic_arn,
            description="SNS topic for SES bounce/complaint/reject events (subscribe ops here)",
        )
        # Close the SES "no subscriber" gap — wire the ops alias to bounce/complaint events.
        for email in ops_alert_emails:
            ses_events_topic.add_subscription(subs.EmailSubscription(email))

        # --- ALB + Fargate service (deploy unit ①: 1 vCPU / 2 GB, min 2 max 6) ---
        # HTTPS :443 terminated on the ALB with the ACM cert + a Route53 alias (origin.docsuri.org
        # → ALB). CloudFront reaches the origin over HTTPS (below), so edge↔origin is encrypted.
        self.service = ecs_patterns.ApplicationLoadBalancedFargateService(
            self, "ApiService",
            cluster=cluster,
            service_name="docsuri-api",
            cpu=1024,
            memory_limit_mib=2048,
            desired_count=2,
            # ECS Exec (SSM-backed): team assumes DocsuriCrossAccountDev → `aws ecs
            # execute-command` into this task → psql to the private RDS. No EC2 bastion.
            # CDK auto-grants the task role ssmmessages:*. ponytail: shell-in only; a
            # local port-forward to RDS still needs a standing SSM host (small EC2).
            enable_execute_command=True,
            task_image_options=ecs_patterns.ApplicationLoadBalancedTaskImageOptions(
                image=ecs.ContainerImage.from_ecr_repository(self.api_repo, tag="latest"),
                container_port=8000,
                environment=container_env,
                secrets=container_secrets,
            ),
            assign_public_ip=True,  # NAT-free: public subnet + IGW outbound
            public_load_balancer=True,
            protocol=elbv2.ApplicationProtocol.HTTPS,
            certificate=origin_cert,
            domain_name=_ORIGIN_DOMAIN,
            domain_zone=zone,
            # Don't open the listener to 0.0.0.0/0 — the origin is reachable only via CloudFront
            # (prefix list below) AND only with the secret header (rule below).
            open_listener=False,
            circuit_breaker=ecs.DeploymentCircuitBreaker(rollback=True),
            health_check_grace_period=Duration.seconds(60),
        )

        # Lock ALB :443 to CloudFront edge IPs (managed prefix list). NOTE: this list is shared by
        # ALL AWS customers' CloudFront, so it is necessary but NOT sufficient — the secret-header
        # rule below is what proves the request came from OUR distribution (confused-deputy fix).
        # Dedicated SG, NOT the pattern's auto-SG: the list is 45 entries, each counting against the
        # 60-rule SG quota — swapping :80→:443 on one SG transiently holds both (90 > 60) and fails.
        # A separate SG holds only this rule. pl-22a6434b = ...cloudfront.origin-facing.
        cf_origin_sg = ec2.SecurityGroup(
            self, "CloudFrontOriginSg", vpc=vpc, allow_all_outbound=False,
            description="ALB inbound from CloudFront origin-facing prefix list only",
        )
        cf_origin_sg.add_ingress_rule(
            ec2.Peer.prefix_list("pl-22a6434b"), ec2.Port.tcp(443),
            description="CloudFront origin-facing only",
        )
        self.service.load_balancer.add_security_group(cf_origin_sg)

        # Origin authentication: forward to the app ONLY when the secret header our CloudFront
        # injects is present; everything else (direct hits, another account's CloudFront) → 403.
        # The TG health check probes targets directly (not through listener rules), so 403-default
        # does not affect health.
        self.service.listener.add_action(
            "VerifiedOriginOnly",
            priority=1,
            conditions=[
                # Accept the existing backend-CF secret AND the shared social-edge secret
                # (Option A): the frontend CF's /auth/social/* behavior sends the latter. Additive —
                # existing backend BFF-gateway auth is unchanged.
                elbv2.ListenerCondition.http_header(
                    "X-Origin-Verify", [origin_verify, social_verify]
                )
            ],
            action=elbv2.ListenerAction.forward([self.service.target_group]),
        )
        self.service.listener.node.default_child.add_override(
            "Properties.DefaultActions",
            [
                {
                    "Type": "fixed-response",
                    "FixedResponseConfig": {"StatusCode": "403", "ContentType": "text/plain"},
                }
            ],
        )

        # ALB health check: the API serves no `GET /`, so the default `/` probe returns
        # 404 → target marked unhealthy → deployment circuit breaker rolls the stack back.
        self.service.target_group.configure_health_check(path="/readyz")

        # Grant the task role permission to read the RDS secret (for runtime DB connection)
        if self.db.secret:
            self.db.secret.grant_read(self.service.task_definition.task_role)

        # Allow the task to send verification email via SES, scoped to the docsuri.org identity.
        self.service.task_definition.task_role.add_to_principal_policy(
            iam.PolicyStatement(
                actions=["ses:SendEmail", "ses:SendRawEmail"],
                resources=[
                    Stack.of(self).format_arn(
                        service="ses", resource="identity", resource_name=_ZONE_NAME,
                    )
                ],
            )
        )

        # Observability (G3): the app ships METRIC events + structured logs via CLOUDWATCH_NAMESPACE
        # (container_env). Without these grants every shipment silently fails — the adapter swallows
        # AccessDenied. Pre-create the log group so retention is bounded (an app-created group never
        # expires → cost creep).
        ops_log_group = logs.LogGroup(
            self, "OpsLogGroup",
            log_group_name="/docsuri/ops",
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=RemovalPolicy.DESTROY,
        )
        ops_log_group.grant_write(self.service.task_definition.task_role)
        self.service.task_definition.task_role.add_to_principal_policy(
            iam.PolicyStatement(
                # PutMetricData has no resource-level scoping; restrict by namespace instead.
                actions=["cloudwatch:PutMetricData"],
                resources=["*"],
                conditions={"StringEquals": {"cloudwatch:namespace": "DocSuri/Production"}},
            )
        )
        self.service.task_definition.task_role.add_to_principal_policy(
            iam.PolicyStatement(
                # The adapter calls create_log_group on startup; AlreadyExists against the
                # pre-created group above is harmless.
                actions=["logs:CreateLogGroup"],
                resources=[ops_log_group.log_group_arn],
            )
        )

        # --- U7 summarization + doc-model IAM (피벗, infra-design §4·§7) ---
        # Single papers bucket (Docsuri-Ingestion owns it) — referenced by ARN-by-name to avoid a
        # cross-stack export. API reads built doc-model/assets and read/writes the summary cache.
        _papers_bucket = f"arn:aws:s3:::docsuri-papers-fulltext-{self.account}"
        self.service.task_definition.task_role.add_to_principal_policy(
            iam.PolicyStatement(
                actions=["s3:GetObject"],
                resources=[f"{_papers_bucket}/doc-model/*", f"{_papers_bucket}/assets/*"],
            )
        )
        # ListBucket on the papers bucket — WITHOUT it, GetObject on a not-yet-built key returns
        # 403 (AccessDenied) instead of 404 (NoSuchKey). The U7 readers treat a non-miss error as
        # a hard 503 (correctly, to surface config faults), so every miss 503s AND the lazy
        # doc-model build never fires (the read raises before the enqueue) → bodies/summaries stay
        # "no source". Granting ListBucket makes a miss read as a miss → 404 → None → build.
        self.service.task_definition.task_role.add_to_principal_policy(
            iam.PolicyStatement(
                actions=["s3:ListBucket"],
                resources=[_papers_bucket],
            )
        )
        # Full-text source (S3FullTextSource reads full-text/{paperId}/v{n}.txt) — the source-
        # selector fallback for summary/full-translation when the doc-model is absent. Without
        # this the fallback hits AccessDenied instead of degrading to abstract.
        self.service.task_definition.task_role.add_to_principal_policy(
            iam.PolicyStatement(
                actions=["s3:GetObject"],
                resources=[f"{_papers_bucket}/full-text/*"],
            )
        )
        self.service.task_definition.task_role.add_to_principal_policy(
            iam.PolicyStatement(
                actions=["s3:GetObject", "s3:PutObject"],
                # Store writes under ``summaries/`` (plural — SummaryCacheKey.object_path,
                # infra-design §2.1); grant must match or every cache write-through hits
                # AccessDenied (put is uncaught → request fails, a successful summary/translation
                # 500s, nothing ever cached). Was ``summary/`` (typo).
                resources=[f"{_papers_bucket}/summaries/*"],
            )
        )
        self.service.task_definition.task_role.add_to_principal_policy(
            iam.PolicyStatement(
                actions=["s3:GetObject", "s3:PutObject"],
                resources=[f"{_papers_bucket}/novelty/*"],
            )
        )
        # SendMessage: doc-model build and long-summary jobs. Novelty uses the real queue object
        # below so CloudFormation owns the dependency instead of a hand-built ARN string.
        self.service.task_definition.task_role.add_to_principal_policy(
            iam.PolicyStatement(
                actions=["sqs:SendMessage"],
                resources=[
                    f"arn:aws:sqs:{self.region}:{self.account}:docsuri-docmodel-queue",
                    f"arn:aws:sqs:{self.region}:{self.account}:docsuri-ingestion-queue",
                    f"arn:aws:sqs:{self.region}:{self.account}:docsuri-summary-job-queue",
                ],
            )
        )
        self.novelty_queue.grant_send_messages(self.service.task_definition.task_role)
        # Bedrock InvokeModel for the U7 summary/translate models (Anthropic on Bedrock). Sonnet
        # 4.6 / Haiku 4.5 are invoked via global inference profiles — the bare foundation-model ids
        # aren't on-demand invokable; a global profile can route the FM to any region, so grant the
        # FM across regions (mirrors the Cohere grant below) + the in-region profile.
        self.service.task_definition.task_role.add_to_principal_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
                resources=[
                    "arn:aws:bedrock:*::foundation-model/anthropic.*",
                    f"arn:aws:bedrock:{self.region}:{self.account}:inference-profile/*",
                ],
            )
        )
        # U2 reader query-embedding: Bedrock invoke on the SAME model the writer uses (Cohere
        # v4). Must match DOCSURI_BEDROCK_MODEL_ID above and ingestion_stack._BEDROCK_MODEL_ID.
        # Without this the real read path 500s on the first search (AccessDenied at embed time).
        self.service.task_definition.task_role.add_to_principal_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel"],
                resources=[
                    # Invoked via the global inference profile (bare model id isn't on-demand
                    # invokable); the profile can route the FM to any region — grant both.
                    f"arn:aws:bedrock:{self.region}:{self.account}:inference-profile/global.cohere.embed-v4:0",
                    "arn:aws:bedrock:*::foundation-model/cohere.embed-v4:0",
                ],
            )
        )
        self.service.task_definition.task_role.add_to_principal_policy(
            iam.PolicyStatement(
                actions=[
                    "es:ESHttpGet",
                    "es:ESHttpHead",
                    "es:ESHttpPost",
                ],
                resources=[f"{opensearch_domain.domain_arn}/*"],
            )
        )

        # Autoscaling: min 2 for AZ/task headroom, max 6 after API search p95 broke under smoke.
        scaling = self.service.service.auto_scale_task_count(min_capacity=2, max_capacity=6)
        scaling.scale_on_cpu_utilization("CpuScale", target_utilization_percent=70)

        # U9 Personalization retention cleanup: one short scheduled task, no always-on worker.
        # Idempotent command; failures emit `personalization.retention_purge_failure`, alarmed
        # below. Uses the same backend image/env/secrets as the API task.
        api_container = self.service.task_definition.default_container
        if api_container is not None:
            events.Rule(
                self,
                "PersonalizationRetentionCleanup",
                description="Daily purge of expired U9 behavior events",
                schedule=events.Schedule.cron(hour="18", minute="0"),
                targets=[
                    targets.EcsTask(
                        cluster=cluster,
                        task_definition=self.service.task_definition,
                        task_count=1,
                        subnet_selection=ec2.SubnetSelection(
                            subnet_type=ec2.SubnetType.PUBLIC
                        ),
                        assign_public_ip=True,
                        security_groups=self.service.service.connections.security_groups,
                        container_overrides=[
                            targets.ContainerOverride(
                                container_name=api_container.container_name,
                                command=[
                                    "python",
                                    "-m",
                                    "backend.modules.personalization.maintenance",
                                ],
                            )
                        ],
                    )
                ],
            )

        # --- U3 account deletion cascade (FR-28/BR-A11) ---
        # Custom EventBridge bus for AccountDeleted fan-out. The API task publishes here
        # (build_account_deleted_publisher reads ACCOUNT_EVENTS_BUS=docsuri-account-events);
        # U4/U2/U11 attach rules to purge owner-scoped data (idempotent · DLQ on their side).
        account_events_bus = events.EventBus(
            self, "AccountEventsBus", event_bus_name="docsuri-account-events"
        )
        account_events_bus.grant_put_events_to(self.service.task_definition.task_role)

        # Grace-purge worker (FR-28): daily scan of DEACTIVATED accounts past purge_after →
        # AccountDeleted + permanent delete. Same image/env/secrets as the API task; reuses the
        # personalization-cleanup pattern. Idempotent — a missed/extra run is harmless.
        if api_container is not None:
            events.Rule(
                self,
                "AccountPurgeWorker",
                description="Daily grace purge of soft-deleted (DEACTIVATED) accounts (FR-28)",
                schedule=events.Schedule.cron(hour="3", minute="30"),
                targets=[
                    targets.EcsTask(
                        cluster=cluster,
                        task_definition=self.service.task_definition,
                        task_count=1,
                        subnet_selection=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
                        assign_public_ip=True,
                        security_groups=self.service.service.connections.security_groups,
                        container_overrides=[
                            targets.ContainerOverride(
                                container_name=api_container.container_name,
                                command=["python", "-m", "backend.modules.accounts.purge_worker"],
                            )
                        ],
                    )
                ],
            )

        # SG: allow ECS → OpenSearch (HTTPS). Direction: egress from ECS → avoids cycle.
        self.service.service.connections.allow_to(
            opensearch_domain.connections, ec2.Port.tcp(443)
        )
        # SG: allow ECS → RDS
        self.db.connections.allow_from(
            self.service.service.connections, ec2.Port.tcp(5432)
        )
        # SG: allow ECS → Redis
        redis_sg.add_ingress_rule(
            self.service.service.connections.security_groups[0], ec2.Port.tcp(6379)
        )

        # --- CloudFront: browser-trusted HTTPS, encrypted edge→origin, origin-authenticated ---
        # Viewer side uses the default *.cloudfront.net cert (no custom domain needed for the BFF).
        # Origin = origin.docsuri.org over HTTPS_ONLY so the edge→origin hop is encrypted and the
        # ACM cert validates (HttpOrigin, not LoadBalancerV2Origin, so CloudFront connects by that
        # name rather than the *.elb.amazonaws.com host). A secret header authenticates US as the
        # caller (the ALB rule above 403s anything without it).
        # API-correct behavior (not the static-content defaults):
        #   • ALLOW_ALL methods — login/library need POST/DELETE
        #   • CACHING_DISABLED — every response is dynamic/authenticated
        #   • ALL_VIEWER_EXCEPT_HOST_HEADER — forward cookies + headers, strip viewer Host
        self.cdn = cloudfront.Distribution(
            self, "ApiCdn",
            comment="docsuri-api - trusted HTTPS edge + encrypted, authenticated origin",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.HttpOrigin(
                    _ORIGIN_DOMAIN,
                    protocol_policy=cloudfront.OriginProtocolPolicy.HTTPS_ONLY,
                    https_port=443,
                    origin_ssl_protocols=[cloudfront.OriginSslPolicy.TLS_V1_2],
                    custom_headers={"X-Origin-Verify": origin_verify},
                ),
                # HTTPS_ONLY (not REDIRECT): refuse plaintext outright rather than 301 it —
                # a redirected POST would still have sent its body over HTTP first.
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.HTTPS_ONLY,
                allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
                cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
            ),
        )
        CfnOutput(
            self, "ApiCdnUrl",
            value=f"https://{self.cdn.distribution_domain_name}",
            description="Browser-trusted HTTPS endpoint for the API (set DOCSURI_GATEWAY_URL here)",
        )

        # --- Ops alerting: the alarm→human "last mile" (runbook §4 G2/G4 + the 3 SLOs §7) ---
        # ponytail: NOT wiring the in-app cost guard's AlertPublisher to SNS. The AWS Budget below
        # catches cost at the billing level (more robust — sees ALL spend, not just what flows
        # through the guard), and the in-app guard already degrades/rejects on its own. Add a
        # per-incident SNS publisher only if you need finer paging than these 3 alarms give.
        ops_alerts = sns.Topic(self, "OpsAlerts", display_name="docsuri-ops-alerts")
        for email in ops_alert_emails:
            ops_alerts.add_subscription(subs.EmailSubscription(email))
        if not ops_alert_emails:
            CfnOutput(
                self, "OpsAlertEmailMissing",
                value="set -c ops_alert_email=<addr>[,<addr>...] so alarms + budget page a human",
            )

        novelty_queue_age_metric = self.novelty_queue.metric_approximate_age_of_oldest_message(
            period=Duration.minutes(5),
            statistic="Maximum",
        )
        novelty_queue_age_alarm = novelty_queue_age_metric.create_alarm(
            self,
            "NoveltyQueueAgeAlarm",
            threshold=900,
            evaluation_periods=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
            alarm_description="Novelty jobs are waiting more than 15 minutes before processing",
        )
        novelty_queue_age_alarm.add_alarm_action(cw_actions.SnsAction(ops_alerts))

        # SLO 1 — API availability: backend 5xx. Native ALB metric, no app instrumentation needed.
        api_5xx_metric = self.service.target_group.metrics.http_code_target(
            elbv2.HttpCodeTarget.TARGET_5XX_COUNT,
            period=Duration.minutes(5),
            statistic="Sum",
        )
        api_5xx_alarm = api_5xx_metric.create_alarm(
            self, "Api5xxAlarm",
            threshold=10,  # tune: >10 backend 5xx in 5 min
            evaluation_periods=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
            alarm_description="DocSuri API target 5xx > 10 / 5min",
        )
        api_5xx_alarm.add_alarm_action(cw_actions.SnsAction(ops_alerts))

        # SLO 2 — search latency: ALB target p95 response time. Native metric.
        api_latency_metric = self.service.target_group.metrics.target_response_time(
            period=Duration.minutes(5),
            statistic="p95",
        )
        api_latency_alarm = api_latency_metric.create_alarm(
            self, "ApiLatencyP95Alarm",
            threshold=2,  # seconds; tune to the search SLO
            evaluation_periods=3,  # 3×5min sustained → avoid paging on a single slow window
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
            alarm_description="DocSuri API p95 latency > 2s sustained 15min",
        )
        api_latency_alarm.add_alarm_action(cw_actions.SnsAction(ops_alerts))

        personalization_purge_metric = cloudwatch.Metric(
            namespace="DocSuri/Production",
            metric_name="personalization.retention_purge_failure",
            period=Duration.minutes(5),
            statistic="Sum",
        )
        personalization_purge_alarm = personalization_purge_metric.create_alarm(
            self,
            "PersonalizationRetentionPurgeFailureAlarm",
            threshold=0,
            evaluation_periods=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
            alarm_description="U9 behavior-event retention purge failed",
        )
        personalization_purge_alarm.add_alarm_action(cw_actions.SnsAction(ops_alerts))

        # Email delivery failures (incident 2026-06-25): verification/reset emails silently failed
        # for every signup because the prod RESEND_API_KEY was invalid (Resend 400 "API key is
        # invalid") — accounts stuck PENDING with NO alert. _emit_email_failure emits
        # EmailDeliveryFailureSignal both per-error_type (diagnostics) AND dimensionless (this alarm
        # target). We alarm on the DIMENSIONLESS stream because CloudWatch metric alarms do NOT
        # support SEARCH (dimension wildcards) — the dimensionless total catches every error_type
        # (Resend RuntimeError, network exceptions, SES boto errors) in one alarm. threshold=0 →
        # any failure in a 5-min window pages ops instead of failing silently.
        email_failure_metric = cloudwatch.Metric(
            namespace="DocSuri/Production",
            metric_name="EmailDeliveryFailureSignal",
            period=Duration.minutes(5),
            statistic="Sum",
        )
        email_failure_alarm = email_failure_metric.create_alarm(
            self,
            "EmailDeliveryFailureAlarm",
            threshold=0,
            evaluation_periods=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
            alarm_description=(
                "DocSuri verification/reset email delivery failing "
                "(e.g. invalid RESEND_API_KEY or unverified sender domain) — accounts stuck PENDING"
            ),
        )
        email_failure_alarm.add_alarm_action(cw_actions.SnsAction(ops_alerts))

        # SLO 3 — cost burn: account budget mirroring the in-app cap ($1600), notifying at the same
        # 80% warning ratio ($1280 — cost_guard.warning_ratio). Budget emails the ops alias directly
        # (no SNS/topic policy needed). Account 028317349537 is dedicated to DocSuri → account
        # spend ≈ app spend.
        if ops_alert_emails:
            budgets.CfnBudget(
                self, "MonthlyCostBudget",
                budget=budgets.CfnBudget.BudgetDataProperty(
                    budget_type="COST",
                    time_unit="MONTHLY",
                    budget_limit=budgets.CfnBudget.SpendProperty(amount=1600, unit="USD"),
                ),
                notifications_with_subscribers=[
                    budgets.CfnBudget.NotificationWithSubscribersProperty(
                        notification=budgets.CfnBudget.NotificationProperty(
                            notification_type="ACTUAL",
                            comparison_operator="GREATER_THAN",
                            threshold=80,  # percent of $1600 = $1280
                        ),
                        # AWS Budgets allows up to 10 email subscribers per notification.
                        subscribers=[
                            budgets.CfnBudget.SubscriberProperty(
                                subscription_type="EMAIL", address=email,
                            )
                            for email in ops_alert_emails
                        ],
                    ),
                ],
            )

        # One on-call view for the alarmed signals. Cross-stack alarm names are generated, so the
        # queue widgets use the stable queue names and the same thresholds as their alarms.
        dashboard = cloudwatch.Dashboard(
            self,
            "OpsDashboard",
            dashboard_name="DocSuri-Production-Ops",
        )
        ingestion_queue_age_metric = cloudwatch.Metric(
            namespace="AWS/SQS",
            metric_name="ApproximateAgeOfOldestMessage",
            dimensions_map={"QueueName": "docsuri-ingestion-queue"},
            period=Duration.minutes(5),
            statistic="Maximum",
        )
        docmodel_queue_age_metric = cloudwatch.Metric(
            namespace="AWS/SQS",
            metric_name="ApproximateAgeOfOldestMessage",
            dimensions_map={"QueueName": "docsuri-docmodel-queue"},
            period=Duration.minutes(5),
            statistic="Maximum",
        )
        summary_queue_age_metric = cloudwatch.Metric(
            namespace="AWS/SQS",
            metric_name="ApproximateAgeOfOldestMessage",
            dimensions_map={"QueueName": "docsuri-summary-job-queue"},
            period=Duration.minutes(5),
            statistic="Maximum",
        )
        ingestion_queue_visible_metric = cloudwatch.Metric(
            namespace="AWS/SQS",
            metric_name="ApproximateNumberOfMessagesVisible",
            dimensions_map={"QueueName": "docsuri-ingestion-queue"},
            period=Duration.minutes(5),
            statistic="Maximum",
        )
        docmodel_queue_visible_metric = cloudwatch.Metric(
            namespace="AWS/SQS",
            metric_name="ApproximateNumberOfMessagesVisible",
            dimensions_map={"QueueName": "docsuri-docmodel-queue"},
            period=Duration.minutes(5),
            statistic="Maximum",
        )
        summary_queue_visible_metric = cloudwatch.Metric(
            namespace="AWS/SQS",
            metric_name="ApproximateNumberOfMessagesVisible",
            dimensions_map={"QueueName": "docsuri-summary-job-queue"},
            period=Duration.minutes(5),
            statistic="Maximum",
        )

        dashboard.add_widgets(
            cloudwatch.TextWidget(
                markdown=(
                    "# DocSuri production ops\n"
                    "Alarm tiles show the current SNS-paged signals. Graphs below use the same "
                    "CloudWatch metrics and thresholds for quick triage."
                ),
                width=24,
                height=2,
            )
        )
        dashboard.add_widgets(
            cloudwatch.AlarmWidget(title="API 5xx", alarm=api_5xx_alarm, width=8, height=4),
            cloudwatch.AlarmWidget(
                title="API p95 latency", alarm=api_latency_alarm, width=8, height=4
            ),
            cloudwatch.AlarmWidget(
                title="Email delivery", alarm=email_failure_alarm, width=8, height=4
            ),
        )
        dashboard.add_widgets(
            cloudwatch.AlarmWidget(
                title="Novelty queue age", alarm=novelty_queue_age_alarm, width=8, height=4
            ),
            cloudwatch.AlarmWidget(title="Novelty DLQ", alarm=novelty_dlq_alarm, width=8, height=4),
            cloudwatch.AlarmWidget(
                title="Retention purge", alarm=personalization_purge_alarm, width=8, height=4
            ),
        )
        dashboard.add_widgets(
            cloudwatch.GraphWidget(
                title="API 5xx count",
                left=[api_5xx_metric],
                left_annotations=[
                    cloudwatch.HorizontalAnnotation(value=10, label="alarm: >10 / 5m")
                ],
                width=12,
                height=6,
            ),
            cloudwatch.GraphWidget(
                title="API p95 latency",
                left=[api_latency_metric],
                left_annotations=[
                    cloudwatch.HorizontalAnnotation(value=2, label="alarm: >2s for 15m")
                ],
                width=12,
                height=6,
            ),
        )
        dashboard.add_widgets(
            cloudwatch.GraphWidget(
                title="Queue age SLOs",
                left=[
                    novelty_queue_age_metric,
                    ingestion_queue_age_metric,
                    docmodel_queue_age_metric,
                    summary_queue_age_metric,
                ],
                left_annotations=[
                    cloudwatch.HorizontalAnnotation(value=300, label="docmodel: 5m"),
                    cloudwatch.HorizontalAnnotation(value=900, label="novelty/summary: 15m"),
                    cloudwatch.HorizontalAnnotation(value=1800, label="ingestion: 30m"),
                ],
                width=24,
                height=6,
            )
        )
        dashboard.add_widgets(
            cloudwatch.GraphWidget(
                title="Queue backlog and DLQ",
                left=[
                    self.novelty_queue.metric_approximate_number_of_messages_visible(),
                    novelty_dlq_visible_metric,
                    ingestion_queue_visible_metric,
                    docmodel_queue_visible_metric,
                    summary_queue_visible_metric,
                ],
                width=12,
                height=6,
            ),
            cloudwatch.GraphWidget(
                title="Application failure signals",
                left=[email_failure_metric, personalization_purge_metric],
                left_annotations=[cloudwatch.HorizontalAnnotation(value=0, label="alarm: >0")],
                width=12,
                height=6,
            ),
        )
        dashboard.add_widgets(
            cloudwatch.TextWidget(
                markdown=(
                    "## Cost alert\n"
                    "AWS Budget remains the source of truth: monthly cap $1600, email alert at "
                    "80% actual spend ($1280)."
                ),
                width=24,
                height=2,
            )
        )
