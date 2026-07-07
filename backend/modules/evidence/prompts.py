from __future__ import annotations

from typing import Any

from docsuri_shared.dtos import DocModel

DocModelSource = tuple[str, DocModel] | tuple[str, DocModel, str]


def build_evidence_extraction_prompt(
    topic: str,
    doc_models: list[DocModelSource],  # (paper_id, DocModel[, record_ref])
) -> tuple[str, str]:
    """DocModel 블록 → EvidenceItem 추출 LLM 프롬프트."""
    system = (
        'You are a scientific evidence extractor. '
        'Your task is to extract evidence items from the provided paper content.\n\n'
        'STRICT RULES:\n'
        '1. Extract statements ONLY from the provided paper text. '
        'Do NOT generate new statements or paraphrase beyond the source text.\n'
        '2. Each statement must be directly traceable to a specific paper and block.\n'
        '3. Return valid JSON only. No explanations outside the JSON.\n'
        '4. Use the exact paperId and recordRef shown for each source. '
        'For userdoc: sources, never invent an arXiv URL or arXiv id.\n'
        '5. If no relevant evidence exists, return {"items": []}.'
    )

    papers_text = _format_papers(doc_models)

    user = (
        f'Topic: {topic}\n\n'
        f'Papers:\n{papers_text}\n\n'
        'Extract evidence items relevant to the topic. '
        'For each item, identify which papers support or conflict with the statement.\n\n'
        'Return JSON in this exact format:\n'
        '{\n'
        '  "items": [\n'
        '    {\n'
        '      "statement": "<extracted statement from paper text>",\n'
        '      "supporting": [\n'
        '        {"paperId": "<paperId>", "recordRef": "<recordRef>", "quote": "<short quote>"}\n'
        '      ],\n'
        '      "conflicting": [\n'
        '        {"paperId": "<paperId>", "recordRef": "<recordRef>", "quote": "<short quote>"}\n'
        '      ]\n'
        '    }\n'
        '  ]\n'
        '}'
    )

    return system, user


def _format_papers(doc_models: list[DocModelSource]) -> str:
    parts = []
    for source in doc_models:
        paper_id, doc_model, record_ref = _source_parts(source)
        # DocModel에는 top-level title이 없고 meta.title에 있다 — 존재하지 않는
        # doc_model.title을 getattr(default='')로 조용히 삼키던 것과 같은 패턴의
        # 버그였다(PR #338 리뷰 Medium #10, prompts.py 본문 추출 버그와 동일 유형).
        title = getattr(getattr(doc_model, 'meta', None), 'title', '') or paper_id
        blocks_text = _extract_block_text(doc_model)
        parts.append(f'[PAPER:{paper_id}] [RECORD:{record_ref}] {title}\n{blocks_text}')
    return '\n\n'.join(parts)


def _source_parts(source: DocModelSource) -> tuple[str, Any, str]:
    paper_id = source[0]
    doc_model = source[1]
    record_ref = source[2] if len(source) >= 3 else paper_id
    return paper_id, doc_model, record_ref


def _extract_block_text(doc_model: DocModel) -> str:
    lines: list[str] = []
    for section in getattr(doc_model, 'sections', None) or []:
        _collect_section_text(section, lines)
    return '\n'.join(lines)[:8000]


def _collect_section_text(section: object, lines: list[str]) -> None:
    title = getattr(section, 'title', '') or ''
    if title:
        lines.append(f'## {title}')
    for block in getattr(section, 'blocks', None) or []:
        text = _block_text(getattr(block, 'root', block))
        if text:
            lines.append(text[:2000])
    for nested in getattr(section, 'sections', None) or []:
        _collect_section_text(nested, lines)


def _block_text(root: object) -> str:
    """블록 타입(paragraph/code/table/formula/figure/list)별로 프롬프트에 실을 텍스트를
    뽑는다. 예전엔 ``.text``만 읽어 Table/Formula/Figure/List가 전부 0바이트로 빠졌다
    (PR #338 리뷰 Medium #9) — 결과 비교표의 핵심 수치·수식·그림 캡션이 애초에 LLM에
    보이지 않아 근거로 추출될 수 없었다."""
    block_type = getattr(root, 'type', None)
    if block_type in ('paragraph', 'code'):
        return getattr(root, 'text', '') or ''
    if block_type == 'table':
        return _table_text(root)
    if block_type == 'formula':
        label = getattr(root, 'anchorLabel', None)
        latex = getattr(root, 'latex', None)
        if not latex:
            return ''
        return f'{label}: {latex}' if label else latex
    if block_type == 'figure':
        caption = getattr(root, 'caption', None) or ''
        label = getattr(root, 'anchorLabel', None)
        if not caption:
            return ''
        return f'{label}: {caption}' if label else caption
    if block_type == 'list':
        items = [getattr(item, 'text', '') for item in getattr(root, 'items', None) or []]
        return '\n'.join(f'- {text}' for text in items if text)
    return ''


def _table_text(root: object) -> str:
    caption = getattr(root, 'caption', None) or ''
    label = getattr(root, 'anchorLabel', None)
    header = f'{label}: {caption}' if label and caption else label or caption
    row_lines = []
    for row in getattr(root, 'rows', None) or []:
        cells = [getattr(cell, 'text', '') or '' for cell in getattr(row, 'cells', None) or []]
        if cells:
            row_lines.append(' | '.join(cells))
    body = '\n'.join(row_lines)
    return f'{header}\n{body}' if header else body
