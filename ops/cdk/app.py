#!/usr/bin/env python3
"""DocSuri CDK app — provisions the system-wide infrastructure defined in
aidlc-docs/construction/infrastructure-design/infrastructure-design.md.

Usage:
    cd ops/cdk && cdk synth   # synthesize CloudFormation
    cd ops/cdk && cdk deploy  # provision to AWS (ap-northeast-2)

Stacks are split by lifecycle/blast-radius so a network change doesn't redeploy compute."""

import aws_cdk as cdk
from stacks.access_stack import AccessStack
from stacks.compute_stack import ComputeStack
from stacks.frontend_stack import FrontendStack
from stacks.ingestion_stack import IngestionStack
from stacks.network_stack import NetworkStack
from stacks.novelty_stack import NoveltyStack
from stacks.search_stack import SearchStack
from stacks.summarization_stack import SummarizationStack

app = cdk.App()

env = cdk.Environment(account="028317349537", region="ap-northeast-2")


def _required_context(name: str) -> str:
    value = app.node.try_get_context(name)
    if value is None or str(value).strip() == "":
        raise ValueError(f"Missing CDK context value: {name}")
    return str(value)


network = NetworkStack(app, "Docsuri-Network", env=env)
search = SearchStack(app, "Docsuri-Search", vpc=network.vpc, env=env)
compute = ComputeStack(
    app, "Docsuri-Compute",
    vpc=network.vpc,
    opensearch_domain=search.domain,
    env=env,
)
ingestion = IngestionStack(
    app, "Docsuri-Ingestion",
    vpc=network.vpc,
    opensearch_domain=search.domain,
    env=env,
)
# Deploy unit ④ — U7 summarization worker (long-summary async jobs, BR-S6/BR-S12). Code/synth
# only; the team owns deploy. Reuses the docsuri-api image + papers bucket (by name).
summarization = SummarizationStack(
    app, "Docsuri-Summarization",
    vpc=network.vpc,
    env=env,
)
# Deploy unit ⑪ — novelty formation agent worker. Code/synth only; deploy remains
# team-owned. The unit is active when deployed (NOVELTY_AGENT_ENABLED=true).
novelty = NoveltyStack(
    app, "Docsuri-Novelty",
    vpc=network.vpc,
    db_endpoint=_required_context("novelty_db_endpoint"),
    db_port=int(_required_context("novelty_db_port")),
    db_security_group_id=_required_context("novelty_db_security_group_id"),
    db_secret_arn=_required_context("novelty_db_secret_arn"),
    env=env,
)
# Deploy unit ④ — U5 frontend. The BFF (server-side) calls the backend gateway over its
# CloudFront HTTPS URL (which injects the origin-auth secret on the way to the backend ALB).
frontend = FrontendStack(
    app, "Docsuri-Frontend",
    vpc=network.vpc,
    gateway_url=f"https://{compute.cdn.distribution_domain_name}",
    env=env,
)

# Cross-account 팀 접근 (Option B) — 신뢰할 팀원 홈 계정 (감사 가능하도록 여기서 관리).
# 부여/회수 = 목록 수정 + PR + cdk deploy Docsuri-Access.
TEAM_ACCOUNT_IDS = ["997784789037", "416963226971", "143495498927"]
AccessStack(app, "Docsuri-Access", account_ids=TEAM_ACCOUNT_IDS, env=env)

app.synth()
