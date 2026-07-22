"""Read approximate LaTeX back out of the formula images on the PDF/GROBID path.

There, a display equation has no LaTeX at all — GROBID hands back OCR'd glyph soup, so the parser
degrades the equation to a page-crop image (TD-12/3a). That is faithful to look at and invisible
to everything else: search cannot match it and an agent cannot quote it.

An OCR model can recover LaTeX close enough to search on but not close enough to trust as the
paper's own equation, so the result lands in ``latexOcr`` — indexed, never rendered. The crop
stays what the reader sees. Only obviously broken output is dropped (unbalanced braces, a bare
transcription with no math in it), because a stricter gate here would need the very LaTeX we do
not have.

Pure given the crops and what the reader returned (P7).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence

from docsuri_ingestion.docmodel.parser import iter_blocks
from docsuri_ingestion.domain.assets import AssetCropSpec

# A recovered string has to look like maths, not like a caption the model transcribed instead.
_MATH_TOKEN_RE = re.compile(r"\\[A-Za-z]+|[=+\-*/^_<>]")
_MAX_LATEX_CHARS = 2000

ReadLatex = Callable[[bytes], "str | None"]


def formula_crops(crops: Sequence[AssetCropSpec]) -> list[AssetCropSpec]:
    """The crop specs whose blocks are image-only formulas — the ones worth reading back."""
    return [spec for spec in crops if spec.type.value == "formula"]


def apply_ocr(doc: dict, images: dict[str, bytes], read: ReadLatex) -> int:
    """Fill ``latexOcr`` on image-only formulas from their crops. Returns how many were read.

    A formula that already carries real ``latex`` (the HTML path) is left alone — an approximation
    must never displace a source-accurate equation.
    """
    filled = 0
    for block in iter_blocks(doc, "formula"):
        if block.get("latex") or block.get("latexOcr"):
            continue
        ref = block.get("assetRef") or {}
        image = images.get(ref.get("assetId", ""))
        if not image:
            continue
        latex = _usable(read(image))
        if latex is None:
            continue
        block["latexOcr"] = latex
        filled += 1
    return filled


def _usable(latex: str | None) -> str | None:
    """Whether recovered LaTeX is worth storing: balanced, bounded, and actually mathematical."""
    if not latex:
        return None
    text = latex.strip()
    if not text or len(text) > _MAX_LATEX_CHARS:
        return None
    if text.count("{") != text.count("}"):
        return None
    if not _MATH_TOKEN_RE.search(text):
        return None
    return text
