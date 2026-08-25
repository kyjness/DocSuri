"""실시간 조회 세 소스(설계 v3 §3.2) — 정규화·중복 제거·부분 저하.

옛 `ArxivExternalSearch`·`ArxivApiClient`에는 **직접 테스트가 하나도 없었다.** 버전 강제도
Atom 파싱도 `external:` 접두어도 아무 데서도 검증되지 않았고, 그 셋 다 게이트가 인용을
떨어뜨리는 방식으로만 표가 나는 종류다(그리고 그건 "근거를 못 찾았다"로 보인다).
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.modules.evidence.adapters.live_sources import (
    ARXIV_ENDPOINT,
    OPENALEX_ENDPOINT,
    S2_ENDPOINT,
    LiveLookup,
)
from backend.modules.evidence.ports.sources import SearchUnavailable
from backend.modules.novelty.adapters.external.base import SourceBreaker

_ATOM = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2304.10557v2</id>
    <title>Attention   Is All\n You Need</title>
    <summary>We propose a new architecture.</summary>
  </entry>
</feed>"""


class _Response:
    def __init__(self, *, json_body: Any = None, content: bytes = b"", status: int = 200) -> None:
        self._json = json_body
        self.content = content
        self.status_code = status

    def json(self) -> Any:
        return self._json

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"status {self.status_code}")


class _Client:
    """엔드포인트별 응답을 미리 심는 대역. 예외를 심으면 그 소스만 죽는다."""

    def __init__(self, **by_endpoint: Any) -> None:
        self._by_endpoint = by_endpoint
        self.calls: list[tuple[str, dict, dict]] = []

    def get(self, url: str, *, params: dict, headers: dict | None = None) -> Any:
        self.calls.append((url, params, headers or {}))
        answer = self._by_endpoint.get(url, _EMPTY[url])
        if isinstance(answer, Exception):
            raise answer
        return answer


# 심지 않은 엔드포인트의 기본 응답 — **소스마다 모양이 다르다.** 전부 `{}`로 두면 arXiv가
# 빈 본문을 XML로 읽다 실패해 "0건"을 재려던 테스트가 "장애"를 재게 된다.
_EMPTY: dict[str, Any] = {
    ARXIV_ENDPOINT: _Response(
        content=b'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"/>'
    ),
    S2_ENDPOINT: _Response(json_body={"data": []}),
    OPENALEX_ENDPOINT: _Response(json_body={"results": []}),
}


def _arxiv_ok() -> _Response:
    return _Response(content=_ATOM.encode("utf-8"))


def _s2(*items: dict) -> _Response:
    return _Response(json_body={"data": list(items)})


def _openalex(*items: dict) -> _Response:
    return _Response(json_body={"results": list(items)})


def _lookup(client: _Client, **kw: Any) -> LiveLookup:
    return LiveLookup(client, **kw)


def _with_s2(client: _Client, **kw: Any) -> LiveLookup:
    """S2가 합류하는 구성 — 키가 없으면 그 소스는 아예 안 불린다(`_sources`)."""
    return LiveLookup(client, s2_api_key="k", **kw)


def _call(client: _Client, endpoint: str, *, nth: int = 0) -> tuple[dict, dict]:
    """그 엔드포인트로 나간 n번째 호출의 (params, headers).

    위치로 집으면 소스 순회 순서에 묶인다 — 순서는 승자 우선순위라 언젠가 바뀌고,
    그때 이 검사들은 엉뚱한 소스를 보면서 초록으로 남는다."""
    hits = [(params, headers) for url, params, headers in client.calls if url == endpoint]
    return hits[nth]


# --- arXiv --------------------------------------------------------------------------


def test_arxiv_entries_become_versioned_candidates():
    client = _Client(**{ARXIV_ENDPOINT: _arxiv_ok()})

    out = _lookup(client).lookup("attention").candidates

    assert len(out) == 1
    assert out[0].paper_id == "arxiv:2304.10557v2"
    assert out[0].record_ref == "external:arxiv:2304.10557v2"
    # 줄바꿈·연속 공백이 남으면 게이트가 대조할 문자열과 어긋난다.
    assert out[0].title == "Attention Is All You Need"


