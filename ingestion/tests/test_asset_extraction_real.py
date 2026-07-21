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
def _make_text_pdf(
    lines: list[tuple],
    rects: list[tuple[float, float, float, float]] | None = None,
) -> bytes:
    """Minimal single-page (612x792) PDF with text lines at given y (PDF coords, from the
    bottom). Real text layer so pdfplumber extracts the lines and pypdfium2 can render.

    Each line is ``(text, y)`` or ``(text, y, x)`` — x defaults to 72 (left margin); pass an x to
    place a caption in the right column when testing two-column layout.

    ``rects`` are filled rectangles ``(x0, y0, x1, y1)`` in the same bottom-origin PDF coords —
    real vector primitives so ``pdfplumber`` reports graphic content (a figure/table's plot area),
    which the crop's content-gate requires. Without them a caption anchors no graphic and is
    dropped as a body cross-reference."""
    parts = []
    for x0, y0, x1, y1 in rects or []:
        parts.append(f"0.8 0.1 0.1 rg {x0} {y0} {x1 - x0} {y1 - y0} re f")
    for line in lines:
        text, y = line[0], line[1]
        x = line[2] if len(line) > 2 else 72
        t = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        parts.append(f"BT /F1 12 Tf {x} {y} Td ({t}) Tj ET")
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
        [("Figure 1: A demo figure caption", 700), ("Table 1: A demo table caption", 400)],
        rects=[
            (100, 720, 300, 780),  # figure plot area, above its caption
            (320, 720, 520, 780),
            (100, 320, 520, 345),  # table rules, below its caption
            (100, 355, 520, 380),
        ],
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


def test_body_cross_reference_caption_is_not_cropped() -> None:
    """A body sentence that merely opens with "Table 1. …" (a cross-reference, no table below it)
    must NOT become a garbage crop of the surrounding prose — the content-gate drops it."""
    pdf = _make_text_pdf(
        [
            ("Table 1. For both models we use the hyperparameters listed below.", 700),
            ("Results. We experimented with multiple combinations of models.", 660),
        ]
        # no rects: nothing graphical anchors the "Table 1." line
    )
    assets = AssetExtractor().extract(paper_id="p", version=1, pdf=pdf, eprint=None)
    assert assets == ()


def test_two_figures_on_one_page_do_not_straddle() -> None:
    """Two stacked figures on one page each crop to their OWN plot area — the earlier bug cropped
    a fixed band that swept the neighbouring figure and the intervening caption into one image."""
    pdf = _make_text_pdf(
        [("Figure 1: top figure", 640), ("Figure 2: bottom figure", 300)],
        rects=[
            (100, 660, 290, 740),  # figure 1 plot (2 panels), above caption 1 (y=640)
            (310, 660, 500, 740),
            (100, 320, 290, 400),  # figure 2 plot (2 panels), above caption 2 (y=300)
            (310, 320, 500, 400),
        ],
    )
    assets = AssetExtractor().extract(paper_id="p", version=1, pdf=pdf, eprint=None)
    figs = sorted(
        (a for a in assets if a.meta.type is AssetType.FIGURE), key=lambda a: a.meta.bbox[1]
    )
    assert len(figs) == 2
    # pdfplumber top-origin: figure 1's crop (near page top) ends above figure 2's crop begins —
    # the two bboxes do not overlap vertically, so neither swept in the other figure.
    assert figs[0].meta.bbox[3] < figs[1].meta.bbox[1]
    # and figure 2's crop starts well below the page top (it did not sweep up to figure 1).
    assert figs[1].meta.bbox[1] > 200


def test_table_then_figure_on_one_page_do_not_cross_assign() -> None:
    """A table (rules below its caption) followed by a figure (plot above its caption) each crop
    only their own content — nearest-content-side assignment keeps the table's rules off the figure
    crop even though the figure caption is the nearer caption line by raw distance."""
    pdf = _make_text_pdf(
        [("Table 1: specs", 748), ("Figure 1: a plot", 372)],
        rects=[
            (100, 690, 500, 700),  # table rule 1, BELOW the table caption (y=748)
            (100, 660, 500, 670),  # table rule 2
            (110, 400, 500, 500),  # figure panel 1, ABOVE the figure caption (y=372)
            (110, 510, 500, 560),  # figure panel 2
        ],
    )
    assets = AssetExtractor().extract(paper_id="p", version=1, pdf=pdf, eprint=None)
    tables = [a for a in assets if a.meta.type is AssetType.TABLE]
    figs = [a for a in assets if a.meta.type is AssetType.FIGURE]
    assert len(tables) == 1 and len(figs) == 1
    # top-origin: the table crop sits entirely above the figure crop (no cross-assignment).
    assert tables[0].meta.bbox[3] < figs[0].meta.bbox[1]


