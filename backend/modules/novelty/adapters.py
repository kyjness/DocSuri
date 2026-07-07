from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Protocol
from urllib.parse import urlparse
from uuid import uuid4

from backend.modules.user_docmodel import (
    NOVELTY_PDF_DEGRADED_REASON,
    USER_DOCMODEL_PDF_CONTENT_TYPE,
    ref_from_attachment,
)

from .models import EvidenceStatus
from .security import sanitize_external_query

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetrievalBundle:
    items: list[dict[str, Any]] = field(default_factory=list)
    evidenceStatus: EvidenceStatus = EvidenceStatus.ABSTAINED
    degradedReason: str | None = None


class CorpusRetrievalPort(Protocol):
    def full_search(self, owner_id: str, query: str) -> RetrievalBundle: ...


class ExternalSearchPort(Protocol):
    def search(self, query: str) -> RetrievalBundle: ...


class SimilarityPort(Protocol):
    def check(self, owner_id: str, manuscript_ref: dict[str, Any]) -> RetrievalBundle: ...


@dataclass(frozen=True)
class NoveltyLlmDraft:
    similarWorks: dict[str, Any]
    noveltyCandidates: dict[str, Any]
    experimentPlan: dict[str, Any]
    degradedReason: str | None = None


class NoveltyLlmPort(Protocol):
    def draft(
        self,
        *,
        topic: str,
        corpus: RetrievalBundle,
        external: RetrievalBundle,
    ) -> NoveltyLlmDraft: ...


class NotionExportPort(Protocol):
    """US-NV8(#258) — connection={"token","parentPageId"}(복호화된 값), content=제목+아티팩트."""

    def export(self, connection: dict[str, str], content: dict[str, Any]) -> str: ...


class EvidenceFormationAdapterPort(Protocol):
    """US-NV1(#251) — 자연어 잡의 근거형성 선행 호출. D5 포트를 RetrievalBundle로 매핑."""

    def form(self, owner_id: str, topic: str) -> RetrievalBundle: ...


class NoopCorpusRetrievalClient:
    def full_search(self, owner_id: str, query: str) -> RetrievalBundle:
        return RetrievalBundle(
            items=[],
            degradedReason=(
                f"U2 full search adapter not configured for {sanitize_external_query(query)}"
            ),
        )


class U2FullSearchCorpusRetrievalClient:
    def __init__(self, orchestrator: Any, grounding_hook: Any) -> None:
        self._orchestrator = orchestrator
        self._grounding_hook = grounding_hook

    def full_search(self, owner_id: str, query: str) -> RetrievalBundle:
        from discovery.api.gateway_seam import run_search
        from discovery.domain.models import AuthSession, RequestContext
        from discovery.service.orchestrator import SearchUnavailable
        from docsuri_shared.dtos import (
            AbstainDTO,
            DegradedResultDTO,
            SearchRequest,
            SearchResultPageDTO,
            ValidationErrorDTO,
        )

        ctx = RequestContext(
            auth_session=AuthSession(user_id=owner_id),
            request_id=f"novelty-{uuid4().hex}",
        )
        try:
            response = run_search(
                self._orchestrator,
                self._grounding_hook,
                SearchRequest(query=query, scope="full"),
                ctx,
            )
        except SearchUnavailable:
            return RetrievalBundle(degradedReason="U2 full search unavailable")

        root = response.root
        if isinstance(root, (SearchResultPageDTO, DegradedResultDTO)):
            items = [_card_item(card) for card in root.cards]
            degraded = getattr(root.meta, "degraded", False)
            mode = getattr(getattr(root, "mode", None), "root", None)
            return RetrievalBundle(
                items=items,
                evidenceStatus=(
                    EvidenceStatus.SUPPORTED if items else EvidenceStatus.ABSTAINED
                ),
                degradedReason=(
                    f"U2 full search returned degraded results: {mode or 'partial'}"
                    if degraded
                    else None
                ),
            )
        if isinstance(root, AbstainDTO):
            return RetrievalBundle(degradedReason=f"U2 full search abstained: {root.reason}")
        if isinstance(root, ValidationErrorDTO):
            return RetrievalBundle(degradedReason=f"U2 full search rejected query: {root.message}")
        return RetrievalBundle(degradedReason="U2 full search returned an unsupported response")


def _card_item(card: Any) -> dict[str, Any]:
    url = card.sourceUrl or card.arxivUrl
    source_name = card.sourceName or "arXiv"
    source_ref = {
        "type": "url",
        "identifier": card.arxivId,
        "title": card.title,
        "url": url,
        "sourceName": source_name,
    }
    return {
        "title": card.title,
        "authors": card.authors,
        "year": card.year,
        "abstractSnippet": card.abstractSnippet,
        "arxivId": card.arxivId,
        "sourceName": source_name,
        "sourceUrl": url,
        "evidenceStatus": EvidenceStatus.SUPPORTED.value,
        "sourceRefs": [source_ref],
    }


class NoopEvidenceFormationClient:
    def form(self, owner_id: str, topic: str) -> RetrievalBundle:
        return RetrievalBundle(items=[])


class EvidenceFormationClient:
    """US-NV1(#251) — U12는 shared/ports EvidenceFormationPort(D5) 추상으로만 근거형성을 소비.

    포트는 async — 동기 워커와 inline 디스패치(이벤트 루프 위) 양쪽에서 안전하도록
    전용 스레드에서 asyncio.run으로 실행한다. abstain·장애는 저하로만 수렴(날조 금지).
    """

    def __init__(self, port: Any) -> None:
        self._port = port

    def form(self, owner_id: str, topic: str) -> RetrievalBundle:
        from docsuri_shared._generated.dtos.evidence_schema import EvidenceRequest

        request = EvidenceRequest(topic=topic[:2000])
        ctx = SimpleNamespace(
            owner_id=owner_id,
            request_id=f"novelty-evidence-{uuid4().hex}",
            budget_signal={},
        )
        try:
            result = _run_coro_in_thread(self._port.form_evidence(request, ctx))
        except Exception:  # noqa: BLE001 - optional enrichment; corpus search is the main path.
            log.warning("novelty evidence formation unavailable", exc_info=True)
            return RetrievalBundle(items=[])
        return _bundle_from_evidence_result(result)


