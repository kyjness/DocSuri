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

    out = _lookup(client).search("attention")

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

    assert _lookup(client).search("x")[0].paper_id == "arxiv:2304.10557v1"


def test_only_the_query_leaves_the_boundary():
    """payload allowlist(BR-EV-20) — 나가는 파라미터에 질의 말고 아무것도 없어야 한다."""
    client = _Client(**{ARXIV_ENDPOINT: _arxiv_ok()})

    _lookup(client).search("사용자가 물어본 것")

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

    assert _with_s2(client).search("x")[0].paper_id == "arxiv:2401.00001v1"


def test_a_paper_with_no_arxiv_id_is_carried_under_the_doi_namespace():
    """학회·저널 전용 논문은 arXiv id가 없다. **지어내지 않는다**(무날조) — 그런 논문은
    본문 승격 대상이 아니고 초록 범위로만 인용된다."""
    client = _Client(
        **{S2_ENDPOINT: _s2({"title": "T", "externalIds": {"DOI": "10.1145/ABC"}})}
    )

    assert _with_s2(client).search("x")[0].paper_id == "doi:10.1145/abc"


def test_a_record_with_neither_id_is_dropped():
    """id가 없으면 인용의 실재를 확인할 핸들이 없다 — 게이트가 어차피 떨어뜨린다."""
    client = _Client(**{S2_ENDPOINT: _s2({"title": "T", "abstract": "A"})})

    assert _with_s2(client).search("x") == ()


def test_the_api_key_rides_in_the_header_not_the_query():
    client = _Client(**{S2_ENDPOINT: _s2()})

    _lookup(client, s2_api_key="k").search("x")

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

    assert _lookup(client).search("x")[0].abstract == "we are sparse"


def test_openalex_doi_loses_its_url_prefix_so_it_meets_the_s2_value():
    """S2는 맨 DOI를, OpenAlex는 `https://doi.org/...`를 준다. 벗기지 않으면 같은 논문이
    두 건으로 남는다."""
    client = _Client(
        **{
            S2_ENDPOINT: _s2({"title": "T", "externalIds": {"DOI": "10.1/X"}}),
            OPENALEX_ENDPOINT: _openalex({"display_name": "T", "doi": "https://doi.org/10.1/x"}),
        }
    )

    assert len(_with_s2(client).search("x")) == 1


def test_openalex_arxiv_url_is_reduced_to_an_id():
    client = _Client(
        **{
            OPENALEX_ENDPOINT: _openalex(
                {"display_name": "T", "ids": {"arxiv": "https://arxiv.org/abs/2401.09999"}}
            )
        }
    )

    assert _lookup(client).search("x")[0].paper_id == "arxiv:2401.09999v1"


def test_the_polite_pool_mailto_is_sent_only_when_configured():
    client = _Client(**{OPENALEX_ENDPOINT: _openalex()})

    _lookup(client).search("x")
    assert "mailto" not in _call(client, OPENALEX_ENDPOINT)[0]

    _lookup(client, mailto="a@b.c").search("x")
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

    out = _with_s2(client).search("x")

    assert len(out) == 1
    assert out[0].title == "Attention Is All You Need"


def test_the_same_arxiv_paper_at_different_versions_is_one_paper():
    client = _Client(
        **{
            ARXIV_ENDPOINT: _arxiv_ok(),  # v2
            S2_ENDPOINT: _s2({"title": "T", "externalIds": {"ArXiv": "2304.10557v5"}}),
        }
    )

    assert len(_with_s2(client).search("x")) == 1


def test_papers_with_no_id_overlap_fall_back_to_the_title():
    client = _Client(
        **{
            S2_ENDPOINT: _s2({"title": "Same  Title", "externalIds": {"DOI": "10.1/a"}}),
            OPENALEX_ENDPOINT: _openalex({"display_name": "same title", "doi": "10.1/a"}),
        }
    )

    assert len(_with_s2(client).search("x")) == 1


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

    assert _lookup(client).search("   ") == ()
    assert client.calls == []


def test_an_overlong_query_is_truncated_at_the_boundary():
    """스펙의 maxLength는 모델에 대한 안내일 뿐 강제가 아니다."""
    client = _Client(**{ARXIV_ENDPOINT: _arxiv_ok()})

    _lookup(client).search("가" * 900)

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

    out = _lookup(client, s2_api_key="k").search("x")

    assert any(url == S2_ENDPOINT for url, _p, _h in client.calls)
    assert any(c.paper_id == "arxiv:2401.00003v1" for c in out)


def test_with_no_key_a_dead_arxiv_and_openalex_is_still_a_full_failure():
    """실패 판정은 **구성된** 소스 전부가 기준이다 — 셋으로 세면 둘이 죽어도 실패가 안 된다."""
    client = _Client(
        **{ARXIV_ENDPOINT: RuntimeError("down"), OPENALEX_ENDPOINT: RuntimeError("down")}
    )

    with pytest.raises(SearchUnavailable):
        _lookup(client).lookup("x")
