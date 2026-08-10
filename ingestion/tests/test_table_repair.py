"""Table repair: when a second reading of the page may replace GROBID's merged cells.

The extractor itself is a heavy optional model stack, so these tests drive the decision logic with
grids a fake extractor returns — what matters here is which rebuilds are accepted and which are
refused, not how the cells were read.
"""

from __future__ import annotations

from dataclasses import replace

from docsuri_ingestion.docmodel.table_repair import (
    PrintedRegion,
    apply_repairs,
    tables_needing_repair,
)
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
# What the page prints in _REBUILT's region — its WORDS as well as its numbers. Every kind of
# token a rebuild emits has to be found here, so a fixture listing numbers alone would refuse the
# rebuild's own headers.
_REGION = "Method C-index Brier ADA 0.696 ± 0.015 0.011 ± 0.000"


def _doc(table: dict | None = None) -> dict:
    return {"sections": [{"id": "s1", "blocks": [dict(table or _MERGED)]}]}


def _printed(text: str, rotated: tuple[str, ...] = ()):
    """The region's printed text, as the pdfplumber reader hands it back.

    ``rotated`` names the words the page draws turned on their side, which the reader reports
    separately from the text so that only the verifier decides what that ambiguity earns."""
    return lambda page, bbox: PrintedRegion(text, rotated)


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
    repaired = apply_repairs(doc, [_SPEC], [_REBUILT], _printed(_REGION))

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

    assert apply_repairs(doc, [_SPEC], [invented], _printed(_REGION)) == 0
    assert _rows(doc) == [["Method", "C-index"], ["ADA", "0.696 ± 0.015 0.011 ± 0.000"]]


def test_a_rebuild_that_reads_fewer_numbers_is_refused() -> None:
    """Merged-but-complete beats tidy-but-partial: a repair must not lose data to gain shape."""
    doc = _doc()
    partial = ExtractedTable(page=3, bbox=_REBUILT.bbox, rows=(("ADA", "0.696"),))

    assert apply_repairs(doc, [_SPEC], [partial], _printed(_REGION)) == 0
    assert _rows(doc)[1] == ["ADA", "0.696 ± 0.015 0.011 ± 0.000"]


def test_verification_reads_the_extractors_own_region() -> None:
    """The yardstick region is the rebuilt table's own box. Widening it (e.g. unioning GROBID's
    box, which can shrink to the caption strip) would let a number printed outside the table vouch
    for an invented cell — the exact fabrication the check exists to refuse."""
    doc = _doc()
    seen: list[tuple[float, float, float, float]] = []

    def printed(page: int, bbox: tuple[float, float, float, float]) -> PrintedRegion:
        seen.append(bbox)
        return PrintedRegion(_REGION)

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

    assert apply_repairs(doc, [_SPEC], [_REBUILT], _printed("")) == 0


def test_a_grid_from_another_region_is_not_used() -> None:
    """Grids are matched to the table they overlap, so a second table on the page cannot be
    swapped in for the first."""
    doc = _doc()
    elsewhere = ExtractedTable(page=3, bbox=(100.0, 500.0, 400.0, 600.0), rows=_REBUILT.rows)

    assert apply_repairs(doc, [_SPEC], [elsewhere], _printed(_REGION)) == 0


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

    assert apply_repairs(doc, [_SPEC], [rebuilt], _printed("HbA1c < 4.69% 0.771 0.775")) == 1
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
    short = "Method C-index Brier ADA 0.696 ± 0.015"
    assert apply_repairs(doc, [_SPEC], [_REBUILT], _printed(short)) == 0
    assert doc["sections"][0]["blocks"][0]["rows"] == []

    doc = _doc(emptied)
    assert apply_repairs(doc, [_SPEC], [_REBUILT], _printed(_REGION)) == 1
    assert _rows(doc) == [
        ["Method", "C-index", "Brier"],
        ["ADA", "0.696 ± 0.015", "0.011 ± 0.000"],
    ]


# --- the caption fallback: matching when GROBID's box collapsed onto the caption strip ---

