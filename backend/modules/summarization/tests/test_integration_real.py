"""Integration tests against real S3/Redis/Postgres services (real-first, Q14/Q7-Q10 infra).

Originally these ran against AWS. That deployment is retired, so they targeted infrastructure
that no longer exists and skipped everywhere — including CI. They now run against the
**solo-local stack** instead: an S3-compatible endpoint (s3proxy locally, MinIO in CI), redis, and
postgres. No adapter code changed for this — boto3 >= 1.28 honours ``AWS_ENDPOINT_URL_S3``, which
is exactly why that substitution was chosen (see ``aidlc-docs/operations/solo-local-migration.md``).

Round-trips matter more here than they look. ``S3RedisSummaryStore.get`` and
``S3FullTextSource.get_full_text`` both swallow every exception and return ``None``, so a wrong
bucket, an unreachable endpoint, or a key-derivation bug is indistinguishable from a cache miss —
the read path degrades silently and forever. Only writing and then reading back proves otherwise.

Self-skips when the stack is absent, so a bare checkout stays green.
"""

from __future__ import annotations

import os
import uuid

import pytest


def _missing(mod: str) -> bool:
    try:
        __import__(mod)
        return False
    except ImportError:
        return True


BUCKET = os.environ.get("DOCSURI_SUMMARY_BUCKET")

pytestmark = pytest.mark.skipif(
    _missing("boto3") or _missing("redis") or not BUCKET,
    reason="local stack absent (boto3 / redis / DOCSURI_SUMMARY_BUCKET) — see module docstring",
)


@pytest.fixture(scope="module")
def s3():
    """A client for the configured endpoint, with the bucket created if it isn't there yet.

    Skips rather than fails when the endpoint is unreachable: an env var pointing at a stack that
    is not running is a local-setup problem, not a defect in the code under test.
    """
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError

    client = boto3.client("s3", region_name=os.environ.get("AWS_REGION") or "us-east-1")
    try:
        client.list_buckets()
    except (BotoCoreError, ClientError) as exc:  # pragma: no cover - environment issue
        pytest.skip(f"S3 endpoint configured but not reachable: {exc}")
    try:
        client.head_bucket(Bucket=BUCKET)
    except ClientError:
        client.create_bucket(Bucket=BUCKET)
    return client


@pytest.fixture
def cache_key():
    from summarization.domain.models import Persona, Scope, SummaryCacheKey, TargetLang, Task

    # A unique paper id per test so a rerun cannot pass on the previous run's object.
    return SummaryCacheKey(
        paper_id=f"9999.{uuid.uuid4().hex[:8]}",
        version=1,
        task=Task.SUMMARY,
        target_lang=TargetLang.KO,
        scope=Scope.FULL,
        persona=Persona.EXPERT,
        glossary_ver=0,
        model_ver="test-model",
        prompt_ver="test-prompt",
    )


def _store(*, with_redis: bool):
    from summarization.adapters.s3_redis_store import S3RedisSummaryStore

    return S3RedisSummaryStore(
        bucket=BUCKET or "",
        ttl_seconds=60,
        region_name=os.environ.get("AWS_REGION") or "us-east-1",
        redis_url=os.environ.get("DOCSURI_REDIS_URL") if with_redis else None,
    )


def test_summary_round_trips_through_real_s3(s3, cache_key) -> None:
    # S3 alone (no redis client), so the object store is what answers — not the hot tier.
    store = _store(with_redis=False)
    payload = {"summary": "요약 본문", "sections": [{"heading": "서론", "text": "내용"}]}

    assert store.get(cache_key) is None, "a fresh key must miss before anything is written"
    store.put(cache_key, payload)

    got = store.get(cache_key)
    assert got == payload, "the durable tier did not return what was written"
    # Non-ASCII must survive the JSON encode/decode round-trip (payloads are Korean).
    assert got["summary"] == "요약 본문"

    # And it really is at the contract path, not wherever the adapter happened to put it.
    body = s3.get_object(Bucket=BUCKET, Key=cache_key.object_path())["Body"].read()
    assert "요약 본문" in body.decode("utf-8")

    s3.delete_object(Bucket=BUCKET, Key=cache_key.object_path())


@pytest.mark.skipif(
    not os.environ.get("DOCSURI_REDIS_URL"), reason="DOCSURI_REDIS_URL not set (hot tier)"
)
def test_put_populates_the_hot_tier_and_get_serves_from_it(s3, cache_key) -> None:
    """Redis is the accelerator; a put must prime it, and a get must prefer it.

    The hot-tier write is best-effort (exceptions swallowed by design), so a broken redis shows up
    only as permanently cold reads. Assert the key is actually there, then delete the S3 object
    and confirm the read still succeeds — which it can only do from redis.
    """
    import redis

    store = _store(with_redis=True)
    payload = {"summary": "핫 티어 확인"}
    store.put(cache_key, payload)

    client = redis.Redis.from_url(os.environ["DOCSURI_REDIS_URL"])
    assert client.get(cache_key.redis_key()), "put did not prime the hot tier"

    s3.delete_object(Bucket=BUCKET, Key=cache_key.object_path())
    assert store.get(cache_key) == payload, "get did not serve from the hot tier"

    client.delete(cache_key.redis_key())


def test_full_text_round_trip_pins_the_key_derivation(s3) -> None:
    """U1 writes full text under the BARE id; the app asks with a version suffix.

    ``S3FullTextSource`` strips the suffix to match. If that derivation ever drifts, the read
    returns None — the summary quietly falls back to the abstract instead of failing, so nothing
    surfaces. Write where U1 writes, read the way the app asks.
    """
    from summarization.adapters.s3_full_text import S3FullTextSource

    bare = f"9999.{uuid.uuid4().hex[:8]}"
    key = f"full-text/{bare}/v1.txt"
    s3.put_object(Bucket=BUCKET, Key=key, Body="본문 전체 텍스트".encode())

    source = S3FullTextSource(
        bucket=BUCKET or "", region_name=os.environ.get("AWS_REGION") or "us-east-1"
    )
    assert source.get_full_text(f"{bare}v1", 1) == "본문 전체 텍스트"
    assert source.get_full_text(bare, 1) == "본문 전체 텍스트"
    # A genuinely absent paper is a miss, not an error.
    assert source.get_full_text(f"9999.{uuid.uuid4().hex[:8]}", 1) is None

    s3.delete_object(Bucket=BUCKET, Key=key)


def test_real_bundle_builds() -> None:
    """The wiring smoke test this module started as — every real adapter constructs together."""
    from docsuri_shared.ports import CostGuardCircuitBreaker  # noqa: F401

    from summarization.adapters.settings import SummarizationSettings
    from summarization.real_wiring import build_real_orchestrator

    settings = SummarizationSettings.from_env()
    assert settings.summarization_enabled

    class _Budget:
        degrade_mode = "normal"
        circuit_state = "closed"
        tier = "normal"

    class _Cost:
        def get_budget_state(self):
            return _Budget()

    class _Obs:
        def emit_metric(self, *a, **k):
            pass

        def emit_log(self, *a, **k):
            pass

        def start_span(self, *a, **k):
            return None

        def audit_append(self, *a, **k):
            pass

    bundle = build_real_orchestrator(settings, cost_guard=_Cost(), observability=_Obs())
    assert bundle.orchestrator is not None