def test_an_arxiv_id_without_a_version_gets_v1():
    """초록 범위 인용의 사후 감사는 그 버전을 다시 받아 대조하는 것이다(FD 게이트 Q5=A) —
    버전이 없으면 개정 뒤 재현이 불가능해진다."""
    atom = _ATOM.replace("2304.10557v2", "2304.10557")
    client = _Client(**{ARXIV_ENDPOINT: _Response(content=atom.encode("utf-8"))})

    assert _lookup(client).lookup("x").candidates[0].paper_id == "arxiv:2304.10557v1"


def test_only_the_query_leaves_the_boundary():
    """payload allowlist(BR-EV-20) — 나가는 파라미터에 질의 말고 아무것도 없어야 한다."""
    client = _Client(**{ARXIV_ENDPOINT: _arxiv_ok()})

    _lookup(client).lookup("사용자가 물어본 것")

    params, _headers = _call(client, ARXIV_ENDPOINT)
    assert params["search_query"] == "all:사용자가 물어본 것"
    assert set(params) == {"search_query", "start", "max_results"}


# --- Semantic Scholar ---------------------------------------------------------------


def test_semantic_scholar_uses_its_arxiv_id_when_it_has_one():
    client = _Client(
        **{
            S2_ENDPOINT: _s2(
                {"title": "T", "abstract": "A", "externalIds": {"ArXiv": "2401.00001"}}
            )
        }
    )

    assert _with_s2(client).lookup("x").candidates[0].paper_id == "arxiv:2401.00001v1"


def test_a_paper_with_no_arxiv_id_is_carried_under_the_doi_namespace():
    """학회·저널 전용 논문은 arXiv id가 없다. **지어내지 않는다**(무날조) — 그런 논문은
    본문 승격 대상이 아니고 초록 범위로만 인용된다."""
    client = _Client(
        **{S2_ENDPOINT: _s2({"title": "T", "externalIds": {"DOI": "10.1145/ABC"}})}
    )

    assert _with_s2(client).lookup("x").candidates[0].paper_id == "doi:10.1145/abc"


def test_a_record_with_neither_id_is_dropped():
    """id가 없으면 인용의 실재를 확인할 핸들이 없다 — 게이트가 어차피 떨어뜨린다."""
    client = _Client(**{S2_ENDPOINT: _s2({"title": "T", "abstract": "A"})})

    assert _with_s2(client).lookup("x").candidates == ()


def test_the_api_key_rides_in_the_header_not_the_query():
    client = _Client(**{S2_ENDPOINT: _s2()})

    _with_s2(client).lookup("x")

    params, headers = _call(client, S2_ENDPOINT)
    assert headers["x-api-key"] == "k"
    assert "k" not in str(params)


# --- OpenAlex -----------------------------------------------------------------------


def test_openalex_abstracts_are_rebuilt_from_the_inverted_index():
    """OpenAlex는 초록을 역색인으로 준다. 복원하지 않으면 초록이 통째로 비고, 초록만
    확보하는 이 도구에서 그것은 결과가 없는 것과 같다 — 대조할 텍스트가 없어 인용이
    전부 게이트에서 떨어진다."""
    client = _Client(
        **{
            OPENALEX_ENDPOINT: _openalex(
                {
                    "display_name": "T",
                    "doi": "https://doi.org/10.1/x",
                    "abstract_inverted_index": {"sparse": [2], "we": [0], "are": [1]},
                }
            )
        }
    )

    assert _lookup(client).lookup("x").candidates[0].abstract == "we are sparse"


def test_openalex_doi_loses_its_url_prefix_so_it_meets_the_s2_value():
    """S2는 맨 DOI를, OpenAlex는 `https://doi.org/...`를 준다. 벗기지 않으면 같은 논문이
    두 건으로 남는다."""
    client = _Client(
        **{
            S2_ENDPOINT: _s2({"title": "T", "externalIds": {"DOI": "10.1/X"}}),
            OPENALEX_ENDPOINT: _openalex({"display_name": "T", "doi": "https://doi.org/10.1/x"}),
        }
    )

    assert len(_with_s2(client).lookup("x").candidates) == 1