def test_two_column_captions_keep_their_own_column() -> None:
    """Two figure captions at the same height in different columns each claim only their column's
    primitives (x-overlap preference), so neither crop spans both columns."""
    # Different y (pdfplumber merges same-top text into one line); the column split is decided by
    # x-overlap, not height, so the y offset is immaterial to what is under test.
    pdf = _make_text_pdf(
        [("Figure 1: left", 300, 72), ("Figure 2: right", 260, 330)],
        rects=[
            (72, 340, 250, 470),  # left-column figure (2 prims)
            (72, 340, 180, 400),
            (330, 340, 520, 470),  # right-column figure (2 prims)
            (400, 340, 520, 400),
        ],
    )
    assets = AssetExtractor().extract(paper_id="p", version=1, pdf=pdf, eprint=None)
    figs = sorted(
        (a for a in assets if a.meta.type is AssetType.FIGURE), key=lambda a: a.meta.bbox[0]
    )
    assert len(figs) == 2
    page_mid = 612 / 2
    left, right = figs
    # Left crop stays left of the mid-line; right crop stays right — neither spans both columns.
    assert left.meta.bbox[2] < page_mid
    assert right.meta.bbox[0] > page_mid


def test_single_large_primitive_is_a_figure_but_a_thin_rule_is_not() -> None:
    """A lone but LARGE vector primitive (a one-path diagram) is accepted; a lone thin rule (a
    body cross-reference underline) is not — the _accept_graphics size gate distinguishes them."""
    big = _make_text_pdf(
        [("Figure 1: one-path schematic", 300)],
        rects=[(80, 340, 530, 600)],  # single primitive, wide AND tall
    )
    assets = AssetExtractor().extract(paper_id="p", version=1, pdf=big, eprint=None)
    assert [a.meta.type for a in assets] == [AssetType.FIGURE]

    thin = _make_text_pdf(
        [("Figure 2: see the line below", 300)],
        rects=[(80, 305, 530, 307)],  # single 2pt-tall rule → not a figure
    )
    assert AssetExtractor().extract(paper_id="p", version=1, pdf=thin, eprint=None) == ()


def test_caption_without_a_delimiter_is_cropped_but_a_cross_reference_is_not() -> None:
    """Some journals punctuate nothing: "Fig. 1 The configuration of …". Requiring a delimiter
    lost every crop on such a paper. A lowercase continuation still marks a body sentence."""
    pdf = _make_text_pdf(
        [("Fig. 1 The configuration of the vehicle", 640)],
        rects=[(100, 660, 290, 740), (310, 660, 500, 740)],
    )
    assets = AssetExtractor().extract(paper_id="p", version=1, pdf=pdf, eprint=None)
    assert [a.meta.type for a in assets] == [AssetType.FIGURE]

    cross_ref = _make_text_pdf(
        [("Figure 1 shows the configuration of the vehicle", 640)],
        rects=[(100, 660, 290, 740), (310, 660, 500, 740)],
    )
    assert AssetExtractor().extract(paper_id="p", version=1, pdf=cross_ref, eprint=None) == ()


def _two_column_body(rows: int, *, top: float, step: float = 16) -> list[tuple]:
    """Body text in two columns — the layout that makes ``extract_text_lines`` merge a row's two
    columns into one line, and that a column-start caption is recognised against."""
    lines: list[tuple] = []
    for i in range(rows):
        y = top - i * step
        lines.append(("left column body text here", y, 72))
        lines.append(("right column body text here", y, 330))
    return lines


def test_caption_in_the_right_column_of_a_merged_line_is_still_found() -> None:
    """On a two-column page pdfplumber merges both columns of a row into ONE line, so the right
    column's caption does not START it. The caption is recovered from its column-start x, and the
    crop stays inside that column."""
    pdf = _make_text_pdf(
        _two_column_body(10, top=700)
        + [("left column text continues", 540, 72), ("Figure 1: right column", 540, 330)],
        rects=[(330, 560, 520, 660), (340, 570, 500, 640)],  # right-column plot, above the caption
    )
    assets = AssetExtractor().extract(paper_id="p", version=1, pdf=pdf, eprint=None)

    assert [a.meta.type for a in assets] == [AssetType.FIGURE]
    assert assets[0].meta.caption.startswith("Figure 1")
    assert assets[0].meta.bbox[0] > 300, "the crop leaked into the left column"


