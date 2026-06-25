"""S3FullTextSource — real ``FullTextSourcePort`` (TD-S5). Reads U1's stored full text.

The object layout mirrors U1's writer (``stored_full_text_ref``); a miss (NoSuchKey) or a
license-disallowed object returns None so the orchestrator falls back to the abstract (Q1).
"""

from __future__ import annotations

from typing import Any

from ._paper_ref import bare_paper_id

# Mirrors U1's full-text object layout (read-only capability).
_FULL_TEXT_PREFIX = "full-text"


class S3FullTextSource:
    def __init__(
        self,
        *,
        bucket: str,
        region_name: str | None = None,
        client: Any | None = None,
        prefix: str = _FULL_TEXT_PREFIX,
    ) -> None:
        if client is None:
            import boto3  # lazy

            client = boto3.client("s3", region_name=region_name)
        self._s3 = client
        self._bucket = bucket
        self._prefix = prefix

    def get_full_text(self, paper_id: str, version: int) -> str | None:
        # U1 keys full text on the bare id (full-text/{bareId}/v{ver}.txt); strip the version
        # suffix the app carries so the read matches the write (else perpetual miss → no
        # full-text fallback for summary/translation).
        key = f"{self._prefix}/{bare_paper_id(paper_id)}/v{version}.txt"
        try:
            obj = self._s3.get_object(Bucket=self._bucket, Key=key)
            return obj["Body"].read().decode("utf-8")
        except Exception:  # noqa: BLE001 — miss / license-disallowed → abstract fallback (Q1)
            return None
