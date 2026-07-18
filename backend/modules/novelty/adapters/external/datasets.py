"""dataset_search 도구 어댑터(FR-31) — 데이터셋 이름·URL·라이선스·태스크 후보.

Hugging Face·Zenodo를 소스별 차단기로 감싼다 — 한 소스의 실패가 도구 전체를
막지 않고(BR-NV16), 전 소스 실패 시에만 오류를 반환한다.
"""

from __future__ import annotations

from typing import Any

from ...domain.models import utc_now
from ...ports.tools import TOOL_DATASET_SEARCH, ToolContext, ToolResult, ToolSpec
from ...security import is_safe_external_url
from .base import SourceBreaker, SourceUnavailable
from .sanitize import sanitize_payload

__all__ = ["DatasetSearchTool"]


class DatasetSearchTool:
    spec = ToolSpec(
        name=TOOL_DATASET_SEARCH,
        description=(
            "데이터셋 검색(Hugging Face·Zenodo) — 이름·URL·라이선스·태스크 후보. "
            "query(필수, 짧은 키워드)·task(선택)만 허용된다."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "maxLength": 180},
                "task": {"type": "string", "maxLength": 80},
            },
            "required": ["query"],
        },
    )

    def __init__(
        self,
        client: Any,
        *,
        per_source: int = 3,
        hf_breaker: SourceBreaker | None = None,
        zenodo_breaker: SourceBreaker | None = None,
    ) -> None:
        self._client = client
        self._per_source = per_source
        self._hf_breaker = hf_breaker or SourceBreaker()
        self._zenodo_breaker = zenodo_breaker or SourceBreaker()

    def invoke(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        payload, violations = sanitize_payload(TOOL_DATASET_SEARCH, args)
        if violations:
            detail = ", ".join(f"{v.key}:{v.reason}" for v in violations)
            return ToolResult(
                ok=False,
                error=f"payload_blocked: {detail}",
                result_summary=f"payload blocked ({detail})",
            )
        query = payload["query"]
        findings: list[dict[str, Any]] = []
        degraded: list[str] = []
        for source, breaker, search in (
            ("huggingface", self._hf_breaker, self._huggingface),
            ("zenodo", self._zenodo_breaker, self._zenodo),
        ):
            try:
                findings.extend(breaker.call(lambda search=search: search(query)))
            except SourceUnavailable:
                degraded.append(source)
        if not findings and degraded:
            return ToolResult(
                ok=False,
                error=f"dataset sources unavailable: {', '.join(degraded)}",
                result_summary="dataset sources unavailable",
            )
        deduped = _dedupe_by_url(findings)
        content: dict[str, Any] = {"findings": deduped}
        if degraded:
            content["degraded_sources"] = degraded
        return ToolResult(
            ok=True,
            content=content,
            result_summary=f"datasets: {len(deduped)} candidates for '{query}'"
            + (f" (degraded: {', '.join(degraded)})" if degraded else ""),
        )

    def _huggingface(self, query: str) -> list[dict[str, Any]]:
        response = self._client.get(
            "https://huggingface.co/api/datasets",
            params={"search": query, "limit": self._per_source},
        )
        _check(response)
        findings = []
        for dataset in list(response.json())[: self._per_source]:
            dataset_id = dataset.get("id")
            if not dataset_id:
                continue
            finding = _normalize(
                canonical_id=str(dataset_id),
                title=str(dataset_id),
                url=f"https://huggingface.co/datasets/{dataset_id}",
                task=_first_tag(dataset.get("tags") or [], prefix="task_categories:"),
            )
            if finding:
                findings.append(finding)
        return findings

    def _zenodo(self, query: str) -> list[dict[str, Any]]:
        response = self._client.get(
            "https://zenodo.org/api/records",
            params={
                "q": f"{query} dataset",
                "type": "dataset",
                "sort": "mostrecent",
                "size": self._per_source,
            },
        )
        _check(response)
        records = (response.json().get("hits") or {}).get("hits") or []
        findings = []
        for record in records[: self._per_source]:
            metadata = record.get("metadata") or {}
            finding = _normalize(
                canonical_id=str(record.get("doi") or record.get("id") or ""),
                title=str(metadata.get("title") or ""),
                url=str((record.get("links") or {}).get("html") or ""),
                license=str((metadata.get("license") or {}).get("id") or "") or None,
            )
            if finding:
                findings.append(finding)
        return findings


def _check(response: Any) -> None:
    if getattr(response, "status_code", 200) >= 400:
        raise RuntimeError("external API unavailable")
    raise_for_status = getattr(response, "raise_for_status", None)
    if raise_for_status is not None:
        raise_for_status()


def _normalize(
    *,
    canonical_id: str,
    title: str,
    url: str,
    license: str | None = None,
    task: str | None = None,
) -> dict[str, Any] | None:
    if not canonical_id or not title or not is_safe_external_url(url):
        return None
    finding: dict[str, Any] = {
        "source_type": "dataset",
        "canonical_id": canonical_id,
        "title": title,
        "url": url,
        "normalized_at": utc_now().isoformat(),
    }
    if license:
        finding["license"] = license
    if task:
        finding["task"] = task
    return finding


def _first_tag(tags: list[Any], *, prefix: str) -> str | None:
    for tag in tags:
        text = str(tag)
        if text.startswith(prefix):
            return text.removeprefix(prefix)
    return None


def _dedupe_by_url(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for finding in findings:
        url = str(finding.get("url") or "")
        if not url or url in seen:
            continue
        seen.add(url)
        deduped.append(finding)
    return deduped