def _run_coro_in_thread(coro: Any) -> Any:
    """이벤트 루프 유무와 무관하게 코루틴을 동기 완주 — inline 디스패치는 루프 위에서 돈다."""
    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def _bundle_from_evidence_result(result: Any) -> RetrievalBundle:
    """D5 EvidenceResult|EvidenceAbstainResult → RetrievalBundle. abstain은 선택 보강 없음."""
    if str(getattr(result, "state", "") or "") == "abstain":
        return RetrievalBundle(items=[])
    items = [
        item
        for claim in (getattr(result, "claims", None) or [])
        if (item := _evidence_claim_item(claim))
    ]
    if not items:
        return RetrievalBundle(items=[])
    return RetrievalBundle(items=items, evidenceStatus=EvidenceStatus.SUPPORTED)


def _evidence_claim_item(claim: Any) -> dict[str, Any]:
    """EvidenceItem → 번들 item. userdoc 출처에는 arXiv URL을 만들지 않는다."""
    statement = str(getattr(claim, "statement", "") or "").strip()
    if not statement:
        return {}
    refs: list[dict[str, Any]] = []
    quote = ""
    for ref in getattr(claim, "supporting", None) or []:
        paper_id = str(getattr(ref, "paperId", "") or "").strip()
        if not paper_id:
            continue
        quote = quote or str(getattr(ref, "quote", "") or "")
        if paper_id.startswith("userdoc:"):
            refs.append(
                {
                    "type": "upload",
                    "identifier": paper_id,
                    "title": "User uploaded PDF",
                    "sourceName": "User upload",
                }
            )
            continue
        refs.append(
            {
                "type": "paper",
                "identifier": paper_id,
                "title": f"arXiv:{paper_id}",
                "url": f"https://arxiv.org/abs/{paper_id}",
                "sourceName": "arXiv",
            }
        )
    item: dict[str, Any] = {
        "title": statement[:240],
        "summary": (quote or statement)[:1000],
        "sourceType": "evidence_claim",
        "sourceName": "U11 evidence",
        "evidenceStatus": (
            EvidenceStatus.SUPPORTED.value if refs else EvidenceStatus.ABSTAINED.value
        ),
        "sourceRefs": refs,
    }
    conflicting = len(getattr(claim, "conflicting", None) or [])
    if conflicting:
        item["conflictingCount"] = conflicting  # D5 — 상충 출처 존재 신호(novelty 판단 입력)
    return item


class NoopExternalSearchClient:
    def search(self, query: str) -> RetrievalBundle:
        return RetrievalBundle(
            items=[],
            degradedReason=(
                f"external browser adapter not configured for {sanitize_external_query(query)}"
            ),
        )


