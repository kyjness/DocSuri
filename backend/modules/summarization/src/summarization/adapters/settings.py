"""SummarizationSettings — env-driven config (infrastructure-design).

``summarization_enabled`` gates the real read path: the app-shell mounts U7 only when the
required deps (Bedrock model ids + S3 bucket) are configured — otherwise it skips
(fail-closed, no silent mock fallback; real-first).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# Concrete model bindings (TD-S3). modelVer is part of the immutable cache key.
DEFAULT_SUMMARY_MODEL = "anthropic.claude-sonnet-4-6"
DEFAULT_TRANSLATE_MODEL = "anthropic.claude-haiku-4-5"
MODEL_VER = "sonnet46-haiku45"


@dataclass(frozen=True, slots=True)
class SummarizationSettings:
    summary_model_id: str
    translate_model_id: str
    s3_bucket: str | None
    redis_url: str | None
    database_url: str | None
    region_name: str | None
    redis_ttl_seconds: int
    model_ver: str
    # FR-17 figure/table assets gate (BR-SF-11). The OA-license SIGNAL is the U1 ingestion gate:
    # only papers whose license is on OPEN_ACCESS_LICENSE_ALLOWLIST (CC-BY/CC-BY-SA/CC0) are stored
    # (BR-1 — non-OA rejected at ingestion), so every corpus paper is safe to render in-app and no
    # per-paper license lookup is needed. This flag is therefore an OPERATIONAL toggle (enable once
    # the `paper_asset` manifest + S3 presign IAM are provisioned), not a per-paper gate. OFF by
    # default → ``license_unavailable`` (no assets shown) until the team enables it at deploy.
    assets_enabled: bool = False
    # Presigned GET URL lifetime for asset images (SEC-9 — short-lived).
    asset_url_ttl_seconds: int = 600
    # doc-model rich-view gate (BR-30 / BR-SF-11). OA-license SIGNAL = the U1 ingestion gate: the
    # corpus only holds OA papers (CC-BY/CC-BY-SA/CC0 — BR-1, non-OA rejected at ingestion), so
    # in-app rich rendering is license-safe for any stored paper and no per-paper license check is
    # needed. This is an OPERATIONAL toggle (enable once the doc-model build queue + reader IAM are
    # provisioned — slice 6). OFF by default → ``license_unavailable`` (arXiv link-out) until the
    # team enables it at deploy. Read-only — U1 builds/caches lazily (D6).
    docmodel_viewer_enabled: bool = False
    # U1 ingestion queue URL for the lazy doc-model build trigger (BR-30/D6, boundary B). When
    # set (and the viewer is enabled), a read miss enqueues a BUILD_DOC_MODEL job and returns
    # ``building``; when unset, a miss stays ``source_unavailable`` (no build triggered).
    docmodel_build_queue_url: str | None = None
    # Long-input map-reduce summary gate (BR-S6, #135). OFF by default: the MAP_REDUCE band
    # abstains (``input_too_long``) as before. When ON, long papers (40K~120K tok) are
    # section-chunked → mapped → reduced. OVER_CAP still rejects.
    map_reduce_enabled: bool = False
    # Async long-summary job queue URL (BR-S8). When set (and map-reduce is on), the API enqueues
    # a background job on the MAP_REDUCE band and returns ``pending`` (the summarization worker
    # produces the result). When unset, map-reduce runs inline on the request (timeout risk).
    summary_job_queue_url: str | None = None

    @property
    def summarization_enabled(self) -> bool:
        # Real path requires Bedrock (always) + a permanent store bucket.
        return bool(self.s3_bucket)

    @classmethod
    def from_env(cls) -> SummarizationSettings:
        return cls(
            summary_model_id=os.environ.get("DOCSURI_SUMMARY_MODEL_ID", DEFAULT_SUMMARY_MODEL),
            translate_model_id=os.environ.get(
                "DOCSURI_TRANSLATE_MODEL_ID", DEFAULT_TRANSLATE_MODEL
            ),
            s3_bucket=os.environ.get("DOCSURI_SUMMARY_BUCKET"),
            redis_url=os.environ.get("DOCSURI_REDIS_URL"),
            database_url=os.environ.get("DATABASE_URL"),
            region_name=os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION"),
            redis_ttl_seconds=int(os.environ.get("DOCSURI_SUMMARY_TTL", "86400")),  # 24h (§11)
            model_ver=MODEL_VER,
            assets_enabled=os.environ.get("DOCSURI_MULTIMODAL_ASSETS_ENABLED", "").lower()
            in ("1", "true", "yes"),
            asset_url_ttl_seconds=int(os.environ.get("DOCSURI_ASSET_URL_TTL_SECONDS", "600")),
            docmodel_viewer_enabled=os.environ.get("DOCSURI_DOCMODEL_VIEWER_ENABLED", "").lower()
            in ("1", "true", "yes"),
            docmodel_build_queue_url=os.environ.get("DOCSURI_DOCMODEL_BUILD_QUEUE_URL"),
            map_reduce_enabled=os.environ.get("DOCSURI_MAP_REDUCE_ENABLED", "").lower()
            in ("1", "true", "yes"),
            summary_job_queue_url=os.environ.get("DOCSURI_SUMMARY_JOB_QUEUE_URL"),
        )
