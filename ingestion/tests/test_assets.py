from __future__ import annotations

import io

import pytest
from hypothesis import given
from hypothesis import strategies as st

from docsuri_ingestion.asset_extraction import (
    ImageNormalizer,
    caption_kind,
    crop_assets_from_specs,
    crop_bbox_for,
    finalize_assets,
)
from docsuri_ingestion.domain.assets import AssetCropSpec, RawAssetCandidate, asset_id
from docsuri_ingestion.domain.enums import AssetSourceMode, AssetType


def test_crop_assets_from_specs_empty_is_noop_without_pdfium() -> None:
    # No specs -> short-circuit before importing the (env-gated) render backend.
    assert crop_assets_from_specs(b"%PDF", [], paper_id="p", version=1) == ()


# ------------------------------------------------------- crop_bbox_for (graphic recovery)
#
# GROBID reports a <graphic> for raster figures only, so a vector figure arrives with coordinates
# covering nothing but its caption's text lines. These pin when the caption-only bbox may be
# widened to the graphic above it — every "unchanged" case is a guard against a crop that reaches
# up the page and swallows content that is not part of the figure.

_CAPTION = (100.0, 300.0, 400.0, 320.0)  # a two-line caption strip, top-left origin
_PLOT_ABOVE = (110.0, 150.0, 390.0, 295.0)  # the graphic it belongs to, 5pt higher up


def _spec(bbox, asset_type=AssetType.FIGURE) -> AssetCropSpec:
    return AssetCropSpec(
        asset_id="p:v1:x:0", type=asset_type, ordinal=0, page=1, bbox=bbox, caption="c"
    )


def test_caption_only_figure_grows_to_include_the_graphic_above_it() -> None:
    assert crop_bbox_for(_spec(_CAPTION), [_PLOT_ABOVE]) == (100.0, 150.0, 400.0, 320.0)


def test_a_table_is_never_widened_even_with_a_graphic_directly_above_it() -> None:
    """A table's coordinates are its body, so there is nothing missing to go looking for."""
    spec = _spec(_CAPTION, AssetType.TABLE)
    assert crop_bbox_for(spec, [_PLOT_ABOVE]) == _CAPTION


def test_a_formula_is_never_widened() -> None:
    spec = _spec(_CAPTION, AssetType.FORMULA)
    assert crop_bbox_for(spec, [_PLOT_ABOVE]) == _CAPTION


def test_a_bbox_that_already_covers_its_graphic_is_left_alone() -> None:
    """GROBID located this figure itself; re-deriving the region could only make it worse."""
    whole = (100.0, 140.0, 400.0, 320.0)  # contains _PLOT_ABOVE outright
    assert crop_bbox_for(_spec(whole), [_PLOT_ABOVE]) == whole


def test_a_caption_tucked_under_its_graphic_still_counts_as_caption_only() -> None:
    """A hairline overlap is not coverage — real captions routinely start a point or two under
    the plot above them, and reading that as 'already covers a graphic' would leave exactly the
    figures this recovery exists for uncorrected."""
    tucked = (100.0, 293.0, 400.0, 320.0)  # overlaps _PLOT_ABOVE by 2pt of its 145pt height
    assert crop_bbox_for(_spec(tucked), [_PLOT_ABOVE])[1] == 150.0


def test_a_distant_graphic_is_not_pulled_down_into_the_crop() -> None:
    """Beyond half an inch the graphic belongs to something else on the page."""
    far = (110.0, 100.0, 390.0, 200.0)  # bottom 100pt above the caption
    assert crop_bbox_for(_spec(_CAPTION), [far]) == _CAPTION


def test_a_graphic_in_the_other_column_is_not_pulled_in() -> None:
    other_column = (420.0, 150.0, 560.0, 295.0)  # no horizontal overlap with the caption
    assert crop_bbox_for(_spec(_CAPTION), [other_column]) == _CAPTION


