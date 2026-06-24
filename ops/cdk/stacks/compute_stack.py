"""ECS Fargate — deploy unit ① (API modular monolith) + ALB + RDS + Redis.

infra-design.md §6 (API compute) + U3 infrastructure-design (RDS/Redis/ALB)."""

import secrets

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
from constructs import Construct

# Public DNS for the API origin (zone docsuri.org lives in this account's Route53). CloudFront
# connects to this name over HTTPS so the ACM cert (issued for it) validates — ACM can't issue
# for the ALB's *.elb.amazonaws.com name, so a controlled domain is mandatory for origin TLS.
_ORIGIN_DOMAIN = "origin.docsuri.org"
_ZONE_NAME = "docsuri.org"
_ZONE_ID = "Z0084324NUV4EPLJ7JH9"

# Shared secret proving a request came from OUR CloudFront (not just any CloudFront in the
# shared origin-facing prefix list — the confused-deputy). Generated per-synth (never in source);
# CloudFront injects it as a header and the ALB 403s requests without it. Both sides use this same
# value within a deploy; a re-deploy rotates it harmlessly (header + rule update together).
_ORIGIN_VERIFY_SECRET = secrets.token_urlsafe(32)


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

        # Ops alert recipients — comma-separated so adding teammates later is a deploy-arg change,
        # not a code change: `cdk deploy -c ops_alert_email=a@x.com,b@y.com` (or cdk.json context).
        # Empty → topic/alarms still synthesize, just with no email subscription/budget. A team
        # alias beats individual inboxes (vacation = missed page), but a list works without one.
        _raw_alert_emails = self.node.try_get_context("ops_alert_email") or ""
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
            "DOCSURI_DOCMODEL_BUILD_QUEUE_URL": (  # doc-model lazy build (BR-30, boundary B)
                f"https://sqs.{self.region}.amazonaws.com/{self.account}/docsuri-ingestion-queue"
            ),
            "DOCSURI_SUMMARY_JOB_QUEUE_URL": (  # long-summary async job (BR-S12)
                f"https://sqs.{self.region}.amazonaws.com/{self.account}/docsuri-summary-job-queue"
            ),
            "PERSONALIZATION_ENABLED": "false",
            "PERSONALIZATION_RAW_EVENT_RETENTION_DAYS": "90",
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

        # --- ALB + Fargate service (deploy unit ①: 0.25 vCPU / 512 MB, min 1 max 2) ---
        # HTTPS :443 terminated on the ALB with the ACM cert + a Route53 alias (origin.docsuri.org
        # → ALB). CloudFront reaches the origin over HTTPS (below), so edge↔origin is encrypted.
        self.service = ecs_patterns.ApplicationLoadBalancedFargateService(
            self, "ApiService",
            cluster=cluster,
            service_name="docsuri-api",
            cpu=256,
            memory_limit_mib=512,
            desired_count=1,
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
                elbv2.ListenerCondition.http_header("X-Origin-Verify", [_ORIGIN_VERIFY_SECRET])
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
        # ponytail: /healthz is the cheap liveness route (no DB/Redis dep); use /readyz only
        # if you want readiness gating once downstream deps are wired.
        self.service.target_group.configure_health_check(path="/healthz")

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
        # cross-stack export. API reads the built doc-model and read/writes the summary cache.
        _papers_bucket = f"arn:aws:s3:::docsuri-papers-fulltext-{self.account}"
        self.service.task_definition.task_role.add_to_principal_policy(
            iam.PolicyStatement(
                actions=["s3:GetObject"],
                resources=[f"{_papers_bucket}/doc-model/*"],
            )
        )
        self.service.task_definition.task_role.add_to_principal_policy(
            iam.PolicyStatement(
                actions=["s3:GetObject", "s3:PutObject"],
                resources=[f"{_papers_bucket}/summary/*"],
            )
        )
        # SendMessage: doc-model build (ingestion queue, boundary B) + long-summary job queue.
        self.service.task_definition.task_role.add_to_principal_policy(
            iam.PolicyStatement(
                actions=["sqs:SendMessage"],
                resources=[
                    f"arn:aws:sqs:{self.region}:{self.account}:docsuri-ingestion-queue",
                    f"arn:aws:sqs:{self.region}:{self.account}:docsuri-summary-job-queue",
                ],
            )
        )
        # Bedrock InvokeModel for the U7 summary/translate models (Anthropic on Bedrock). Scoped to
        # Anthropic foundation models + inference profiles in-region (concrete ids are app config).
        self.service.task_definition.task_role.add_to_principal_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
                resources=[
                    f"arn:aws:bedrock:{self.region}::foundation-model/anthropic.*",
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

        # Autoscaling: min 1 — max 2 (U3 spec)
        scaling = self.service.service.auto_scale_task_count(min_capacity=1, max_capacity=2)
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
                    custom_headers={"X-Origin-Verify": _ORIGIN_VERIFY_SECRET},
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

        # SLO 1 — API availability: backend 5xx. Native ALB metric, no app instrumentation needed.
        api_5xx_alarm = self.service.target_group.metrics.http_code_target(
            elbv2.HttpCodeTarget.TARGET_5XX_COUNT,
            period=Duration.minutes(5),
            statistic="Sum",
        ).create_alarm(
            self, "Api5xxAlarm",
            threshold=10,  # tune: >10 backend 5xx in 5 min
            evaluation_periods=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
            alarm_description="DocSuri API target 5xx > 10 / 5min",
        )
        api_5xx_alarm.add_alarm_action(cw_actions.SnsAction(ops_alerts))

        # SLO 2 — search latency: ALB target p95 response time. Native metric.
        api_latency_alarm = self.service.target_group.metrics.target_response_time(
            period=Duration.minutes(5),
            statistic="p95",
        ).create_alarm(
            self, "ApiLatencyP95Alarm",
            threshold=2,  # seconds; tune to the search SLO
            evaluation_periods=3,  # 3×5min sustained → avoid paging on a single slow window
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
            alarm_description="DocSuri API p95 latency > 2s sustained 15min",
        )
        api_latency_alarm.add_alarm_action(cw_actions.SnsAction(ops_alerts))

        personalization_purge_alarm = cloudwatch.Metric(
            namespace="DocSuri/Production",
            metric_name="personalization.retention_purge_failure",
            period=Duration.minutes(5),
            statistic="Sum",
        ).create_alarm(
            self,
            "PersonalizationRetentionPurgeFailureAlarm",
            threshold=0,
            evaluation_periods=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
            alarm_description="U9 behavior-event retention purge failed",
        )
        personalization_purge_alarm.add_alarm_action(cw_actions.SnsAction(ops_alerts))

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
