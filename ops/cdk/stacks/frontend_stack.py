"""ECS Fargate — deploy unit ④ (U5 Next.js SSR frontend) + ALB + CloudFront.

Mirrors the backend (compute_stack) hardening: HTTPS-only edge, ACM-terminated origin,
secret-header origin authentication, CloudFront-only network lockdown. Difference: the
frontend is browser-facing, so it carries a custom apex domain (docsuri.org) on the viewer
side — which is what makes the httpOnly+Secure session cookie work in a real browser."""

from aws_cdk import (
    CfnOutput,
    Duration,
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
        }

        # --- ALB + Fargate (HTTPS :443 with ACM cert + Route53 alias app-origin.docsuri.org) ---
        self.service = ecs_patterns.ApplicationLoadBalancedFargateService(
            self, "WebService",
            cluster=cluster,
            service_name="docsuri-frontend",
            cpu=256,
            memory_limit_mib=512,
            desired_count=1,
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
        # The Next.js `/` route is statically prerendered (no backend dependency), so it is a
        # safe ALB liveness probe; a 3xx redirect from it is still "healthy" to the ALB.
        self.service.target_group.configure_health_check(path="/")

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

        scaling = self.service.service.auto_scale_task_count(min_capacity=1, max_capacity=2)
        scaling.scale_on_cpu_utilization("CpuScale", target_utilization_percent=70)

        # --- CloudFront: browser-trusted HTTPS at docsuri.org, encrypted+authenticated origin ---
        origin = origins.HttpOrigin(
            _ORIGIN_DOMAIN,
            protocol_policy=cloudfront.OriginProtocolPolicy.HTTPS_ONLY,
            https_port=443,
            origin_ssl_protocols=[cloudfront.OriginSslPolicy.TLS_V1_2],
            custom_headers={"X-Origin-Verify": origin_verify},
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
        self.cdn = cloudfront.Distribution(
            self, "WebCdn",
            comment="docsuri frontend (U5) - trusted HTTPS edge + authenticated origin",
            domain_names=[_APP_DOMAIN],
            certificate=viewer_cert,
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
            },
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
