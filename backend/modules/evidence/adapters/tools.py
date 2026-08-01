"""도구 6종(BLM §2) — 포트를 부르고 루프 상태를 갱신하는 얇은 껍데기.

도구는 스스로 판단하지 않는다. 여기서 하는 일은 셋뿐이다: 포트 호출, 상태 갱신,
**모델이 다음에 무엇을 할 수 있는지 알려주는 결과 만들기**.

세 번째가 특히 중요하다 — 거부 사유는 판정이자 **수리 지시**여야 한다(BR-EV-18).
"실패했다"만 돌려주면 자율 루프는 같은 실수를 반복하고 그 반복이 캡을 태운다.

도구는 **턴마다 새로 만들어진다**(루프 상태를 쥐므로). 세션·소유자 경계는
`ToolContext`가 아니라 상태 자체가 격리한다.
"""

from __future__ import annotations

import base64
import logging
from typing import Any

from backend.modules.paper_assets import AssetStoreUnavailable, parse_record_ref

from ..domain.gate import run_gate
from ..domain.models import LoopState, PaperHandle, PaperOrigin, PromotionOutcome
from ..ports.llm import EvidenceExtractionPort, LlmUnavailable
from ..ports.sources import (
    CorpusSearchPort,
    DocModelReadPort,
    ExternalPaperSearchPort,
    PaperPromotionPort,
    SearchUnavailable,
)
from ..ports.tools import (
    TOOL_CORPUS_SEARCH,
    TOOL_EXTERNAL_SEARCH,
    TOOL_EXTRACT_EVIDENCE,
    TOOL_FETCH_PAPER,
    TOOL_READ_PAPER,
    TOOL_VIEW_FIGURE,
    ImageAttachment,
    ToolContext,
    ToolResult,
    ToolSpec,
)

__all__ = [
    "CorpusSearchTool",
    "ExternalSearchTool",
    "ExtractEvidenceTool",
    "FetchPaperTool",
    "ReadPaperTool",
    "ViewFigureTool",
]

log = logging.getLogger("docsuri.evidence.tools")

_ABSTRACT_PREVIEW = 400
_MAX_HITS = 10
_MAX_BLOCKS = 60
_ASSET_LIST_LIMIT = 60


def _fail(summary: str, message: str) -> ToolResult:
    return ToolResult(ok=False, error=message, result_summary=summary)


def _candidate_view(candidate: Any) -> dict[str, Any]:
    """모델에 보이는 후보 1건 — 내부 점수·청크 id는 싣지 않는다(INV-EV-5)."""
    return {
        "paperId": candidate.paper_id,
        "recordRef": candidate.record_ref,
        "title": candidate.title,
        "abstract": (candidate.abstract or "")[:_ABSTRACT_PREVIEW],
    }


