"""Asset-stage signals — what the reader actually SEES, not what the doc-model says.

Every other audit in this directory stops at the doc-model. That left the whole image layer
unmeasured, and it is where the defects hide: a figure block can carry a caption, an ``assetRef``
and a healthy body-coverage ratio while the stored image is 20% of the figure (arXiv:2608.07458
Figure 1, found by eye because nothing measured the rectangle).

Sits at ``_pipeline.py``'s layer, NOT ``_common.py``'s: these signals read package internals
(``_graphic_boxes``) and run the real crop stage, so they cannot be the yardstick of an A/B sweep
across two checkouts the way ``_common.py`` is. Read them as "what did this checkout deliver".
"""

from __future__ import annotations

from contextlib import suppress
from typing import Any

# A vertical gap wider than this between two graphic objects means they are not the same picture.
# Deliberately generous: the point is to bound a run of stacked panels from below, and a figure's
# own panels sit far closer (16.9pt measured on arXiv:2608.07458). See ``_graphic_cluster``.
_CLUSTER_GAP_PT = 40.0
# Under this share of its graphic cluster, a rendered figure crop is showing part of the figure.
# Measured over 25 recovery-eligible figures in 4 real papers, the ratio is bimodal with nothing
# in between: the one defective crop scored 0.20 and every sound one scored 1.00.
_PARTIAL_MAX_COVER = 0.75
# Two crops overlapping by more than this share of the smaller one are worth a look. NOT a defect
# on its own: measured on the fixtures, this fires on legitimate nesting too — a parent figure and
# the sub-panels GROBID also gave specs for (2607.16138 figure:0 against figure:7/8) sit inside one
# another by construction. Reported for drill-down, the way this directory already treats a listing
# that landed as a paragraph.
_OVERLAP_MAX_SHARE = 0.5
# Near-identical boxes are a different matter and unambiguous: two assets picturing the SAME region
# means one image is stored twice and at most one of the two captions belongs to it. Observed on
# 2607.16138, where "Figure 1: Heatmap …" and "Figure 2: Heatmap …" both rendered (72,377,539,535).
_DUPLICATE_MIN_IOU = 0.9


