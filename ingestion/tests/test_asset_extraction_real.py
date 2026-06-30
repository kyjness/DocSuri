"""FR-17 real extraction tests (A — runs the actual hybrid machinery, no AWS).

Unlike ``test_assets.py`` (pure caption/finalize/normalize logic) and ``test_asset_wiring.py``
(orchestration gating with stubs), this exercises ``AssetExtractor`` end to end against real
inputs: a synthetic text-layer PDF (real ``pdfplumber`` caption detection + ``pypdfium2``
render + crop + WebP normalize) and a real e-print tarball (structured graphics path). No
network, no AWS, no committed third-party PDFs — fully deterministic and CI-safe.

Skipped when the ``assets`` extra isn't installed (pdfplumber/pypdfium2/Pillow).
"""

from __future__ import annotations

import io
import tarfile

import pytest

pytest.importorskip("pdfplumber")
pytest.importorskip("pypdfium2")
pytest.importorskip("PIL")

from PIL import Image  # noqa: E402

from docsuri_ingestion.asset_extraction import AssetExtractor  # noqa: E402
from docsuri_ingestion.domain.assets import FigureSpec  # noqa: E402
from docsuri_ingestion.domain.enums import AssetSourceMode, AssetType  # noqa: E402


# --------------------------------------------------------------------------- helpers
def _make_text_pdf(lines: list[tuple[str, float]]) -> bytes:
    """Minimal single-page (612x792) PDF with text lines at given y (PDF coords, from the
    bottom). Real text layer so pdfplumber extracts the lines and pypdfium2 can render."""
    parts = []
    for text, y in lines:
        t = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        parts.append(f"BT /F1 12 Tf 72 {y} Td ({t}) Tj ET")
    content = "\n".join(parts).encode("latin-1")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    buf = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(buf))
        buf += str(i).encode() + b" 0 obj\n" + body + b"\nendobj\n"
    xref_pos = len(buf)
    n = len(objs) + 1
    buf += b"xref\n0 " + str(n).encode() + b"\n0000000000 65535 f \n"
    for off in offsets:
        buf += f"{off:010d} 00000 n \n".encode()
    buf += b"trailer\n<< /Size " + str(n).encode() + b" /Root 1 0 R >>\n"
    buf += b"startxref\n" + str(xref_pos).encode() + b"\n%%EOF"
    return bytes(buf)


def _img_bytes(
    fmt: str, *, w: int = 48, h: int = 32, color: tuple[int, int, int] = (200, 30, 30)
) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (w, h), color).save(out, format=fmt)
    return out.getvalue()


def _eprint_tar(members: list[tuple[str, bytes]]) -> bytes:
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w") as tar:
        for name, data in members:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return out.getvalue()


def _is_webp(data: bytes) -> bool:
    return Image.open(io.BytesIO(data)).format == "WEBP"


# ----------------------------------------------------------------------- page-crop path
def test_page_crop_extracts_figure_and_table_from_real_pdf() -> None:
    pdf = _make_text_pdf(
        [("Figure 1: A demo figure caption", 700), ("Table 1: A demo table caption", 400)]
    )
    assets = AssetExtractor().extract(paper_id="2401.00001", version=1, pdf=pdf, eprint=None)

    by_type = {a.meta.type: a for a in assets}
    assert AssetType.FIGURE in by_type and AssetType.TABLE in by_type

    for asset in assets:
        m = asset.meta
        assert m.source_mode is AssetSourceMode.PAGE_CROP
        assert m.page_ref == 0
        assert m.bbox is not None and m.bbox[2] > m.bbox[0] and m.bbox[3] > m.bbox[1]
        assert m.ordinal == 0  # one of each type → contiguous from 0
        # Image is a real, re-encoded WebP (never the raw page bytes) — SEC/normalize.
        assert _is_webp(asset.image)

    assert by_type[AssetType.FIGURE].meta.caption.startswith("Figure 1")
    assert by_type[AssetType.TABLE].meta.caption.startswith("Table 1")


def test_uncaptioned_pdf_yields_no_assets() -> None:
    pdf = _make_text_pdf([("Just some body text with no caption", 700)])
    assets = AssetExtractor().extract(paper_id="p", version=1, pdf=pdf, eprint=None)
    assert assets == ()


# ---------------------------------------------------------------------- structured path
def test_structured_figures_from_eprint_tar() -> None:
    tar = _eprint_tar(
        [
            ("figures/fig1.png", _img_bytes("PNG")),
            ("notes.txt", b"not an image"),
            ("figures/fig2.jpg", _img_bytes("JPEG", color=(30, 30, 200))),
        ]
    )
    assets = AssetExtractor().extract(paper_id="2401.00002", version=1, pdf=None, eprint=tar)

    assert len(assets) == 2  # png + jpg; the .txt is ignored
    for asset in assets:
        assert asset.meta.type is AssetType.FIGURE
        assert asset.meta.source_mode is AssetSourceMode.STRUCTURED
        assert _is_webp(asset.image)  # re-encoded, original bytes never served