def test_the_doi_prefix_is_only_stripped_from_the_front():
    """벗기는 것은 접두어이지 문자열 어디에 있든이 아니다 — `doi.org/`를 본문에 품은 DOI를
    뒤에서부터 자르면 식별자가 잘려 나가고, 중복 제거 키가 갈려 같은 논문이 두 건으로 남는다."""
    client = _Client(
        **{
            S2_ENDPOINT: _s2({"title": "T", "externalIds": {"DOI": "10.1/doi.org/x"}}),
            OPENALEX_ENDPOINT: _openalex(
                {"display_name": "T", "doi": "https://doi.org/10.1/doi.org/x"}
            ),
        }
    )

    candidates = _with_s2(client).lookup("x").candidates

    assert [c.paper_id for c in candidates] == ["doi:10.1/doi.org/x"]


def test_openalex_arxiv_url_is_reduced_to_an_id():
    client = _Client(
        **{
            OPENALEX_ENDPOINT: _openalex(
                {"display_name": "T", "ids": {"arxiv": "https://arxiv.org/abs/2401.09999"}}
            )
        }
    )

    assert _lookup(client).lookup("x").candidates[0].paper_id == "arxiv:2401.09999v1"


def test_the_polite_pool_mailto_is_sent_only_when_configured():
    client = _Client(**{OPENALEX_ENDPOINT: _openalex()})

    _lookup(client).lookup("x")
    assert "mailto" not in _call(client, OPENALEX_ENDPOINT)[0]

    _lookup(client, mailto="a@b.c").lookup("x")
    assert _call(client, OPENALEX_ENDPOINT, nth=1)[0]["mailto"] == "a@b.c"


# --- 중복 제거: 순회 순서가 곧 승자 우선순위다 --------------------------------------


def test_the_arxiv_copy_wins_over_the_same_paper_from_the_other_two():
    """승자 arXiv > S2 > OpenAlex(§3.2). 순서가 뒤집히면 본문을 확보할 수 있는 사본을
    버리고 초록만 있는 사본을 남긴다."""
    client = _Client(
        **{
            ARXIV_ENDPOINT: _arxiv_ok(),
            S2_ENDPOINT: _s2(
                {"title": "S2 copy", "externalIds": {"ArXiv": "2304.10557"}}
            ),
            OPENALEX_ENDPOINT: _openalex(
                {"display_name": "OA copy", "ids": {"arxiv": "https://arxiv.org/abs/2304.10557"}}
            ),
        }
    )

    out = _with_s2(client).lookup("x").candidates

    assert len(out) == 1
    assert out[0].title == "Attention Is All You Need"


def test_the_same_arxiv_paper_at_different_versions_is_one_paper():
    client = _Client(
        **{
            ARXIV_ENDPOINT: _arxiv_ok(),  # v2
            S2_ENDPOINT: _s2({"title": "T", "externalIds": {"ArXiv": "2304.10557v5"}}),
        }
    )

    assert len(_with_s2(client).lookup("x").candidates) == 1


def test_papers_with_no_id_overlap_fall_back_to_the_title():
    client = _Client(
        **{
            S2_ENDPOINT: _s2({"title": "Same  Title", "externalIds": {"DOI": "10.1/a"}}),
            OPENALEX_ENDPOINT: _openalex({"display_name": "same title", "doi": "10.1/a"}),
        }
    )

    assert len(_with_s2(client).lookup("x").candidates) == 1


# --- 부분 저하 vs 전면 실패 ---------------------------------------------------------


def test_one_dead_source_degrades_instead_of_failing():
    client = _Client(
        **{
            ARXIV_ENDPOINT: RuntimeError("arxiv down"),
            S2_ENDPOINT: _s2({"title": "T", "externalIds": {"ArXiv": "2401.00002"}}),
        }
    )

    outcome = _with_s2(client).lookup("x")

    assert len(outcome.candidates) == 1
    assert outcome.degraded_sources == ("arxiv",)


def test_all_three_dead_is_the_only_failure():
    client = _Client(
        **{
            ARXIV_ENDPOINT: RuntimeError("down"),
            S2_ENDPOINT: RuntimeError("down"),
            OPENALEX_ENDPOINT: RuntimeError("down"),
        }
    )

    with pytest.raises(SearchUnavailable):
        _with_s2(client).lookup("x")


