"""Rerank client region resolution — it must NOT default to the Seoul deploy region, since the
rerank model only exists cross-region (Tokyo/us-west-2). Regression for the deploy-wiring fix."""

from __future__ import annotations

from discovery.adapters.settings import DiscoverySettings, _region_from_arn

TOKYO_ARN = "arn:aws:bedrock:ap-northeast-1::foundation-model/cohere.rerank-v3-5:0"


def _s(**kw) -> DiscoverySettings:
    return DiscoverySettings(aws_region="ap-northeast-2", **kw)


def test_region_from_arn() -> None:
    assert _region_from_arn(TOKYO_ARN) == "ap-northeast-1"
    assert _region_from_arn(None) is None
    assert _region_from_arn("not-an-arn") is None
    # ARN with an empty region segment (partition-global FM) → None.
    assert _region_from_arn("arn:aws:bedrock:::foundation-model/cohere.rerank-v3-5:0") is None


def test_explicit_rerank_region_wins() -> None:
    s = _s(rerank_model_arn=TOKYO_ARN, rerank_region="us-west-2")
    assert s.rerank_region_resolved == "us-west-2"


def test_region_derived_from_arn_when_unset() -> None:
    s = _s(rerank_model_arn=TOKYO_ARN)
    # Derived from the ARN — crucially NOT the Seoul deploy region (aws_region).
    assert s.rerank_region_resolved == "ap-northeast-1"


def test_falls_back_to_aws_region_only_without_arn_region() -> None:
    s = _s(rerank_model_arn="arn:aws:bedrock:::foundation-model/cohere.rerank-v3-5:0")
    assert s.rerank_region_resolved == "ap-northeast-2"