class ExternalApiSearchClient:
    def __init__(
        self,
        client: Any,
        *,
        github_token: str | None = None,
        per_source: int = 3,
    ) -> None:
        self._client = client
        self._github_token = github_token
        self._per_source = per_source

    def search(self, query: str) -> RetrievalBundle:
        cleaned = sanitize_external_query(query)
        items: list[dict[str, Any]] = []
        degraded: list[str] = []
        for source, search in (
            ("github", self._github_repos),
            ("huggingface", self._huggingface_datasets),
            ("zenodo", self._zenodo_records),
        ):
            try:
                items.extend(search(cleaned))
            except Exception:  # noqa: BLE001 - one external source must not fail the job.
                degraded.append(f"{source} external search unavailable")

        deduped = _dedupe_by_url(items)
        return RetrievalBundle(
            items=deduped,
            evidenceStatus=(
                EvidenceStatus.SUPPORTED if deduped else EvidenceStatus.ABSTAINED
            ),
            degradedReason="; ".join(degraded) or None,
        )

    def _github_repos(self, query: str) -> list[dict[str, Any]]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self._github_token:
            headers["Authorization"] = f"Bearer {self._github_token}"
        payload = self._json(
            "https://api.github.com/search/repositories",
            params={
                "q": f"{query} in:name,description,readme",
                "sort": "updated",
                "order": "desc",
                "per_page": self._per_source,
            },
            headers=headers,
        )
        return [
            _external_item(
                source_type="github_repo",
                source_name="GitHub",
                title=str(repo.get("full_name") or ""),
                url=str(repo.get("html_url") or ""),
                summary=str(repo.get("description") or ""),
                identifier=str(repo.get("full_name") or ""),
                updatedAt=repo.get("updated_at"),
                stars=repo.get("stargazers_count"),
                language=repo.get("language"),
                license=((repo.get("license") or {}).get("spdx_id")),
                topics=repo.get("topics") or [],
            )
            for repo in payload.get("items", [])[: self._per_source]
        ]

    def _huggingface_datasets(self, query: str) -> list[dict[str, Any]]:
        payload = self._json(
            "https://huggingface.co/api/datasets",
            params={"search": query, "limit": self._per_source},
        )
        return [
            _external_item(
                source_type="dataset",
                source_name="Hugging Face",
                title=str(dataset.get("id") or ""),
                url=f"https://huggingface.co/datasets/{dataset.get('id')}",
                summary=_summary_from_hf_dataset(dataset),
                identifier=str(dataset.get("id") or ""),
                provider="huggingface",
                downloads=dataset.get("downloads"),
                likes=dataset.get("likes"),
                updatedAt=dataset.get("lastModified"),
                tags=dataset.get("tags") or [],
            )
            for dataset in payload[: self._per_source]
            if dataset.get("id")
        ]

    def _zenodo_records(self, query: str) -> list[dict[str, Any]]:
        payload = self._json(
            "https://zenodo.org/api/records",
            params={
                "q": f"{query} dataset",
                "type": "dataset",
                "sort": "mostrecent",
                "size": self._per_source,
            },
        )
        records = (payload.get("hits") or {}).get("hits") or []
        return [
            _external_item(
                source_type="dataset",
                source_name="Zenodo",
                title=str((record.get("metadata") or {}).get("title") or ""),
                url=str((record.get("links") or {}).get("html") or ""),
                summary=_strip_html(str((record.get("metadata") or {}).get("description") or "")),
                identifier=str(record.get("doi") or record.get("id") or ""),
                provider="zenodo",
                publishedAt=(record.get("metadata") or {}).get("publication_date"),
                keywords=(record.get("metadata") or {}).get("keywords") or [],
            )
            for record in records[: self._per_source]
        ]

    def _json(
        self,
        url: str,
        *,
        params: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> Any:
        response = self._client.get(url, params=params, headers=headers or {})
        if getattr(response, "status_code", 200) >= 400:
            raise RuntimeError("external API unavailable")
        raise_for_status = getattr(response, "raise_for_status", None)
        if raise_for_status is not None:
            raise_for_status()
        return response.json()


def _external_item(
    *,
    source_type: str,
    source_name: str,
    title: str,
    url: str,
    summary: str,
    identifier: str,
    **extra: Any,
) -> dict[str, Any]:
    if not title or not _safe_https_url(url):
        return {}
    source_ref = {
        "type": "url",
        "identifier": identifier or url,
        "title": title,
        "url": url,
        "sourceName": source_name,
    }
    return {
        "title": title,
        "summary": summary[:1000],
        "url": url,
        "sourceType": source_type,
        "sourceName": source_name,
        "evidenceStatus": EvidenceStatus.SUPPORTED.value,
        "sourceRefs": [source_ref],
        **{key: value for key, value in extra.items() if value not in (None, "", [])},
    }


def _dedupe_by_url(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for item in items:
        url = item.get("url")
        if not url or url in seen:
            continue
        seen.add(str(url))
        deduped.append(item)
    return deduped


def _safe_https_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" and bool(parsed.hostname)


def _summary_from_hf_dataset(dataset: dict[str, Any]) -> str:
    card = dataset.get("cardData") or {}
    description = card.get("description") if isinstance(card, dict) else None
    if description:
        return str(description)
    return ", ".join(str(tag) for tag in dataset.get("tags") or [])[:1000]


def _strip_html(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).strip()


class NoopSimilarityClient:
    def check(self, owner_id: str, manuscript_ref: dict[str, Any]) -> RetrievalBundle:
        return RetrievalBundle(items=[], degradedReason="similarity adapter not configured")


class NoopNoveltyLlmClient:
    def draft(
        self,
        *,
        topic: str,
        corpus: RetrievalBundle,
        external: RetrievalBundle,
    ) -> NoveltyLlmDraft:
        return NoveltyLlmDraft(
            similarWorks=_fallback_similar_works(),
            noveltyCandidates=_fallback_novelty_candidates(),
            experimentPlan=_fallback_experiment_plan(topic),
            degradedReason="LLM adapter not configured",
        )


def _cost_gated(cost_guard: Any) -> bool:
    """NFR-C1 — agent LLM hard gate는 critical 이상에서만 발화(None이면 게이트 없음)."""
    if cost_guard is None:
        return False
    from docsuri_ops.cost_guard import is_cost_critical

    return is_cost_critical(cost_guard.get_budget_state())


def _record_bedrock_spend(cost_guard: Any, usage: dict[str, Any]) -> None:
    """NFR-C1 — Bedrock usage 토큰을 cost guard 지출로 기록. 계측은 best-effort."""
    if cost_guard is None or not usage:
        return
    try:
        from docsuri_ops.cost_guard import estimate_bedrock_usd
        from docsuri_ops.domain.models import UsageEvent

        amount = estimate_bedrock_usd(
            input_tokens=int(usage.get("input_tokens") or 0),
            output_tokens=int(usage.get("output_tokens") or 0),
        )
        if amount > 0:
            cost_guard.record_spend(
                UsageEvent(
                    event_id=f"novelty-llm-{uuid4()}",
                    amount_usd=amount,
                    source="novelty.llm",
                )
            )
    except Exception:  # noqa: BLE001 — 지출 계측 실패가 draft를 막으면 안 된다
        import logging

        logging.getLogger(__name__).warning("failed to record novelty Bedrock spend")


class BedrockNoveltyLlmClient:
    def __init__(
        self,
        *,
        model_id: str,
        client: Any,
        max_tokens: int = 8192,
        cost_guard: Any = None,
    ) -> None:
        self._model_id = model_id
        self._client = client
        self._max_tokens = max_tokens
        self._cost_guard = cost_guard

    def draft(
        self,
        *,
        topic: str,
        corpus: RetrievalBundle,
        external: RetrievalBundle,
    ) -> NoveltyLlmDraft:
        # NFR-C1 비용 게이트 — LLM 호출 전에 차단, 기존 저하(not-fail) 패턴으로 강등.
        if _cost_gated(self._cost_guard):
            return NoveltyLlmDraft(
                similarWorks=_fallback_similar_works(),
                noveltyCandidates=_fallback_novelty_candidates(),
                experimentPlan=_fallback_experiment_plan(topic),
                degradedReason="cost_degraded",
            )
        refs = _source_ref_catalog(corpus.items + external.items)
        if not refs:
            return NoveltyLlmDraft(
                similarWorks=_fallback_similar_works(),
                noveltyCandidates=_fallback_novelty_candidates(),
                experimentPlan=_fallback_experiment_plan(topic),
                degradedReason="LLM input has no grounded sourceRefs",
            )
        try:
            payload = self._invoke_json(
                _novelty_system_prompt(),
                _novelty_user_prompt(topic, corpus.items, external.items, refs),
            )
        except Exception as exc:  # noqa: BLE001 - LLM outage degrades, not fails, the job.
            return NoveltyLlmDraft(
                similarWorks=_fallback_similar_works(),
                noveltyCandidates=_fallback_novelty_candidates(),
                experimentPlan=_fallback_experiment_plan(topic),
                degradedReason=f"LLM generation unavailable: {type(exc).__name__}",
            )
        return NoveltyLlmDraft(
            similarWorks=_llm_items_payload(
                payload.get("similarWorks"),
                refs,
                fallback=_fallback_similar_works(),
                detail_fields=SIMILAR_WORK_DETAIL_FIELDS,
            ),
            noveltyCandidates=_llm_items_payload(
                payload.get("noveltyCandidates"),
                refs,
                fallback=_fallback_novelty_candidates(),
            ),
            experimentPlan=_llm_experiment_plan(payload.get("experimentPlan"), topic, refs),
        )

    def _invoke_json(self, system: str, user: str) -> dict[str, Any]:
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": self._max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": [{"type": "text", "text": user}]}],
            "tools": [_novelty_tool()],
            "tool_choice": {"type": "tool", "name": "emit_novelty_analysis"},
        }
        response = self._client.invoke_model_with_response_stream(
            modelId=self._model_id,
            body=json.dumps(body).encode("utf-8"),
            accept="application/json",
            contentType="application/json",
        )
        text, usage = _bedrock_stream_read(response)
        _record_bedrock_spend(self._cost_guard, usage)
        try:
            return _parse_json_object(text)
        except json.JSONDecodeError as exc:
            log.warning(
                "novelty Bedrock JSON parse failed; stopReason=%s outputLength=%d "
                "jsonPos=%d rawPreview=%r",
                usage.get("stop_reason"),
                len(text),
                exc.pos,
                _safe_log_preview(text),
            )
            raise
        except ValueError:
            log.warning(
                "novelty Bedrock JSON parse failed; stopReason=%s outputLength=%d "
                "jsonPos=n/a rawPreview=%r",
                usage.get("stop_reason"),
                len(text),
                _safe_log_preview(text),
            )
            raise


