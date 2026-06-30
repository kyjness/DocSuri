from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from .models import ArtifactKind, ArtifactValidationError, EvidenceStatus


def normalize_source_key(source_type: str, identifier: str) -> str:
    kind = source_type.strip().lower()
    value = re.sub(r"\s+", " ", identifier.strip())
    if kind == "url":
        parsed = urlparse(value if "://" in value else f"https://{value}")
        path = re.sub(r"/+$", "", parsed.path)
        query = urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=False)))
        normalized = urlunparse(
            (
                (parsed.scheme or "https").lower(),
                parsed.netloc.lower(),
                path,
                "",
                query,
                "",
            )
        )
        return f"url:{normalized}"
    return f"{kind}:{value.lower()}"


def dedupe_sources(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for source in sources:
        key = source.get("sourceKey") or normalize_source_key(
            str(source.get("type") or "unknown"),
            str(source.get("identifier") or source.get("url") or source.get("title") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append({**source, "sourceKey": key})
    return deduped


def validate_artifact_payload(kind: ArtifactKind, payload: dict[str, Any]) -> None:
    if kind is ArtifactKind.EXPERIMENT_PLAN:
        _validate_experiment_plan(payload)
    for item in _iter_supported_items(payload):
        source_refs = item.get("sourceRefs") or item.get("source_refs") or []
        if not source_refs:
            raise ArtifactValidationError("supported item must include sourceRefs")


def _iter_supported_items(payload: Any):
    if isinstance(payload, dict):
        status = payload.get("evidenceStatus") or payload.get("evidence_status")
        if status == EvidenceStatus.SUPPORTED.value:
            yield payload
        for value in payload.values():
            yield from _iter_supported_items(value)
    elif isinstance(payload, list):
        for item in payload:
            yield from _iter_supported_items(item)


def _validate_experiment_plan(payload: dict[str, Any]) -> None:
    required = {"researchQuestion", "hypotheses", "datasets", "metrics", "risks"}
    missing = sorted(key for key in required if not payload.get(key))
    if missing:
        raise ArtifactValidationError(f"experiment plan missing: {', '.join(missing)}")
