"""SummaryStore — real two-tier store (TD-S5): Redis hot (TTL) + S3 permanent.

read-through: Redis ``sum:`` → miss → S3 ``summaries/`` → miss → None.
write-through: S3 (permanent, immutable key) + Redis (hot, TTL). Cache misses read the
origin and backfill; the hot tier always carries a TTL (no never-expiring keys).
"""

from __future__ import annotations

import json
from typing import Any

from ..domain.models import SummaryCacheKey


class S3RedisSummaryStore:
    def __init__(
        self,
        *,
        bucket: str,
        ttl_seconds: int,
        region_name: str | None = None,
        s3_client: Any | None = None,
        redis_client: Any | None = None,
        redis_url: str | None = None,
    ) -> None:
        if s3_client is None:
            import boto3  # lazy

            s3_client = boto3.client("s3", region_name=region_name)
        if redis_client is None and redis_url:
            import redis  # lazy

            redis_client = redis.Redis.from_url(redis_url)
        self._s3 = s3_client
        self._redis = redis_client
        self._bucket = bucket
        self._ttl = ttl_seconds

    def get(self, key: SummaryCacheKey) -> dict | None:
        rk = key.redis_key()
        if self._redis is not None:
            try:
                hot = self._redis.get(rk)
                if hot:
                    return json.loads(hot)
            except Exception:  # noqa: BLE001, S110 — hot tier best-effort; fall through to S3
                pass
        try:
            obj = self._s3.get_object(Bucket=self._bucket, Key=key.object_path())
            payload = json.loads(obj["Body"].read().decode("utf-8"))
        except Exception:  # noqa: BLE001 — miss (NoSuchKey) or transient S3 error
            return None
        self._backfill_hot(rk, payload)
        return payload

    def put(self, key: SummaryCacheKey, payload: dict) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        # S3 first (durable truth); Redis is the accelerator.
        self._s3.put_object(
            Bucket=self._bucket,
            Key=key.object_path(),
            Body=data,
            ContentType="application/json",
        )
        self._backfill_hot(key.redis_key(), payload)

    def put_transient(self, key: SummaryCacheKey, payload: dict, *, ttl_seconds: int) -> None:
        # Hot-tier-only write with a short TTL — deliberately NOT persisted to S3. Hands a polled
        # abstain back to the client on the next poll, then self-expires so a later retry
        # re-evaluates (never pins a possibly-transient abstain permanently). No-op without Redis —
        # degrades to the pre-existing behaviour (the poll keeps re-enqueuing), so no regression.
        if self._redis is None:
            return
        try:
            data = json.dumps(payload, ensure_ascii=False)
            self._redis.set(key.redis_key(), data, ex=ttl_seconds)
        except Exception:  # noqa: BLE001, S110 — hot-tier write is best-effort
            pass

    def _backfill_hot(self, redis_key: str, payload: dict) -> None:
        if self._redis is None:
            return
        try:
            self._redis.set(redis_key, json.dumps(payload, ensure_ascii=False), ex=self._ttl)
        except Exception:  # noqa: BLE001, S110 — hot-tier write is best-effort
            pass
