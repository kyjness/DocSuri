"""evidence 코퍼스 검색 — U2의 랭킹을 **끝까지** 쓰는지 고정한다.

리랭크는 `HybridRetriever`가 아니라 그 위 오케스트레이터 단계에 있다. 그래서 리트리버를
직접 들면 RRF 순서까지만 받고도 아무 신호가 없다 — 실제로 그 상태로 돌고 있었고, 넘기던
`rerank_enabled=True`는 리트리버가 읽지 않는 인자였다. 여기서 고정하는 것은 어댑터가
`retrieve_ranked`(리랭크 포함 경로)로 묶여 있다는 사실이다.

같은 파일에 있던 임베딩 동일공간 가드 테스트 셋은 지웠다. evidence가 자기 임베더를 더는
세우지 않기 때문이다 — 오케스트레이터가 discovery의 읽기 경로와 **같은 팩토리**로 조립하므로
"두 번째 리더가 같은 공간을 쓰는가"는 미러링된 배선을 검사할 일이 아니라 구조로 참이 됐다.
가드 자체의 동작은 discovery 쪽 테스트가 본다.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from discovery.ports.search_ports import SearchUnavailable as U2SearchUnavailable

from backend.modules.evidence.adapters.sources import CorpusSearch
from backend.modules.evidence.ports.sources import SearchUnavailable, YearBound


def _record(paper_id: str, *, abstract: str = "") -> SimpleNamespace:
    return SimpleNamespace(arxivId=paper_id, title=f"title {paper_id}", abstract=abstract)


class _Orchestrator:
    """`retrieve_ranked`만 가진 대역 — 호출 인자를 그대로 적어 둔다."""

    def __init__(self, records: list[SimpleNamespace]) -> None:
        self._records = records
        self.calls: list[dict] = []

    def retrieve_ranked(self, query, *, scope, years=None, top_n=None):
        self.calls.append({"query": query, "scope": scope, "years": years, "top_n": top_n})
        return SimpleNamespace(
            ranked=tuple(SimpleNamespace(record=r) for r in self._records)
        )


class _LexicalIndex:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def phrase_search(self, phrase, top_k, paper_ids=None, years=None):
        self.calls.append({"phrase": phrase, "top_k": top_k, "years": years})
        return [(_record("2106.09685"), 1.0)]


def test_hybrid_search_goes_through_the_ranked_path() -> None:
    """리트리버가 아니라 오케스트레이터를 부른다 — 이것이 리랭크가 걸리는 유일한 경로다."""
    orch = _Orchestrator([_record("1706.03762", abstract="attention is all you need")])
    search = CorpusSearch(orchestrator=orch, lexical_index=_LexicalIndex())

    candidates = search.search("transformer attention")

    assert len(orch.calls) == 1
    assert orch.calls[0]["query"] == "transformer attention"
    # 본문 청크까지 보는 breadth. lite로 내려가면 에이전트가 초록에만 걸린다.
    assert orch.calls[0]["scope"].value == "full"
    assert [c.paper_id for c in candidates] == ["1706.03762"]
    # 초록은 **전체**가 실려야 한다 — 카드의 abstractSnippet(색인 시 절삭)이 아니다.
    assert candidates[0].abstract == "attention is all you need"


def test_year_bound_reaches_the_orchestrator() -> None:
    """연도는 필터다 — 후처리로 깎으면 0건이 '그런 논문이 없다'와 구분되지 않는다."""
    orch = _Orchestrator([_record("2304.10557")])
    search = CorpusSearch(orchestrator=orch, lexical_index=_LexicalIndex())

    search.search("rlhf", years=YearBound(start=2023, end=2024))

    years = orch.calls[0]["years"]
    assert (years.start, years.end) == (2023, 2024)


def test_phrase_search_bypasses_the_orchestrator() -> None:
    """정확 문구는 매치/비매치뿐이라 크로스인코더가 다시 줄 세울 순서가 없다."""
    orch = _Orchestrator([_record("1706.03762")])
    lexical = _LexicalIndex()
    search = CorpusSearch(orchestrator=orch, lexical_index=lexical)

    candidates = search.search("attention is all you need", phrase=True)

    assert orch.calls == []
    assert lexical.calls[0]["phrase"] == "attention is all you need"
    assert [c.paper_id for c in candidates] == ["2106.09685"]


def test_record_ref_is_the_bare_paper_id() -> None:
    """버전·청크가 섞이면 자산 조회(view_figure)가 전량 미스된다(INV-EV-5)."""
    orch = _Orchestrator([_record("1706.03762v7")])
    search = CorpusSearch(orchestrator=orch, lexical_index=_LexicalIndex())

    candidates = search.search("transformer")

    assert candidates[0].record_ref == "1706.03762"


def test_index_failure_surfaces_as_the_evidence_search_error() -> None:
    """U2는 인덱스 장애를 자기 예외로 올린다 — 도구가 아는 형태로 번역돼야 턴이 계속된다."""

    class _Down:
        def retrieve_ranked(self, query, *, scope, years=None, top_n=None):
            raise U2SearchUnavailable("search index unavailable")

    search = CorpusSearch(orchestrator=_Down(), lexical_index=_LexicalIndex())

    with pytest.raises(SearchUnavailable):
        search.search("transformer")


def test_real_orchestrator_reranks_what_the_adapter_returns() -> None:
    """대역이 아니라 **실제 `SearchOrchestrationService`**에 붙여 순서가 바뀌는지 본다.

    위의 테스트들은 "어댑터가 `retrieve_ranked`를 부른다"는 호출 계약을 고정한다. 그것만으로는
    리랭크가 실제로 걸리는지 알 수 없다 — 이 결함이 처음 생긴 방식이 바로 "맞는 이름의 인자를
    넘기지만 아무도 읽지 않는" 것이었다. 여기서는 U2가 자기 목 배선으로 세운 진짜
    오케스트레이터에 리랭커를 물려, 어댑터가 돌려주는 후보 순서가 RRF 순서와 달라지는지 센다.
    """
    from collections.abc import Sequence

    from discovery.testing import build_mock_orchestrator

    class _ReverseRerank:
        def rerank(self, query: str, documents: Sequence[str]) -> list[float]:
            return [float(i) for i in range(len(documents))]

    def _ids(reranker) -> list[str]:
        orch = build_mock_orchestrator(reranker=reranker).orchestrator
        search = CorpusSearch(orchestrator=orch, lexical_index=_LexicalIndex())
        return [c.paper_id for c in search.search("diffusion models for protein structure")]

    baseline = _ids(None)
    reranked = _ids(_ReverseRerank())

    assert baseline, "목 코퍼스가 0건을 줬다 — 픽스처 쪽 문제다"
    assert baseline != reranked, "리랭커를 물렸는데 순서가 그대로다 — 경로가 안 닿았다"
    assert set(baseline) == set(reranked)


def test_app_shell_calls_the_runner_builder_with_the_arguments_it_accepts() -> None:
    """마운트가 조용히 실패하던 자리 — 앱은 초록으로 뜨고 evidence만 skipped가 된다.

    `_mount_evidence`는 `build_evidence_runner(...)`를 키워드로 부르는데, 그 호출은 실 경로
    (DocModel 버킷·OpenSearch 구성)에서만 실행돼 단위 테스트가 한 번도 밟지 않는다. 인자
    이름이 갈리면 `TypeError`가 WARNING 한 줄로 삼켜진다 — 서명만 기계적으로 맞춰 둔다.
    """
    import ast
    import inspect
    from pathlib import Path

    from backend.modules.evidence.real_wiring import build_evidence_runner

    accepted = set(inspect.signature(build_evidence_runner).parameters)
    source = Path(__file__).resolve().parents[1] / "wiring.py"
    tree = ast.parse(source.read_text())
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "build_evidence_runner"
    ]
    assert calls, "wiring.py가 build_evidence_runner를 부르지 않는다"
    for call in calls:
        used = {kw.arg for kw in call.keywords if kw.arg}
        assert used <= accepted, f"wiring이 넘기는 {used - accepted}를 러너 빌더가 안 받는다"
