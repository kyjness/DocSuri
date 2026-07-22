"""Formula OCR: which recovered LaTeX is stored, and where it is allowed to appear.

The model is a heavy optional extra, so the decision logic is driven with a fake reader. What
matters here is that an approximation never displaces source-accurate LaTeX and never becomes a
render source — it exists so the PDF path's equations can be searched at all.
"""

from __future__ import annotations

from docsuri_ingestion.docmodel.formula_ocr import apply_ocr, formula_crops
from docsuri_ingestion.domain.assets import AssetCropSpec
from docsuri_ingestion.domain.enums import AssetType

_ASSET = "p:v1:formula:0"


def _spec(kind: AssetType, asset_id: str) -> AssetCropSpec:
    return AssetCropSpec(
        asset_id=asset_id, type=kind, ordinal=0, page=2, bbox=(0.0, 0.0, 10.0, 10.0)
    )


def _doc(block: dict) -> dict:
    return {"sections": [{"id": "s1", "blocks": [block]}]}


def _image_only(asset_id: str = _ASSET) -> dict:
    return {
        "id": "s1.eq1",
        "type": "formula",
        "display": True,
        "assetRef": {"assetId": asset_id, "type": "formula", "ordinal": 0},
    }


def test_only_formula_crops_are_read() -> None:
    crops = [_spec(AssetType.FORMULA, _ASSET), _spec(AssetType.TABLE, "p:v1:table:0")]

    assert formula_crops(crops) == [crops[0]]


def test_recovered_latex_is_stored_beside_the_image_not_as_it() -> None:
    """The crop stays the render source: ``latex`` is what KaTeX draws, and a mis-read equation
    must never be displayed as the paper's own."""
    doc = _doc(_image_only())

    assert apply_ocr(doc, {_ASSET: b"img"}, lambda image: r"E = mc^{2}") == 1
    block = doc["sections"][0]["blocks"][0]
    assert block["latexOcr"] == r"E = mc^{2}"
    assert "latex" not in block
    assert block["assetRef"]["assetId"] == _ASSET


def test_source_latex_is_never_overwritten() -> None:
    """An HTML-path formula has real LaTeX from the source markup; an approximation of a picture
    has nothing to add to it."""
    block = {"id": "s1.eq1", "type": "formula", "latex": r"\alpha + \beta"}
    doc = _doc(block)

    assert apply_ocr(doc, {_ASSET: b"img"}, lambda image: r"a + b") == 0
    assert doc["sections"][0]["blocks"][0]["latex"] == r"\alpha + \beta"


def test_broken_output_is_dropped() -> None:
    """Only obviously unusable output is refused — unbalanced braces, or a transcription with no
    maths in it at all, which is the model reading a caption rather than an equation."""
    for recovered in (r"\frac{a}{b", "Figure 3 shows the result", "", None):
        doc = _doc(_image_only())
        assert apply_ocr(doc, {_ASSET: b"img"}, lambda image, r=recovered: r) == 0
        assert "latexOcr" not in doc["sections"][0]["blocks"][0]


def test_a_formula_without_its_crop_is_left_alone() -> None:
    doc = _doc(_image_only("p:v1:formula:9"))

    assert apply_ocr(doc, {_ASSET: b"img"}, lambda image: r"E = mc^{2}") == 0
