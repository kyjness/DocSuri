"""Table repair: when a second reading of the page may replace GROBID's merged cells.

The extractor itself is a heavy optional model stack, so these tests drive the decision logic with
grids a fake extractor returns — what matters here is which rebuilds are accepted and which are
refused, not how the cells were read.
"""

from __future__ import annotations

from docsuri_ingestion.docmodel.table_repair import apply_repairs, tables_needing_repair
from docsuri_ingestion.domain.assets import AssetCropSpec, ExtractedTable
from docsuri_ingestion.domain.enums import AssetType

_ASSET = "p:v1:table:0"
_SPEC = AssetCropSpec(
    asset_id=_ASSET, type=AssetType.TABLE, ordinal=0, page=3, bbox=(100.0, 100.0, 400.0, 200.0)
)
# The failure GROBID produces: a whole data row glued into one cell.
_MERGED = {
    "id": "s1.tbl1",
    "type": "table",
    "assetRef": {"assetId": _ASSET, "type": "table", "ordinal": 0},
    "rows": [
        {"cells": [{"text": "Method"}, {"text": "C-index"}]},
        {"cells": [{"text": "ADA"}, {"text": "0.696 ± 0.015 0.011 ± 0.000"}]},
    ],
}
_REBUILT = ExtractedTable(
    page=3,
    bbox=(100.0, 100.0, 400.0, 260.0),
    rows=(("Method", "C-index", "Brier"), ("ADA", "0.696 ± 0.015", "0.011 ± 0.000")),
)


def _doc(table: dict | None = None) -> dict:
    return {"sections": [{"id": "s1", "blocks": [dict(table or _MERGED)]}]}


def _printed(numbers: str):
    return lambda page, bbox: tuple(numbers.split())


def _rows(doc: dict) -> list[list[str]]:
    block = doc["sections"][0]["blocks"][0]
    return [[cell["text"] for cell in row["cells"]] for row in block["rows"]]


def test_only_tables_with_glued_numbers_are_re_read() -> None:
    """Re-reading a page costs seconds of inference, and GROBID is usually right — so only the
    tables showing the merge signature are worth the second reading."""
    clean = dict(_MERGED)
    clean["rows"] = [{"cells": [{"text": "ADA"}, {"text": "0.696"}, {"text": "0.011"}]}]

    assert tables_needing_repair(_doc(), [_SPEC]) == [_SPEC]
    assert tables_needing_repair(_doc(clean), [_SPEC]) == []


def test_a_verified_rebuild_replaces_the_merged_cells() -> None:
    doc = _doc()
    repaired = apply_repairs(doc, [_SPEC], [_REBUILT], _printed("0.696 0.015 0.011 0.000"))

    assert repaired == 1
    assert _rows(doc) == [
        ["Method", "C-index", "Brier"],
        ["ADA", "0.696 ± 0.015", "0.011 ± 0.000"],
    ]


def test_a_number_not_printed_on_the_page_refuses_the_whole_rebuild() -> None:
    """The one thing a second reader must never do is introduce a figure the paper does not
    contain — a rebuild is only allowed to re-divide what is actually printed there."""
    doc = _doc()
    invented = ExtractedTable(
        page=3, bbox=_REBUILT.bbox, rows=(("ADA", "0.696 ± 0.015", "0.842 ± 0.000"),)
    )

    assert apply_repairs(doc, [_SPEC], [invented], _printed("0.696 0.015 0.011 0.000")) == 0
    assert _rows(doc) == [["Method", "C-index"], ["ADA", "0.696 ± 0.015 0.011 ± 0.000"]]


def test_a_rebuild_that_reads_fewer_numbers_is_refused() -> None:
    """Merged-but-complete beats tidy-but-partial: a repair must not lose data to gain shape."""
    doc = _doc()
    partial = ExtractedTable(page=3, bbox=_REBUILT.bbox, rows=(("ADA", "0.696"),))

    assert apply_repairs(doc, [_SPEC], [partial], _printed("0.696 0.015 0.011 0.000")) == 0
    assert _rows(doc)[1] == ["ADA", "0.696 ± 0.015 0.011 ± 0.000"]


