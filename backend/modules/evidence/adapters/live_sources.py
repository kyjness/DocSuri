"""실시간 조회 세 소스(설계 v3 §3.2) — arXiv · Semantic Scholar · OpenAlex.

`external_search`(arXiv 하나)를 대체한다. 코퍼스 밖 논문을 **제목·초록까지만** 확보하고,
본문은 승격(`fetch_paper`)이 담당한다.

**왜 ingestion 것을 재사용하지 않나** — 설계는 "ingestion 것을 포트 뒤에서 재사용"이라 적었지만
둘 다 성립하지 않았다: `docsuri_ingestion`은 backend 의존성이 아니고(별도 uv 프로젝트, import
자체가 마운트를 죽인다), 그쪽 S2·OpenAlex 소스는 `fetch_incremental(since, until)` — 날짜 창
**수확**용이라 질의 검색 메서드 자체가 없다. 재사용할 대상이 저쪽에 없으므로 이건 중복이 아니다.
다만 **승자 규칙(arXiv > S2 > OpenAlex)만은 같은 규칙이 두 곳**이 된다
(`ingestion/domain/canonical.py`의 `canonical_key`·`source_priority`) — 소스 집합이 바뀌면
양쪽을 함께 봐야 한다.

**나가는 것은 검색어뿐이다**(BR-EV-20). 엔드포인트는 상수이고 모델이 쓴 값은 질의 문자열
하나뿐이라, 사용자 원문·근거 전문·세션 내용은 이 경계를 구조적으로 넘을 수 없다.

**소스별 서킷 브레이커.** LLM용 브레이커(`real_wiring`의 Bedrock 셋이 나눠 쓰는 것)와는
반드시 분리한다 — 공유하면 arXiv 장애가 `decide`를 죽인다. 소스 하나가 죽어도 나머지로
진행하고(부분 저하), **셋 다 죽었을 때만** 실패다(§7).
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from typing import Any
from xml.etree import ElementTree

from backend.modules.novelty.adapters.external.base import (
    SourceBreaker,
    SourceUnavailable,
    check_response,
)

from ..ports.sources import PaperCandidate, SearchUnavailable

__all__ = ["ARXIV_ENDPOINT", "LiveLookup", "LiveLookupResult", "OPENALEX_ENDPOINT", "S2_ENDPOINT"]

log = logging.getLogger("docsuri.evidence.sources")

# 허용 호스트는 상수다(BR-EV-20 내부망 접근 방지) — 모델이 쓴 값은 질의뿐이고 URL 조립에
# 관여할 수 없다. novelty의 `is_safe_external_url`을 쓰지 않는 이유: 그쪽은 **모델·외부가
# 준 URL**을 검사하는 헬퍼인데, 여기서 나가는 URL은 아래 세 상수뿐이고 응답의 URL은 어디에도
# 싣지 않는다(초록만 싣는다). 검사할 변수가 없다.
ARXIV_ENDPOINT = "https://export.arxiv.org/api/query"
S2_ENDPOINT = "https://api.semanticscholar.org/graph/v1/paper/search"
OPENALEX_ENDPOINT = "https://api.openalex.org/works"

_ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}
_MAX_QUERY_CHARS = 400
_ARXIV_ID_RE = re.compile(r"\d{4}\.\d{4,5}(v\d+)?|[a-z-]{2,}(\.[A-Z]{2})?/\d{7}(v\d+)?")
_WS_RE = re.compile(r"\s+")

# S2 무키 호출은 공용 풀이라 초당 제한이 빡빡하다. 한 도구 호출이 세 소스를 한 번씩만
# 치므로 페이지는 돌지 않는다 — 소스당 상한만 둔다.
_PER_SOURCE = 8


@dataclass(frozen=True, slots=True)
class _LiveRecord:
    """정규화 전 한 건. **dedup이 읽는 필드가 여기 다 있어야 한다** — `PaperCandidate`에는
    doi·year가 없어서, 후보로 접고 나면 같은 논문을 다시 알아볼 수단이 사라진다."""

    source: str
    title: str
    abstract: str = ""
    arxiv_id: str | None = None
    doi: str | None = None
    year: int | None = None


@dataclass(frozen=True, slots=True)
class LiveLookupResult:
    """조회 결과 + **어느 소스가 빠졌는지**.

    저하를 결과값으로 나르는 이유는 두 소비자가 있기 때문이다: 도구가 모델에게 알리고
    (안 알리면 모델은 "이게 전부"라고 믿는다 — novelty 실측), 마감이 확인 범위 줄에
    "실시간 조회 불가"를 싣는다(§7).
    """

    candidates: tuple[PaperCandidate, ...]
    degraded_sources: tuple[str, ...] = ()


class LiveLookup:
    """세 소스 합성 — 순회 순서가 곧 **승자 우선순위**다(arXiv > S2 > OpenAlex).

    S2는 키가 구성됐을 때만 합류한다 — `_sources()` 참조.
    """

    def __init__(
        self,
        client: Any,
        *,
        per_source: int = _PER_SOURCE,
        s2_api_key: str | None = None,
        mailto: str | None = None,
        contact: str | None = None,
        arxiv_breaker: SourceBreaker | None = None,
        s2_breaker: SourceBreaker | None = None,
        openalex_breaker: SourceBreaker | None = None,
    ) -> None:
        self._client = client
        self._per_source = per_source
        self._s2_api_key = s2_api_key
        self._mailto = mailto  # OpenAlex polite pool — 그 API의 질의 파라미터일 뿐이다
        self._contact = contact
        self._arxiv_breaker = arxiv_breaker or SourceBreaker()
        self._s2_breaker = s2_breaker or SourceBreaker()
        self._openalex_breaker = openalex_breaker or SourceBreaker()

    def search(self, query: str) -> tuple[PaperCandidate, ...]:
        """포트 계약(`LivePaperLookupPort`) — 후보만 돌려준다."""
        return self.lookup(query).candidates

    def _sources(self) -> tuple[tuple[str, SourceBreaker, Any], ...]:
        """실제로 칠 소스 — 순회 순서가 곧 승자 우선순위다(arXiv > S2 > OpenAlex).

        **S2는 키가 있을 때만 합류한다.** 무키 공용 풀은 사실상 항상 429다(2026-08-25 실측:
        12초 간격 5회 연속 429, 요청 모양은 정상). 그런데도 매 턴 부르면 왕복 두 번(브레이커의
        기계 재시도 포함)을 버리고, 더 나쁘게는 `degraded`에 항상 실려 화면에 "실시간 조회가
        온전히 돌지 못했어요"가 **상시로** 뜬다 — 설정이 없는 것은 저하가 아니라 미구성이고,
        미구성을 장애로 보여주면 진짜 장애가 묻힌다. 설정이 없으면 조용히 빠지는 것은 이
        모듈이 도구 등록에서 쓰는 규칙과 같다.
        """
        sources: list[tuple[str, SourceBreaker, Any]] = [
            ("arxiv", self._arxiv_breaker, self._arxiv)
        ]
        if self._s2_api_key:
            sources.append(("semantic_scholar", self._s2_breaker, self._semantic_scholar))
        sources.append(("openalex", self._openalex_breaker, self._openalex))
        return tuple(sources)

    def lookup(self, query: str) -> LiveLookupResult:
        query = _WS_RE.sub(" ", query).strip()[:_MAX_QUERY_CHARS]
        if not query:
            return LiveLookupResult(())

        sources = self._sources()
        records: list[_LiveRecord] = []
        degraded: list[str] = []
        for source, breaker, fetch in sources:
            try:
                # 기본인자 바인딩 — 클로저가 루프 변수를 늦게 읽으면 셋 다 마지막 소스를 친다.
                records.extend(breaker.call(lambda fetch=fetch: fetch(query)))
            except SourceUnavailable as exc:
                log.warning("live lookup source unavailable (%s): %s", source, exc)
                degraded.append(source)

        if len(degraded) == len(sources):
            # **구성된 소스가 전부 죽었을 때만** 실패다(§7). "0건인데 한 소스가 죽었다"를
            # 실패로 삼으면 안 된다 — 살아 있는 쪽이 "없다"고 답한 것이고 그것도 답이다.
            raise SearchUnavailable(f"live lookup unavailable: {', '.join(degraded)}")
        return LiveLookupResult(_dedupe(records), tuple(degraded))

    # --- 소스 셋 -----------------------------------------------------------------

    def _arxiv(self, query: str) -> list[_LiveRecord]:
        response = self._client.get(
            ARXIV_ENDPOINT,
            params={
                "search_query": f"all:{query}",
                "start": 0,
                "max_results": self._per_source,
            },
            headers=self._headers(),
        )
        check_response(response)
        # 외부 XML은 신뢰 경계 밖이다. 표준 파서는 외부 엔티티를 해석하지 않지만 크기 상한은
        # 여기서 건다 — httpx는 스트리밍이 아니면 이미 다 읽었으므로 길이로 자른다.
        payload = response.content[:2_000_000]
        root = ElementTree.fromstring(payload)

        out: list[_LiveRecord] = []
        for entry in root.findall("atom:entry", _ATOM_NS):
            raw_id = (entry.findtext("atom:id", default="", namespaces=_ATOM_NS) or "").strip()
            # 'http://arxiv.org/abs/2304.10557v1' → '2304.10557v1'
            arxiv_id = raw_id.rsplit("/abs/", 1)[-1] if "/abs/" in raw_id else raw_id
            if not arxiv_id:
                continue
            out.append(
                _LiveRecord(
                    source="arxiv",
                    title=_clean(entry.findtext("atom:title", "", _ATOM_NS)),
                    abstract=_clean(entry.findtext("atom:summary", "", _ATOM_NS)),
                    arxiv_id=arxiv_id,
                )
            )
        return out

    def _semantic_scholar(self, query: str) -> list[_LiveRecord]:
        headers = self._headers()
        if self._s2_api_key:
            headers["x-api-key"] = self._s2_api_key
        response = self._client.get(
            S2_ENDPOINT,
            params={
                "query": query,
                "limit": self._per_source,
                "fields": "title,abstract,year,externalIds",
            },
            headers=headers,
        )
        check_response(response)
        out: list[_LiveRecord] = []
        for item in (response.json() or {}).get("data") or []:
            title = _clean(item.get("title"))
            if not title:
                continue
            ids = item.get("externalIds") or {}
            out.append(
                _LiveRecord(
                    source="semantic_scholar",
                    title=title,
                    abstract=_clean(item.get("abstract")),
                    arxiv_id=_clean(ids.get("ArXiv")) or None,
                    doi=_clean(ids.get("DOI")).lower() or None,
                    year=_as_year(item.get("year")),
                )
            )
        return out

    def _openalex(self, query: str) -> list[_LiveRecord]:
        params = {
            "search": query,
            "per-page": self._per_source,
            "select": "ids,doi,display_name,abstract_inverted_index,publication_year",
        }
        if self._mailto:
            params["mailto"] = self._mailto  # polite pool — 더 높고 안정적인 한도
        response = self._client.get(OPENALEX_ENDPOINT, params=params, headers=self._headers())
        check_response(response)
        out: list[_LiveRecord] = []
        for item in (response.json() or {}).get("results") or []:
            title = _clean(item.get("display_name"))
            if not title:
                continue
            ids = item.get("ids") or {}
            out.append(
                _LiveRecord(
                    source="openalex",
                    title=title,
                    # OpenAlex는 초록을 **역색인**으로 준다(전문 재배포 제약). 복원하지 않으면
                    # 초록이 통째로 비고, 초록만 확보하는 이 도구에서 그것은 결과가 없는 것과
                    # 같다 — 게이트가 대조할 텍스트가 없어 인용이 전부 떨어진다.
                    abstract=_from_inverted_index(item.get("abstract_inverted_index")),
                    arxiv_id=_arxiv_id_from(ids.get("arxiv")),
                    doi=_bare_doi(item.get("doi")),
                    year=_as_year(item.get("publication_year")),
                )
            )
        return out

    def _headers(self) -> dict[str, str]:
        # 아웃바운드 User-Agent에 연락처를 싣는다 — 출판사·API가 요청자를 식별하는 값이고,
        # 없으면 공용 풀에서 먼저 조여진다.
        agent = "docsuri-evidence/1.0"
        if self._contact:
            agent += f" (mailto:{self._contact})"
        return {"User-Agent": agent}


# --- 정규화 · 중복 제거 ------------------------------------------------------------


def _dedupe(records: list[_LiveRecord]) -> tuple[PaperCandidate, ...]:
    """같은 논문을 한 건으로 접는다 — 승자는 **먼저 온 것**이고 순회 순서가 우선순위다.

    키는 `ingestion.domain.canonical.canonical_key`와 같은 사다리다: DOI → arXiv id →
    제목 해시. arXiv 사본과 S2/OpenAlex 사본은 DOI가 없어도 arXiv id로 만나고, 학회 논문은
    DOI로 만나며, 둘 다 없으면 정규화 제목으로 만난다.
    """
    seen: dict[str, PaperCandidate] = {}
    for record in records:
        key = _canonical_key(record)
        if key in seen:
            continue
        candidate = _as_candidate(record)
        if candidate is not None:
            seen[key] = candidate
    return tuple(seen.values())


def _canonical_key(record: _LiveRecord) -> str:
    if record.doi:
        return f"doi:{record.doi}"
    if record.arxiv_id:
        return f"arxiv:{_strip_version(record.arxiv_id.lower())}"
    normalized = f"{_WS_RE.sub(' ', record.title).strip().lower()}|{record.year or ''}"
    return "title:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]


def _as_candidate(record: _LiveRecord) -> PaperCandidate | None:
    """`_LiveRecord` → 포트 계약.

    **arXiv id가 있으면 버전을 박는다**(`arxiv:{id}v{n}`). 초록 범위 인용의 사후 감사는 그
    버전을 다시 가져와 대조하는 것이므로(FD 게이트 Q5=A) 버전이 없으면 개정 후 재현이 안 된다.

    arXiv id가 없는 논문(학회·저널 전용)은 `doi:` 네임스페이스로 나른다. **arxiv.org id를
    지어내지 않는다**(무날조) — 그런 논문은 본문 승격 대상이 아니고 초록 범위로만 인용된다.
    """
    if record.arxiv_id:
        bare = record.arxiv_id.strip()
        versioned = bare if _has_version(bare) else f"{bare}v1"
        paper_id = f"arxiv:{versioned}"
    elif record.doi:
        paper_id = f"doi:{record.doi}"
    else:
        # id가 없으면 인용의 실재를 확인할 핸들이 없다 — 게이트가 어차피 떨어뜨린다.
        return None
    return PaperCandidate(
        paper_id=paper_id,
        record_ref=f"external:{paper_id}",
        title=record.title,
        abstract=record.abstract,
    )


def _from_inverted_index(index: Any) -> str:
    """OpenAlex `abstract_inverted_index` → 평문.

    `{"word": [pos, ...]}`를 위치로 되펼친다. 빠진 위치가 있어도(드물다) 있는 것만으로 잇는다.
    """
    if not isinstance(index, dict) or not index:
        return ""
    slots: dict[int, str] = {}
    for word, positions in index.items():
        if not isinstance(positions, list):
            continue
        for position in positions:
            if isinstance(position, int):
                slots[position] = str(word)
    return " ".join(slots[i] for i in sorted(slots))


def _arxiv_id_from(url: Any) -> str | None:
    """OpenAlex는 arXiv를 URL로 준다(`https://arxiv.org/abs/2304.10557`)."""
    match = _ARXIV_ID_RE.search(str(url or ""))
    return match.group(0) if match else None


def _bare_doi(doi: Any) -> str | None:
    """OpenAlex의 `doi`는 `https://doi.org/10.x/y` 형태다 — 접두어를 벗겨 S2의 값과 만나게 한다."""
    text = str(doi or "").strip().lower()
    if not text:
        return None
    return text.rsplit("doi.org/", 1)[-1] if "doi.org/" in text else text


def _has_version(arxiv_id: str) -> bool:
    tail = arxiv_id.rsplit("/", 1)[-1]
    base, marker, suffix = tail.rpartition("v")
    return bool(base and marker and suffix.isdigit())


def _strip_version(arxiv_id: str) -> str:
    base, marker, suffix = arxiv_id.rpartition("v")
    return base if base and marker and suffix.isdigit() else arxiv_id


def _as_year(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _clean(value: Any) -> str:
    return _WS_RE.sub(" ", str(value or "")).strip()
