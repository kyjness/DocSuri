"""Cross-account 팀 접근 (Option B) — 팀원의 자체 AWS 계정이 028317349537로 assume.

각 팀원의 홈 계정을 신뢰하고, MFA로 DocsuriCrossAccountDev를 assume → Administrator
(인프라 전체 조회·조작). 정식 배포는 여전히 CI OIDC 파이프라인 권장 — 이 역할은
콘솔/CLI/디버그용. 사용 제한은 IAM이 아니라 런북 §9 운영 규약으로 부여.

신뢰 계정 목록은 app.py의 TEAM_ACCOUNT_IDS (버전 관리 → 부여/회수가 PR diff로 감사됨).
배포:
    cdk deploy Docsuri-Access"""

from aws_cdk import CfnOutput, Duration, Stack
from aws_cdk import aws_iam as iam
from constructs import Construct


class AccessStack(Stack):
    def __init__(
        self, scope: Construct, construct_id: str,
        *, account_ids: list[str], **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        if not account_ids:
            raise ValueError("account_ids 비어있음 — 신뢰할 팀원 계정 ID 필요")

        # 신뢰 계정 전체에 단일 trust statement + MFA 조건 (보안 경계, 옵션 아님).
        trusted = iam.PrincipalWithConditions(
            iam.CompositePrincipal(
                *[iam.AccountPrincipal(aid) for aid in account_ids]
            ),
            {"Bool": {"aws:MultiFactorAuthPresent": "true"}},
        )

        role = iam.Role(
            self, "CrossAccountDev",
            role_name="DocsuriCrossAccountDev",
            assumed_by=trusted,
            managed_policies=[
                # 인프라 전체 가시성·조작을 위해 AdministratorAccess 부여(IAM/결제 포함).
                # 사용 제한(무엇을 만지지 말 것 등)은 IAM이 아니라 런북 §9로 운영 규약화.
                # 경계는 trust(3계정·MFA·4h 세션)와 PR-감사되는 TEAM_ACCOUNT_IDS가 담당.
                iam.ManagedPolicy.from_aws_managed_policy_name("AdministratorAccess"),
            ],
            # 12h 세션 — 운영 중 수동으로 상향된 라이브 값(43200s)을 코드화해 드리프트 제거.
            # MFA(trust 조건)가 1차 경계이고, 세션 길이는 편의↔보안 트레이드오프로 12h 채택.
            max_session_duration=Duration.hours(12),
        )

        CfnOutput(
            self, "CrossAccountDevRoleArn",
            value=role.role_arn,
            description="팀원이 assume할 역할 ARN (CLI 프로필 role_arn에 사용)",
        )