def _source_ref_catalog(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        for ref in item.get("sourceRefs") or item.get("source_refs") or []:
            if not isinstance(ref, dict):
                continue
            key = str(ref.get("url") or ref.get("identifier") or "")
            if not key or key in seen:
                continue
            seen.add(key)
            refs.append(ref)
    return refs[:12]


# US-NV3(#253) — 유사 연구 표 상세 칼럼. 근거 없는 칸은 null(기권)로 남기고 FE가
# '근거 부족'으로 표시한다. 추측 금지는 시스템 프롬프트와 정규화가 함께 강제한다.
SIMILAR_WORK_DETAIL_FIELDS = (
    "problem",
    "method",
    "dataset",
    "results",
    "limitations",
    "overlap",
)


def _novelty_system_prompt() -> str:
    return (
        "You are DocSuri's novelty-analysis assistant. Return only valid JSON. "
        "Fit the response within the available output budget: at most 3 similarWorks, "
        "3 noveltyCandidates, 5 items per experimentPlan list, and concise strings. "
        "Use only the supplied sourceRefIndexes; never invent URLs, titles, datasets, or papers. "
        "For each similarWorks detail field (problem, method, dataset, results, limitations, "
        'overlap — how it overlaps the user\'s topic), return {"value": string, '
        '"sourceRefIndexes": [int]} citing the specific sources that support that value; '
        "if no supplied source supports it, set the field to null. Never guess."
    )


def _novelty_user_prompt(
    topic: str,
    corpus_items: list[dict[str, Any]],
    external_items: list[dict[str, Any]],
    refs: list[dict[str, Any]],
) -> str:
    context = {
        "topic": topic,
        "corpusItems": _compact_items(corpus_items),
        "externalItems": _compact_items(external_items),
        "sourceRefs": [
            {
                "index": i,
                "title": ref.get("title"),
                "url": ref.get("url"),
                "sourceName": ref.get("sourceName"),
            }
            for i, ref in enumerate(refs)
        ],
    }
    contract = {
        "similarWorks": [
            {
                "title": "string",
                "summary": "string",
                "problem": {"value": "string", "sourceRefIndexes": [0]},
                "method": {"value": "string", "sourceRefIndexes": [0]},
                "dataset": {"value": "string", "sourceRefIndexes": [0]},
                "results": {"value": "string", "sourceRefIndexes": [0]},
                "limitations": {"value": "string", "sourceRefIndexes": [0]},
                "overlap": {"value": "string", "sourceRefIndexes": [0]},
                "sourceRefIndexes": [0],
            }
        ],
        "noveltyCandidates": [
            {"title": "string", "rationale": "string", "sourceRefIndexes": [0]}
        ],
        "experimentPlan": {
            "researchQuestion": "string",
            "noveltyAngle": "string",
            "hypotheses": ["string"],
            "baselines": ["string"],
            "procedure": ["string"],
            "datasets": ["string"],
            "metrics": ["string"],
            "resources": ["string"],
            "risks": ["string"],
            "sourceRefIndexes": [0],
        },
    }
    return (
        f"<context>{json.dumps(context, ensure_ascii=False)}</context>\n"
        f"<json_contract>{json.dumps(contract, ensure_ascii=False)}</json_contract>"
    )


def _novelty_tool() -> dict[str, Any]:
    text_field = {"type": "string", "maxLength": 600}
    short_list = {"type": "array", "items": text_field, "maxItems": 5}
    ref_indexes = {"type": "array", "items": {"type": "integer"}, "maxItems": 3}
    detail = {
        "anyOf": [
            {
                "type": "object",
                "properties": {"value": text_field, "sourceRefIndexes": ref_indexes},
                "required": ["value", "sourceRefIndexes"],
            },
            {"type": "null"},
        ]
    }
    return {
        "name": "emit_novelty_analysis",
        "description": "Emit grounded novelty analysis using only supplied sourceRefIndexes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "similarWorks": {
                    "type": "array",
                    "maxItems": 3,
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": text_field,
                            "summary": text_field,
                            "problem": detail,
                            "method": detail,
                            "dataset": detail,
                            "results": detail,
                            "limitations": detail,
                            "overlap": detail,
                            "sourceRefIndexes": ref_indexes,
                        },
                        "required": ["title", "summary", "sourceRefIndexes"],
                    },
                },
                "noveltyCandidates": {
                    "type": "array",
                    "maxItems": 3,
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": text_field,
                            "rationale": text_field,
                            "sourceRefIndexes": ref_indexes,
                        },
                        "required": ["title", "rationale", "sourceRefIndexes"],
                    },
                },
                "experimentPlan": {
                    "type": "object",
                    "properties": {
                        "researchQuestion": text_field,
                        "noveltyAngle": text_field,
                        "hypotheses": short_list,
                        "baselines": short_list,
                        "procedure": short_list,
                        "datasets": short_list,
                        "metrics": short_list,
                        "resources": short_list,
                        "risks": short_list,
                        "sourceRefIndexes": ref_indexes,
                    },
                    "required": [
                        "researchQuestion",
                        "noveltyAngle",
                        "hypotheses",
                        "baselines",
                        "procedure",
                        "datasets",
                        "metrics",
                        "resources",
                        "risks",
                        "sourceRefIndexes",
                    ],
                },
            },
            "required": ["similarWorks", "noveltyCandidates", "experimentPlan"],
        },
    }


