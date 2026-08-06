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


def _printed(text: str):
    """The region's printed text, as the pdfplumber reader hands it back."""
    return lambda page, bbox: text


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

    def printed(page: int, bbox: tuple[float, float, float, float]) -> str:
        seen.append(bbox)
        return "0.696 0.015 0.011 0.000"

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

    assert apply_repairs(doc, [_SPEC], [_REBUILT], lambda page, bbox: "") == 0


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


# --- the caption fallback: matching when GROBID's box collapsed onto the caption strip ---

# The box GROBID leaves when its reconstruction fails: a caption-height strip that sits BETWEEN
# the tables on the page and so overlaps neither (observed at 21pt on 1909.03716 page 5).
_COLLAPSED = AssetCropSpec(
    asset_id=_ASSET, type=AssetType.TABLE, ordinal=0, page=3, bbox=(72.0, 258.0, 526.0, 279.0)
)
_CAPTION = (
    "Performance comparison of the proposed model on the test set of both datasets. "
    "The term 'best' refers to the best performance on the development set."
)
_EMPTIED = {
    "id": "s1.tbl1",
    "type": "table",
    "assetRef": {"assetId": _ASSET, "type": "table", "ordinal": 0},
    "caption": _CAPTION,
    "anchorLabel": "Table 2 :",
    "rows": [],
}
# The grid the caption names, 11pt above the strip — and the one 12pt below that it does not.
_ABOVE = ExtractedTable(
    page=3,
    bbox=(71.0, 62.0, 526.0, 247.0),
    rows=(("Method", "C-index", "Brier"), ("ADA", "0.696 ± 0.015", "0.011 ± 0.000")),
    caption=f"Table 2: {_CAPTION}",
)
_BELOW = ExtractedTable(
    page=3,
    bbox=(71.0, 291.0, 526.0, 393.0),
    rows=(("Method", "C-index"), ("FINRISK", "0.702")),
    caption=(
        "Table 3: Performance comparison of the proposed model on the dev set of both datasets."
    ),
)


def test_the_caption_picks_the_grid_when_the_collapsed_box_overlaps_none() -> None:
    """Distance cannot choose between a grid 11pt above and one 12pt below, and choosing wrong
    files one table's numbers under another's caption — numbers that ARE printed on the page, so
    the verification downstream would not catch it. The caption chooses."""
    doc = _doc(_EMPTIED)
    repaired = apply_repairs(
        doc, [_COLLAPSED], [_ABOVE, _BELOW], _printed("0.696 0.015 0.011 0.000 0.702")
    )

    assert repaired == 1
    assert _rows(doc) == [
        ["Method", "C-index", "Brier"],
        ["ADA", "0.696 ± 0.015", "0.011 ± 0.000"],
    ]


def test_a_label_rendered_differently_by_each_reader_still_matches() -> None:
    """GROBID writes "Table 2 :" where Docling writes "Table 2:" — the label is dropped from both
    before comparing, because what identifies the table is the sentence after it."""
    doc = _doc(_EMPTIED)
    labelled = ExtractedTable(
        page=_ABOVE.page, bbox=_ABOVE.bbox, rows=_ABOVE.rows, caption=f"TABLE II. {_CAPTION}"
    )
    assert apply_repairs(doc, [_COLLAPSED], [labelled], _printed("0.696 0.015 0.011 0.000")) == 1


def test_two_grids_matching_the_same_caption_leave_the_table_alone() -> None:
    """The fallback runs where geometry has already failed, so it gets no second chance to be
    checked — an ambiguous page is left unrepaired rather than guessed at."""
    doc = _doc(_EMPTIED)
    twin = ExtractedTable(
        page=_BELOW.page, bbox=_BELOW.bbox, rows=_BELOW.rows, caption=f"Table 5: {_CAPTION}"
    )
    assert apply_repairs(doc, [_COLLAPSED], [_ABOVE, twin], _printed("0.696 0.015 0.011")) == 0
    assert doc["sections"][0]["blocks"][0]["rows"] == []


def test_a_caption_too_generic_to_identify_a_table_is_not_used() -> None:
    """"Results" names half the tables in a paper; a caption has to carry enough to single one
    out before it may stand in for the region."""
    generic = dict(_EMPTIED)
    generic["caption"] = "Results"
    short = ExtractedTable(
        page=_ABOVE.page, bbox=_ABOVE.bbox, rows=_ABOVE.rows, caption="Table 2: Results"
    )
    doc = _doc(generic)
    assert apply_repairs(doc, [_COLLAPSED], [short], _printed("0.696 0.015 0.011 0.000")) == 0


def test_a_region_that_does_overlap_is_still_matched_by_region() -> None:
    """The fallback is additive: where GROBID's box survived, the proven signal decides and a
    caption that happens to name a different grid never overrides it."""
    doc = _doc()
    misleading = ExtractedTable(
        page=3, bbox=(71.0, 500.0, 526.0, 600.0), rows=(("x", "1"),), caption=f"Table 2: {_CAPTION}"
    )
    merged_block = _doc()["sections"][0]["blocks"][0]
    merged_block["caption"] = _CAPTION
    doc = {"sections": [{"id": "s1", "blocks": [merged_block]}]}
    repaired = apply_repairs(
        doc, [_SPEC], [_REBUILT, misleading], _printed("0.696 0.015 0.011 0.000")
    )
    assert repaired == 1
    assert _rows(doc)[0] == ["Method", "C-index", "Brier"]