def test_verification_reads_the_extractors_own_region() -> None:
    """The yardstick region is the rebuilt table's own box. Widening it (e.g. unioning GROBID's
    box, which can shrink to the caption strip) would let a number printed outside the table vouch
    for an invented cell — the exact fabrication the check exists to refuse."""
    doc = _doc()
    seen: list[tuple[float, float, float, float]] = []

    def printed(page: int, bbox: tuple[float, float, float, float]) -> tuple[str, ...]:
        seen.append(bbox)
        return ("0.696", "0.015", "0.011", "0.000")

    assert apply_repairs(doc, [_SPEC], [_REBUILT], printed) == 1
    assert seen == [_REBUILT.bbox]  # not a union with _SPEC.bbox


def test_a_malformed_row_does_not_crash_the_merge_check() -> None:
    """A stray non-dict row is skipped; the dict rows still decide whether the table looks
    merged (the scan runs on plain payload dicts, so shape is not guaranteed)."""
    table = dict(_MERGED)
    table["rows"] = ["stray", *_MERGED["rows"]]

    assert tables_needing_repair(_doc(table), [_SPEC]) == [_SPEC]


def test_an_unreadable_page_refuses_the_rebuild() -> None:
    """With no yardstick there is no verification, and an unverified rebuild is not applied."""
    doc = _doc()

    assert apply_repairs(doc, [_SPEC], [_REBUILT], lambda page, bbox: ()) == 0


def test_a_grid_from_another_region_is_not_used() -> None:
    """Grids are matched to the table they overlap, so a second table on the page cannot be
    swapped in for the first."""
    doc = _doc()
    elsewhere = ExtractedTable(page=3, bbox=(100.0, 500.0, 400.0, 600.0), rows=_REBUILT.rows)

    assert apply_repairs(doc, [_SPEC], [elsewhere], _printed("0.696 0.015 0.011 0.000")) == 0


def test_spacing_inside_a_value_does_not_look_like_two_numbers() -> None:
    """An extractor may hand back "4. 69%" for a cell; that is one value, and the page prints it
    as one, so the check must not read it as "4" and "69" and refuse."""
    doc = _doc(
        {
            "id": "s1.tbl1",
            "type": "table",
            "assetRef": {"assetId": _ASSET, "type": "table", "ordinal": 0},
            "rows": [{"cells": [{"text": "HbA1c < 4.69% 0.771 0.775"}]}],
        }
    )
    rebuilt = ExtractedTable(
        page=3, bbox=_REBUILT.bbox, rows=(("HbA1c < 4. 69%", "0.771", "0.775"),)
    )

    assert apply_repairs(doc, [_SPEC], [rebuilt], _printed("4.69 0.771 0.775")) == 1
    assert _rows(doc) == [["HbA1c < 4. 69%", "0.771", "0.775"]]


def test_a_table_grobid_emptied_is_re_read_too() -> None:
    """The other GROBID failure, and the one that was never routed here.

    Cells can come out glued, which the merge signature names — or they can come out EMPTY, when
    reconstruction fails outright and the block keeps its caption with no rows at all. That is the
    worse of the two: the whole grid is gone rather than mis-split. The merge check read it as
    healthy (no cell holds several numbers), so the repair skipped exactly the tables that had
    lost everything.
    """
    emptied = dict(_MERGED)
    emptied["rows"] = []

    assert tables_needing_repair(_doc(emptied), [_SPEC]) == [_SPEC]


def test_a_rebuild_of_an_emptied_table_still_has_to_be_printed_on_the_page() -> None:
    """Routing an empty table in must not relax the safety argument: with no TEI numbers to fall
    short of, the printed-numbers check is the only thing standing between the block and a
    fabricated grid (C-2)."""
    emptied = dict(_MERGED)
    emptied["rows"] = []

    doc = _doc(emptied)
    assert apply_repairs(doc, [_SPEC], [_REBUILT], _printed("0.696 0.015")) == 0
    assert doc["sections"][0]["blocks"][0]["rows"] == []

    doc = _doc(emptied)
    assert apply_repairs(doc, [_SPEC], [_REBUILT], _printed("0.696 0.015 0.011 0.000")) == 1
    assert _rows(doc) == [
        ["Method", "C-index", "Brier"],
        ["ADA", "0.696 ± 0.015", "0.011 ± 0.000"],
    ]
