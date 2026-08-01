"""출처 어댑터 — 코퍼스 검색·외부 검색·DocModel 읽기.

v1 `tools.py`의 검색·DocModel 로직을 이식하되 **포트 형태로** 바꿨다: v1은 도구가
곧 어댑터였고(검색 방식과 도구 계약이 한 클래스에 섞여 있었다), v2는 도구가 얇은
껍데기이고 여기가 구현이다.

이식하면서 유지한 것: 하이브리드 검색은 U2를 재사용하고 전용 인덱스·랭킹을 만들지
않는다(BR-EV-2), 임베딩 실패는 lexical-only로 저하한다, 색인의 paperId는 버전
없는 bare id인데 evidence가 나르는 것은 버전 붙은 arxivId라 phrase 필터에는 버전을
떼고 넘긴다(안 그러면 좁히기가 항상 0건이 된다).
"""

from __future__ import annotations

import logging
from typing import Any, Protocol, runtime_checkable

from summarization.adapters._paper_ref import bare_paper_id

from backend.modules.paper_assets import parse_record_ref

from ..ports.sources import PaperCandidate, SearchUnavailable

__all__ = [
    "ArxivExternalSearch",
    "CorpusSearch",
    "DocModelReader",
]

log = logging.getLogger("docsuri.evidence.sources")

_TOP_K = 50
_PHRASE_TOP_K = 200
_MAX_PAPERS = 20


@runtime_checkable
class EmbeddingPort(Protocol):
    def embed_query(self, text: str) -> list[float]: ...


@runtime_checkable
class VectorStorePort(Protocol):
    def knn_search(
        self, vector: list[float], top_k: int, abstract_only: bool = False
    ) -> list[Any]: ...


@runtime_checkable
class LexicalIndexPort(Protocol):
    def bm25_search(self, terms: list[str], top_k: int, fields: tuple[str, ...] = ...) -> list: ...

    def phrase_search(
        self, phrase: str, top_k: int, paper_ids: list[str] | None = None
    ) -> list: ...


class CorpusSearch:
    """내부 코퍼스 하이브리드 검색(U2 재사용). `phrase=True`면 정확 문구 검색."""

    def __init__(
        self,
        *,
        embedding: EmbeddingPort,
        vector_store: VectorStorePort,
        lexical_index: LexicalIndexPort,
    ) -> None:
        self._embedding = embedding
        self._vector_store = vector_store
        self._lexical_index = lexical_index

    def search(self, query: str, *, phrase: bool = False) -> tuple[PaperCandidate, ...]:
        from discovery.ports.search_ports import IndexUnavailable

        try:
            records = self._phrase(query) if phrase else self._hybrid(query)
        except IndexUnavailable as exc:
            raise SearchUnavailable("corpus index unavailable") from exc

        seen: dict[str, PaperCandidate] = {}
        for record in records:
            candidate = _candidate_from_record(record)
            if candidate is not None and candidate.paper_id not in seen:
                seen[candidate.paper_id] = candidate
            if len(seen) >= _MAX_PAPERS:
                break
        return tuple(seen.values())

    def _hybrid(self, query: str) -> list[Any]:
        from discovery.domain.models import (
            DegradationSignal,
            QueryPlan,
            RetrievalMode,
            SearchScope,
        )
        from discovery.domain.retriever import HybridRetriever

        try:
            vector = self._embedding.embed_query(query)
            mode = RetrievalMode.HYBRID
        except Exception:  # noqa: BLE001 — 임베딩 부재는 저하이지 실패가 아니다
            log.warning("embedding unavailable — falling back to lexical-only")
            vector = None
            mode = RetrievalMode.LEXICAL_ONLY

        plan = QueryPlan(
            lexical_terms=tuple(query.split()),
            mode=mode,
            embedding_vector=tuple(vector) if vector else None,
            scope=SearchScope.FULL,
        )

        retriever = HybridRetriever(self._vector_store, self._lexical_index)
        candidate_set = retriever.retrieve(
            plan, DegradationSignal(llm_enabled=True, rerank_enabled=True)
        )
        return [c.record for c in candidate_set.candidates[:_TOP_K]]

    def _phrase(self, phrase: str) -> list[Any]:
        hits = self._lexical_index.phrase_search(phrase, top_k=_PHRASE_TOP_K)
        return [record for record, _score in hits]


