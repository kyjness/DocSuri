"""X-Origin-Verify secrets, pinned in SSM Parameter Store so synth is deterministic.

Each secret proves a request came from OUR CloudFront (not just any CloudFront in the shared
origin-facing prefix list — the confused-deputy): CloudFront injects it as a header and the backend
ALB 403s requests without it. There are three:
  • api    — backend API origin (ComputeStack ApiCdn → origin.docsuri.org)
  • web    — frontend web origin (FrontendStack WebCdn → app-origin.docsuri.org)
  • social — shared /auth/social/* edge route; FrontendStack's WebCdn sends it and ComputeStack's
             ALB accepts it as a SECOND value (Option A, FR-27), so the two MUST match.

Read at DEPLOY time via a CloudFormation SSM-parameter reference, NOT generated per-synth: the value
never lands in the synthesized template or the git-tracked cdk.context.json, and is identical across
synths — so `cdk deploy` on an unchanged tree is a true no-op instead of rotating the secret and
briefly 403-ing the origin while the CloudFront distribution update propagates.

One-time setup (String, NOT SecureString — CloudFront custom headers can't read ssm-secure refs;
these are origin-verification shared secrets guarded by IAM, not user credentials):
    for k in api web social; do
      aws ssm put-parameter --name "/docsuri/origin-verify/$k" --type String \
        --value "$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')"
    done
Rotate by `aws ssm put-parameter --overwrite` then redeploy ComputeStack + FrontendStack.
"""

from aws_cdk import aws_ssm as ssm
from constructs import Construct

_API_PARAM = "/docsuri/origin-verify/api"
_WEB_PARAM = "/docsuri/origin-verify/web"
_SOCIAL_PARAM = "/docsuri/origin-verify/social"


def api_origin_verify_secret(scope: Construct) -> str:
    return ssm.StringParameter.value_for_string_parameter(scope, _API_PARAM)


def web_origin_verify_secret(scope: Construct) -> str:
    return ssm.StringParameter.value_for_string_parameter(scope, _WEB_PARAM)


def social_origin_verify_secret(scope: Construct) -> str:
    return ssm.StringParameter.value_for_string_parameter(scope, _SOCIAL_PARAM)