def test_an_empty_but_healthy_source_set_is_not_a_failure():
    """0건은 장애가 아니다 — "그런 논문이 없다"이고, 그것도 답이다(§2.3)."""
    client = _Client()

    assert _lookup(client).lookup("x").candidates == ()


def test_a_4xx_counts_as_a_source_failure():
    """`check_response`를 `.json()` 앞에서, 브레이커 안에서 불러야 실패로 집계된다."""
    client = _Client(**{S2_ENDPOINT: _Response(json_body={"data": []}, status=429)})

    assert _with_s2(client).lookup("x").degraded_sources == ("semantic_scholar",)


def test_each_source_has_its_own_circuit():
    """한 소스의 연속 실패가 다른 소스의 회로를 열면 안 된다 — 다른 엔드포인트다."""
    clock = _Clock()
    s2_breaker = SourceBreaker(failure_threshold=1, clock=clock)
    arxiv_breaker = SourceBreaker(failure_threshold=1, clock=clock)
    client = _Client(**{ARXIV_ENDPOINT: _arxiv_ok(), S2_ENDPOINT: RuntimeError("down")})
    lookup = _with_s2(client, arxiv_breaker=arxiv_breaker, s2_breaker=s2_breaker)

    lookup.lookup("x")
    second = lookup.lookup("x")

    assert second.degraded_sources == ("semantic_scholar",)
    assert len(second.candidates) == 1, "arXiv 회로가 S2 실패에 함께 열렸다"


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


# --- 경계 ---------------------------------------------------------------------------


def test_an_empty_query_never_leaves_the_process():
    client = _Client()

    assert _lookup(client).lookup("   ").candidates == ()
    assert client.calls == []


def test_an_overlong_query_is_truncated_at_the_boundary():
    """스펙의 maxLength는 모델에 대한 안내일 뿐 강제가 아니다."""
    client = _Client(**{ARXIV_ENDPOINT: _arxiv_ok()})

    _lookup(client).lookup("가" * 900)

    assert len(_call(client, ARXIV_ENDPOINT)[0]["search_query"]) == len("all:") + 400


# --- 미구성 소스는 저하가 아니다 ------------------------------------------------


def test_semantic_scholar_stays_out_without_a_key():
    """무키 공용 풀은 사실상 항상 429다(2026-08-25 실측: 12초 간격 5회 연속). 그런데도 매 턴
    부르면 왕복을 버리고, 더 나쁘게는 화면에 "실시간 조회가 온전히 돌지 못했어요"가 상시로
    뜬다 — 미구성을 장애로 보여주면 진짜 장애가 묻힌다."""
    client = _Client(**{S2_ENDPOINT: RuntimeError("429")})

    outcome = _lookup(client).lookup("x")

    assert outcome.degraded_sources == ()
    assert all(url != S2_ENDPOINT for url, _p, _h in client.calls), "키가 없는데 S2를 쳤다"


def test_a_configured_key_puts_it_back_in():
    client = _Client(**{S2_ENDPOINT: _s2({"title": "T", "externalIds": {"ArXiv": "2401.00003"}})})

    out = _with_s2(client).lookup("x").candidates

    assert any(url == S2_ENDPOINT for url, _p, _h in client.calls)
    assert any(c.paper_id == "arxiv:2401.00003v1" for c in out)


def test_with_no_key_a_dead_arxiv_and_openalex_is_still_a_full_failure():
    """실패 판정은 **구성된** 소스 전부가 기준이다 — 셋으로 세면 둘이 죽어도 실패가 안 된다."""
    client = _Client(
        **{ARXIV_ENDPOINT: RuntimeError("down"), OPENALEX_ENDPOINT: RuntimeError("down")}
    )

    with pytest.raises(SearchUnavailable):
        _lookup(client).lookup("x")


# --- 같은 논문을 세 건으로 남기던 것 ------------------------------------------------


