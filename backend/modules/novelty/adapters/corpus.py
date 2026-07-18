"""corpus_search 도구 어댑터 — U2 `full` 검색 재사용(BR-NV4, 전용 인덱스·랭킹 금지).

record_refs는 카드의 arxivId를 실재성 핸들로 노출한다 — U11도 retrieval doc의
record_ref 부재 시 paper_id로 폴백하는 동일 관행(orchestrator 참조). 게이트의
SourceRef 실재성 검사(BR-NV19)가 이 집합과 대조한다.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import uuid4

from ..ports.tools import TOOL_CORPUS_SEARCH, ToolContext, ToolResult, ToolSpec

__all__ = ["CorpusSearchTool"]


class CorpusSearchTool:
    spec = ToolSpec(
        name=TOOL_CORPUS_SEARCH,
        description="내부 arXiv 코퍼스 하이브리드 검색(U2 full) — 유사 연구 확장 탐색.",
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string", "maxLength": 500}},
            "required": ["query"],
        },
    )

    def __init__(
        self,
        orchestrator: Any,
        grounding_hook: Any,
        *,
        runner: Callable[..., Any] | None = None,
    ) -> None:
        self._orchestrator = orchestrator
        self._grounding_hook = grounding_hook
        self._runner = runner

    def invoke(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        from discovery.domain.models import AuthSession, RequestContext
        from discovery.service.orchestrator import SearchUnavailable
        from docsuri_shared._generated.dtos.search_schema import (
            AbstainDTO,
            DegradedResultDTO,
            SearchRequest,
            SearchResultPageDTO,
            ValidationErrorDTO,
        )

        query = str(args.get("query") or "").strip()
        if not query:
            return ToolResult(ok=False, error="query is required", result_summary="empty query")

        runner = self._runner
        if runner is None:
            from discovery.api.gateway_seam import run_search

            runner = run_search

        request_ctx = RequestContext(
            auth_session=AuthSession(user_id=ctx.owner_id),
            request_id=f"novelty-{uuid4().hex}",
        )
        try:
            response = runner(
                self._orchestrator,
                self._grounding_hook,
                SearchRequest(query=query[:500], scope="full"),
                request_ctx,
            )
        except SearchUnavailable:
            return ToolResult(
                ok=False, error="U2 full search unavailable", result_summary="corpus unavailable"
            )

        root = response.root
        if isinstance(root, (SearchResultPageDTO, DegradedResultDTO)):
            items = [_card_view(card) for card in root.cards]
            degraded = bool(getattr(root.meta, "degraded", False))
            content: dict[str, Any] = {"items": items}
            if degraded:
                content["degraded"] = True
            return ToolResult(
                ok=True,
                content=content,
                record_refs=tuple(item["arxivId"] for item in items if item.get("arxivId")),
                result_summary=f"corpus: {len(items)} papers"
                + (" (degraded)" if degraded else ""),
            )
        if isinstance(root, AbstainDTO):
            return ToolResult(
                ok=True,
                content={"items": [], "note": f"abstained: {root.reason}"},
                result_summary="corpus abstained",
            )
        if isinstance(root, ValidationErrorDTO):
            return ToolResult(
                ok=False,
                error=f"query rejected: {root.message}",
                result_summary="corpus query rejected",
            )
        return ToolResult(
            ok=False, error="unsupported search response", result_summary="corpus error"
        )


def _card_view(card: Any) -> dict[str, Any]:
    return {
        "title": card.title,
        "authors": list(card.authors),
        "year": card.year,
        "arxivId": card.arxivId,
        "abstractSnippet": card.abstractSnippet,
        "sourceName": card.sourceName or "arXiv",
        "sourceUrl": card.sourceUrl or card.arxivUrl,
    }
