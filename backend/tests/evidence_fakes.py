"""evidence v2 테스트 공용 대역 — novelty_fakes와 같은 성격.

네 테스트 파일이 같은 DocModel 스탠드인(s4.tbl1/AlphaFold2/92.4)을 조금씩 다르게
복사해 쓰고 있었다. 게이트·프롬프트·러너가 **같은 문서**를 봐야 투영 정합 단언이
의미가 있으므로 한 벌로 모은다.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from docsuri_shared.authz import Principal, UserRole

TABLE_ROW = "AlphaFold2 | 92.4 | 87.0"
FIGURE_CAPTION = "Figure 3 Accuracy versus training set size across three model scales"
INTRO = "Protein structure prediction has progressed rapidly in recent years."
LATEX = "L = -\\sum_i y_i \\log p_i"


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
    return SimpleNamespace(sections=[section])


def principal() -> Principal:
    return Principal(user_id=str(uuid4()), role=UserRole.USER)