class CorpusSearchTool:
    spec = ToolSpec(
        name=TOOL_CORPUS_SEARCH,
        description=(
            "내부 코퍼스(arXiv AI/ML)를 검색한다. **기본은 의미 검색(semantic)이다** — "
            "mode를 생략하라. mode=\"phrase\"는 사용자가 특정 문장을 그대로 찾아달라고 "
            "했을 때만 쓴다: 그 문구가 원문에 글자 그대로 있는 논문만 찾으므로 일반 "
            "질문에는 거의 0건이 나온다. 결과는 제목·초록까지이며, 본문 근거가 "
            "필요하면 fetch_paper로 본문을 확보해야 한다."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "maxLength": 400},
                "mode": {"type": "string", "enum": ["semantic", "phrase"]},
            },
            "required": ["query"],
        },
    )

    def __init__(self, port: CorpusSearchPort, state: LoopState) -> None:
        self._port = port
        self._state = state

    def invoke(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        query = str(args.get("query") or "").strip()
        if not query:
            return _fail("corpus_search: empty query", "query는 필수다 — 검색어를 넣어라")
        phrase = str(args.get("mode") or "") == "phrase"
        try:
            hits = self._port.search(query, phrase=phrase)
        except SearchUnavailable as exc:
            log.warning("corpus search unavailable: %s", exc)
            return _fail(
                "corpus_search: unavailable",
                "코퍼스 검색을 쓸 수 없다 — 같은 검색을 반복하지 말고 "
                "external_search로 진행하거나 확보한 논문에서 근거를 추출하라",
            )
        return _register(self._state, hits[:_MAX_HITS], PaperOrigin.CORPUS, "corpus_search")


class ExternalSearchTool:
    spec = ToolSpec(
        name=TOOL_EXTERNAL_SEARCH,
        description=(
            "코퍼스 밖 논문을 검색한다(제목·초록만). 여기서 얻은 논문은 아직 본문 근거가 "
            "아니다 — 초록만으로 인용할 수 있고, 본문 근거가 필요하면 fetch_paper로 "
            "본문을 가져와야 한다. 검색어 외의 내용(사용자 원문·근거 전문)은 보내지 않는다."
        ),
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string", "maxLength": 400}},
            "required": ["query"],
        },
    )

    def __init__(self, port: ExternalPaperSearchPort, state: LoopState) -> None:
        self._port = port
        self._state = state

    def invoke(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        query = str(args.get("query") or "").strip()
        if not query:
            return _fail("external_search: empty query", "query는 필수다 — 검색어를 넣어라")
        try:
            hits = self._port.search(query)
        except SearchUnavailable as exc:
            log.warning("external search unavailable: %s", exc)
            return _fail(
                "external_search: unavailable",
                "외부 검색을 쓸 수 없다 — 코퍼스 검색과 확보한 논문으로 진행하라",
            )
        return _register(self._state, hits[:_MAX_HITS], PaperOrigin.EXTERNAL, "external_search")


def _register(
    state: LoopState, hits: tuple[Any, ...], origin: PaperOrigin, tool: str
) -> ToolResult:
    for candidate in hits:
        state.candidates_seen.add(candidate.paper_id)
        if state.handle(candidate.paper_id) is None:
            state.discovered[candidate.paper_id] = PaperHandle(
                paper_id=candidate.paper_id,
                record_ref=candidate.record_ref,
                origin=origin,
                title=candidate.title,
                abstract_text=candidate.abstract,
            )
    if not hits:
        return ToolResult(
            ok=True,
            content={
                "hits": [],
                "note": (
                    "결과가 없다 — 다른 검색어를 시도하라. phrase 모드였다면 "
                    "mode를 빼고 의미 검색으로 다시 하라."
                ),
            },
            result_summary=f"{tool}: 0 hits",
        )
    return ToolResult(
        ok=True,
        content={"hits": [_candidate_view(c) for c in hits]},
        result_summary=f"{tool}: {len(hits)} hits",
    )


class FetchPaperTool:
    """본문 확보 — 코퍼스 논문은 DocModel 읽기, 코퍼스 밖은 온디맨드 승격."""

    spec = ToolSpec(
        name=TOOL_FETCH_PAPER,
        description=(
            "논문의 본문(DocModel)을 확보한다. 확보하면 그 논문의 문단·표·수식·그림·"
            "알고리즘을 근거로 인용할 수 있고, 확보하지 못하면 초록 범위 인용만 가능하다. "
            "초록을 보고 근거로 쓸 값이 있다고 판단한 논문만 골라라 — 비용이 드는 호출이다."
        ),
        parameters={
            "type": "object",
            "properties": {"paper_id": {"type": "string", "maxLength": 100}},
            "required": ["paper_id"],
        },
    )

    def __init__(
        self,
        *,
        doc_models: DocModelReadPort,
        promotion: PaperPromotionPort | None,
        state: LoopState,
    ) -> None:
        self._doc_models = doc_models
        self._promotion = promotion
        self._state = state

    def invoke(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        paper_id = str(args.get("paper_id") or "").strip()
        handle = self._state.handle(paper_id)
        if handle is None:
            return _fail(
                "fetch_paper: unknown paper",
                f"'{paper_id}'는 아직 검색으로 찾지 못한 논문이다 — "
                "corpus_search·external_search 결과의 paperId를 그대로 넣어라",
            )
        if handle.doc_model is not None:
            self._state.examine(handle)
            return ToolResult(
                ok=True,
                content={"paperId": paper_id, "status": "already_fetched"},
                result_summary="fetch_paper: already fetched",
            )

        if handle.origin is PaperOrigin.CORPUS:
            doc_model = self._doc_models.get_doc_model(paper_id)
            if doc_model is None:
                self._state.examine(handle)
                return ToolResult(
                    ok=True,
                    content={"paperId": paper_id, "status": "abstract_only",
                             "note": "본문을 읽을 수 없어 초록 범위 인용만 가능하다"},
                    result_summary="fetch_paper: abstract only",
                )
            handle.doc_model = doc_model
            handle.invalidate_projections()
            self._state.examine(handle)
            return _fetched(handle)

        if self._promotion is None:
            self._state.examine(handle)
            return _fail(
                "fetch_paper: promotion unavailable",
                "코퍼스 밖 논문의 본문 확보 기능이 꺼져 있다 — 초록 범위로 인용하라",
            )

        result = self._promotion.promote(paper_id)
        if result.outcome != PromotionOutcome.PROMOTED or result.doc_model is None:
            self._state.examine(handle)
            # 실패는 정상 결과값이다 — 초록 범위로 계속한다(BLM §4).
            return ToolResult(
                ok=True,
                content={
                    "paperId": paper_id,
                    "status": str(result.outcome),
                    "note": "본문을 가져오지 못했다 — 이 논문은 초록 범위로만 인용할 수 있다",
                },
                result_summary=f"fetch_paper: {result.outcome}",
            )
        handle.doc_model = result.doc_model
        handle.invalidate_projections()
        self._state.examine(handle)
        return _fetched(handle)


def _fetched(handle: PaperHandle) -> ToolResult:
    blocks = handle.blocks()
    kinds: dict[str, int] = {}
    for _bid, kind, _text in blocks:
        kinds[kind] = kinds.get(kind, 0) + 1
    return ToolResult(
        ok=True,
        content={
            "paperId": handle.paper_id,
            "status": "fetched",
            "blockCount": len(blocks),
            "blockKinds": kinds,
        },
        result_summary=f"fetch_paper: {len(blocks)} blocks",
    )


class ReadPaperTool:
    spec = ToolSpec(
        name=TOOL_READ_PAPER,
        description=(
            "확보한 논문의 본문을 블록 단위로 읽는다. 각 블록에는 id가 붙어 있고, "
            "근거를 인용할 때 그 id를 anchor로 써야 한다. anchor 없이는 인용이 저장되지 "
            "않는다. keyword를 주면 그 말이 든 블록만 추려 본다."
        ),
        parameters={
            "type": "object",
            "properties": {
                "paper_id": {"type": "string", "maxLength": 100},
                "keyword": {"type": "string", "maxLength": 200},
            },
            "required": ["paper_id"],
        },
    )

    def __init__(self, state: LoopState) -> None:
        self._state = state

    def invoke(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        paper_id = str(args.get("paper_id") or "").strip()
        handle = self._state.handle(paper_id)
        if handle is None:
            return _fail("read_paper: unknown paper", f"'{paper_id}'를 찾지 못했다 — 먼저 검색하라")
        if handle.doc_model is None:
            return _fail(
                "read_paper: no full text",
                f"'{paper_id}'는 본문이 없다 — fetch_paper로 확보하거나 초록 범위로 인용하라",
            )
        self._state.examine(handle)

        keyword = str(args.get("keyword") or "").strip().lower()
        blocks = handle.blocks()
        if keyword:
            blocks = [b for b in blocks if keyword in b[2].lower()]
        shown = blocks[:_MAX_BLOCKS]
        content: dict[str, Any] = {
            "paperId": paper_id,
            # 블록 id를 반드시 노출한다 — v1은 이걸 감춰서 모델이 유효한 anchor를
            # 쓸 방법이 없었고, 지어낸 anchor는 게이트가 떨어뜨렸다.
            "blocks": [{"id": bid, "type": kind, "text": text} for bid, kind, text in shown],
        }
        if len(blocks) > len(shown):
            content["moreBlocks"] = len(blocks) - len(shown)
        if not shown:
            content["note"] = "조건에 맞는 블록이 없다 — keyword를 바꾸거나 생략하라"
        return ToolResult(
            ok=True, content=content, result_summary=f"read_paper: {len(shown)} blocks"
        )


class ViewFigureTool:
    """그림·수식 조회 — 2모드(목록 / 이미지). novelty와 같은 계약(⑤3)."""

    spec = ToolSpec(
        name=TOOL_VIEW_FIGURE,
        description=(
            "확보한 논문의 그림·수식을 조회한다. asset_id 없이 부르면 목록(assetId·종류·"
            "캡션)을 돌려주고, asset_id를 주면 그 자산을 **이미지로 보여준다**. 캡션은 "
            "그림이 무엇을 그렸는지 알려주지 않는다 — 축·수치·추세처럼 그림을 봐야 아는 "
            "것이 필요할 때만 열어라. 그림에서 읽은 내용을 근거로 쓸 때는 그 그림 블록을 "
            "anchor로 하고 sourceScope=figure로 표시해야 한다."
        ),
        parameters={
            "type": "object",
            "properties": {
                "record_ref": {"type": "string", "maxLength": 100},
                "asset_id": {"type": "string", "maxLength": 200},
            },
            "required": ["record_ref"],
        },
    )

    def __init__(self, assets: Any, *, max_image_bytes: int) -> None:
        self._assets = assets
        self._max_image_bytes = max_image_bytes

    def invoke(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        record_ref = str(args.get("record_ref") or "").strip()
        parsed = parse_record_ref(record_ref) if record_ref else None
        if parsed is None:
            return _fail(
                "view_figure: missing record_ref",
                "record_ref는 필수다 — 검색 결과의 recordRef 값을 그대로 넣어라",
            )
        paper_id, version = parsed
        asset_id = str(args.get("asset_id") or "").strip()
        if asset_id:
            return self._image(record_ref, paper_id, version, asset_id)
        return self._list(record_ref, paper_id, version)

    def _list(self, record_ref: str, paper_id: str, version: int | None) -> ToolResult:
        manifest = self._assets.list_assets(paper_id, version, limit=_ASSET_LIST_LIMIT)
        version_note: str | None = None
        if manifest is None and version is not None:
            # 명시 버전 미스 ≠ 자산 없음 — 백필 코퍼스는 버전 하나만 갖는다. 폴백하되
            # 어긋남을 밝힌다("자산 없음" 오답이 실재 자산에서 모델을 떼어놓는다).
            manifest = self._assets.list_assets(paper_id, None, limit=_ASSET_LIST_LIMIT)
            if manifest is not None:
                version_note = (
                    f"요청한 v{version}의 자산은 없어 저장된 v{manifest.version}의 자산이다"
                )
        if manifest is None:
            return _fail(
                "view_figure: no assets",
                f"{record_ref} 논문에는 저장된 그림·수식이 없다 — "
                "다른 논문을 고르거나 텍스트 근거로 진행하라",
            )
        content: dict[str, Any] = {
            "recordRef": record_ref,
            "assets": [
                {
                    "assetId": a.asset_id,
                    "type": a.type,
                    "ordinal": a.ordinal,
                    "caption": a.caption,
                }
                for a in manifest.assets
            ],
        }
        # 목록이 전부가 아님을 알린다 — 모르면 모델이 "이게 다"라고 믿는다(novelty 실측).
        if manifest.total > len(manifest.assets):
            content["totalAssets"] = manifest.total
        if version_note:
            content["note"] = version_note
        return ToolResult(
            ok=True,
            content=content,
            result_summary=f"view_figure: {len(manifest.assets)} assets",
        )

    def _image(
        self, record_ref: str, paper_id: str, version: int | None, asset_id: str
    ) -> ToolResult:
        match = self._assets.get_asset(paper_id, version, asset_id)
        if match is None and version is not None:
            match = self._assets.get_asset(paper_id, None, asset_id)
        if match is None:
            return _fail(
                "view_figure: unknown asset",
                f"asset_id '{asset_id}'는 {record_ref} 논문에 없다 — "
                "asset_id 없이 호출해 목록을 먼저 받아라",
            )
        try:
            fetched = self._assets.fetch_bytes(match.object_ref, max_bytes=self._max_image_bytes)
        except AssetStoreUnavailable:
            return _fail(
                "view_figure: asset store unavailable",
                "자산 스토어에 접근할 수 없다 — 이미지 조회를 반복하지 말고 "
                "캡션·텍스트 근거로 진행하라",
            )
        if not fetched or not fetched[1]:
            return _fail(
                "view_figure: asset unavailable",
                f"asset_id '{asset_id}' 이미지를 쓸 수 없다 — 다른 자산을 고르거나 "
                "텍스트 근거로 진행하라",
            )
        media_type, data = fetched
        return ToolResult(
            ok=True,
            content={
                "recordRef": record_ref,
                "assetId": match.asset_id,
                "type": match.type,
                "caption": match.caption,
            },
            images=(
                ImageAttachment(
                    media_type=media_type,
                    data_b64=base64.b64encode(data).decode("ascii"),
                    asset_id=match.asset_id,
                ),
            ),
            result_summary=f"view_figure: {match.type} {match.asset_id}",
        )


class ExtractEvidenceTool:
    """근거가 쌓이는 **유일한 경로**(INV-EV-6) — 게이트 통과분만 누적한다."""

    spec = ToolSpec(
        name=TOOL_EXTRACT_EVIDENCE,
        description=(
            "확보한 논문들에서 질문과 관련된 근거를 추출한다. 각 근거는 원문 인용과 "
            "그 인용이 있는 블록의 anchor를 갖춰야 하며, 검증을 통과한 것만 저장된다. "
            "focus로 무엇을 찾을지 좁힐 수 있다."
        ),
        parameters={
            "type": "object",
            "properties": {
                "paper_ids": {
                    "type": "array",
                    "items": {"type": "string", "maxLength": 100},
                    "maxItems": 10,
                },
                "focus": {"type": "string", "maxLength": 300},
            },
            "required": ["paper_ids"],
        },
    )

    def __init__(self, port: EvidenceExtractionPort, state: LoopState) -> None:
        self._port = port
        self._state = state

    def invoke(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        requested = [str(pid).strip() for pid in args.get("paper_ids") or [] if str(pid).strip()]
        if not requested:
            return _fail(
                "extract_evidence: no papers",
                "paper_ids는 필수다 — 확보한 논문의 paperId를 넣어라",
            )

        handles = []
        unknown = []
        for paper_id in requested:
            handle = self._state.handle(paper_id)
            if handle is None:
                unknown.append(paper_id)
            else:
                handles.append(self._state.examine(handle))
        if not handles:
            return _fail(
                "extract_evidence: unknown papers",
                f"{', '.join(unknown)}를 찾지 못했다 — 검색 결과의 paperId를 그대로 넣어라",
            )

        try:
            raw_items = self._port.extract(
                topic=self._state.topic,
                focus=str(args.get("focus") or ""),
                papers=tuple(handles),
            )
        except LlmUnavailable as exc:
            log.warning("evidence extraction unavailable: %s", exc)
            return _fail(
                "extract_evidence: llm unavailable",
                "근거 추출 모델을 쓸 수 없다 — 잠시 후 다시 시도하거나 종료하라",
            )

        outcome = run_gate(raw_items, {h.paper_id: h.as_source() for h in handles})
        accepted = self._state.accumulator.absorb(outcome)

        content: dict[str, Any] = {
            "accepted": accepted,
            "rejected": outcome.rejected_count,
            "totalEvidence": len(self._state.accumulator.items),
        }
        if outcome.rejected_count:
            # 사유 **분포**만 준다 — 어떤 인용이 왜 떨어졌는지는 내부에 둔다(INV-EV-5).
            # 그래도 다음 판단이 달라질 만큼은 알려야 같은 실수를 반복하지 않는다.
            content["rejectedReasons"] = dict(outcome.rejections)
            content["hint"] = (
                "인용문은 원문 그대로여야 하고, anchor는 그 인용문이 실제로 있는 "
                "블록의 id여야 한다. read_paper로 블록 id와 본문을 다시 확인하라."
            )
        if unknown:
            content["unknownPapers"] = unknown
        return ToolResult(
            ok=True,
            content=content,
            result_summary=f"extract_evidence: +{accepted} (rejected {outcome.rejected_count})",
        )
