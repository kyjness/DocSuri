"""S3DocModelReader — real ``DocModelReadPort`` (BR-30). Reads U1's cached doc-model.

The object layout mirrors U1's ``S3DocModelStore`` writer (``doc-model/{paperId}/v{ver}.json``);
a miss (NoSuchKey — not yet lazily built) or a license-disallowed object returns None so the
router surfaces ``source_unavailable``. Read-only: building/caching is U1's role (D6).
"""

from __future__ import annotations

import logging
from typing import Any

from docsuri_shared.dtos import DocModel

from ._paper_ref import bare_paper_id

logger = logging.getLogger(__name__)

# Mirrors U1's doc-model object layout (read-only capability).
_DOCMODEL_PREFIX = "doc-model"
# S3 error codes that mean a genuine lazy-miss (not-yet-built) → source_unavailable.
_MISS_CODES = {"NoSuchKey", "NoSuchBucket", "404"}


class S3DocModelReader:
    def __init__(
        self,
        *,
        bucket: str,
        region_name: str | None = None,
        client: Any | None = None,
        prefix: str = _DOCMODEL_PREFIX,
    ) -> None:
        if client is None:
            import boto3  # lazy

            client = boto3.client("s3", region_name=region_name)
        self._s3 = client
        self._bucket = bucket
        self._prefix = prefix.strip("/")

    def get_doc_model(self, paper_id: str, version: int) -> DocModel | None:
        from botocore.exceptions import ClientError

        key = f"{self._prefix}/{bare_paper_id(paper_id)}/v{version}.json"
        try:
            obj = self._s3.get_object(Bucket=self._bucket, Key=key)
            return DocModel.model_validate_json(obj["Body"].read())
        except ClientError as exc:
            # Only a genuine miss (not yet lazily built) is None → source_unavailable.
            # AccessDenied / throttling etc. must NOT masquerade as a miss — log + propagate
            # so a corpus-wide config failure is observable instead of silently degrading.
            if exc.response.get("Error", {}).get("Code") in _MISS_CODES:
                return None
            logger.warning("doc-model read failed for %s", key, exc_info=True)
            raise
        except Exception:
            # Parse / schema-version drift on a corrupt object — surface, don't mask as a miss.
            logger.exception("doc-model parse failed for %s", key)
            raise