def _compact_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for item in items[:8]:
        compact.append(
            {
                "title": item.get("title"),
                "summary": (item.get("summary") or item.get("abstractSnippet") or "")[:500],
                "sourceType": item.get("sourceType"),
                "sourceName": item.get("sourceName"),
            }
        )
    return compact


def _llm_items_payload(
    raw: Any,
    refs: list[dict[str, Any]],
    *,
    fallback: dict[str, Any],
    detail_fields: tuple[str, ...] = (),
) -> dict[str, Any]:
    if not isinstance(raw, list):
        return fallback
    items: list[dict[str, Any]] = []
    for item in raw[:5]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        item_refs = _refs_by_indexes(item.get("sourceRefIndexes"), refs)
        entry: dict[str, Any] = {
            "title": title[:240],
            "summary": str(item.get("summary") or item.get("rationale") or "")[:1000],
            "evidenceStatus": (
                EvidenceStatus.SUPPORTED.value
                if item_refs
                else EvidenceStatus.ABSTAINED.value
            ),
            "sourceRefs": item_refs,
        }
        for column in detail_fields:
            # B-001 — 상세 칸은 칸 자신의 sourceRefIndexes로 근거를 증명해야 값이 남는다.
            # row 단위 출처를 포괄 근거로 쓰지 않으며, 검증 불가(bare string 포함)는 기권.
            # 키는 항상 실어 null=기권을 명시한다 — FE가 '근거 부족' 칸으로 구분(#253).
            entry[column] = _grounded_detail(item.get(column), refs)
        items.append(entry)
    if not items:
        return fallback
    return _items_payload(items)


