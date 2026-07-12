"""Real-adapter configuration — environment-driven (DOCSURI_* namespace).

Deliberately reuses the SAME env names as the U1 writer (``ingestion.settings``) for the
shared resources — ``DOCSURI_OPENSEARCH_ENDPOINT`` / ``DOCSURI_OPENSEARCH_INDEX`` /
``DOCSURI_BEDROCK_MODEL_ID`` / ``DOCSURI_AWS_REGION`` — so writer and reader point at one
index/space by construction (vector-spec §4). The cluster/model are provisioned by the
shared infrastructure track (U1 infra + system event bus); U2 only *reads* the endpoint.

``search_enabled`` is the mount toggle: when the OpenSearch endpoint and Bedrock model are
configured the app-shell wires the real read path; otherwise it stays mock-first.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

_TRUTHY = {"1", "true", "yes", "on"}

# Defaults live at module scope (NOT referenced via ``cls.<field>``): with ``slots=True`` the
# class attribute is the slot descriptor, not the default value, so ``cls.opensearch_index``
# would yield the descriptor — not the string.
_DEFAULT_INDEX = "docsuri-corpus"
_DEFAULT_USE_SSL = True
_DEFAULT_VERIFY_CERTS = True
_DEFAULT_CACHE_TTL_SECONDS = 300.0


def _flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in _TRUTHY


def _region_from_arn(arn: str | None) -> str | None:
    """Region embedded in a Bedrock model ARN (``arn:aws:bedrock:<region>::...``), or None."""
    if not arn:
        return None
    parts = arn.split(":")
    return parts[3] if len(parts) > 3 and parts[3] else None


@dataclass(frozen=True, slots=True)
class DiscoverySettings:
    """Immutable, fully-resolved U2 read-path settings. Build via :meth:`from_env`."""

    opensearch_endpoint: str | None = None
    opensearch_index: str = _DEFAULT_INDEX
    opensearch_username: str | None = None
    opensearch_password: str | None = None
    # Local docker OpenSearch runs plain HTTP; managed clusters use TLS. Default to secure.
    opensearch_use_ssl: bool = _DEFAULT_USE_SSL
    opensearch_verify_certs: bool = _DEFAULT_VERIFY_CERTS
    bedrock_model_id: str | None = None
    aws_region: str | None = None
    # Bedrock embedding region, decoupled from aws_region (used for OpenSearch SigV4). Needed
    # because Cohere Embed Multilingual v3 is NOT available in ap-northeast-2 (the domain region),
    # so the reader must embed queries cross-region. None → falls back to aws_region.
    bedrock_region: str | None = None
    # SearchExecuted event bus (→ U4 history). Absent → events stay in-memory (bus not yet
    # provisioned). When set, the real EventBridge publisher is wired.
    search_event_bus: str | None = None
    embedding_cache_ttl_seconds: float = _DEFAULT_CACHE_TTL_SECONDS
    # Cross-encoder rerank model ARN (Bedrock Rerank API, e.g. Cohere Rerank v3.5). Presence is
    # the feature toggle: set → the real reranker is wired; absent → baseline RRF order (FR-3).
    rerank_model_arn: str | None = None
    # Region the rerank CLIENT is created in. Rerank is NOT in the Seoul deploy region and has no
    # global inference profile, so it is a cross-region call (nearest = ap-northeast-1 Tokyo).
    # Absent → derived from the model ARN's region (below), so the ARN alone is enough.
    rerank_region: str | None = None

    @property
    def rerank_region_resolved(self) -> str | None:
        """Region for the Bedrock rerank client: explicit ``DOCSURI_RERANK_REGION``, else the
        region embedded in the model ARN (rerank runs cross-region, so it must NOT default to the
        Seoul deploy region), else ``aws_region`` as a last resort."""
        return self.rerank_region or _region_from_arn(self.rerank_model_arn) or self.aws_region

    @property
    def search_enabled(self) -> bool:
        """True when the real read path can be wired (cluster + model configured)."""
        return bool(self.opensearch_endpoint and self.bedrock_model_id)

    @classmethod
    def from_env(cls) -> DiscoverySettings:
        ttl = os.getenv("DOCSURI_EMBEDDING_CACHE_TTL_SECONDS")
        return cls(
            opensearch_endpoint=os.getenv("DOCSURI_OPENSEARCH_ENDPOINT") or None,
            opensearch_index=os.getenv("DOCSURI_OPENSEARCH_INDEX", _DEFAULT_INDEX),
            opensearch_username=os.getenv("DOCSURI_OPENSEARCH_USERNAME") or None,
            opensearch_password=os.getenv("DOCSURI_OPENSEARCH_PASSWORD") or None,
            opensearch_use_ssl=_flag("DOCSURI_OPENSEARCH_USE_SSL", _DEFAULT_USE_SSL),
            opensearch_verify_certs=_flag("DOCSURI_OPENSEARCH_VERIFY_CERTS", _DEFAULT_VERIFY_CERTS),
            bedrock_model_id=os.getenv("DOCSURI_BEDROCK_MODEL_ID") or None,
            aws_region=os.getenv("DOCSURI_AWS_REGION") or None,
            bedrock_region=os.getenv("DOCSURI_BEDROCK_REGION") or None,
            search_event_bus=os.getenv("DOCSURI_SEARCH_EVENT_BUS") or None,
            embedding_cache_ttl_seconds=float(ttl) if ttl else _DEFAULT_CACHE_TTL_SECONDS,
            rerank_model_arn=os.getenv("DOCSURI_RERANK_MODEL_ARN") or None,
            rerank_region=os.getenv("DOCSURI_RERANK_REGION") or None,
        )
