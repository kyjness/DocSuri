"""form_evidence 도구 어댑터 — U11 EvidenceFormationPort 소비(공유 계약, BR-NV1).

포트는 async·FROZEN — 재구현 금지, 전용 스레드에서 동기 완주(레거시 관행 승계).
결과는 EvidenceSnapshot 형태로 content["evidence"]에 실린다 — 루프가 게이트
경유로 자동 보존한다. abstain은 오류가 아니라 결과다(날조 금지, C-2).
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from ..ports.tools import TOOL_FORM_EVIDENCE, ToolContext, ToolResult, ToolSpec
from .external.base import SourceBreaker, SourceUnavailable

__all__ = ["FormEvidenceTool"]


class FormEvidenceTool:
    spec = ToolSpec(
        name=TOOL_FORM_EVIDENCE,
        description=(
            "U11 문헌탐색 엔진으로 근거표 형성 — 주제의 핵심 주장·방법·결과를 "
            "실재 출처(SourceRef)와 함께 수집한다. 자연어 잡은 이 도구가 선행된다."
        ),
        parameters={
            "type": "object",
            "properties": {
                "topic": {"type": "string", "maxLength": 2000},
                "paper_ids": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["topic"],
        },
    )

    def __init__(self, port: Any, *, breaker: SourceBreaker | None = None) -> None:
        self._port = port
        self._breaker = breaker or SourceBreaker()

    def invoke(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        from docsuri_shared._generated.dtos.evidence_schema import EvidenceRequest

        topic = str(args.get("topic") or "").strip()
        if not topic:
            return ToolResult(ok=False, error="topic is required", result_summary="empty topic")
        paper_ids = [str(pid) for pid in args.get("paper_ids") or [] if str(pid).strip()]
        request = EvidenceRequest(
            topic=topic[:2000],
            scope="mixed" if paper_ids else None,
            paperIds=paper_ids or None,
        )
        port_ctx = SimpleNamespace(
            owner_id=ctx.owner_id,
            request_id=f"novelty-evidence-{uuid4().hex}",
            budget_signal={},
        )
        try:
            result = self._breaker.call(
                lambda: _run_coro_in_thread(self._port.form_evidence(request, port_ctx))
            )
        except SourceUnavailable:
            return ToolResult(
                ok=False,
                error="evidence engine unavailable",
                result_summary="evidence engine unavailable",
            )
        return _to_result(result)


_FALLBACK_POOL: ThreadPoolExecutor | None = None


def _fallback_pool() -> ThreadPoolExecutor:
    global _FALLBACK_POOL  # noqa: PLW0603 — 프로세스 수명 단일 실행기(지연 생성)
    if _FALLBACK_POOL is None:
        _FALLBACK_POOL = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="novelty-evidence"
        )
    return _FALLBACK_POOL


def _run_coro_in_thread(coro: Any) -> Any:
    """코루틴 동기 완주 — 동기 워커(일반 경로)에선 asyncio.run 직행, 이벤트 루프
    위에서 호출된 경우에만 공유 실행기로 우회(호출당 스레드풀 생성 없음)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    return _fallback_pool().submit(asyncio.run, coro).result()


def _to_result(result: Any) -> ToolResult:
    state = str(getattr(result, "state", "") or "")
    if state == "abstain":
        reason = str(getattr(result, "abstainReason", "") or "insufficient_evidence")
        snapshot = {"state": "abstain", "claims": [], "abstain_reason": reason}
        return ToolResult(
            ok=True,
            content={"evidence": snapshot},
            result_summary=f"evidence abstained: {reason}",
        )
    claims = [_claim_dict(claim) for claim in getattr(result, "claims", None) or []]
    coverage = getattr(result, "coverage", None)
    snapshot: dict[str, Any] = {"state": "ok", "claims": claims}
    if coverage is not None:
        snapshot["coverage"] = {
            "paperCount": getattr(coverage, "paperCount", 0),
            "queryUsed": getattr(coverage, "queryUsed", None),
        }
    record_refs = tuple(
        ref["recordRef"]
        for claim in claims
        for ref in (*claim["supporting"], *claim["conflicting"])
        if ref.get("recordRef")
    )
    return ToolResult(
        ok=True,
        content={"evidence": snapshot},
        record_refs=record_refs,
        result_summary=f"evidence formed: {len(claims)} claims",
    )


def _claim_dict(claim: Any) -> dict[str, Any]:
    def _refs(refs: Any) -> list[dict[str, Any]]:
        out = []
        for ref in refs or []:
            out.append(
                {
                    "paperId": str(getattr(ref, "paperId", "") or ""),
                    "recordRef": str(getattr(ref, "recordRef", "") or ""),
                    "anchor": getattr(ref, "anchor", None),
                    "quote": getattr(ref, "quote", None),
                }
            )
        return out

    return {
        "statement": str(getattr(claim, "statement", "") or ""),
        "supporting": _refs(getattr(claim, "supporting", None)),
        "conflicting": _refs(getattr(claim, "conflicting", None)),
    }
