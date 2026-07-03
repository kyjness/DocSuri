from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urlparse
from uuid import uuid4

from .models import EvidenceStatus
from .security import sanitize_external_query


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
    def export(self, owner_id: str, preview: dict[str, Any]) -> str: ...


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


class BedrockNoveltyLlmClient:
    def __init__(self, *, model_id: str, client: Any, max_tokens: int = 4096) -> None:
        self._model_id = model_id
        self._client = client
        self._max_tokens = max_tokens

    def draft(
        self,
        *,
        topic: str,
        corpus: RetrievalBundle,
        external: RetrievalBundle,
    ) -> NoveltyLlmDraft:
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
        }
        response = self._client.invoke_model(
            modelId=self._model_id,
            body=json.dumps(body).encode("utf-8"),
            accept="application/json",
            contentType="application/json",
        )
        raw_body = response["body"].read()
        model_payload = json.loads(raw_body.decode("utf-8"))
        text = "".join(
            part.get("text", "")
            for part in model_payload.get("content", [])
            if isinstance(part, dict)
        )
        return _parse_json_object(text)


def _source_ref_catalog(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        for ref in item.get("sourceRefs") or item.get("source_refs") or []:
            url = ref.get("url") if isinstance(ref, dict) else None
            if not url or url in seen:
                continue
            seen.add(str(url))
            refs.append(ref)
    return refs[:12]


def _novelty_system_prompt() -> str:
    return (
        "You are DocSuri's novelty-analysis assistant. Return only valid JSON. "
        "Use only the supplied sourceRefIndexes; never invent URLs, titles, datasets, or papers."
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
            {"title": "string", "summary": "string", "sourceRefIndexes": [0]}
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
        items.append(
            {
                "title": title[:240],
                "summary": str(item.get("summary") or item.get("rationale") or "")[:1000],
                "evidenceStatus": (
                    EvidenceStatus.SUPPORTED.value
                    if item_refs
                    else EvidenceStatus.ABSTAINED.value
                ),
                "sourceRefs": item_refs,
            }
        )
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


class S3ManuscriptSimilarityClient:
    def __init__(
        self,
        *,
        bucket: str,
        corpus: CorpusRetrievalPort,
        client: Any,
        prefix: str = "novelty/",
    ) -> None:
        self._bucket = bucket
        self._corpus = corpus
        self._client = client
        self._prefix = prefix

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
        if content_type not in {"text/plain", "text/markdown"}:
            return RetrievalBundle(
                degradedReason=f"similarity text extraction not configured for {content_type}"
            )

        text = self._read_text(object_key)
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
    def export(self, owner_id: str, preview: dict[str, Any]) -> str:
        raise RuntimeError("Notion export adapter is not configured")


@dataclass(frozen=True)
class NoveltyAdapters:
    corpus: CorpusRetrievalPort = field(default_factory=NoopCorpusRetrievalClient)
    external: ExternalSearchPort = field(default_factory=NoopExternalSearchClient)
    similarity: SimilarityPort = field(default_factory=NoopSimilarityClient)
    llm: NoveltyLlmPort = field(default_factory=NoopNoveltyLlmClient)
    notion: NotionExportPort = field(default_factory=NoopNotionExportClient)


def build_default_novelty_adapters(observability=None, cost_guard=None) -> NoveltyAdapters:
    corpus = build_u2_full_search_corpus_adapter(
        observability=observability,
        cost_guard=cost_guard,
    )
    return NoveltyAdapters(
        corpus=corpus,
        external=build_external_adapter(),
        similarity=build_similarity_adapter(corpus),
        llm=build_llm_adapter(),
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


def build_similarity_adapter(corpus: CorpusRetrievalPort) -> SimilarityPort:
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


def build_llm_adapter() -> NoveltyLlmPort:
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
                read_timeout=45.0,
                retries={"max_attempts": 1},
            ),
        ),
    )
