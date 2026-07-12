from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field, SecretStr, ValidationError


class SecretSetting(BaseModel):
    value: SecretStr

    def __repr__(self) -> str:
        return "SecretSetting(value=**********)"


class IngestionSettings(BaseModel):
    env: str = Field(default="local", alias="DOCSURI_ENV")
    aws_region: str | None = Field(default=None, alias="DOCSURI_AWS_REGION")
    s3_bucket: str | None = Field(default=None, alias="DOCSURI_S3_BUCKET")
    bedrock_model_id: str | None = Field(default=None, alias="DOCSURI_BEDROCK_MODEL_ID")
    bedrock_model_id_v2: str | None = Field(default=None, alias="DOCSURI_BEDROCK_MODEL_ID_V2")
    opensearch_endpoint: str | None = Field(default=None, alias="DOCSURI_OPENSEARCH_ENDPOINT")
    opensearch_index: str = Field(default="docsuri-corpus-v1", alias="DOCSURI_OPENSEARCH_INDEX")
    opensearch_index_v2: str = Field(
        default="docsuri-corpus-v2", alias="DOCSURI_OPENSEARCH_INDEX_V2"
    )
    opensearch_alias: str = Field(default="docsuri-corpus", alias="DOCSURI_OPENSEARCH_ALIAS")
    # Fast re-embed rebuild knobs (see reembed.py / runbook): reindex the existing corpus into a
    # fresh bulk-tuned target, then alias-swap. reembed_shard_* slice the source across a fan-out
    # of one-off ECS tasks so the wall-clock re-index window is as short as possible.
    opensearch_index_reembed: str = Field(
        default="docsuri-corpus-v3", alias="DOCSURI_OPENSEARCH_INDEX_REEMBED"
    )
    reembed_source: str | None = Field(default=None, alias="DOCSURI_REEMBED_SOURCE")
    reembed_shards: int = Field(default=6, alias="DOCSURI_REEMBED_SHARDS")
    reembed_shard_index: int = Field(default=0, alias="DOCSURI_REEMBED_SHARD")
    reembed_shard_count: int = Field(default=1, alias="DOCSURI_REEMBED_SHARD_COUNT")
    reembed_batch_size: int = Field(default=96, alias="DOCSURI_REEMBED_BATCH_SIZE")  # <=96
    reembed_min_documents: int = Field(default=1, alias="DOCSURI_REEMBED_MIN_DOCUMENTS")
    reembed_copy_rps: int = Field(default=-1, alias="DOCSURI_REEMBED_COPY_RPS")  # -1 = unlimited
    # None → frozen spec width (1024). Set to Cohere v4's 1536 default for a dimension-changing
    # re-embed; the target index + embed both use it. Cutover then needs a coordinated vector-spec
    # bump + reader redeploy (same-space invariant) or search breaks — see the runbook.
    reembed_dimension: int | None = Field(default=None, alias="DOCSURI_REEMBED_DIMENSION")
    # >0 → client-side embed pacing: cap aggregate Bedrock throughput to this many tokens/min so a
    # binding, non-adjustable on-demand quota (Cohere v4 = 300k/min = 432M/day) never throttle-
    # storms the run — one paced task grinds continuously under both caps. Also turns on mget-skip
    # resumability (skip docs already in the target) so a killed multi-day task can be relaunched
    # without re-embedding. 0 = off → unpaced (needs quota headroom); live path byte-identical.
    reembed_target_tpm: int = Field(default=0, alias="DOCSURI_REEMBED_TARGET_TPM")
    # Decouple the Bedrock embed region from DOCSURI_AWS_REGION (which signs the VPC OpenSearch
    # client). Lets a re-embed shard scroll/write the in-VPC domain (ap-northeast-2) while invoking
    # the embed model in ANOTHER region — the basis of a multi-region fan-out across per-region
    # on-demand buckets (e.g. Cohere Embed Multilingual v3, which has NO daily cap, only 300k TPM
    # per region). None → embed in DOCSURI_AWS_REGION (unchanged single-region behaviour).
    reembed_embed_region: str | None = Field(default=None, alias="DOCSURI_REEMBED_EMBED_REGION")
    # Live harvester embed region, decoupled from DOCSURI_AWS_REGION (which signs VPC OpenSearch).
    # Cohere Embed Multilingual v3 is NOT in ap-northeast-2, so the worker must embed new papers
    # cross-region once on v3. None → embed in DOCSURI_AWS_REGION (unchanged single-region path).
    embed_region: str | None = Field(default=None, alias="DOCSURI_EMBED_REGION")
    # B3 fast full-re-parse (raw cache + bulk PDF prime + offline re-parse; see reparse.py /
    # raw_backfill.py / runbook). Default OFF → the live fetch path stays byte-identical.
    raw_cache_mode: Literal["off", "prefer", "only"] = Field(
        default="off", alias="DOCSURI_RAW_CACHE_MODE"
    )
    raw_cache_prefix: str = Field(default="raw", alias="DOCSURI_RAW_CACHE_PREFIX")
    # arXiv requester-pays bulk PDF bucket + optional YYMM month shards (csv, e.g. "2501,2502").
    arxiv_bulk_bucket: str = Field(default="arxiv", alias="DOCSURI_ARXIV_BULK_BUCKET")
    raw_backfill_months: str | None = Field(default=None, alias="DOCSURI_RAW_BACKFILL_MONTHS")
    control_plane_dsn: str | None = Field(default=None, alias="DOCSURI_CONTROL_PLANE_DSN")
    sqs_queue_url: str | None = Field(default=None, alias="DOCSURI_SQS_QUEUE_URL")
    sqs_dlq_url: str | None = Field(default=None, alias="DOCSURI_SQS_DLQ_URL")
    # Priority doc-model build queue (BR-30/D6). Separate from the bulk ingestion queue so
    # reader-triggered BUILD_DOC_MODEL jobs (viewer/citation tree) are not starved behind a large
    # backfill. Optional — unset → worker polls only the main queue (backward compatible).
    docmodel_queue_url: str | None = Field(default=None, alias="DOCSURI_DOCMODEL_QUEUE_URL")
    docmodel_dlq_url: str | None = Field(default=None, alias="DOCSURI_DOCMODEL_DLQ_URL")
    corpus_sources: str = Field(
        default="ARXIV,SEMANTIC_SCHOLAR,OPENALEX", alias="DOCSURI_CORPUS_SOURCES"
    )
    grobid_url: str | None = Field(default=None, alias="DOCSURI_GROBID_URL")
    semantic_scholar_api_key: str | None = Field(
        default=None, alias="DOCSURI_SEMANTIC_SCHOLAR_API_KEY"
    )
    # OpenAlex "polite pool" contact — sent as the `mailto` query param. Without it requests land
    # in the throttled common pool and 429 (observed on the very first /works page). Email kept
    # out of source; supplied via env.
    openalex_mailto: str | None = Field(default=None, alias="DOCSURI_OPENALEX_MAILTO")
    request_timeout_seconds: float = Field(default=30.0, alias="DOCSURI_REQUEST_TIMEOUT_SECONDS")
    # Wall-clock cap for one resilience dependency_call. Must exceed the worst LEGITIMATE
    # multi-request chain (politeness-paced html→ar5iv→pdf + pdfplumber on a big PDF ≈ 2-3 min);
    # 30s (= one request's timeout) killed slow-but-healthy papers and tripped the arxiv
    # circuit breaker into fast-fail storms (2026-07-02 drain incident).
    dependency_timeout_seconds: float = Field(
        default=180.0, alias="DOCSURI_DEPENDENCY_TIMEOUT_SECONDS"
    )
    index_stats_ttl_seconds: float = Field(default=60.0, alias="DOCSURI_INDEX_STATS_TTL_SECONDS")
    arxiv_rate_per_second: float = Field(default=0.33, alias="DOCSURI_ARXIV_RATE_PER_SECOND")
    worker_max_messages: int = Field(default=1, alias="DOCSURI_WORKER_MAX_MESSAGES")
    worker_loop_delay_seconds: float = Field(
        default=3.0, alias="DOCSURI_WORKER_LOOP_DELAY_SECONDS"
    )
    worker_queue_mode: Literal["all", "bulk", "docmodel"] = Field(
        default="all", alias="DOCSURI_WORKER_QUEUE_MODE"
    )
    max_chunks_per_paper: int = Field(default=128, alias="DOCSURI_MAX_CHUNKS_PER_PAPER")
    max_chunk_chars: int = Field(default=2400, alias="DOCSURI_MAX_CHUNK_CHARS")
    chunk_overlap_chars: int = Field(default=240, alias="DOCSURI_CHUNK_OVERLAP_CHARS")
    # FR-17 multimodal assets (display-only). Safe default OFF — base worker unaffected.
    multimodal_assets_enabled: bool = Field(
        default=False, alias="DOCSURI_MULTIMODAL_ASSETS_ENABLED"
    )
    corpus_build_rollout_confirmed: bool = Field(
        default=False, alias="DOCSURI_CORPUS_BUILD_ROLLOUT_CONFIRMED"
    )
    asset_s3_prefix: str = Field(default="assets", alias="DOCSURI_ASSET_S3_PREFIX")
    asset_max_longest_side: int = Field(default=2048, alias="DOCSURI_ASSET_MAX_LONGEST_SIDE")
    asset_max_pixels: int = Field(default=30_000_000, alias="DOCSURI_ASSET_MAX_PIXELS")
    asset_webp_quality: int = Field(default=80, alias="DOCSURI_ASSET_WEBP_QUALITY")
    asset_kms_key_id: str | None = Field(default=None, alias="DOCSURI_ASSET_KMS_KEY_ID")
    asset_fetch_timeout_seconds: float = Field(
        default=20.0, alias="DOCSURI_ASSET_FETCH_TIMEOUT_SECONDS"
    )
    user_document_max_bytes: int = Field(
        default=10 * 1024 * 1024, alias="DOCSURI_USER_DOCUMENT_MAX_BYTES"
    )

    @classmethod
    def from_env(cls) -> IngestionSettings:
        values = {name: os.environ[name] for name in os.environ if name.startswith("DOCSURI_")}
        return cls.model_validate(values)

    def require_production(self) -> None:
        missing = [
            field
            for field in (
                "aws_region",
                "s3_bucket",
                "bedrock_model_id",
                "opensearch_endpoint",
                "control_plane_dsn",
                "sqs_queue_url",
                "sqs_dlq_url",
            )
            if getattr(self, field) in (None, "")
        ]
        if missing:
            raise RuntimeError(f"missing required production settings: {', '.join(missing)}")

    def safe_log_dict(self) -> dict[str, object]:
        data = self.model_dump(by_alias=False)
        for key in list(data):
            if "dsn" in key.lower() or "url" in key.lower() or "endpoint" in key.lower():
                if data[key]:
                    data[key] = "***configured***"
        return data


def validate_corpus_build_settings(settings: IngestionSettings) -> None:
    if settings.env == "local":
        return
    sources = {part.strip() for part in settings.corpus_sources.split(",") if part.strip()}
    errors: list[str] = []
    if not settings.multimodal_assets_enabled:
        errors.append("DOCSURI_MULTIMODAL_ASSETS_ENABLED must be true before corpus build")
    if settings.bedrock_model_id_v2:
        errors.append("DOCSURI_BEDROCK_MODEL_ID_V2 must be unset before corpus build")
    if not settings.corpus_build_rollout_confirmed:
        errors.append(
            "DOCSURI_CORPUS_BUILD_ROLLOUT_CONFIRMED must be true after worker rollout "
            "completion and during a worker deployment freeze"
        )
    if sources.intersection({"SEMANTIC_SCHOLAR", "OPENALEX"}) and not settings.grobid_url:
        errors.append("DOCSURI_GROBID_URL is required for Semantic Scholar/OpenAlex corpus build")
    if errors:
        raise RuntimeError("; ".join(errors))


@dataclass(frozen=True, slots=True)
class SettingsLoadResult:
    settings: IngestionSettings | None
    error: ValidationError | RuntimeError | None
