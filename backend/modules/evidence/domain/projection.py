"""블록 텍스트 투영 — 프롬프트와 날조 검사가 **같은 문자열**을 보게 하는 단일 지점.

이 모듈이 존재하는 이유는 v1의 구조적 결함이다: 추출 프롬프트는 캡션을
``"Figure 2: ..."``(콜론)로 실었고 대조 대상인 ``DocModel.fullText``는
``"Figure 2 ..."``(공백)로 만들어져, 모델이 프롬프트에 보이는 대로 인용하면
verbatim 검사에서 탈락했다. 캡션 근거가 사실상 인용 불가였고 그 사실이
드러나지 않았다.

따라서 규칙은 하나다 — **프롬프트에 싣는 표현과 게이트가 대조하는 투영은
이 함수 하나에서만 나온다.** 새 블록 타입이 생기면 여기만 고치면 되고,
두 곳이 갈라질 방법이 없다.

투영 대상(BLM §3 "블록별 대조 대상"):

===========  ==========================================
paragraph    본문 텍스트
code         본문 텍스트(알고리즘 리스팅 포함)
list         항목 텍스트(줄 단위)
table        라벨·캡션 + 행별 ``"cell | cell"``
formula      LaTeX (없으면 빈 문자열 — crop 이미지는 인용 대상이 아니다)
figure       라벨·캡션
===========  ==========================================

라벨·캡션 결합은 ingestion의 ``block_text_parts``와 같은 규칙(공백 결합)을
쓴다. u1이 ``fullText``를 만드는 방식과 어긋나면 코퍼스 논문의 인용이
탈락하기 때문이다.
"""

from __future__ import annotations

import re
from typing import Any

__all__ = [
    "ANCHOR_TYPES",
    "block_id",
    "block_projection",
    "block_type",
    "iter_blocks",
    "normalize",
    "paper_projection",
    "section_title_projection",
]

# SourceRef.anchorType이 취할 수 있는 값 — 공유 계약 enum과 같아야 한다.
ANCHOR_TYPES = frozenset({"paragraph", "list", "code", "table", "figure", "formula"})

_WS = re.compile(r"\s+")


def normalize(text: str | None) -> str:
    """공백 정규화 — 대조는 항상 정규화형끼리 한다.

    원문의 줄바꿈·연속 공백은 소스(HTML/TEI)마다 다르고, 모델은 그것을 보존해
    인용하지 않는다. 어순·표현은 그대로이므로 정규화해도 grounding은 불변이다.
    """
    return _WS.sub(" ", text or "").strip()


def _root(block: Any) -> Any:
    """생성 계약의 ``Block``은 판별 유니온 RootModel이라 실제 블록은 ``.root``에 있다."""
    return getattr(block, "root", block)


def block_type(block: Any) -> str | None:
    value = getattr(_root(block), "type", None)
    if value is None:
        return None
    # StrEnum도 문자열로 통일한다(계약 enum과 직접 비교하기 위해).
    return str(getattr(value, "value", value))


def block_id(block: Any) -> str | None:
    value = getattr(_root(block), "id", None)
    return str(value) if value else None


def _labelled(root: Any) -> str:
    """라벨 + 캡션 — u1 ``block_text_parts``와 동일하게 **공백으로** 잇는다."""
    label = getattr(root, "anchorLabel", None) or ""
    caption = getattr(root, "caption", None) or ""
    return " ".join(part for part in (label, caption) if part)


def _table_rows(root: Any) -> list[str]:
    rows: list[str] = []
    for row in getattr(root, "rows", None) or []:
        cells = [getattr(cell, "text", "") or "" for cell in getattr(row, "cells", None) or []]
        if cells:
            rows.append(" | ".join(cells))
    return rows


def block_projection(block: Any) -> str:
    """한 블록의 투영. 프롬프트 표시와 게이트 대조가 공유하는 유일한 표현."""
    root = _root(block)
    kind = block_type(block)

    if kind in ("paragraph", "code"):
        return normalize(getattr(root, "text", ""))
    if kind == "formula":
        # latex이 1차 표현이고 crop 이미지는 렌더 폴백이다 — 인용 대상이 아니다.
        return normalize(getattr(root, "latex", None) or getattr(root, "latexOcr", None) or "")
    if kind == "list":
        raw_items = getattr(root, "items", None) or []
        items = [normalize(getattr(item, "text", "")) for item in raw_items]
        return "\n".join(item for item in items if item)
    if kind == "figure":
        return normalize(_labelled(root))
    if kind == "table":
        parts = [normalize(_labelled(root)), *(normalize(row) for row in _table_rows(root))]
        return "\n".join(part for part in parts if part)
    return ""


def section_title_projection(section: Any) -> str:
    return normalize(getattr(section, "title", ""))


def iter_blocks(doc_model: Any) -> list[tuple[str, str, str]]:
    """(block_id, anchor_type, projection) — 문서 순서. 투영이 빈 블록은 뺀다.

    투영이 비었다는 것은 인용할 텍스트가 없다는 뜻이므로(예: LaTeX 없는 수식),
    프롬프트에 실을 이유도 앵커로 허용할 이유도 없다.
    """
    out: list[tuple[str, str, str]] = []

    def walk(section: Any) -> None:
        for block in getattr(section, "blocks", None) or []:
            bid = block_id(block)
            kind = block_type(block)
            if not bid or kind not in ANCHOR_TYPES:
                continue
            text = block_projection(block)
            if text:
                out.append((bid, kind, text))
        for nested in getattr(section, "sections", None) or []:
            walk(nested)

    for section in getattr(doc_model, "sections", None) or []:
        walk(section)
    return out


def paper_projection(doc_model: Any) -> str:
    """논문 전체의 투영 — 섹션 제목 + 블록 투영을 문서 순서로 이은 것.

    ``DocModel.fullText``를 쓰지 않는다: fullText는 u1이 만든 별도 투영이라
    이 모듈의 규칙과 어긋날 수 있고, 어긋나면 v1과 같은 조용한 탈락이 재발한다.
    대조 대상은 **우리가 프롬프트에 실은 것**이어야 한다.
    """
    parts: list[str] = []

    def walk(section: Any) -> None:
        title = section_title_projection(section)
        if title:
            parts.append(title)
        for block in getattr(section, "blocks", None) or []:
            text = block_projection(block)
            if text:
                parts.append(text)
        for nested in getattr(section, "sections", None) or []:
            walk(nested)

    for section in getattr(doc_model, "sections", None) or []:
        walk(section)
    return "\n\n".join(parts)