def _refs_by_indexes(raw: Any, refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    selected: list[dict[str, Any]] = []
    for value in raw[:3]:
        if isinstance(value, int) and 0 <= value < len(refs):
            selected.append(refs[value])
    return selected


def _grounded_detail(raw: Any, refs: list[dict[str, Any]]) -> str | None:
    """유사 연구 표 상세 칸(#253 B-001) — {value, sourceRefIndexes} 필드별 근거 필수."""
    if not isinstance(raw, dict):
        return None
    value = raw.get("value")
    text = value.strip() if isinstance(value, str) else ""
    if not text or not _refs_by_indexes(raw.get("sourceRefIndexes"), refs):
        return None
    return text[:500]


def _llm_experiment_plan(raw: Any, topic: str, refs: list[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return _fallback_experiment_plan(topic)
    source_refs = _refs_by_indexes(raw.get("sourceRefIndexes"), refs)
    return {
        "researchQuestion": str(raw.get("researchQuestion") or topic)[:500],
        "noveltyAngle": str(
            raw.get("noveltyAngle")
            or "Ground the differentiator in retrieved evidence."
        )[:500],
        "hypotheses": _string_list(raw.get("hypotheses"))
        or ["A grounded differentiator improves over close prior work."],
        "baselines": _string_list(raw.get("baselines"))
        or ["Closest retrieved prior-work baseline."],
        "procedure": _string_list(raw.get("procedure"))
        or [
            "Select the closest retrieved prior work.",
            "Run the same task against the proposed differentiator and baselines.",
            "Compare metrics and inspect failure cases with source references.",
        ],
        "datasets": _string_list(raw.get("datasets")) or ["Select from dataset search results."],
        "metrics": _string_list(raw.get("metrics")) or [
            "baseline delta",
            "evidence coverage",
            "reproducibility checklist pass rate",
        ],
        "resources": _string_list(raw.get("resources"))
        or ["Retrieved papers, public datasets, and reproducible evaluation scripts."],
        "risks": _string_list(raw.get("risks")) or ["Weak evidence", "dataset mismatch"],
        "evidenceStatus": (
            EvidenceStatus.SUPPORTED.value
            if source_refs
            else EvidenceStatus.ABSTAINED.value
        ),
        "sourceRefs": source_refs,
    }


def _string_list(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(item).strip()[:240] for item in raw[:8] if str(item).strip()]


def _items_payload(items: list[dict[str, Any]]) -> dict[str, Any]:
    refs = _source_ref_catalog(items)
    return {
        "items": items,
        "evidenceStatus": (
            EvidenceStatus.SUPPORTED.value if refs else EvidenceStatus.ABSTAINED.value
        ),
        "sourceRefs": refs,
    }


def _fallback_similar_works() -> dict[str, Any]:
    return {
        "items": [],
        "evidenceStatus": EvidenceStatus.ABSTAINED.value,
        "sourceRefs": [],
    }


def _fallback_novelty_candidates() -> dict[str, Any]:
    return {
        "items": [
            {
                "title": "Add an evidence-backed differentiator after corpus retrieval",
                "evidenceStatus": EvidenceStatus.ABSTAINED.value,
                "sourceRefs": [],
            }
        ],
        "evidenceStatus": EvidenceStatus.ABSTAINED.value,
        "sourceRefs": [],
    }


def _fallback_experiment_plan(topic: str) -> dict[str, Any]:
    return {
        "researchQuestion": topic,
        "noveltyAngle": "Ground the differentiator in retrieved evidence before execution.",
        "hypotheses": ["A differentiator grounded in retrieved evidence improves novelty."],
        "baselines": ["Closest retrieved prior-work baseline."],
        "procedure": [
            "Select the closest retrieved prior work.",
            "Run the proposed differentiator against the same task and data.",
            "Compare outcomes and document unsupported assumptions.",
        ],
        "datasets": ["To be selected from dataset search results."],
        "metrics": [
            "baseline delta",
            "evidence coverage",
            "reproducibility checklist pass rate",
        ],
        "resources": ["Retrieved papers, public datasets, and evaluation scripts."],
        "risks": ["Weak evidence", "dataset mismatch", "unapproved Notion export"],
        "evidenceStatus": EvidenceStatus.ABSTAINED.value,
        "sourceRefs": [],
    }


def _parse_json_object(text: str) -> dict[str, Any]:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in model output")
    parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("model output is not a JSON object")
    return parsed


def _bedrock_stream_read(response: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """스트림에서 tool input JSON과 usage 수집."""
    tool_chunks: list[str] = []
    text_chunks: list[str] = []
    usage: dict[str, Any] = {}
    for event in response.get("body", []):
        raw = event.get("chunk", {}).get("bytes")
        if not raw:
            continue
        data = json.loads(raw.decode("utf-8"))
        kind = data.get("type")
        if kind == "message_start":
            usage.update(data.get("message", {}).get("usage") or {})
        elif kind == "message_delta":
            usage.update(data.get("usage") or {})
            stop_reason = data.get("delta", {}).get("stop_reason")
            if stop_reason:
                usage["stop_reason"] = stop_reason
        elif kind == "content_block_delta":
            delta = data.get("delta", {})
            if delta.get("type") == "input_json_delta":
                tool_chunks.append(str(delta.get("partial_json") or ""))
            elif delta.get("type") == "text_delta":
                text_chunks.append(str(delta.get("text") or ""))
    return "".join(tool_chunks or text_chunks), usage


def _safe_log_preview(text: str, limit: int = 500) -> str:
    return re.sub(r"[\x00-\x1f\x7f]+", " ", text)[:limit]


class S3ManuscriptSimilarityClient:
    def __init__(
        self,
        *,
        bucket: str,
        corpus: CorpusRetrievalPort,
        client: Any,
        prefix: str = "novelty/",
        user_docmodel: Any = None,
    ) -> None:
        self._bucket = bucket
        self._corpus = corpus
        self._client = client
        self._prefix = prefix
        self._user_docmodel = user_docmodel

    def check(self, owner_id: str, manuscript_ref: dict[str, Any]) -> RetrievalBundle:
        object_key = str(manuscript_ref.get("objectKey") or "")
        content_type = str(manuscript_ref.get("contentType") or "").lower()
        if not object_key:
            return RetrievalBundle(degradedReason="manuscript objectKey is required")
        if not object_key.startswith(self._prefix):
            return RetrievalBundle(degradedReason="manuscript objectKey is outside novelty prefix")
        if not object_key.startswith(f"{self._prefix}{owner_id}/"):
            return RetrievalBundle(degradedReason="manuscript objectKey is outside owner prefix")
        job_id = str(manuscript_ref.get("jobId") or "")
        if job_id and not object_key.startswith(f"{self._prefix}{owner_id}/{job_id}/"):
            return RetrievalBundle(degradedReason="manuscript objectKey is outside job prefix")
        if content_type == USER_DOCMODEL_PDF_CONTENT_TYPE:
            text = self._read_pdf_doc_model(owner_id, manuscript_ref)
            if not text:
                return RetrievalBundle(degradedReason=NOVELTY_PDF_DEGRADED_REASON)
        elif content_type in {"text/plain", "text/markdown"}:
            text = self._read_text(object_key)
        else:
            return RetrievalBundle(
                degradedReason=f"similarity text extraction not configured for {content_type}"
            )

        sentences = _candidate_sentences(text)
        items = _ai_style_items(text)
        for sentence in sentences[:3]:
            bundle = self._corpus.full_search(owner_id, sentence[:500])
            match = _best_supported_match(bundle.items)
            if match is not None:
                items.append(_similarity_item(sentence, match))

        supported = any(
            item.get("evidenceStatus") == EvidenceStatus.SUPPORTED.value for item in items
        )
        return RetrievalBundle(
            items=items,
            evidenceStatus=EvidenceStatus.SUPPORTED if supported else EvidenceStatus.ABSTAINED,
        )

    def _read_text(self, object_key: str) -> str:
        # ponytail: first 256 KiB is enough for a fast risk signal; stream extraction if needed.
        response = self._client.get_object(
            Bucket=self._bucket,
            Key=object_key,
            Range="bytes=0-262143",
        )
        return response["Body"].read().decode("utf-8", errors="replace")

    def _manuscript_docmodel_ref(self, owner_id: str, manuscript_ref: dict[str, Any]):
        object_key = str(manuscript_ref.get("objectKey") or "")
        job_id = str(manuscript_ref.get("jobId") or "manuscript")
        try:
            return ref_from_attachment(
                owner_id=owner_id,
                scope_id=job_id,
                attachment_id="manuscript",
                object_key=object_key,
                module="novelty",
                paper_id=manuscript_ref.get("paperId"),
                record_ref=manuscript_ref.get("recordRef"),
            )
        except ValueError:
            return None

    def manuscript_doc_model_ready(self, owner_id: str, manuscript_ref: dict[str, Any]) -> bool:
        """Non-blocking readiness probe for the worker's early retry gate. True when the user PDF's
        doc-model is already built — or when no reader is configured / the ref is unbuildable, so
        the caller proceeds to the normal (degrade) path instead of looping forever."""
        if self._user_docmodel is None:
            return True
        ref = self._manuscript_docmodel_ref(owner_id, manuscript_ref)
        if ref is None:
            return True
        # Re-trigger the build (idempotent) so a lost/expired build message still lands.
        self._user_docmodel.enqueue_build(ref)
        return self._user_docmodel.peek_doc_model(ref) is not None

    def _read_pdf_doc_model(self, owner_id: str, manuscript_ref: dict[str, Any]) -> str:
        if self._user_docmodel is None:
            return ""
        ref = self._manuscript_docmodel_ref(owner_id, manuscript_ref)
        if ref is None:
            return ""
        doc_model = self._user_docmodel.enqueue_and_poll(ref)
        text = str(getattr(doc_model, "fullText", "") or "") if doc_model is not None else ""
        return text.strip()


def _candidate_sentences(text: str) -> list[str]:
    sentences = [
        re.sub(r"\s+", " ", part).strip()
        for part in re.split(r"(?<=[.!?。！？])\s+", text)
    ]
    return sorted(
        [sentence for sentence in sentences if len(sentence) >= 80],
        key=len,
        reverse=True,
    )


def _best_supported_match(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    for item in items:
        refs = item.get("sourceRefs") or item.get("source_refs") or []
        if refs:
            return item
    return None


def _similarity_item(sentence: str, match: dict[str, Any]) -> dict[str, Any]:
    refs = match.get("sourceRefs") or match.get("source_refs") or []
    return {
        "title": f"Potential overlap with {match.get('title') or 'corpus result'}",
        "riskType": "sentence_similarity",
        "sentence": sentence[:500],
        "matchedTitle": match.get("title"),
        "evidenceStatus": EvidenceStatus.SUPPORTED.value,
        "sourceRefs": refs,
    }


def _ai_style_items(text: str) -> list[dict[str, Any]]:
    normalized = re.sub(r"\s+", " ", text).strip()
    if len(normalized) < 400:
        return []
    markers = (
        "delve",
        "underscore",
        "pivotal",
        "landscape",
        "robust framework",
        "comprehensive analysis",
    )
    hits = [marker for marker in markers if marker in normalized.lower()]
    if not hits:
        return []
    return [
        {
            "title": "AI-style phrasing risk",
            "riskType": "ai_style",
            "markers": hits[:5],
            "evidenceStatus": EvidenceStatus.ABSTAINED.value,
            "sourceRefs": [],
        }
    ]


class NoopNotionExportClient:
    def export(self, connection: dict[str, str], content: dict[str, Any]) -> str:
        raise RuntimeError("Notion export adapter is not configured")


class NotionApiExportClient:
    """US-NV8(#258) — 명시 연결 토큰으로 Notion 페이지 생성. api.notion.com만 호출(allowlist)."""

    _API_URL = "https://api.notion.com/v1/pages"
    _VERSION = "2022-06-28"
    _MAX_BLOCKS = 90  # Notion 페이지 생성 children 한도(100) 밑

    def __init__(self, client: Any) -> None:
        self._client = client

    def export(self, connection: dict[str, str], content: dict[str, Any]) -> str:
        response = self._client.post(
            self._API_URL,
            headers={
                "Authorization": f"Bearer {connection['token']}",
                "Notion-Version": self._VERSION,
                "Content-Type": "application/json",
            },
            json={
                "parent": {"page_id": connection["parentPageId"]},
                "properties": {
                    "title": {
                        "title": [
                            {
                                "text": {
                                    "content": str(
                                        content.get("title") or "Novelty analysis"
                                    )[:200]
                                }
                            }
                        ]
                    }
                },
                "children": _notion_blocks(content)[: self._MAX_BLOCKS],
            },
        )
        if getattr(response, "status_code", 500) >= 400:
            raise RuntimeError(
                f"notion api returned {getattr(response, 'status_code', 'error')}"
            )
        page_id = str((response.json() or {}).get("id") or "")
        if not page_id:
            raise RuntimeError("notion api returned no page id")
        return page_id


def _notion_blocks(content: dict[str, Any]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    prompt = str(content.get("inputPrompt") or "").strip()
    if prompt:
        blocks.append(_notion_bullet(f"입력 프롬프트: {prompt}"))
    for artifact in content.get("artifacts") or []:
        title = str(artifact.get("title") or artifact.get("kind") or "").strip()
        if title:
            blocks.append(_notion_heading(title))
        payload = artifact.get("payload") or {}
        for item in (payload.get("items") or [])[:5]:
            if not isinstance(item, dict):
                continue
            item_title = str(item.get("title") or "").strip()
            summary = str(item.get("summary") or "").strip()
            text = f"{item_title} — {summary}" if item_title and summary else item_title or summary
            if text:
                blocks.append(_notion_bullet(text))
        question = str(payload.get("researchQuestion") or "").strip()
        if question:
            blocks.append(_notion_bullet(f"Research question: {question}"))
    return blocks


def _notion_heading(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "heading_2",
        "heading_2": {"rich_text": [{"type": "text", "text": {"content": text[:200]}}]},
    }


def _notion_bullet(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {
            "rich_text": [{"type": "text", "text": {"content": text[:500]}}]
        },
    }


def build_notion_adapter() -> NotionExportPort:
    import httpx

    return NotionApiExportClient(
        httpx.Client(timeout=10.0, headers={"User-Agent": "DocSuri-Novelty/1.0"})
    )


@dataclass(frozen=True)
class NoveltyAdapters:
    corpus: CorpusRetrievalPort = field(default_factory=NoopCorpusRetrievalClient)
    external: ExternalSearchPort = field(default_factory=NoopExternalSearchClient)
    similarity: SimilarityPort = field(default_factory=NoopSimilarityClient)
    llm: NoveltyLlmPort = field(default_factory=NoopNoveltyLlmClient)
    notion: NotionExportPort = field(default_factory=NoopNotionExportClient)
    evidence: EvidenceFormationAdapterPort = field(
        default_factory=NoopEvidenceFormationClient
    )


def build_default_novelty_adapters(
    observability=None,
    cost_guard=None,
    user_docmodel: Any = None,
) -> NoveltyAdapters:
    corpus = build_u2_full_search_corpus_adapter(
        observability=observability,
        cost_guard=cost_guard,
    )
    return NoveltyAdapters(
        corpus=corpus,
        external=build_external_adapter(),
        similarity=build_similarity_adapter(corpus, user_docmodel=user_docmodel),
        llm=build_llm_adapter(cost_guard=cost_guard),
        evidence=build_evidence_formation_adapter(cost_guard=cost_guard),
        notion=build_notion_adapter(),
    )


def build_evidence_formation_adapter(cost_guard: Any = None) -> EvidenceFormationAdapterPort:
    """U11 실 오케스트레이터 → D5 포트 조립 — corpus(U2 재사용) 어댑터와 같은 조립 루트 관례.

    U12 도메인 코드는 포트 추상만 호출하고, 구체 조립은 이 build 함수에만 둔다.
    DocModel 버킷 미구성이면 Noop(저하)로 동작한다.
    """
    try:
        from backend.modules.evidence.settings import EvidenceSettings
    except ModuleNotFoundError:
        return NoopEvidenceFormationClient()

    settings = EvidenceSettings.from_env()
    if not settings.evidence_enabled:
        return NoopEvidenceFormationClient()

    from backend.modules.evidence.real_wiring import build_evidence_orchestrator
    from backend.modules.evidence.service import EvidenceFormationService

    bundle = build_evidence_orchestrator(settings, cost_guard=cost_guard)
    return EvidenceFormationClient(
        EvidenceFormationService(orchestrator=bundle.orchestrator)
    )


def build_u2_full_search_corpus_adapter(observability=None, cost_guard=None) -> CorpusRetrievalPort:
    try:
        from discovery.adapters.settings import DiscoverySettings
    except ModuleNotFoundError:
        return NoopCorpusRetrievalClient()

    settings = DiscoverySettings.from_env()
    if not settings.search_enabled:
        return NoopCorpusRetrievalClient()

    from discovery.real_wiring import build_real_orchestrator
    from docsuri_ops.grounding import GroundingEnforcementHook

    bundle = build_real_orchestrator(
        settings,
        observability=observability,
        cost_guard=cost_guard,
    )
    return U2FullSearchCorpusRetrievalClient(bundle.orchestrator, GroundingEnforcementHook())


def store_manuscript_text(owner_id: str, job_id: str, content_type: str, text: str) -> str:
    """US-NV2(#252) — 원고 본문을 novelty/{owner}/{job}/ 프리픽스에 적재하고 key 반환.

    유사도 어댑터(S3ManuscriptSimilarityClient)가 같은 프리픽스 규약으로 읽는다.
    버킷 미구성 시 ValueError — 컨트롤러가 422 비기술 안내로 변환(SEC-5).
    """
    bucket = os.getenv("DOCSURI_NOVELTY_ARTIFACT_BUCKET")
    if not bucket:
        raise ValueError("원고 저장소가 구성되지 않아 파일 분석을 시작할 수 없습니다.")

    import boto3
    from botocore.exceptions import BotoCoreError, ClientError

    region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION", "ap-northeast-2")
    prefix = os.getenv("DOCSURI_NOVELTY_ARTIFACT_PREFIX", "novelty/")
    ext = ".md" if content_type == "text/markdown" else ".txt"
    object_key = f"{prefix}{owner_id}/{job_id}/manuscript{ext}"
    try:
        boto3.client("s3", region_name=region).put_object(
            Bucket=bucket,
            Key=object_key,
            Body=text.encode("utf-8"),
            ContentType=content_type,
        )
    except (BotoCoreError, ClientError) as exc:
        # IAM 권한 부재(PutObject) 포함 — 내부 오류 상세 없이 비기술 문구만(SEC-5/9).
        raise ValueError("원고 저장에 실패했습니다. 잠시 후 다시 시도해 주세요.") from exc
    return object_key


def build_similarity_adapter(
    corpus: CorpusRetrievalPort,
    *,
    user_docmodel: Any = None,
) -> SimilarityPort:
    bucket = os.getenv("DOCSURI_NOVELTY_ARTIFACT_BUCKET")
    if not bucket:
        return NoopSimilarityClient()

    import boto3

    region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION", "ap-northeast-2")
    return S3ManuscriptSimilarityClient(
        bucket=bucket,
        corpus=corpus,
        client=boto3.client("s3", region_name=region),
        prefix=os.getenv("DOCSURI_NOVELTY_ARTIFACT_PREFIX", "novelty/"),
        user_docmodel=user_docmodel,
    )


def build_external_adapter() -> ExternalSearchPort:
    import httpx

    return ExternalApiSearchClient(
        httpx.Client(
            timeout=5.0,
            headers={"User-Agent": "DocSuri-Novelty/1.0"},
        ),
        github_token=os.getenv("DOCSURI_GITHUB_TOKEN") or os.getenv("GITHUB_TOKEN"),
    )


def build_llm_adapter(cost_guard: Any = None) -> NoveltyLlmPort:
    import boto3
    from botocore.config import Config

    region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION", "ap-northeast-2")
    return BedrockNoveltyLlmClient(
        model_id=os.getenv(
            "DOCSURI_NOVELTY_LLM_MODEL_ID",
            "global.anthropic.claude-sonnet-4-6",
        ),
        client=boto3.client(
            "bedrock-runtime",
            region_name=region,
            config=Config(
                connect_timeout=5.0,
                read_timeout=300.0,
                retries={"max_attempts": 1},
            ),
        ),
        cost_guard=cost_guard,
    )