def test_only_the_nearest_graphic_is_merged() -> None:
    """Unioning every candidate would merge stacked figures and the text between them.

    Both graphics here are close enough to qualify, so the choice between them is what is being
    pinned: the crop must stop at the lower one rather than stretching over both.
    """
    lower = (110.0, 275.0, 390.0, 295.0)  # 5pt above the caption
    upper = (110.0, 150.0, 390.0, 270.0)  # 30pt above the caption — also within the bound
    assert crop_bbox_for(_spec(_CAPTION), [upper, lower]) == (100.0, 275.0, 400.0, 320.0)


def test_a_page_with_no_graphics_leaves_the_caption_crop_untouched() -> None:
    """A text block GROBID mislabelled as a figure lands here: nothing to find, nothing lost."""
    assert crop_bbox_for(_spec(_CAPTION), []) == _CAPTION

# ---------------------------------------------------------------- caption_kind


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Figure 1: overview", AssetType.FIGURE),
        ("Fig. 2: results", AssetType.FIGURE),
        ("Table 3 — metrics", AssetType.TABLE),
        ("Figure1:Ourreparametrization", AssetType.FIGURE),  # no-space PDF extraction
        ("Figure 4. Caption with a period delimiter", AssetType.FIGURE),
        ("  table 10: latency ", AssetType.TABLE),
        ("Table 6 shows that, surprisingly, LoRA", None),  # body sentence, NOT a caption
        ("As shown in Figure", None),  # no number
        ("Figure 1 overview", None),  # no caption delimiter after the number
        ("Section 2", None),
        ("", None),
    ],
)
def test_caption_kind(text: str, expected: AssetType | None) -> None:
    assert caption_kind(text) == expected


def test_caption_kind_and_number() -> None:
    from docsuri_ingestion.asset_extraction import caption_kind_and_number

    assert caption_kind_and_number("Figure 3: subspace similarity") == (AssetType.FIGURE, 3)
    assert caption_kind_and_number("Table12:hyperparameters") == (AssetType.TABLE, 12)
    assert caption_kind_and_number("Table 6 shows that") is None


# ---------------------------------------------------------------- finalize_assets (P7)


def _candidate(kind: AssetType, page: int, y: float, x: float = 0.0) -> RawAssetCandidate:
    return RawAssetCandidate(
        type=kind,
        image=b"img",
        source_mode=AssetSourceMode.PAGE_CROP,
        page=page,
        y=y,
        x=x,
    )


def test_finalize_orders_by_page_y_x_and_numbers_per_type() -> None:
    cands = [
        _candidate(AssetType.TABLE, page=1, y=10),
        _candidate(AssetType.FIGURE, page=0, y=50),
        _candidate(AssetType.FIGURE, page=0, y=10),
    ]
    assets = finalize_assets("2401.00001", 1, cands)
    # ordered: (p0,y10 fig), (p0,y50 fig), (p1,y10 table)
    assert [a.meta.type for a in assets] == [AssetType.FIGURE, AssetType.FIGURE, AssetType.TABLE]
    assert [a.meta.ordinal for a in assets] == [0, 1, 0]  # ordinals independent per type
    assert assets[0].meta.asset_id == asset_id("2401.00001", 1, AssetType.FIGURE, 0)
    assert assets[2].meta.asset_id == asset_id("2401.00001", 1, AssetType.TABLE, 0)


def test_finalize_is_deterministic() -> None:
    cands = [_candidate(AssetType.FIGURE, 0, 10), _candidate(AssetType.TABLE, 0, 20)]
    assert finalize_assets("p", 1, cands) == finalize_assets("p", 1, cands)


@given(
    st.lists(
        st.tuples(
            st.sampled_from([AssetType.FIGURE, AssetType.TABLE]),
            st.integers(min_value=0, max_value=5),
            st.floats(min_value=0, max_value=1000, allow_nan=False),
        ),
        max_size=12,
    )
)
def test_pbt_p7_finalize_deterministic_and_contiguous_ordinals(raw) -> None:
    cands = [_candidate(k, p, y) for (k, p, y) in raw]
    first = finalize_assets("2401.00002", 1, cands)
    second = finalize_assets("2401.00002", 1, cands)
    assert first == second  # determinism (P7)
    for kind in (AssetType.FIGURE, AssetType.TABLE):
        ordinals = [a.meta.ordinal for a in first if a.meta.type is kind]
        assert ordinals == list(range(len(ordinals)))  # contiguous per type
        ids = [a.meta.asset_id for a in first if a.meta.type is kind]
        assert len(ids) == len(set(ids))  # unique


