"""GitHub Actions OIDC 프로바이더 + CD 역할 (배포 유닛 ①②④).

감사에서 확인(2026-07-01): 계정 028317349537에 GitHub OIDC 프로바이더도 CD 역할도 부재 →
cd.yml이 한 번도 AWS에 인증하지 못했음(완전 휴면의 근본 원인). 이 스택이 그 공백을 IaC로 메운다.

- OIDC 프로바이더: token.actions.githubusercontent.com (audience = sts.amazonaws.com), 계정당 1개.
- CD 역할: 신뢰를 **이 repo의 v* 릴리스 태그**로 한정(cd.yml이 태그 트리거). 다른 브랜치/포크/repo는
  assume 불가. 권한 = ECR 로그인 + 3개 리포 push + ECS 3개 서비스 update/describe(강제 새 배포·
  안정화 대기)만. register-task-definition을 하지 않으므로 iam:PassRole 불필요.

배포:
    cdk deploy Docsuri-CICD
배포 후(파일 밖): 출력된 역할 ARN을 GitHub org 변수 CD_ROLE_ARN 에 설정(cd.yml이 vars.CD_ROLE_ARN
사용). 신뢰 sub가 refs/tags/v* 라 태그 트리거 CD와 정합."""

from aws_cdk import CfnOutput, Stack
from aws_cdk import aws_iam as iam
from constructs import Construct

# 이 repo만 신뢰. 두 배포 진입점의 OIDC sub를 모두 허용(least privilege 유지):
#   • v* 태그 직접 push(수동/hotfix)         → ref:refs/tags/v*
#   • release.yml(push:main)이 cd.yml 재사용 호출 → ref:refs/heads/main (호출자 브랜치 ref)
# main은 보호 브랜치이고 이 역할은 OIDC 전용 배포 역할이라 main-ref 허용은 안전.
_GITHUB_REPO = "80-hours-a-week/DocSuri"
_TRUSTED_SUBS = [
    f"repo:{_GITHUB_REPO}:ref:refs/tags/v*",
    f"repo:{_GITHUB_REPO}:ref:refs/heads/main",
]
_ECR_REPOS = ["docsuri-api", "docsuri-ingestion", "docsuri-frontend"]
_ECS_CLUSTER = "docsuri"
# (cluster, service). Frontend runs on its OWN cluster (frontend_stack.py), not `docsuri`;
# scoping it to `docsuri` builds service/docsuri/docsuri-frontend and ecs:UpdateService is denied.
_ECS_SERVICES = [
    (_ECS_CLUSTER, "docsuri-api"),
    (_ECS_CLUSTER, "docsuri-ingestion"),
    (_ECS_CLUSTER, "docsuri-novelty-agent-worker"),
    ("docsuri-frontend", "docsuri-frontend"),
]


class CicdStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # 계정당 1개. 라이브 스택이 이 리소스를 L2(Custom::AWSCDKOpenIdConnectProvider,
        # 논리 ID GithubOidcProviderD8241A88)로 이미 소유 중(2026-07-02 확인) — L1
        # CfnOIDCProvider로 바꾸면 새 리소스 생성을 시도해 EntityAlreadyExists로 배포가
        # 깨진다. 같은 construct id의 L2를 유지해야 논리 ID가 일치해 no-op diff가 된다.
        provider = iam.OpenIdConnectProvider(
            self, "GithubOidcProvider",
            url="https://token.actions.githubusercontent.com",
            client_ids=["sts.amazonaws.com"],
        )

        # 신뢰: 이 provider + aud=sts + sub가 이 repo의 v* 태그 또는 main 브랜치일 때만 assume 허용.
        principal = iam.FederatedPrincipal(
            provider.open_id_connect_provider_arn,
            conditions={
                "StringEquals": {
                    "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
                },
                "StringLike": {
                    "token.actions.githubusercontent.com:sub": _TRUSTED_SUBS,
                },
            },
            assume_role_action="sts:AssumeRoleWithWebIdentity",
        )

        role = iam.Role(
            self, "GithubActionsCdRole",
            role_name="docsuri-github-actions-cd",
            assumed_by=principal,
            # IAM description must be ASCII (regex [\t\n\r\x20-\x7E\xA1-\xFF]*): Korean/em-dash
            # are rejected. Keep plain ASCII; the Korean rationale lives in the docstring.
            description="GitHub Actions (cd.yml) OIDC deploy role - v* tags, ECR + ECS.",
        )

        # ECR 로그인 토큰은 계정 전역이라 리소스 스코프 불가.
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["ecr:GetAuthorizationToken"],
                resources=["*"],
            )
        )
        # 이미지 push/pull은 3개 리포로 한정.
        role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "ecr:BatchCheckLayerAvailability",
                    "ecr:InitiateLayerUpload",
                    "ecr:UploadLayerPart",
                    "ecr:CompleteLayerUpload",
                    "ecr:PutImage",
                    "ecr:BatchGetImage",
                    "ecr:GetDownloadUrlForLayer",
                ],
                resources=[
                    f"arn:aws:ecr:{self.region}:{self.account}:repository/{repo}"
                    for repo in _ECR_REPOS
                ],
            )
        )
        # 배포: 강제 새 배포 + 안정화 대기. 태스크 정의를 새로 등록하지 않으므로 PassRole 불필요.
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["ecs:UpdateService", "ecs:DescribeServices"],
                resources=[
                    f"arn:aws:ecs:{self.region}:{self.account}:service/{cluster}/{svc}"
                    for cluster, svc in _ECS_SERVICES
                ],
            )
        )

        CfnOutput(
            self, "CdRoleArn",
            value=role.role_arn,
            description="Role ARN cd.yml assumes (inlined in cd.yml env; no GitHub var needed).",
        )