_CAPTION = (
    "Performance comparison of the proposed model on the test set of both datasets. "
    "The term 'best' refers to the best performance on the development set."
)
# The box GROBID leaves when its reconstruction fails: a caption-height strip that sits BETWEEN
# the tables on the page and so overlaps neither (observed at 21pt on 1909.03716 page 5). The
# caption rides on the spec, where the parser writes it — the same string it puts on the block.
_COLLAPSED = AssetCropSpec(
    asset_id=_ASSET,
    type=AssetType.TABLE,
    ordinal=0,
    page=3,
    bbox=(72.0, 258.0, 526.0, 279.0),
    caption=_CAPTION,
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
        doc, [_COLLAPSED], [_ABOVE, _BELOW], _printed(_REGION + " Method C-index FINRISK 0.702")
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
    assert apply_repairs(doc, [_COLLAPSED], [labelled], _printed(_REGION)) == 1


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
    generic = replace(_COLLAPSED, caption="Results")
    short = ExtractedTable(
        page=_ABOVE.page, bbox=_ABOVE.bbox, rows=_ABOVE.rows, caption="Table 2: Results"
    )
    doc = _doc(_EMPTIED)
    assert apply_repairs(doc, [generic], [short], _printed(_REGION)) == 0


def test_a_region_that_does_overlap_is_still_matched_by_region() -> None:
    """The fallback is additive: where GROBID's box survived, the proven signal decides and a
    caption that happens to name a different grid never overrides it."""
    misleading = ExtractedTable(
        page=3, bbox=(71.0, 500.0, 526.0, 600.0), rows=(("x", "1"),), caption=f"Table 2: {_CAPTION}"
    )
    doc = _doc()
    repaired = apply_repairs(
        doc,
        [replace(_SPEC, caption=_CAPTION)],
        [_REBUILT, misleading],
        _printed(_REGION),
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
    quoted = replace(
        _COLLAPSED,
        caption='Instantiations of L t "bounded by M " means for any x and r ~ p(*)',
    )
    rebuilt = ExtractedTable(
        page=_ABOVE.page,
        bbox=_ABOVE.bbox,
        rows=_ABOVE.rows,
        caption="Table 1: Instantiations of L t 'bounded by M ' means for any x and r ~ p (*)",
    )
    doc = _doc(_EMPTIED)
    assert apply_repairs(doc, [quoted], [rebuilt], _printed(_REGION)) == 1


def test_a_caption_the_readers_truncate_differently_still_matches() -> None:
    """One reader stops at the caption, the other runs on into the paragraph below it. Comparing
    the whole of either against the other fails on that tail, so an opening stretch is compared."""
    long_tail = replace(
        _COLLAPSED, caption=_CAPTION + " And then a whole paragraph the other reader never saw."
    )
    doc = _doc(_EMPTIED)
    assert apply_repairs(doc, [long_tail], [_ABOVE], _printed(_REGION)) == 1


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


def test_one_number_does_not_wave_the_rest_of_a_grid_through() -> None:
    """Judging on numbers ALONE meant a single digit disabled every other check on the grid.

    An emptied table has no TEI cells to fall short of, so the "no fewer than GROBID" condition is
    vacuous there and the printed-token check is the only thing left. With a text grid carrying one
    stray number — a citation year, a version — that check saw the year, passed, and the extractor's
    misread text cells were written into the block unexamined. Every kind of token the rebuild
    emits is now checked, so the fabricated headers are refused.
    """
    emptied = dict(_MERGED)
    emptied["rows"] = []
    doc = _doc(emptied)
    fabricated = ExtractedTable(
        page=3,
        bbox=_REBUILT.bbox,
        rows=(("2022", "Completely Fabricated Header"), ("Another Invention", "Never Printed")),
    )
    assert apply_repairs(
        doc, [_SPEC], [fabricated], _printed("Reference year 2022 appears here")
    ) == 0
    assert doc["sections"][0]["blocks"][0]["rows"] == []


def test_a_word_the_page_prints_is_not_refused_by_a_reader_seam() -> None:
    """The word path compares cells against the pool, so both sides must be read the same way.

    The pool used to be re-split at digit boundaries while the cells were not, which made an
    identifier unmatchable against itself: the page prints "ResNet50", the pool held "resnet" and
    "50", the cell held "resnet50", and a perfectly good repair of a table full of model names was
    refused. Neither side is rewritten now.
    """
    emptied = dict(_MERGED)
    emptied["rows"] = []
    doc = _doc(emptied)
    rebuilt = ExtractedTable(
        page=3, bbox=_REBUILT.bbox, rows=(("Model", "Backbone"), ("ours", "ResNet50"))
    )
    assert apply_repairs(
        doc, [_SPEC], [rebuilt], _printed("Model Backbone ours ResNet50")
    ) == 1


def test_an_abbreviation_dot_does_not_swallow_the_value_after_it() -> None:
    """The decimal healing belongs to a CELL, where an extractor has already delimited one value.

    Applied to the whole region it rewrote the page's own spacing: "avg. 0.85" became "avg.0.85",
    where the number pattern's lookbehind refuses both halves, so a value plainly printed vanished
    from the pool and the correct rebuild was refused. The pool is read exactly as printed.
    """
    emptied = dict(_MERGED)
    emptied["rows"] = []
    doc = _doc(emptied)
    rebuilt = ExtractedTable(page=3, bbox=_REBUILT.bbox, rows=(("avg", "0.85"),))
    assert apply_repairs(doc, [_SPEC], [rebuilt], _printed("avg. 0.85 reported")) == 1


def test_a_value_the_page_spaces_normally_verifies_without_healing_the_pool() -> None:
    """The seam these fixtures used to carry is the reader's, not the page's.

    ``extract_text()`` closes word gaps below its tolerance — "30-60 meters" came back
    "30-60meters" — and the pool was patched afterwards by re-splitting digit/letter boundaries.
    ``printed_text`` now reads the page's own word boxes, so the seam never forms and no rewriting
    is needed on either side.
    """
    emptied = dict(_MERGED)
    emptied["rows"] = []
    rebuilt = ExtractedTable(
        page=3,
        bbox=_REBUILT.bbox,
        rows=(("Parameter", "Value Range"), ("Stack Height", "30-60 meters")),
    )
    doc = _doc(emptied)
    assert apply_repairs(
        doc, [_SPEC], [rebuilt], _printed("Parameter Value Range Stack Height 30-60 meters")
    ) == 1


def test_an_identifier_does_not_vouch_for_the_digits_inside_it() -> None:
    """C-2's sharpest edge, and where the old seam-healing broke it.

    Re-splitting the pool to heal a glued unit also cut identifiers apart: "ResNet50" became
    "ResNet 50", minting a standalone "50" the page never prints AS A VALUE, and a rebuild could
    then place that "50" in a cell and still verify.

    Two changes refuse it now and the test does not distinguish them, deliberately — the pool keeps
    the identifier whole so the number pattern's boundary rejects the digits, AND a bare "50" is a
    word token too, so the word check demands it be printed as its own word. Either alone would do;
    both is what makes the hole hard to reopen by accident.
    """
    emptied = dict(_MERGED)
    emptied["rows"] = []

    for region, claim in (("Metric HbA1c", "1"), ("backbone ResNet50 was used", "50")):
        doc = _doc(emptied)
        invented = ExtractedTable(page=3, bbox=_REBUILT.bbox, rows=(("Metric", claim),))
        assert apply_repairs(doc, [_SPEC], [invented], _printed(region)) == 0, (
            f"{region!r} vouched for a bare {claim!r} it never prints as a value"
        )


def test_a_spanned_cell_replicated_per_column_still_verifies() -> None:
    """A cell spanning seven columns is printed once but lands in the extractor's grid seven
    times. Demanding seven printed copies refused real tables wholesale; what fabrication-safety
    needs is only that every value IS printed in the region."""
    emptied = dict(_MERGED)
    emptied["rows"] = []
    spanned = ExtractedTable(
        page=3,
        bbox=_REBUILT.bbox,
        rows=(
            ("Standard", "1.12 (210)", "1.12 (210)", "1.12 (210)"),
            ("", "Polynomial degree", "Polynomial degree", "Polynomial degree"),
        ),
    )
    doc = _doc(emptied)
    assert apply_repairs(
        doc, [_SPEC], [spanned], _printed("Standard 1.12 (210) Polynomial degree")
    ) == 1

    # A value the region never prints is still refused — replication is not a licence to invent.
    doc = _doc(emptied)
    foreign = ExtractedTable(
        page=3, bbox=_REBUILT.bbox, rows=(("Standard", "1.12 (210)", "9.99"),)
    )
    assert apply_repairs(
        doc, [_SPEC], [foreign], _printed("Standard 1.12 (210) Polynomial degree")
    ) == 0


def test_a_citation_year_beside_an_author_name_verifies() -> None:
    """The other direction of the seam the old pool-healing existed for: "Giannacopoulos 2022".

    Word boxes keep the year a separate token from the name, so the rebuild's correctly-spaced
    copy is found without a letter->digit rule — and, unlike that rule, nothing here can invent a
    number out of an identifier.
    """
    emptied = dict(_MERGED)
    emptied["rows"] = []
    rebuilt = ExtractedTable(
        page=3,
        bbox=_REBUILT.bbox,
        rows=(("Model", "Year"), ("PhysGNN (Salehi and Giannacopoulos 2022)", "1.71")),
    )
    doc = _doc(emptied)
    region = "Model Year PhysGNN (Salehi and Giannacopoulos 2022) 1.71"
    assert apply_repairs(doc, [_SPEC], [rebuilt], _printed(region)) == 1


def test_a_grid_whose_cells_are_all_blank_is_re_read_too() -> None:
    """The third shape of the same GROBID failure, and it was slipping past the routing.

    Reconstruction can fail with no rows at all, or it can recover the grid's SHAPE and none of its
    contents — ``<row><cell/><cell/></row>``. A reader gets a blank grid either way, but a check
    that only asked whether rows existed read the second as healthy and skipped the re-read.
    """
    blank = dict(_MERGED)
    blank["rows"] = [
        {"cells": [{"text": ""}, {"text": "  "}]},
        {"cells": [{"text": ""}, {"text": ""}]},
    ]

    assert tables_needing_repair(_doc(blank), [_SPEC]) == [_SPEC]

    # A grid that holds real text is still left alone — blankness is the signal, not row count.
    filled = dict(_MERGED)
    filled["rows"] = [{"cells": [{"text": "Method"}, {"text": "0.696"}]}]
    assert tables_needing_repair(_doc(filled), [_SPEC]) == []


# --- 실논문 실패 원인에서 나온 회귀 (2026-08-10) ------------------------------
#
# 50편 표본에서 표 212개 중 61개가 셀이 붙은 채 남았다. 미수리를 분류했더니 검증 게이트에서
# 거부된 것이 44%였고, 그중 다수의 원인이 아래 둘이다 — 재구성이 틀린 게 아니라 페이지 쪽을
# 잘못 읽고 있었다.


def test_a_minus_printed_as_a_unicode_sign_still_matches_the_cell() -> None:
    """Papers set a minus as U+2212; an extractor's cell uses ASCII "-". Read literally the two
    sides disagree about the same value, and one verified rebuild was refused over "-5 -4 -3 -2"."""
    doc = _doc(
        {
            "id": "s1.tbl1",
            "type": "table",
            "assetRef": {"assetId": _ASSET, "type": "table", "ordinal": 0},
            "rows": [{"cells": [{"text": "lr"}, {"text": "-5 -4 -3"}]}],
        }
    )
    rebuilt = ExtractedTable(page=3, bbox=_REBUILT.bbox, rows=(("lr", "-5", "-4", "-3"),))

    # The page prints them with the typographic minus, and with the ASCII one they already matched.
    assert apply_repairs(doc, [_SPEC], [rebuilt], _printed("lr −5 −4 −3")) == 1


def test_the_reader_names_the_rotated_words_instead_of_folding_them_into_the_text() -> None:
    """pdfplumber orders a rotated run geometrically, so a top-to-bottom label comes back
    backwards ("elbmesnE" for "Ensemble"). The reader reports that ambiguity SEPARATELY rather
    than adding a second reading to the region's text — the text is the yardstick a rebuild is
    measured against, and one that quietly contains more than the page does is not one."""
    from docsuri_ingestion.docmodel.table_repair import _rotated_words

    rotated = {"text": "elbmesnE", "upright": False}
    upright = {"text": "Ensemble", "upright": True}
    # Anything holding a digit is left out here, so no check downstream can ever reverse it:
    # reversing "12.5" would mint "5.21", a value the page never prints.
    numeric = {"text": "12.5", "upright": False}

    assert _rotated_words([rotated, upright, numeric]) == ("elbmesnE",)


def test_a_rebuild_matching_only_a_rotated_label_verifies() -> None:
    doc = _doc(
        {
            "id": "s1.tbl1",
            "type": "table",
            "assetRef": {"assetId": _ASSET, "type": "table", "ordinal": 0},
            "rows": [{"cells": [{"text": "Ensemble"}, {"text": "0.90 0.80 0.70"}]}],
        }
    )
    rebuilt = ExtractedTable(
        page=3, bbox=_REBUILT.bbox, rows=(("Ensemble", "0.90", "0.80", "0.70"),)
    )
    # The page prints the label backwards and nothing else vouches for "Ensemble".
    printed = _printed("elbmesnE 0.90 0.80 0.70", ("elbmesnE",))

    assert apply_repairs(doc, [_SPEC], [rebuilt], printed) == 1


def test_a_word_the_page_does_not_print_is_not_excused_by_an_unrelated_rotated_label() -> None:
    """The allowance is a second reading of a rotated word, not a licence for any word. A token
    that matches neither the page's text nor a reversed rotated label stays refused (C-2)."""
    doc = _doc(
        {
            "id": "s1.tbl1",
            "type": "table",
            "assetRef": {"assetId": _ASSET, "type": "table", "ordinal": 0},
            "rows": [{"cells": [{"text": "Ensemble"}, {"text": "0.90 0.80 0.70"}]}],
        }
    )
    invented = ExtractedTable(
        page=3, bbox=_REBUILT.bbox, rows=(("Ensemble", "Baseline", "0.90", "0.80", "0.70"),)
    )
    printed = _printed("elbmesnE 0.90 0.80 0.70", ("elbmesnE",))

    assert apply_repairs(doc, [_SPEC], [invented], printed) == 0


# --- 캡션 폴백: 고정 프로브가 두 방향으로 실패하던 것 (2026-08-10) --------------
#
# GROBID가 빈 표에는 좌표를 안 줘서 기하 매칭이 구조적으로 불가능하고, 그때 캡션이 유일한
# 식별 수단이 된다. 50편 census에서 남은 빈 표 7건 중 5건이 이 지점에서 막혀 있었다.

_EMPTY = {
    "id": "s1.tbl1",
    "type": "table",
    "assetRef": {"assetId": _ASSET, "type": "table", "ordinal": 0},
    "rows": [],
}


def _far(caption: str, rows=(("A", "1"), ("B", "2"))) -> ExtractedTable:
    """A rebuild whose region does NOT overlap the spec — the caption is the only route to it."""
    return ExtractedTable(page=3, bbox=(10.0, 600.0, 300.0, 700.0), rows=rows, caption=caption)


def _spec_with(caption: str) -> AssetCropSpec:
    return replace(_SPEC, caption=caption)


_TRUE = "Four-dimensional case. Performances on P 4 of the GINN-based detector."


def test_a_caption_grobid_ran_into_the_next_float_still_matches() -> None:
    """GROBID appends what follows the caption — here the next table's "Algorithm 2" arrives as
    "rithm 2". A fixed 60-char probe reached into that tail and matched nothing, though the real
    caption (56 chars normalised) is quoted exactly."""
    spec = _spec_with(_TRUE + " rithm 2 (Λ min = 2/2 (hmax) = 2 -4 ) on a piece-wise")
    tables = [
        _far("Table 3: Results of Algorithm 2 with respect to the Shepp-Logan phantom."),
        _far("Table 4: " + _TRUE),
        _far("Table 5: Results of Algorithm 2 with respect to test function."),
    ]
    doc = _doc(_EMPTY)

    assert apply_repairs(doc, [spec], tables, _printed("A 1 B 2")) == 1
    assert _rows(doc) == [["A", "1"], ["B", "2"]]


def test_sibling_captions_are_separated_by_where_they_diverge() -> None:
    """Two tables opening identically used to read as an ambiguous page and be refused. They part
    at one word, and the longest agreement finds it."""
    shared = (
        "Accuracy (%) under different experimental conditions. "
        "The values are averaged for each"
    )
    spec = _spec_with(f"{shared} backbone and TTA loss of the Domainbed benchmark.")
    tables = [
        _far(f"Table 5: {shared} backbone and TTA loss of the Domainbed benchmark."),
        _far(
            f"Table 6: {shared} dataset and TTA loss of the Continual TTA benchmark.",
            (("C", "3"),),
        ),
    ]
    doc = _doc(_EMPTY)

    assert apply_repairs(doc, [spec], tables, _printed("A 1 B 2")) == 1
    assert _rows(doc) == [["A", "1"], ["B", "2"]]


def test_captions_that_agree_equally_far_are_still_refused() -> None:
    """A tie means the captions do not identify a table, and filing one table's numbers under
    another's caption is the misattribution this fallback exists to avoid."""
    spec = _spec_with(_TRUE)
    tables = [_far("Table 4: " + _TRUE), _far("Table 7: " + _TRUE, (("C", "3"),))]

    assert apply_repairs(_doc(_EMPTY), [spec], tables, _printed("A 1 B 2")) == 0


def test_a_caption_too_short_to_name_a_table_matches_nothing() -> None:
    spec = _spec_with("Complexity analysis.")

    tables = [_far("Table 2: Complexity analysis.")]

    assert apply_repairs(_doc(_EMPTY), [spec], tables, _printed("A 1 B 2")) == 0
