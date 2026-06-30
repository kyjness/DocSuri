from __future__ import annotations

import io

import pytest
from hypothesis import given
from hypothesis import strategies as st

from docsuri_ingestion.asset_extraction import (
    ImageNormalizer,
    caption_kind,
    crop_assets_from_specs,
    finalize_assets,
)
from docsuri_ingestion.domain.assets import RawAssetCandidate, asset_id
from docsuri_ingestion.domain.enums import AssetSourceMode, AssetType


def test_crop_assets_from_specs_empty_is_noop_without_pdfium() -> None:
    # No specs -> short-circuit before importing the (env-gated) render backend.
    assert crop_assets_from_specs(b"%PDF", [], paper_id="p", version=1) == ()

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
