"""Unit tests for the preservation audit's source-signal detectors and violation rules.

The audit is a loss detector run over real papers; these lock the calibration decisions made on the
dry run (what counts as a standalone block, which signals flag loss) so a later edit cannot quietly
bring back the false-positive floods that the raw tabular / equation / inline-verbatim counts gave.
"""

from __future__ import annotations

import sys
from pathlib import Path

from bs4 import BeautifulSoup

# The audit script lives in tools/parse_audit and imports its siblings by bare name (it is run as a
# script from that directory), so put it on the path before importing.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "parse_audit"))

import preservation_audit as pa  # noqa: E402


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def test_numbered_captions_counted_by_type_panels_ignored() -> None:
    html = """
    <figcaption class="ltx_caption"><span class="ltx_tag">Figure 1:</span> a plot</figcaption>
    <figcaption class="ltx_caption"><span class="ltx_tag">Fig. 2</span> another</figcaption>
    <figcaption class="ltx_caption"><span class="ltx_tag">TABLE III:</span> results</figcaption>
    <figcaption class="ltx_caption"><span class="ltx_tag">(a)</span> a sub-panel</figcaption>
    """
    sig = pa._source_signals(_soup(html))
    assert sig["src_fig_captions"] == 2  # Figure 1, Fig. 2
    assert sig["src_table_captions"] == 1  # TABLE III (roman numeral)
    # the "(a)" sub-panel mark is neither a figure nor a table float


def test_inline_verbatim_inside_paragraph_is_not_a_code_block() -> None:
    # \verb|foo| renders as <code class="ltx_verbatim"> INSIDE a paragraph — the parser folds it
    # into the paragraph text, so it must not count as a standalone code block.
    html = """
    <p class="ltx_p">call <code class="ltx_verbatim">make_regression</code> then
       <code class="ltx_verbatim">fit</code>.</p>
    <div class="ltx_listing">real = block()</div>
    """
    sig = pa._source_signals(_soup(html))
    assert sig["src_listings"] == 1  # only the block-level ltx_listing


def test_nested_list_counts_once() -> None:
    html = """
    <ul class="ltx_itemize"><li>outer
      <ul class="ltx_itemize"><li>inner</li></ul>
    </li></ul>
    """
    sig = pa._source_signals(_soup(html))
    assert sig["src_lists"] == 1  # the nested list is part of its parent


def test_figure_caption_shortfall_flags_a_lost_numbered_figure() -> None:
    sig = {
        "src_fig_captions": 5,
        "doc_figures": 4,
        "src_table_captions": 0,
        "doc_tables_with_caption": 0,
        "doc_empty_tables": 0,
        "src_lists": 0,
        "doc_lists": 0,
        "src_listings": 0,
        "doc_code": 0,
        "doc_figures_no_assetref": 0,
        "coverage": 0.9,
    }
    assert "figure_caption_shortfall" in pa._violations(sig)


def test_healthy_signals_produce_no_violations() -> None:
    sig = {
        "src_fig_captions": 3,
        "doc_figures": 3,
        "src_table_captions": 2,
        "doc_tables_with_caption": 2,
        "doc_empty_tables": 0,
        "src_lists": 4,
        "doc_lists": 4,
        "src_listings": 1,
        "doc_code": 1,
        "doc_figures_no_assetref": 0,
        "coverage": 0.82,
    }
    assert pa._violations(sig) == []


def test_empty_table_and_missing_assetref_and_low_coverage_flag() -> None:
    sig = {
        "src_fig_captions": 0,
        "doc_figures": 1,
        "src_table_captions": 0,
        "doc_tables_with_caption": 0,
        "doc_empty_tables": 1,
        "src_lists": 0,
        "doc_lists": 0,
        "src_listings": 0,
        "doc_code": 0,
        "doc_figures_no_assetref": 1,
        "coverage": 0.30,
    }
    v = pa._violations(sig)
    assert {"empty_table", "figure_missing_assetref", "coverage_low"} <= set(v)
