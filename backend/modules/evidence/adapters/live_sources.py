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

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from itertools import zip_longest
from typing import Any
from xml.etree import ElementTree

from backend.modules.novelty.adapters.external.base import (
    SourceBreaker,
    SourceUnavailable,
    check_response,
)
from backend.modules.paper_assets import parse_record_ref

from ..domain.projection import normalize
from ..ports.sources import LiveLookupResult, PaperCandidate, SearchUnavailable

__all__ = ["ARXIV_ENDPOINT", "LiveLookup", "OPENALEX_ENDPOINT", "S2_ENDPOINT"]

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

# S2 무키 호출은 공용 풀이라 초당 제한이 빡빡하다. 한 도구 호출이 세 소스를 한 번씩만
# 치므로 페이지는 돌지 않는다 — 소스당 상한만 둔다.
_PER_SOURCE = 8


@dataclass(frozen=True, slots=True)
class _LiveRecord:
    """정규화 전 한 건 — **dedup이 읽는 id가 여기 있어야 한다.** `PaperCandidate`에는 `doi`도
    원본 `arxiv_id`도 없어서, 후보로 접고 나면 같은 논문을 다시 알아볼 수단이 사라진다.

    담는 것은 그 둘뿐이다. 초안에는 `source`·`year`도 있었는데 `source`는 어디서도 안 읽혔고
    `year`는 도달 불가한 제목 사다리만 읽었다 — 모델에 필드가 있으면 다음 소스를 붙이는
    사람이 성실하게 채우고, 채운 값은 영영 안 쓰인다."""

    title: str
    abstract: str = ""
    arxiv_id: str | None = None
    doi: str | None = None


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
        query = normalize(query)[:_MAX_QUERY_CHARS]
        if not query:
            return LiveLookupResult(())

        sources = self._sources()
        degraded: list[str] = []

        # **동시에 던지고 제출 순서대로 모은다.** 순차로 돌면 타임아웃 15초 × 브레이커의 기계
        # 재시도 1회 × 소스 수 = 최악 90초가 사용자가 기다리는 경로에 얹힌다.
        #
        # 승자 우선순위(arXiv > S2 > OpenAlex)는 그대로다 — 그 규칙을 지키는 것은 호출 순서가
        # 아니라 `_dedupe`가 `records` **리스트 순서**를 걷는 것이고, 아래 루프가 완료 순서가
        # 아닌 제출 순서로 `extend`하므로 리스트가 순차 실행과 바이트째로 같다.
        with ThreadPoolExecutor(max_workers=len(sources)) as pool:
            futures = [
                (name, pool.submit(_guarded, breaker, fetch, query))
                for name, breaker, fetch in sources
            ]
            per_source: list[list[_LiveRecord]] = []
            for name, future in futures:
                rows = future.result()
                if rows is None:
                    degraded.append(name)
                else:
                    per_source.append(rows)
            records = _interleave(per_source)

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
                "fields": "title,abstract,externalIds",
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
                    title=title,
                    abstract=_clean(item.get("abstract")),
                    arxiv_id=_clean(ids.get("ArXiv")) or None,
                    doi=_clean(ids.get("DOI")).lower() or None,
                )
            )
        return out

    def _openalex(self, query: str) -> list[_LiveRecord]:
        params = {
            "search": query,
            "per-page": self._per_source,
            "select": "ids,doi,display_name,abstract_inverted_index",
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
                    title=title,
                    # OpenAlex는 초록을 **역색인**으로 준다(전문 재배포 제약). 복원하지 않으면
                    # 초록이 통째로 비고, 초록만 확보하는 이 도구에서 그것은 결과가 없는 것과
                    # 같다 — 게이트가 대조할 텍스트가 없어 인용이 전부 떨어진다.
                    abstract=_from_inverted_index(item.get("abstract_inverted_index")),
                    arxiv_id=_arxiv_id_from(ids.get("arxiv")),
                    doi=_bare_doi(item.get("doi")),
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


def _interleave(per_source: list[list[_LiveRecord]]) -> list[_LiveRecord]:
    """소스별 결과를 **번갈아** 담는다 — 앞 소스가 자리를 다 먹지 않게.

    도구는 후보를 상위 `_MAX_HITS`(10)로 자르는데, 소스마다 8건씩 오므로 그냥 이어 붙이면
    arXiv 8 + S2 2로 차고 **OpenAlex 결과는 모델에게 한 번도 안 보인다**. S2·OpenAlex를 더한
    이유가 "arXiv에 없는 논문"인데 그 논문이 구조적으로 잘려 나가는 것이다.

    승자 우선순위는 그대로다 — 같은 논문이 여러 소스에 있으면 `_dedupe`가 **먼저 오는 것**을
    남기고, 번갈아 담아도 각 라운드에서 arXiv가 S2보다 앞이다.
    """
    out: list[_LiveRecord] = []
    for row in zip_longest(*per_source):
        out += [r for r in row if r is not None]
    return out


def _guarded(breaker: SourceBreaker, fetch: Any, query: str) -> list[_LiveRecord] | None:
    """브레이커를 지나 한 소스를 친다 — 죽었으면 None. 예외는 **워커 안에서** 흡수한다.

    `future.result()`로 새어 나가게 두면 한 소스의 장애가 다른 소스의 결과까지 버린다.
    """
    try:
        return breaker.call(lambda: fetch(query))
    except SourceUnavailable as exc:
        log.warning("live lookup source unavailable: %s", exc)
        return None


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


# arXiv가 자기 논문에 붙이는 DataCite DOI. OpenAlex는 arXiv 사본을 이 DOI로만 실어 오는
# 일이 잦아, 그냥 두면 같은 논문이 arXiv 사본과 따로 남는다.
_ARXIV_DOI_PREFIX = "10.48550/arxiv."


def _canonical_key(record: _LiveRecord) -> str:
    """**arXiv id 먼저**, 없으면 DOI.

    처음에는 ingestion의 `canonical_key`를 따라 DOI를 앞에 뒀는데 **여기서는 틀렸다**:
    arXiv 소스는 DOI를 아예 안 싣고 S2/OpenAlex는 출판된 논문에 대개 DOI를 싣는다. 그러면
    같은 논문의 arXiv 사본은 `arxiv:` 키를, S2 사본은 `doi:` 키를 받아 **한 번도 안 접힌다**
    (실측: 한 논문이 후보 세 건으로 남았다). 그 뒤는 조용히 나쁘다 — 모델은 한 논문을 세
    출처로 보고, 승격이 두 번 돌고(각 20초 폴링), 색인 잡이 두 철자로 나가고, 같은 논문이
    독립 근거로 두 번 인용될 수 있다.

    ingestion이 DOI를 앞에 두는 것은 수확 경로에 arXiv 전용 레코드가 없기 때문이고, 여기는
    그 전제가 다르다.
    """
    if record.arxiv_id:
        return f"arxiv:{_bare_arxiv(record.arxiv_id)}"
    doi = (record.doi or "").lower()
    if doi.startswith(_ARXIV_DOI_PREFIX):
        # arXiv 사본이 DOI로만 실려 온 것 — id를 되찾아 arXiv 사본과 같은 키를 준다.
        return f"arxiv:{_bare_arxiv(doi[len(_ARXIV_DOI_PREFIX):])}"
    return f"doi:{doi}"


def _as_candidate(record: _LiveRecord) -> PaperCandidate | None:
    """`_LiveRecord` → 포트 계약.

    **arXiv id가 있으면 버전을 박는다**(`arxiv:{id}v{n}`). 초록 범위 인용의 사후 감사는 그
    버전을 다시 가져와 대조하는 것이므로(FD 게이트 Q5=A) 버전이 없으면 개정 후 재현이 안 된다.

    arXiv id가 없는 논문(학회·저널 전용)은 `doi:` 네임스페이스로 나른다. **arxiv.org id를
    지어내지 않는다**(무날조) — 그런 논문은 본문 승격 대상이 아니고 초록 범위로만 인용된다.
    """
    from .tools import versioned_arxiv

    if record.arxiv_id:
        versioned = versioned_arxiv(record.arxiv_id.strip())
        if versioned is None:
            # 문법에 안 맞는 id — 인용의 실재를 확인할 핸들이 없다.
            return None
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
    """OpenAlex는 arXiv를 URL로 준다(`https://arxiv.org/abs/2304.10557`).

    문법은 `tools.ARXIV_ID_BODY` 하나를 쓴다. 두 벌로 뒀더니 **이미 갈려 있었다** —
    이쪽만 대소문자를 안 받아 `HEP-TH/9901001`을 실은 레코드가 `arxiv_id=None`이 되고,
    `doi:`로 실려 승격도 색인도 안 되면서 사용자에게는 "이 논문은 arXiv에 없다"는 확신에
    찬 오답이 나갔다. 예외도 로그도 없다.
    """
    from .tools import ARXIV_ID_SEARCH

    match = ARXIV_ID_SEARCH.search(str(url or ""))
    return match.group(0) if match else None


_DOI_PREFIX = re.compile(r"^(?:https?://)?(?:dx\.)?doi\.org/")


def _bare_doi(doi: Any) -> str | None:
    """OpenAlex의 `doi`는 `https://doi.org/10.x/y` 형태다 — 접두어를 벗겨 S2의 값과 만나게 한다.

    **맨 앞에서만 벗긴다.** 담기는 것이 URL이 아니라 식별자이므로, 문자열 어디에 있든
    자르면 벗기려던 접두어가 아니라 DOI 본문을 자를 수 있다 — 그러면 중복 제거 키가 갈려
    같은 논문이 두 건으로 남는다.
    """
    text = str(doi or "").strip().lower()
    if not text:
        return None
    return _DOI_PREFIX.sub("", text, count=1)


def _bare_arxiv(arxiv_id: str) -> str:
    """버전을 뗀 id — 같은 논문의 v1과 v3이 한 건으로 접히게 한다."""
    parsed = parse_record_ref(arxiv_id.lower())
    return parsed[0] if parsed else arxiv_id.lower()


def _clean(value: Any) -> str:
    """공백 정규화 — **게이트가 대조하는 그 함수**를 쓴다(`domain.projection.normalize`).

    여기서 만드는 초록은 초록 범위 인용의 대조 **반대편**이다. 두 벌로 두면 갈리는 날
    초록 인용이 전부 떨어지고, 그 실패는 "모델이 초록에 없는 말을 했다"로 보인다.
    """
    return normalize(str(value or ""))