def test_two_readers_punctuating_the_same_caption_differently_still_match() -> None:
    """The same caption comes back with different punctuation from each reader.

    GROBID gave `"bounded by M " means … r ∼ p(•` where the re-read gave `'bounded by M ' means …
    r ∼ p (` — same sentence, different quotes and bracket spacing. Comparing the raw text made a
    caption that names the table look like a mismatch, so the fallback refused a repair it should
    have made. Only letters and digits survive normalisation now.
    """
    quoted = dict(_EMPTIED)
    quoted["caption"] = 'Instantiations of L t "bounded by M " means for any x and r ~ p(*)'
    rebuilt = ExtractedTable(
        page=_ABOVE.page,
        bbox=_ABOVE.bbox,
        rows=_ABOVE.rows,
        caption="Table 1: Instantiations of L t 'bounded by M ' means for any x and r ~ p (*)",
    )
    doc = _doc(quoted)
    assert apply_repairs(doc, [_COLLAPSED], [rebuilt], _printed("0.696 0.015 0.011 0.000")) == 1


def test_a_caption_the_readers_truncate_differently_still_matches() -> None:
    """One reader stops at the caption, the other runs on into the paragraph below it. Comparing
    the whole of either against the other fails on that tail, so an opening stretch is compared."""
    long_tail = dict(_EMPTIED)
    long_tail["caption"] = _CAPTION + " And then a whole paragraph the other reader never saw."
    doc = _doc(long_tail)
    assert apply_repairs(doc, [_COLLAPSED], [_ABOVE], _printed("0.696 0.015 0.011 0.000")) == 1


# --- text tables: the ones a number-only check could never verify ---

_TEXT_TABLE = {
    "id": "s1.tbl1",
    "type": "table",
    "assetRef": {"assetId": _ASSET, "type": "table", "ordinal": 0},
    "caption": "Attack taxonomy with one worked example per row of the evaluation suite.",
    "rows": [],
}
_TEXT_REBUILT = ExtractedTable(
    page=3,
    bbox=_REBUILT.bbox,
    rows=(("Attack Type", "Example"), ("Prompt injection", "Ignore prior instructions")),
)
_TEXT_PRINTED = "Attack Type Example Prompt injection Ignore prior instructions"


def test_a_table_holding_no_numbers_can_be_verified_on_its_words() -> None:
    """Judging only on numbers meant a table without any could never be checked, so it was never
    repaired — and the check refused it for having nothing to compare, not for being wrong. Plenty
    of tables here are text: attack taxonomies, ablation descriptions, dataset overviews."""
    doc = _doc(_TEXT_TABLE)

    assert apply_repairs(doc, [_SPEC], [_TEXT_REBUILT], _printed(_TEXT_PRINTED)) == 1
    assert _rows(doc) == [
        ["Attack Type", "Example"],
        ["Prompt injection", "Ignore prior instructions"],
    ]


def test_a_word_not_printed_on_the_page_refuses_the_whole_rebuild() -> None:
    """The safety argument is unchanged, only what it compares: a second reader may re-divide what
    the page prints and nothing else (C-2)."""
    doc = _doc(_TEXT_TABLE)
    invented = ExtractedTable(
        page=3,
        bbox=_REBUILT.bbox,
        rows=(("Attack Type", "Example"), ("Prompt injection", "Exfiltrate the private key")),
    )

    assert apply_repairs(doc, [_SPEC], [invented], _printed(_TEXT_PRINTED)) == 0
    assert doc["sections"][0]["blocks"][0]["rows"] == []


def test_a_word_rebuild_that_reads_less_than_grobid_is_refused() -> None:
    """Merged-but-complete beats tidy-but-partial on the word path too."""
    merged_text = dict(_TEXT_TABLE)
    merged_text["rows"] = [
        {"cells": [{"text": "Attack Type Example Prompt injection Ignore prior instructions"}]}
    ]
    partial = ExtractedTable(page=3, bbox=_REBUILT.bbox, rows=(("Attack Type", "Example"),))

    doc = _doc(merged_text)
    assert apply_repairs(doc, [_SPEC], [partial], _printed(_TEXT_PRINTED)) == 0


def test_a_rebuild_with_nothing_comparable_is_refused() -> None:
    """Single characters carry no evidence, so a grid made only of them would verify against an
    empty set — which would let ANY grid through. Refused rather than waved past."""
    doc = _doc(_TEXT_TABLE)
    noise = ExtractedTable(page=3, bbox=_REBUILT.bbox, rows=(("-", "|"), ("*", "")))

    assert apply_repairs(doc, [_SPEC], [noise], _printed(_TEXT_PRINTED)) == 0


def test_a_numeric_table_is_still_judged_on_its_numbers() -> None:
    """The word path opens only where there are no numbers. A numeric rebuild whose words all
    appear on the page must still fail when one of its NUMBERS does not."""
    doc = _doc()
    wrong_number = ExtractedTable(
        page=3, bbox=_REBUILT.bbox, rows=(("Method", "C-index"), ("ADA", "0.842"))
    )

    assert apply_repairs(doc, [_SPEC], [wrong_number], _printed("Method C-index ADA 0.696")) == 0
