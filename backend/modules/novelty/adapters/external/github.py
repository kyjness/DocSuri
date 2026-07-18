"""github_search 도구 어댑터(FR-31) — 구현체·baseline·license 단서.

품질 점수 판정은 하지 않는다(FR-31). 결과는 ExternalFinding 필드명으로 정규화되어
에이전트가 external_findings 산출물로 저장할 수 있다(정규화는 결정론 — BR-NV8).
"""

from __future__ import annotations

from typing import Any

from ...domain.models import utc_now
from ...ports.tools import TOOL_GITHUB_SEARCH, ToolContext, ToolResult, ToolSpec
from ...security import is_safe_external_url
from .base import SourceBreaker, SourceUnavailable
from .sanitize import sanitize_payload

__all__ = ["GithubSearchTool"]


class GithubSearchTool:
    spec = ToolSpec(
        name=TOOL_GITHUB_SEARCH,
        description=(
            "GitHub 저장소 검색 — 구현체·baseline·license 단서. "
            "query(필수, 짧은 키워드)·language(선택)만 허용된다."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "maxLength": 180},
                "language": {"type": "string", "maxLength": 40},
            },
            "required": ["query"],
        },
    )

    def __init__(
        self,
        client: Any,
        *,
        token: str | None = None,
        per_source: int = 3,
        breaker: SourceBreaker | None = None,
    ) -> None:
        self._client = client
        self._token = token
        self._per_source = per_source
        self._breaker = breaker or SourceBreaker()

    def invoke(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        payload, violations = sanitize_payload(TOOL_GITHUB_SEARCH, args)
        if violations:
            detail = ", ".join(f"{v.key}:{v.reason}" for v in violations)
            return ToolResult(
                ok=False,
                error=f"payload_blocked: {detail}",
                result_summary=f"payload blocked ({detail})",
            )
        try:
            repos = self._breaker.call(lambda: self._search(payload))
        except SourceUnavailable:
            return ToolResult(
                ok=False, error="github unavailable", result_summary="github unavailable"
            )
        findings = [finding for finding in map(_normalize_repo, repos) if finding]
        return ToolResult(
            ok=True,
            content={"findings": findings},
            result_summary=f"github: {len(findings)} repos for '{payload.get('query', '')}'",
        )

    def _search(self, payload: dict[str, str]) -> list[dict[str, Any]]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        query = f"{payload['query']} in:name,description,readme"
        if payload.get("language"):
            query += f" language:{payload['language']}"
        response = self._client.get(
            "https://api.github.com/search/repositories",
            params={
                "q": query,
                "sort": "updated",
                "order": "desc",
                "per_page": self._per_source,
            },
            headers=headers,
        )
        if getattr(response, "status_code", 200) >= 400:
            raise RuntimeError("github API unavailable")
        raise_for_status = getattr(response, "raise_for_status", None)
        if raise_for_status is not None:
            raise_for_status()
        return list(response.json().get("items", []))[: self._per_source]


def _normalize_repo(repo: dict[str, Any]) -> dict[str, Any] | None:
    title = str(repo.get("full_name") or "")
    url = str(repo.get("html_url") or "")
    if not title or not is_safe_external_url(url):
        return None
    finding: dict[str, Any] = {
        "source_type": "github",
        "canonical_id": title,
        "title": title,
        "url": url,
        "normalized_at": utc_now().isoformat(),
    }
    license_id = (repo.get("license") or {}).get("spdx_id")
    if license_id:
        finding["license"] = str(license_id)
    description = str(repo.get("description") or "")
    if description:
        finding["baseline_or_code_hint"] = description[:500]
    return finding
