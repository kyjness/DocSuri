"""evidence/prompts.py — 블록 타입별 텍스트 추출 회귀 테스트 (PR #338 리뷰 Medium #9).

기존엔 ``getattr(block.root, 'text', '')``만 읽어 Table/Formula/Figure/List 블록이
전부 0바이트로 프롬프트에서 빠졌다 — 결과 비교표의 핵심 수치, 수식, 그림 캡션이
애초에 LLM에 보이지 않아 근거로 추출될 수 없었다.
"""

from __future__ import annotations

from types import SimpleNamespace

from backend.modules.evidence.prompts import build_evidence_extraction_prompt


def _block(root: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(root=root)


def _section(*, title: str = '', blocks=None, sections=None) -> SimpleNamespace:
    return SimpleNamespace(title=title, blocks=blocks or [], sections=sections or [])


def _doc_model(sections: list[SimpleNamespace]) -> SimpleNamespace:
    return SimpleNamespace(sections=sections, fullText='', meta=SimpleNamespace(title='제목'))


def _prompt_body(doc_model: SimpleNamespace) -> str:
    _, user = build_evidence_extraction_prompt('topic', [('p1', doc_model)])
    return user


def test_paragraph_and_code_blocks_still_extracted() -> None:
    section = _section(
        title='Intro',
        blocks=[
            _block(SimpleNamespace(type='paragraph', text='본문 문단입니다.')),
            _block(SimpleNamespace(type='code', text='x = 1')),
        ],
    )
    body = _prompt_body(_doc_model([section]))

    assert '본문 문단입니다.' in body
    assert 'x = 1' in body


def test_table_block_caption_and_rows_are_extracted() -> None:
    table = SimpleNamespace(
        type='table',
        caption='Table 3: Accuracy comparison',
        anchorLabel='Table 3',
        rows=[
            SimpleNamespace(cells=[SimpleNamespace(text='Model'), SimpleNamespace(text='Acc')]),
            SimpleNamespace(cells=[SimpleNamespace(text='BERT'), SimpleNamespace(text='92.3')]),
        ],
    )
    body = _prompt_body(_doc_model([_section(blocks=[_block(table)])]))

    assert 'Table 3: Accuracy comparison' in body
    assert 'Model | Acc' in body
    assert 'BERT | 92.3' in body


def test_formula_block_latex_is_extracted() -> None:
    formula = SimpleNamespace(
        type='formula', latex='E = mc^2', anchorLabel='(3)', assetRef=None, display=True,
    )
    body = _prompt_body(_doc_model([_section(blocks=[_block(formula)])]))

    assert 'E = mc^2' in body
    assert '(3)' in body


def test_formula_block_without_latex_yields_nothing() -> None:
    # 페이지 크롭 이미지만 있는 폴백 케이스 — 텍스트로 추출할 게 없다(assetRef는 픽셀).
    formula = SimpleNamespace(type='formula', latex=None, anchorLabel='(3)', assetRef=object())
    body = _prompt_body(_doc_model([_section(blocks=[_block(formula)])]))

    assert '(3)' not in body


def test_figure_block_caption_is_extracted() -> None:
    figure = SimpleNamespace(
        type='figure', caption='Loss curve over epochs', anchorLabel='Figure 2',
    )
    body = _prompt_body(_doc_model([_section(blocks=[_block(figure)])]))

    assert 'Figure 2: Loss curve over epochs' in body


def test_list_block_items_are_extracted() -> None:
    lst = SimpleNamespace(
        type='list',
        ordered=True,
        items=[SimpleNamespace(text='first point'), SimpleNamespace(text='second point')],
    )
    body = _prompt_body(_doc_model([_section(blocks=[_block(lst)])]))

    assert '- first point' in body
    assert '- second point' in body


def test_nested_sections_still_traverse_with_new_block_types() -> None:
    fig = SimpleNamespace(type='figure', caption='Fig 1', anchorLabel=None)
    inner = _section(title='Results', blocks=[_block(fig)])
    outer = _section(title='Experiments', blocks=[], sections=[inner])
    body = _prompt_body(_doc_model([outer]))

    assert 'Experiments' in body
    assert 'Results' in body
    assert 'Fig 1' in body