def test_the_same_paper_folds_even_when_only_some_sources_carry_a_doi():
    """**arXiv id를 먼저 본다.** arXiv 소스는 DOI를 아예 안 싣고 S2/OpenAlex는 출판된 논문에
    대개 싣는다 — DOI를 앞에 두면 같은 논문의 arXiv 사본과 S2 사본이 한 번도 안 접힌다
    (실측: 한 논문이 후보 세 건으로 남았다).

    그 뒤는 조용히 나쁘다: 모델은 한 논문을 세 출처로 보고, 승격이 두 번 돌고(각 20초 폴링),
    색인 잡이 두 철자로 나가고, 같은 논문이 독립 근거로 두 번 인용될 수 있다.
    """
    client = _Client(
        **{
            ARXIV_ENDPOINT: _arxiv_ok(),  # 2304.10557v2, DOI 없음
            S2_ENDPOINT: _s2(
                {"title": "S2", "externalIds": {"ArXiv": "2304.10557", "DOI": "10.1145/xyz"}}
            ),
            OPENALEX_ENDPOINT: _openalex(
                {"display_name": "OA", "doi": "https://doi.org/10.48550/arXiv.2304.10557"}
            ),
        }
    )

    out = _with_s2(client).lookup("x").candidates

    assert [c.paper_id for c in out] == ["arxiv:2304.10557v2"]


def test_a_datacite_doi_becomes_an_arxiv_paper_id_not_just_an_arxiv_key():
    """되찾기가 **중복 제거 키에만** 있고 후보 id에는 없던 동안, 같은 논문이 키로는 접히는데
    모델에게는 `doi:`로 보였다(배포본 실측). `promotable()`이 `doi:`를 거부하므로 본문 승격도
    백그라운드 색인도 안 되고, 화면에는 arXiv에 없는 논문처럼 보인다 — 예외도 로그도 없다."""
    client = _Client(
        **{
            OPENALEX_ENDPOINT: _openalex(
                {"display_name": "RAG survey", "doi": "https://doi.org/10.48550/arXiv.2312.10997"}
            )
        }
    )

    candidate = _lookup(client).lookup("x").candidates[0]

    assert candidate.paper_id == "arxiv:2312.10997v1", (
        f"arXiv 논문이 doi: 로 실렸다 — {candidate.paper_id}"
    )
    assert candidate.record_ref == "external:arxiv:2312.10997v1"


def test_an_arxiv_datacite_doi_is_recognised_as_that_arxiv_paper():
    """OpenAlex는 arXiv 사본을 `10.48550/arXiv.…` DOI로만 싣는 일이 잦다."""
    client = _Client(
        **{
            ARXIV_ENDPOINT: _arxiv_ok(),
            OPENALEX_ENDPOINT: _openalex(
                {"display_name": "OA", "doi": "10.48550/arxiv.2304.10557"}
            ),
        }
    )

    assert len(_lookup(client).lookup("x").candidates) == 1


def test_every_source_gets_slots_when_the_tool_truncates():
    """도구가 상위 10건으로 자르는데 그냥 이어 붙이면 arXiv 8 + S2 2로 차고 **OpenAlex는
    한 번도 안 보인다** — S2·OpenAlex를 더한 이유가 "arXiv에 없는 논문"인데 그 논문이
    구조적으로 잘려 나간다."""
    client = _Client(
        **{
            ARXIV_ENDPOINT: _Response(content=_many_arxiv(8).encode("utf-8")),
            OPENALEX_ENDPOINT: _openalex(
                *({"display_name": f"OA {i}", "doi": f"10.9/{i}"} for i in range(8))
            ),
        }
    )

    top = _lookup(client).lookup("x").candidates[:10]
    namespaces = {c.paper_id.split(":")[0] for c in top}

    assert "doi" in namespaces, "앞 소스가 자리를 다 먹어 뒤 소스가 안 보인다"
    assert top[0].paper_id.startswith("arxiv:"), "승자 우선순위가 뒤집혔다"


def _many_arxiv(n: int) -> str:
    entries = "".join(
        f"<entry><id>http://arxiv.org/abs/24{i:02d}.00001v1</id>"
        f"<title>A {i}</title><summary>s {i}</summary></entry>"
        for i in range(n)
    )
    return f'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">{entries}</feed>'
