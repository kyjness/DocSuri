"""ECS Fargate — deploy unit ④ (U5 Next.js SSR frontend) + ALB + CloudFront.

Mirrors the backend (compute_stack) hardening: HTTPS-only edge, ACM-terminated origin,
secret-header origin authentication, CloudFront-only network lockdown. Difference: the
frontend is browser-facing, so it carries a custom apex domain (docsuri.org) on the viewer
side — which is what makes the httpOnly+Secure session cookie work in a real browser."""

from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
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
    aws_elasticloadbalancingv2 as elbv2,
)
from aws_cdk import (
    aws_route53 as route53,
)
from aws_cdk import (
    aws_route53_targets as r53_targets,
)
from aws_cdk import (
    aws_s3 as s3,
)
from aws_cdk import (
    aws_s3_deployment as s3deploy,
)
from aws_cdk import (
    aws_sns as sns,
)
from aws_cdk import (
    aws_sns_subscriptions as subs,
)
from constructs import Construct

from ._origin_auth import social_origin_verify_secret, web_origin_verify_secret

_APP_DOMAIN = "docsuri.org"  # viewer (browser-facing) — the app's public URL
_ORIGIN_DOMAIN = "app-origin.docsuri.org"  # ALB origin name (distinct from backend's origin.*)
# Backend API origin (ComputeStack's ALB) — only the social-login full-page redirects route here
# so the session cookie is first-party on docsuri.org (Option A, FR-27). Authenticated by the
# shared X-Origin-Verify secret (accepted as a 2nd value on the backend ALB rule).
_BACKEND_ORIGIN_DOMAIN = "origin.docsuri.org"
_ZONE_NAME = "docsuri.org"
_ZONE_ID = "Z0084324NUV4EPLJ7JH9"
# Viewer cert lives in us-east-1 (CloudFront requirement); created out-of-band, DNS-validated.
_VIEWER_CERT_ARN = "arn:aws:acm:us-east-1:028317349537:certificate/8973dd50-5acb-4cb6-9a68-c64ddcdf0243"  # noqa: E501
# com.amazonaws.global.cloudfront.origin-facing in ap-northeast-2.
_CLOUDFRONT_PREFIX_LIST = "pl-22a6434b"
_LIBRARY_ENTRY_PATH = "/library/saved"
_ALB_IDLE_TIMEOUT_SECONDS = 60
_NEXT_KEEP_ALIVE_TIMEOUT_MS = (_ALB_IDLE_TIMEOUT_SECONDS + 5) * 1000