# ---------------------------------------------------- caption matching (asset id alignment)


def _fig(caption: str, x: float, page: int = 0) -> RawAssetCandidate:
    return RawAssetCandidate(
        type=AssetType.FIGURE,
        image=b"img",
        source_mode=AssetSourceMode.PAGE_CROP,
        caption=caption,
        page=page,
        x=x,
    )


def test_no_anchors_keeps_positional_legacy_behavior() -> None:
    cands = [_fig("Figure 2: b", x=0.0), _fig("Figure 1: a", x=1.0)]
    assert [a.meta.ordinal for a in finalize_assets("p", 1, cands)] == [0, 1]


# ---------------------------------------------------------------- ImageNormalizer


def _png(width: int, height: int) -> bytes:
    Image = pytest.importorskip("PIL.Image")
    buf = io.BytesIO()
    Image.new("RGB", (width, height), (10, 20, 30)).save(buf, format="PNG")
    return buf.getvalue()


def test_normalizer_reencodes_to_webp_and_downscales() -> None:
    pytest.importorskip("PIL")
    out = ImageNormalizer(max_longest_side=64).normalize(_png(200, 100))
    assert out is not None and out[:4] == b"RIFF"  # WebP container magic
    from PIL import Image

    with Image.open(io.BytesIO(out)) as img:
        assert max(img.size) == 64  # downscaled to the cap


def test_normalizer_rejects_decompression_bomb() -> None:
    pytest.importorskip("PIL")
    # 100x100 = 10_000 px > max_pixels(100) → rejected.
    assert ImageNormalizer(max_pixels=100).normalize(_png(100, 100)) is None


def test_normalizer_rejects_undecodable_and_empty() -> None:
    pytest.importorskip("PIL")
    norm = ImageNormalizer()
    assert norm.normalize(b"") is None
    assert norm.normalize(b"not an image") is None


def test_a_decorative_hairline_does_not_count_as_a_graphic() -> None:
    """A QED tombstone's sides are 0.5pt-thick form objects; latching onto one drags in text."""
    qed_side = (380.0, 288.0, 386.0, 288.5)  # 6.0 x 0.5pt, directly above the caption
    assert crop_bbox_for(_spec(_CAPTION), [qed_side]) == _CAPTION


def test_a_graphic_just_over_the_area_floor_still_counts() -> None:
    """The floor must separate glyphs from figures, not reject small real plots."""
    small_plot = (110.0, 255.0, 250.0, 295.0)  # 140 x 40pt = 5,600pt²
    assert crop_bbox_for(_spec(_CAPTION), [small_plot])[1] == 255.0


def test_a_crop_too_small_to_hold_anything_is_not_rendered() -> None:
    """GROBID sometimes emits a formula element for a stray glyph — a lone ``)``.

    Cropping it faithfully produces a 4x10pt image of one bracket, which is stored, referenced by
    a block and shown to a reader as if it were the equation. Below this floor a crop cannot carry
    a formula or a figure at all, so no asset is better than a misleading one. The separation is
    not a hair: across the three TEI fixtures the offenders are 35-42pt² and the smallest real crop
    is over 600pt². Assets are best-effort (BR-27), so a skipped one is an already-handled state.
    """
    from docsuri_ingestion.asset_extraction import crop_is_renderable

    assert not crop_is_renderable((296.3, 310.4, 300.8, 320.0))  # the real ')' from 2607.16138
    assert not crop_is_renderable((10.0, 10.0, 14.1, 18.6))
    assert crop_is_renderable((110.8, 304.1, 499.4, 324.8))  # a caption strip is still renderable
    assert crop_is_renderable((100.0, 100.0, 130.0, 120.0))  # 600pt², the small end of real crops