def test_structured_figures_align_to_docmodel_specs() -> None:
    """figure_specs (doc-model FigureBlocks, document order) pins each graphic's ordinal and
    excludes rasters no block references — so assetId matches the block that points at it."""
    # Document order: intro, method, results. Tarball filenames sort the OTHER way, and carry an
    # extra incidental raster (a logo) that no FigureBlock references.
    tar = _eprint_tar(
        [
            ("img/zeta_intro.png", _img_bytes("PNG", color=(255, 0, 0))),
            ("img/mu_method.png", _img_bytes("PNG", color=(0, 255, 0))),
            ("img/alpha_results.png", _img_bytes("PNG", color=(0, 0, 255))),
            ("logo.png", _img_bytes("PNG", color=(9, 9, 9))),
        ]
    )
    figure_specs = [
        FigureSpec(src="zeta_intro.png", label="Figure 1"),
        FigureSpec(src="mu_method.png", label="Figure 2"),
        FigureSpec(src="alpha_results.png", label="Figure 3"),
    ]
    assets = AssetExtractor().extract(
        paper_id="2401.00003", version=1, pdf=None, eprint=tar, figure_specs=figure_specs
    )

    figures = [a for a in assets if a.meta.type is AssetType.FIGURE]
    assert len(figures) == 3  # the unreferenced logo.png is excluded
    by_ordinal = {a.meta.ordinal: a.meta.asset_id for a in figures}
    # Ordinals follow document order, not filename order.
    assert by_ordinal == {
        0: "2401.00003:v1:figure:0",
        1: "2401.00003:v1:figure:1",
        2: "2401.00003:v1:figure:2",
    }


def test_structured_figures_stem_match_skips_undecodable_source() -> None:
    """An <img src> that matches only a vector source (undecodable) yields no structured asset
    for that block — it degrades to caption/page-crop rather than a wrong image."""
    tar = _eprint_tar(
        [
            ("fig1.png", _img_bytes("PNG")),
            ("fig2.pdf", b"%PDF-1.4 not a real raster"),  # vector source, can't normalize
        ]
    )
    assets = AssetExtractor().extract(
        paper_id="p",
        version=1,
        pdf=None,
        eprint=tar,
        figure_specs=[FigureSpec(src="fig1.png", label="Figure 1"),
                      FigureSpec(src="fig2.png", label="Figure 2")],
    )
    figures = [a for a in assets if a.meta.type is AssetType.FIGURE]
    assert [a.meta.ordinal for a in figures] == [0]  # only fig1 resolved; fig2 left for fallback


def test_unmatched_figure_filled_by_pagecrop_via_label_number() -> None:
    """A figure with no e-print raster (vector source) is filled by a PDF page-crop matched on its
    label NUMBER, landing on the right ordinal alongside the structured figure (mixed paper)."""
    tar = _eprint_tar([("diagram.png", _img_bytes("PNG"))])  # only figure 1 has a raster
    pdf = _make_text_pdf([("Figure 2: a vector plot rendered by LaTeX", 700)])
    specs = [
        FigureSpec(src="diagram.png", label="Figure 1"),  # structured
        FigureSpec(src="x2.png", label="Figure 2"),  # no raster → page-crop by number 2
    ]
    assets = AssetExtractor().extract(
        paper_id="p", version=1, pdf=pdf, eprint=tar, figure_specs=specs
    )
    figs = {a.meta.ordinal: a.meta.source_mode for a in assets if a.meta.type is AssetType.FIGURE}
    assert figs == {
        0: AssetSourceMode.STRUCTURED,  # figure 1 from e-print
        1: AssetSourceMode.PAGE_CROP,  # figure 2 filled from the PDF caption "Figure 2:"
    }


# ------------------------------------------------------------ hybrid preference (Q2=C)
def test_eprint_figures_preferred_pdf_tables_when_both_present() -> None:
    """e-print structured graphics win for figures; tables still come from PDF page-crop."""
    tar = _eprint_tar([("fig1.png", _img_bytes("PNG"))])
    pdf = _make_text_pdf(
        [("Figure 1: PDF figure caption", 700), ("Table 1: PDF table caption", 400)]
    )
    assets = AssetExtractor().extract(paper_id="p", version=1, pdf=pdf, eprint=tar)

    figures = [a for a in assets if a.meta.type is AssetType.FIGURE]
    tables = [a for a in assets if a.meta.type is AssetType.TABLE]
    assert figures and all(a.meta.source_mode is AssetSourceMode.STRUCTURED for a in figures)
    assert tables and all(a.meta.source_mode is AssetSourceMode.PAGE_CROP for a in tables)


# --------------------------------------------------------- decompression-bomb guard (TD-15)
def test_structured_figure_over_cap_is_skipped(monkeypatch) -> None:
    """An e-print image member larger than the per-image cap is dropped, never decoded — the
    ported #237 zip-bomb guard. Removing the cap re-emits it and fails this test."""
    import docsuri_ingestion.asset_extraction as ae

    monkeypatch.setattr(ae, "_MAX_IMAGE_BYTES", 50)  # any real PNG exceeds this
    tar = _eprint_tar([("figures/big.png", _img_bytes("PNG"))])
    assert AssetExtractor().extract(paper_id="p", version=1, pdf=None, eprint=tar) == ()