# Branded static error page (#341) — served from S3 at the edge when the origin returns a 5xx,
# so users never see a raw ALB/gateway error. Self-contained: inline CSS, no external refs
# (works even mid-incident), dark-mode aware, retry-in-place. Not under the app CSP (it bypasses
# the Next middleware), so the one inline handler is safe here.
_EDGE_ERROR_HTML = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>일시적인 오류 · DocSuri</title>
<style>
  :root { color-scheme: light dark; }
  * { box-sizing: border-box; }
  body {
    margin: 0; min-height: 100vh; display: grid; place-items: center; padding: 2rem;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Apple SD Gothic Neo",
      "Noto Sans KR", sans-serif;
    background: #fbfbfd; color: #1a1a1f;
  }
  main { max-width: 26rem; text-align: center; }
  .mark { margin: 0; font-weight: 700; font-size: 0.9rem; letter-spacing: 0.02em; color: #6b6b76; }
  h1 { margin: 0.9rem 0 0.5rem; font-size: 1.5rem; line-height: 1.3; letter-spacing: -0.02em; }
  p.msg { margin: 0.2rem 0; color: #55555f; line-height: 1.65; }
  button {
    margin-top: 1.75rem; padding: 0.7rem 1.6rem; border: 0; border-radius: 999px;
    font: inherit; font-weight: 600; color: #fff; background: #3d5afe; cursor: pointer;
    transition: transform .15s ease, background .15s ease;
  }
  button:hover { background: #2f49e0; transform: translateY(-1px); }
  button:active { transform: translateY(0); }
  button:focus-visible { outline: 3px solid rgba(61, 90, 254, 0.45); outline-offset: 2px; }
  @media (prefers-color-scheme: dark) {
    body { background: #0e0e11; color: #f2f2f5; }
    .mark { color: #8b8b96; }
    p.msg { color: #a8a8b3; }
  }
</style>
</head>
<body>
  <main>
    <p class="mark">DocSuri</p>
    <h1>잠시 후 다시 시도해 주세요</h1>
    <p class="msg">일시적인 문제로 페이지를 불러오지 못했어요.</p>
    <p class="msg">잠깐 사이에 해결되는 경우가 많아요.</p>
    <button type="button" onclick="location.reload()">새로고침</button>
  </main>
</body>
</html>
"""


class FrontendStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        vpc: ec2.IVpc,
        gateway_url: str,  # backend CloudFront HTTPS URL — the BFF's DOCSURI_GATEWAY_URL
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # X-Origin-Verify secrets (web: our WebCdn→ALB; social: shared with the backend ALB for the
        # /auth/social/* edge). Read from SSM at deploy time so synth is deterministic — see
        # ._origin_auth.
        origin_verify = web_origin_verify_secret(self)
        social_verify = social_origin_verify_secret(self)
        _DEFAULT_OPS_ALERT_EMAIL = "corpseonthemission@icloud.com"
        _ctx_alert_emails = self.node.try_get_context("ops_alert_email")
        _raw_alert_emails = (
            _DEFAULT_OPS_ALERT_EMAIL if _ctx_alert_emails is None else _ctx_alert_emails
        )
        ops_alert_emails = [e.strip() for e in _raw_alert_emails.split(",") if e.strip()]

        repo = ecr.Repository.from_repository_name(self, "FrontendRepo", "docsuri-frontend")
        cluster = ecs.Cluster(self, "Cluster", cluster_name="docsuri-frontend", vpc=vpc)

        zone = route53.HostedZone.from_hosted_zone_attributes(
            self, "Zone", hosted_zone_id=_ZONE_ID, zone_name=_ZONE_NAME,
        )
        origin_cert = acm.Certificate(
            self, "OriginCert",
            domain_name=_ORIGIN_DOMAIN,
            validation=acm.CertificateValidation.from_dns(zone),
        )
        viewer_cert = acm.Certificate.from_certificate_arn(self, "ViewerCert", _VIEWER_CERT_ARN)

        # The SSR server is stateless (session lives in the httpOnly cookie). NEXT_PUBLIC_*
        # flags are baked at image build; DOCSURI_GATEWAY_URL is server-only runtime config that
        # points the BFF at the backend gateway (CloudFront). Never reaches the browser bundle.
        container_env = {
            "NODE_ENV": "production",
            "DOCSURI_GATEWAY_URL": gateway_url,
            "DOCSURI_LIBRARY_ENTRY_PATH": _LIBRARY_ENTRY_PATH,
            # Issue #341 root cause: a logged paper-page 502 had ALB target_status_code "-",
            # with the same target serving adjacent 200s. Next standalone supports this
            # env var; keep the Node backend socket alive longer than the ALB idle window
            # so ALB does not reuse a connection the SSR server has already closed.
            "KEEP_ALIVE_TIMEOUT": str(_NEXT_KEEP_ALIVE_TIMEOUT_MS),
        }

        # --- ALB + Fargate (HTTPS :443 with ACM cert + Route53 alias app-origin.docsuri.org) ---
        self.service = ecs_patterns.ApplicationLoadBalancedFargateService(
            self, "WebService",
            cluster=cluster,
            service_name="docsuri-frontend",
            cpu=512,
            memory_limit_mib=1024,
            desired_count=2,
            task_image_options=ecs_patterns.ApplicationLoadBalancedTaskImageOptions(
                image=ecs.ContainerImage.from_ecr_repository(repo, tag="latest"),
                container_port=3000,
                environment=container_env,
            ),
            assign_public_ip=True,
            public_load_balancer=True,
            protocol=elbv2.ApplicationProtocol.HTTPS,
            certificate=origin_cert,
            domain_name=_ORIGIN_DOMAIN,
            domain_zone=zone,
            open_listener=False,
            circuit_breaker=ecs.DeploymentCircuitBreaker(rollback=True),
            health_check_grace_period=Duration.seconds(60),
        )
        self.service.load_balancer.set_attribute(
            "idle_timeout.timeout_seconds", str(_ALB_IDLE_TIMEOUT_SECONDS)
        )
        # The Next.js `/` route is statically prerendered (no backend dependency), so it is a
        # safe ALB liveness probe; a 3xx redirect from it is still "healthy" to the ALB.
        self.service.target_group.configure_health_check(path="/")

        # Edge/origin access logs (#341): the paper page returns intermittent SSR 5xx and we
        # can't yet correlate a failing request against the SSR server's CloudWatch container
        # logs. ALB logs give the failing path+timestamp at the origin; CloudFront logs add
        # edge-vs-origin attribution. BUCKET_OWNER_PREFERRED (ACLs on) is required for CloudFront
        # standard S3 logging; ALB writes via bucket policy. RETAIN so incident evidence survives
        # a stack replace; a 90-day lifecycle caps storage cost.
        edge_logs = s3.Bucket(
            self, "WebEdgeLogs",
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            object_ownership=s3.ObjectOwnership.BUCKET_OWNER_PREFERRED,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.RETAIN,
            lifecycle_rules=[s3.LifecycleRule(expiration=Duration.days(90))],
        )
        self.service.load_balancer.log_access_logs(edge_logs, prefix="alb")

        # Network lockdown: ALB :443 only from CloudFront edge IPs (dedicated SG — the 45-entry
        # prefix list vs the 60-rule SG quota; see compute_stack). Necessary but not sufficient —
        # the secret-header rule below is the real origin-auth (shared-prefix-list confused-deputy).
        cf_origin_sg = ec2.SecurityGroup(
            self, "CloudFrontOriginSg", vpc=vpc, allow_all_outbound=False,
            description="ALB inbound from CloudFront origin-facing prefix list only",
        )
        cf_origin_sg.add_ingress_rule(
            ec2.Peer.prefix_list(_CLOUDFRONT_PREFIX_LIST), ec2.Port.tcp(443),
            description="CloudFront origin-facing only",
        )
        self.service.load_balancer.add_security_group(cf_origin_sg)

        # Origin auth: forward only when our CloudFront's secret header is present; else 403.
        self.service.listener.add_action(
            "VerifiedOriginOnly",
            priority=1,
            conditions=[
                elbv2.ListenerCondition.http_header("X-Origin-Verify", [origin_verify])
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

        scaling = self.service.service.auto_scale_task_count(min_capacity=2, max_capacity=4)
        scaling.scale_on_cpu_utilization("CpuScale", target_utilization_percent=70)

        ops_alerts = sns.Topic(self, "OpsAlerts", display_name="docsuri-frontend-ops-alerts")
        for email in ops_alert_emails:
            ops_alerts.add_subscription(subs.EmailSubscription(email))

        web_5xx_alarm = self.service.target_group.metrics.http_code_target(
            elbv2.HttpCodeTarget.TARGET_5XX_COUNT,
            period=Duration.minutes(5),
            statistic="Sum",
        ).create_alarm(
            self,
            "Frontend5xxAlarm",
            threshold=10,
            evaluation_periods=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
            alarm_description="DocSuri frontend target 5xx > 10 / 5min",
        )
        web_5xx_alarm.add_alarm_action(cw_actions.SnsAction(ops_alerts))

        web_latency_alarm = self.service.target_group.metrics.target_response_time(
            period=Duration.minutes(5),
            statistic="p95",
        ).create_alarm(
            self,
            "FrontendLatencyP95Alarm",
            threshold=2,
            evaluation_periods=3,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
            alarm_description="DocSuri frontend p95 latency > 2s sustained 15min",
        )
        web_latency_alarm.add_alarm_action(cw_actions.SnsAction(ops_alerts))

        # --- CloudFront: browser-trusted HTTPS at docsuri.org, encrypted+authenticated origin ---
        # read_timeout 60s(기본 30s에서 상향, AWS 계정 기본 할당량 최대치) — evidence 채팅 턴은
        # OpenSearch 검색 + 다건 S3 DocModel 로드 + Bedrock 추출을 동기로 거쳐 30초를 쉽게
        # 넘긴다. 기본값이면 백엔드가 정상 완료돼도 CloudFront가 먼저 504를 반환해 사용자에게
        # "네트워크 연결" 에러로 보임(임시 완화 — 근본 해결은 비동기 job+폴링 전환 필요).
        origin = origins.HttpOrigin(
            _ORIGIN_DOMAIN,
            protocol_policy=cloudfront.OriginProtocolPolicy.HTTPS_ONLY,
            https_port=443,
            origin_ssl_protocols=[cloudfront.OriginSslPolicy.TLS_V1_2],
            custom_headers={"X-Origin-Verify": origin_verify},
            read_timeout=Duration.seconds(60),
        )
        # Backend origin for the social-login redirects only (Option A, FR-27). Sends the SHARED
        # verify secret (accepted as a 2nd value on the backend ALB rule in ComputeStack).
        backend_origin = origins.HttpOrigin(
            _BACKEND_ORIGIN_DOMAIN,
            protocol_policy=cloudfront.OriginProtocolPolicy.HTTPS_ONLY,
            https_port=443,
            origin_ssl_protocols=[cloudfront.OriginSslPolicy.TLS_V1_2],
            custom_headers={"X-Origin-Verify": social_verify},
        )
        # Edge error page (#341): served from S3, NOT the ALB — in the worst case (origin
        # unreachable) the ALB can't serve its own error page. Private bucket; CloudFront reads
        # it via OAC (no public access).
        error_bucket = s3.Bucket(
            self, "WebErrorAssets",
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            # ponytail: RETAIN — trivial redeployable asset, orphans on `cdk destroy`.
            # Add auto_delete_objects=True if teardown cleanliness ever matters.
            removal_policy=RemovalPolicy.RETAIN,
        )
        error_origin = origins.S3BucketOrigin.with_origin_access_control(error_bucket)
        self.cdn = cloudfront.Distribution(
            self, "WebCdn",
            comment="docsuri frontend (U5) - trusted HTTPS edge + authenticated origin",
            domain_names=[_APP_DOMAIN],
            certificate=viewer_cert,
            # Access logs (#341) — same bucket as the ALB logs, under a cf/ prefix.
            enable_logging=True,
            log_bucket=edge_logs,
            log_file_prefix="cf/",
            log_includes_cookies=False,
            default_behavior=cloudfront.BehaviorOptions(
                origin=origin,
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.HTTPS_ONLY,
                allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,  # /bff/* needs POST/DELETE
                # SSR HTML + /bff are dynamic/authenticated → no caching.
                cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
            ),
            additional_behaviors={
                # Immutable, content-hashed build assets — safe (and worthwhile) to cache at edge.
                "/_next/static/*": cloudfront.BehaviorOptions(
                    origin=origin,
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.HTTPS_ONLY,
                    cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
                ),
                # Social-login OIDC full-page redirects (start + callback) → backend origin, so the
                # session cookie is set first-party on docsuri.org (Option A, FR-27). Dynamic/
                # authenticated → no caching; forward cookies + query (code/state/nonce).
                "/auth/social/*": cloudfront.BehaviorOptions(
                    origin=backend_origin,
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.HTTPS_ONLY,
                    allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
                    cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                    origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
                ),
                # Branded edge error page (#341) — S3-backed so it survives an origin outage.
                "/__edge/*": cloudfront.BehaviorOptions(
                    origin=error_origin,
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.HTTPS_ONLY,
                    cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
                ),
            },
            # Map origin 5xx → the branded S3 page. Keep the 5xx status (don't mask as 200 —
            # monitors and crawlers should still see the error). Short TTL lightly shields a
            # struggling origin from retry storms.
            # ponytail: 10s error cache; drop to 0 for fastest recovery, raise to shield harder.
            error_responses=[
                cloudfront.ErrorResponse(
                    http_status=code,
                    response_http_status=code,
                    response_page_path="/__edge/error.html",
                    ttl=Duration.seconds(10),
                )
                for code in (500, 502, 503, 504)
            ],
        )
        s3deploy.BucketDeployment(
            self, "WebErrorPageDeploy",
            destination_bucket=error_bucket,
            sources=[s3deploy.Source.data("__edge/error.html", _EDGE_ERROR_HTML)],
            distribution=self.cdn,
            distribution_paths=["/__edge/*"],
        )

        # Apex docsuri.org → CloudFront (Route53 alias supports apex; CNAME would not).
        route53.ARecord(
            self, "AppAlias",
            zone=zone,
            target=route53.RecordTarget.from_alias(r53_targets.CloudFrontTarget(self.cdn)),
        )

        CfnOutput(self, "AppUrl", value=f"https://{_APP_DOMAIN}", description="Public app URL")
        CfnOutput(self, "CdnDomain", value=self.cdn.distribution_domain_name)
        CfnOutput(self, "LibraryEntryPath", value=_LIBRARY_ENTRY_PATH)
