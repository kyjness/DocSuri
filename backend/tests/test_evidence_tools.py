"""evidence/tools.py — EvidencePaperSearchTool 예외 변환 회귀 테스트.

배경: real_wiring.py는 OpenSearch 어댑터를 최상위 discovery.* 경로에서 import하는데,
tools.py는 IndexUnavailable을 backend.modules.discovery.src.discovery.* (중첩 경로)에서
import하고 있었다. 소스는 동일해도 Python은 두 경로를 별개 모듈로 취급해 두 IndexUnavailable
클래스가 서로 다른 객체가 되고, tools.py의 `except IndexUnavailable`이 실제로 발생한
예외와 매칭에 실패해 raw 500으로 새어나갔다(프로덕션에서 OpenSearch 콜드 그래프 로드로
재현·확인됨). 이 테스트는 real_wiring.py와 동일한 최상위 경로에서 IndexUnavailable을
raise하는 fake 어댑터로 이 클래스 불일치가 재발하지 않는지 검증한다.
"""

from __future__ import annotations

import pytest
from discovery.ports.search_ports import IndexUnavailable

from backend.modules.evidence.tools import (
    EvidenceDocModelTool,
    EvidencePaperSearchTool,
    PaperSearchUnavailable,
)


class _FailingVectorStore:
    def knn_search(self, *args, **kwargs):
        raise IndexUnavailable('search after 3 attempt(s)')


class _FailingLexicalIndex:
    def bm25_search(self, *args, **kwargs):
        raise IndexUnavailable('search after 3 attempt(s)')


class _NoEmbedding:
    def embed_query(self, text: str) -> list[float]:
        raise RuntimeError('embedding backend unavailable')


def _search_tool() -> EvidencePaperSearchTool:
    return EvidencePaperSearchTool(
        embedding=_NoEmbedding(),
        vector_store=_FailingVectorStore(),
        lexical_index=_FailingLexicalIndex(),
        paper_lookup=None,
    )


def test_index_unavailable_from_top_level_discovery_path_is_caught() -> None:
    """real_wiring.py가 실제로 쓰는 최상위 discovery.ports.search_ports.IndexUnavailable을
    그대로 raise해도 PaperSearchUnavailable로 정상 변환돼야 한다(raw로 새면 안 됨)."""
    with pytest.raises(PaperSearchUnavailable):
        _search_tool().search(topic='self-attention', scope=None, paper_ids=None)


def test_index_unavailable_never_escapes_as_itself() -> None:
    """IndexUnavailable 자체가 그대로 호출자까지 전파되면 안 된다 — 반드시
    PaperSearchUnavailable로 변환된 채로만 나가야 orchestrator가 abstain으로 잡을 수 있다."""
    try:
        _search_tool().search(topic='self-attention', scope=None, paper_ids=None)
    except IndexUnavailable:
        pytest.fail('IndexUnavailable leaked raw — tools.py의 except가 매칭에 실패함')
    except PaperSearchUnavailable:
        pass


# --- EvidenceDocModelTool: arXiv 버전 배선 회귀 ---------------------------------------------
#
# 배경: evidence orchestrator는 versioned arxivId만 들고 get_doc_model(paper_id)를 버전 없이
# 호출했고, 예전 기본값 version=1 탓에 개정판(v2+) 논문은 S3에 doc-model(v{N}.json)이 있어도
# 항상 v1을 읽어 perpetual miss → grounded 근거 0 → "문서 카드만 나오고 설명이 없음"
# (프로덕션 novelty 워커에서 재현·확인). tool이 paper_id의 arXiv 버전을 reader에 그대로
# 넘기는지 검증한다.


class _RecordingDocModelReader:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def get_doc_model(self, paper_id: str, version: int):
        self.calls.append((paper_id, version))
        return None  # miss는 무관 — 넘어간 version만 검증


def test_doc_model_tool_uses_arxiv_version_from_paper_id() -> None:
    reader = _RecordingDocModelReader()
    EvidenceDocModelTool(doc_model_reader=reader).get_doc_model('2309.15039v4')  # 개정판
    assert reader.calls == [('2309.15039v4', 4)]  # v1 아님 → 실제 v4를 읽어야 함


def test_doc_model_tool_bare_id_defaults_to_v1() -> None:
    reader = _RecordingDocModelReader()
    EvidenceDocModelTool(doc_model_reader=reader).get_doc_model('2309.15039')
    assert reader.calls == [('2309.15039', 1)]  # 버전 없는 id → v1 유지


def test_doc_model_tool_explicit_version_wins() -> None:
    reader = _RecordingDocModelReader()
    EvidenceDocModelTool(doc_model_reader=reader).get_doc_model('2309.15039v4', 2)
    assert reader.calls == [('2309.15039v4', 2)]  # 명시 버전이 우선
