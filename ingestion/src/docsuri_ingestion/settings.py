from __future__ import annotations

import os
from dataclasses import dataclass

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
    control_plane_dsn: str | None = Field(default=None, alias="DOCSURI_CONTROL_PLANE_DSN")
    sqs_queue_url: str | None = Field(default=None, alias="DOCSURI_SQS_QUEUE_URL")
    sqs_dlq_url: str | None = Field(default=None, alias="DOCSURI_SQS_DLQ_URL")
    request_timeout_seconds: float = Field(default=30.0, alias="DOCSURI_REQUEST_TIMEOUT_SECONDS")
    index_stats_ttl_seconds: float = Field(default=60.0, alias="DOCSURI_INDEX_STATS_TTL_SECONDS")
    arxiv_rate_per_second: float = Field(default=0.33, alias="DOCSURI_ARXIV_RATE_PER_SECOND")
    max_chunks_per_paper: int = Field(default=128, alias="DOCSURI_MAX_CHUNKS_PER_PAPER")
    max_chunk_chars: int = Field(default=2400, alias="DOCSURI_MAX_CHUNK_CHARS")
    chunk_overlap_chars: int = Field(default=240, alias="DOCSURI_CHUNK_OVERLAP_CHARS")
    # FR-17 multimodal assets (display-only). Safe default OFF — base worker unaffected.
    multimodal_assets_enabled: bool = Field(
        default=False, alias="DOCSURI_MULTIMODAL_ASSETS_ENABLED"
    )
    asset_s3_prefix: str = Field(default="assets", alias="DOCSURI_ASSET_S3_PREFIX")
    asset_max_longest_side: int = Field(default=2048, alias="DOCSURI_ASSET_MAX_LONGEST_SIDE")
    asset_max_pixels: int = Field(default=30_000_000, alias="DOCSURI_ASSET_MAX_PIXELS")
    asset_webp_quality: int = Field(default=80, alias="DOCSURI_ASSET_WEBP_QUALITY")
    asset_kms_key_id: str | None = Field(default=None, alias="DOCSURI_ASSET_KMS_KEY_ID")
    asset_fetch_timeout_seconds: float = Field(
        default=20.0, alias="DOCSURI_ASSET_FETCH_TIMEOUT_SECONDS"
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


@dataclass(frozen=True, slots=True)
class SettingsLoadResult:
    settings: IngestionSettings | None
    error: ValidationError | RuntimeError | None
