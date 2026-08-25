"""evidence v2 테스트 공용 대역 — novelty_fakes와 같은 성격.

네 테스트 파일이 같은 DocModel 스탠드인(s4.tbl1/AlphaFold2/92.4)을 조금씩 다르게
복사해 쓰고 있었다. 게이트·프롬프트·러너가 **같은 문서**를 봐야 투영 정합 단언이
의미가 있으므로 한 벌로 모은다.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from docsuri_shared.authz import Principal, UserRole

from backend.modules.evidence.domain.models import PaperHandle, PaperOrigin
from backend.modules.evidence.ports.llm import LoopObservation, PaperView

TABLE_ROW = "AlphaFold2 | 92.4 | 87.0"
FIGURE_CAPTION = "Figure 3 Accuracy versus training set size across three model scales"
INTRO = "Protein structure prediction has progressed rapidly in recent years."
LATEX = "L = -\\sum_i y_i \\log p_i"


PAPER_TITLE = "Highly accurate protein structure prediction with AlphaFold"


def doc_model() -> SimpleNamespace:
    """구조 동형 DocModel 스탠드인 — 문단·표·그림·수식 각 1블록.

    게이트·프롬프트는 pydantic 인스턴스가 아니라 모양만 본다. 블록 id는
    테스트 전반이 앵커로 참조하므로 바꾸면 넓게 깨진다: s1.p1 / s4.tbl1 /
    s5.fig3 / s2.eq1.
    """
    paragraph = SimpleNamespace(id="s1.p1", type="paragraph", text=INTRO)
    table = SimpleNamespace(
        id="s4.tbl1",
        type="table",
        anchorLabel="Table 1",
        caption="CASP14 results",
        rows=[
            SimpleNamespace(cells=[SimpleNamespace(text=c) for c in ("Method", "GDT", "TM")]),
            SimpleNamespace(
                cells=[SimpleNamespace(text=c) for c in ("AlphaFold2", "92.4", "87.0")]
            ),
        ],
    )
    figure = SimpleNamespace(
        id="s5.fig3",
        type="figure",
        anchorLabel="Figure 3",
        caption="Accuracy versus training set size across three model scales",
    )
    formula = SimpleNamespace(id="s2.eq1", type="formula", latex=LATEX)
    section = SimpleNamespace(
        id="s1", title="Introduction", blocks=[paragraph, table, figure, formula], sections=[]
    )
    # `meta`가 빠져 있던 동안 본문에서 제목을 가져오는 경로가 **검사에 안 걸렸다** — 대역이
    # 실물보다 좁으면 그 필드를 읽는 코드는 항상 빈 값을 보고, 테스트는 초록으로 지나간다.
    meta = SimpleNamespace(paperId="2107.06xxx", version=1, title=PAPER_TITLE, abstract=None)
    return SimpleNamespace(meta=meta, sections=[section])


def principal() -> Principal:
    return Principal(user_id=str(uuid4()), role=UserRole.USER)


def paper_handle(doc_model=None, abstract: str = "") -> PaperHandle:
    """확보한 논문 1편 — 프로바이더 중립이라 어댑터 테스트가 공유한다."""
    return PaperHandle(
        paper_id="p1",
        record_ref="r1",
        origin=PaperOrigin.CORPUS,
        title="AlphaFold2",
        doc_model=doc_model,
        abstract_text=abstract,
    )


def observation(**overrides) -> LoopObservation:
    """`decide` 입력의 기본형. 케이스별로 바꿀 필드만 키워드로 덮어쓴다."""
    base = dict(
        topic="단백질 구조 예측 정확도",
        papers=(PaperView("p1", "r1", "AlphaFold2", "corpus", "fulltext"),),
        recent_results=(),
        evidence_count=0,
        cited_paper_count=0,
        has_conflicts=False,
        iterations_left=5,
        tool_calls_left=10,
        cost_left_usd=0.5,
    )
    base.update(overrides)
    return LoopObservation(**base)