def _overlap_area(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return w * h if w > 0 and h > 0 else 0.0


def _graphic_cluster(
    graphics: list[tuple[float, float, float, float]], bbox: tuple[float, float, float, float]
) -> float:
    """Height of the run of graphic objects the crop sits in, by GAPS alone.

    Deliberately a different rule from the one the crop stage uses. That one asks whether another
    float's caption sits between two graphics; measuring with it would compare the crop stage to
    itself and report 1.00 whatever it did. This asks only "is there more picture immediately
    above, with no room for anything else between", which is an independent question — and the
    disagreement between the two rules is exactly what a regression in the crop stage looks like.

    Returns the crop's own height when nothing adjoins it, so the ratio is 1.0 by default and
    only a crop that genuinely left picture behind scores low.
    """
    top, bottom = bbox[1], bbox[3]
    members = [g for g in graphics if g[2] > bbox[0] and g[0] < bbox[2] and g[1] < bottom + 1]
    changed = True
    while changed:
        changed = False
        for g in members:
            if g[3] < top and top - g[3] <= _CLUSTER_GAP_PT:
                top, changed = min(top, g[1]), True
            elif g[1] < top < g[3]:  # overlaps the run's top edge
                top, changed = min(top, g[1]), True
    return bottom - top


def asset_signals(paper_id: str, version: int, pdf: bytes, crops: list) -> dict[str, Any]:
    """Render this paper's crop specs and report what came out. Never raises.

    Runs the real ``crop_assets_from_specs`` — the point is to measure the delivered artifact, so
    a reimplementation here would measure the wrong thing.
    """
    from docsuri_ingestion.asset_extraction import _graphic_boxes, crop_assets_from_specs
    from docsuri_ingestion.domain.enums import AssetType

    if not crops:
        return {"crop_specs": 0, "crops_stored": 0, "crops_refused": {}}
    refusals: list[tuple[str, str]] = []
    assets = crop_assets_from_specs(
        pdf, crops, paper_id=paper_id, version=version, refusals=refusals
    )
    by_reason: dict[str, int] = {}
    for _aid, why in refusals:
        by_reason[why] = by_reason.get(why, 0) + 1

    partial: list[dict[str, Any]] = []
    overlapping: list[str] = []
    duplicated: list[str] = []
    doc = None
    try:
        import pypdfium2 as pdfium

        doc = pdfium.PdfDocument(pdf)
        spec_by_id = {c.asset_id: c for c in crops}
        by_page: dict[int, list] = {}
        for asset in assets:
            by_page.setdefault(asset.meta.page_ref, []).append(asset)
        for page, page_assets in by_page.items():
            page_idx = page - 1
            if page_idx < 0 or page_idx >= len(doc):
                continue
            graphics = list(_graphic_boxes(doc, page_idx))
            for asset in page_assets:
                spec = spec_by_id.get(asset.meta.asset_id)
                # Only the recovered figures can be partial: everywhere else the box came from
                # GROBID's own content element and there is no cluster to be short of.
                if spec is None or spec.type is not AssetType.FIGURE or spec.content_coords:
                    continue
                bbox = tuple(asset.meta.bbox)
                cluster = _graphic_cluster(graphics, bbox)
                cover = (bbox[3] - bbox[1]) / cluster if cluster > 0 else 1.0
                if cover < _PARTIAL_MAX_COVER:
                    partial.append({"asset_id": asset.meta.asset_id, "cover": round(cover, 3)})
            for i, a in enumerate(page_assets):
                for b in page_assets[i + 1 :]:
                    ax, bx = tuple(a.meta.bbox), tuple(b.meta.bbox)
                    area = _overlap_area(ax, bx)
                    if not area:
                        continue
                    areas = [(x[2] - x[0]) * (x[3] - x[1]) for x in (ax, bx)]
                    pair = f"{a.meta.asset_id}~{b.meta.asset_id}"
                    union = areas[0] + areas[1] - area
                    if union > 0 and area / union >= _DUPLICATE_MIN_IOU:
                        duplicated.append(pair)
                    elif min(areas) > 0 and area / min(areas) > _OVERLAP_MAX_SHARE:
                        overlapping.append(pair)
    except Exception as exc:  # noqa: BLE001 - a geometry read that fails costs the signal, not the row
        return {
            "crop_specs": len(crops),
            "crops_stored": len(assets),
            "crops_refused": by_reason,
            "crop_geometry_error": f"{type(exc).__name__}: {exc}",
        }
    finally:
        # A sweep opens one of these per paper; pypdfium2 closes nothing on its own, so leaving
        # them to the interpreter is how a 150-paper run ends in a wall of teardown warnings.
        if doc is not None:
            with suppress(Exception):
                doc.close()

    return {
        "crop_specs": len(crops),
        "crops_stored": len(assets),
        "crops_refused": by_reason,
        "figure_crops_partial": len(partial),
        "partial_detail": partial[:8],
        "crop_duplicates": len(duplicated),
        "duplicate_detail": duplicated[:8],
        "crop_overlaps": len(overlapping),
        "overlap_detail": overlapping[:8],
    }


def merged_cell_tables(doc: dict, crops: list) -> int:
    """Tables whose cells are still glued together after the repair stage.

    ``empty_table`` only catches a table with NO rows; a table whose whole grid landed in one row
    reads as healthy to it. The rule is not restated here — ``table_repair`` owns the definition
    of "this table would benefit from a re-read", and a second copy would drift from it.
    """
    from docsuri_ingestion.docmodel.table_repair import tables_needing_repair

    try:
        return len(tables_needing_repair(doc, crops))
    except Exception:  # noqa: BLE001 - a signal that cannot be read is not a defect
        return 0