class DocModelReader:
    """확보된 DocModel 읽기. 개별 실패는 '없음'과 같이 다룬다(부분 실패 허용).

    **버전 해석이 이 어댑터의 본체다.** U1은 doc-model을 `.../v{N}.json`으로 키잉하는데
    id가 두 형태로 들어온다:

    - 버전 붙은 arxivId(`2304.10557v3`) — 멀티턴에서 이어지는 값. 그 버전을 읽는다.
    - **버전 없는 bare id**(`1706.03762`) — 색인이 돌려주는 값. v1로 가정하면 개정된
      논문이 전부 미스가 되어 코퍼스 논문이 통째로 초록 범위로 떨어진다(로컬 실측:
      `1706.03762`의 실제 저장분은 v7). 최신 버전은 스토어에 **질의**한다 —
      레이아웃을 소유한 `S3DocModelReader.latest_version`이 프리픽스 목록 1회로
      답하므로, 순차 GET으로 추측할 이유가 없다.
    """

    def __init__(self, reader: Any) -> None:
        self._reader = reader

    def get_doc_model(self, paper_id: str) -> Any | None:
        version = _explicit_version(paper_id)
        if version is None:
            version = self._latest(paper_id)
        if version is None:
            return None
        try:
            return self._reader.get_doc_model(paper_id, version)
        except Exception:  # noqa: BLE001 — 논문 1편 실패로 턴을 깨지 않는다
            log.warning("docmodel read failed for %s v%s", paper_id, version, exc_info=True)
            return None

    def _latest(self, paper_id: str) -> int | None:
        lookup = getattr(self._reader, "latest_version", None)
        if lookup is None:
            return 1  # 목록을 못 주는 리더(테스트 대역 등)는 v1 규약으로 폴백
        try:
            return lookup(paper_id)
        except Exception:  # noqa: BLE001
            log.warning("docmodel version lookup failed for %s", paper_id, exc_info=True)
            return None


def _explicit_version(paper_id: str) -> int | None:
    """id가 버전을 **명시**했을 때만 그 값. bare id는 None(=최신 해석 대상).

    `parse_record_ref`가 정확히 version-or-None 의미라 재사용한다 — paper_version의
    기본값 센티널로 같은 것을 흉내내던 우회를 없앤다.
    """
    parsed = parse_record_ref(paper_id)
    return parsed[1] if parsed else None


class ArxivExternalSearch:
    """코퍼스 밖 arXiv 검색 — 제목·초록만 확보한다(본문은 승격이 담당).

    **payload allowlist**(BR-EV-20): 나가는 것은 검색어뿐이다. 사용자 원문·근거
    전문·세션 내용은 어댑터 경계에서 구조적으로 나갈 수 없다 — 여기서 쓰는 인자가
    `query` 하나뿐이기 때문이다.

    식별자에는 **버전을 박는다**(`arxiv:{id}v{n}`). 초록 범위 인용의 사후 감사는
    그 버전을 다시 가져와 대조하는 것이므로(FD 게이트 Q5=A), 버전이 없으면
    개정 후 재현이 불가능해진다.
    """

    def __init__(self, client: Any, *, max_results: int = 10) -> None:
        self._client = client
        self._max_results = max_results

    def search(self, query: str) -> tuple[PaperCandidate, ...]:
        try:
            entries = self._client.search(query=query, max_results=self._max_results)
        except Exception as exc:  # noqa: BLE001 — 외부 장애는 그 도구만 실패시킨다
            raise SearchUnavailable("external paper search unavailable") from exc

        out: list[PaperCandidate] = []
        for entry in entries or []:
            arxiv_id = str(_attr(entry, "arxiv_id", "arxivId", "id") or "").strip()
            if not arxiv_id:
                continue
            versioned = arxiv_id if "v" in arxiv_id.rsplit("/", 1)[-1] else f"{arxiv_id}v1"
            paper_id = f"arxiv:{versioned}"
            out.append(
                PaperCandidate(
                    paper_id=paper_id,
                    record_ref=f"external:{paper_id}",
                    title=str(_attr(entry, "title") or ""),
                    abstract=str(_attr(entry, "abstract", "summary") or ""),
                )
            )
        return tuple(out)


def _attr(obj: Any, *names: str) -> Any:
    for name in names:
        value = getattr(obj, name, None)
        if value is None and isinstance(obj, dict):
            value = obj.get(name)
        if value:
            return value
    return None


def _candidate_from_record(record: Any) -> PaperCandidate | None:
    paper_id = _attr(record, "arxivId", "paper_id", "paperId", "id")
    if not paper_id:
        return None
    paper_id = str(paper_id)
    return PaperCandidate(
        paper_id=paper_id,
        # 색인의 recordRef는 bare id 기준이다 — 실재성 핸들이므로 색인 형태를 따른다.
        record_ref=str(_attr(record, "recordRef", "chunkId") or bare_paper_id(paper_id)),
        title=str(_attr(record, "title") or paper_id),
        abstract=str(_attr(record, "abstract") or ""),
    )