def test_caption_stops_at_the_next_column_and_does_not_absorb_it() -> None:
    """A left-column caption merged with the neighbouring column's text must keep only its own
    column: absorbing the other one stretched its x-span across the page, and the crop with it."""
    pdf = _make_text_pdf(
        _two_column_body(10, top=700)
        + [("Table 1: left column results", 540, 72), ("Diagram label text", 540, 330)],
        rects=[(72, 440, 250, 520), (72, 430, 250, 434)],  # the table's rules, below its caption
    )
    assets = AssetExtractor().extract(paper_id="p", version=1, pdf=pdf, eprint=None)

    assert [a.meta.type for a in assets] == [AssetType.TABLE]
    assert assets[0].meta.caption == "Table 1: left column results"
    assert assets[0].meta.bbox[2] < 300, "the crop absorbed the neighbouring column"


def test_a_stray_rule_far_from_the_caption_is_not_pulled_into_the_crop() -> None:
    """A caption is the nearest one for everything on its side of the page, including a rule at the
    far edge that belongs to nothing. Only the contiguous band around the caption is cropped."""
    pdf = _make_text_pdf(
        [("Table 1: results", 700)],
        rects=[
            (100, 640, 500, 660),  # the table's own rules, just below the caption
            (100, 600, 500, 620),
            (100, 80, 500, 84),  # a rule at the bottom of the page, unrelated
        ],
    )
    assets = AssetExtractor().extract(paper_id="p", version=1, pdf=pdf, eprint=None)

    assert [a.meta.type for a in assets] == [AssetType.TABLE]
    # top-origin: the crop stops well above the stray rule (792 - 84 = 708).
    assert assets[0].meta.bbox[3] < 400


def test_mid_sentence_cross_reference_is_not_read_as_a_column_caption() -> None:
    """Recovering mid-line captions must not admit the body cross-references that sit INSIDE prose.
    Single-column prose flows through the strip left of "Figure 1.", so it is not a column start."""
    pdf = _make_text_pdf(
        [
            ("Body prose that runs the full width of this single column page", 700 - i * 16, 72)
            for i in range(10)
        ]
        + [("Results are strongest here as shown in Figure 1. We now turn to costs", 520, 72)],
        rects=[(100, 560, 500, 680)],  # a graphic the false caption would have claimed
    )
    assert AssetExtractor().extract(paper_id="p", version=1, pdf=pdf, eprint=None) == ()


def test_table_captioned_under_its_table_is_cropped() -> None:
    """Journals differ on where a table's caption goes; this one prints it UNDER the table, which a
    below-the-caption-only rule dropped entirely."""
    pdf = _make_text_pdf(
        [("Table 1: caption printed under its table", 600)],
        rects=[(100, 620, 500, 640), (100, 660, 500, 680)],  # table rules ABOVE the caption
    )
    assets = AssetExtractor().extract(paper_id="p", version=1, pdf=pdf, eprint=None)

    assert [a.meta.type for a in assets] == [AssetType.TABLE]
    # top-origin: the crop sits entirely above the caption line (792 - 600 = 192).
    assert assets[0].meta.bbox[3] < 192


def test_table_caption_takes_only_the_nearer_side() -> None:
    """A table caption with primitives on BOTH sides keeps the nearer side only — a crop spanning
    its own caption is wrong whichever way the paper prints it."""
    pdf = _make_text_pdf(
        [("Table 1: caption printed under its table", 600)],
        rects=[
            (100, 620, 500, 640),  # its own table, just above the caption
            (100, 660, 500, 680),
            (100, 200, 500, 220),  # a far-below graphic that must not join the crop
            (100, 240, 500, 260),
        ],
    )
    assets = AssetExtractor().extract(paper_id="p", version=1, pdf=pdf, eprint=None)

    assert [a.meta.type for a in assets] == [AssetType.TABLE]
    assert assets[0].meta.bbox[3] < 192  # top-origin: nothing from below the caption came along


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
    pdf = _make_text_pdf(
        [("Figure 2: a vector plot rendered by LaTeX", 700)],
        rects=[(100, 720, 300, 780), (320, 720, 520, 780)],  # the vector plot above its caption
    )
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
        [("Figure 1: PDF figure caption", 700), ("Table 1: PDF table caption", 400)],
        rects=[(100, 320, 520, 345), (100, 355, 520, 380)],  # table rules below the table caption
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
