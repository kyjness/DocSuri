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


def test_fatal_conversion_notice_is_source_unavailable() -> None:
    # ar5iv left its own failure notice as the only body — the paper has no HTML to preserve.
    html = """
    <article class="ltx_document"><p class="ltx_p">Conversion to HTML had a Fatal error
    and exited abruptly. This document may be truncated or damaged.</p></article>
    """
    assert pa._source_unavailable(_soup(html), html) is True


def test_metadata_shell_without_ltx_document_is_source_unavailable() -> None:
    # A real title but a JS/footer body and no LaTeXML content — ar5iv could not build the paper.
    html = '<title>[2505.08489] A Real Paper Title</title><div class="flex-wrap-footer"></div>'
    assert pa._source_unavailable(_soup(html), html) is True


def test_real_paper_with_sections_is_available() -> None:
    html = """
    <article class="ltx_document">
      <section class="ltx_section"><p class="ltx_p">Real body text here.</p></section>
    </article>
    """
    assert pa._source_unavailable(_soup(html), html) is False


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


_FIG = (
    '<figure class="ltx_figure"><figcaption class="ltx_caption">'
    '<span class="ltx_tag">Figure 1:</span> {body}</figcaption></figure>'
)


def test_caption_text_present_in_full_text_is_not_dropped() -> None:
    html = _FIG.format(body="we visualize edits made by our model on real user requests")
    # fullText glues the label prefix; whitespace-insensitive matching still finds the caption.
    full_text = "Figure 1 we visualize edits made by our model on real user requests. Body."
    assert pa._caption_text_dropped(_soup(html), full_text) == 0


def test_caption_text_absent_from_full_text_is_dropped() -> None:
    html = _FIG.format(body="we visualize edits made by our model on real user requests")
    assert pa._caption_text_dropped(_soup(html), "Unrelated body text only.") == 1


def test_caption_with_inline_math_matches_via_parser_normalization() -> None:
    # get_text renders <math> as "sigma"; the parser renders it \(\sigma\). Reading the caption
    # with the parser's own extraction makes both sides \(\sigma\), so a present caption is kept.
    html = (
        '<figure class="ltx_figure"><figcaption class="ltx_caption">'
        '<span class="ltx_tag">Figure 1:</span> '
        '<math alttext="\\sigma">sigma</math> represents the noisy portion of the training set'
        "</figcaption></figure>"
    )
    full_text = "Figure 1 \\(\\sigma\\) represents the noisy portion of the training set."
    assert pa._caption_text_dropped(_soup(html), full_text) == 0


def test_short_caption_is_not_judged() -> None:
    html = _FIG.format(body="A plot.")  # under 20 chars — too little to match reliably
    assert pa._caption_text_dropped(_soup(html), "unrelated") == 0


def test_caption_text_dropped_flags_content_loss() -> None:
    sig = {"caption_text_dropped": 2, "doc_empty_tables": 0,
           "doc_figures_no_assetref": 0, "coverage": 0.9}
    assert "caption_text_dropped" in pa._violations(sig)


def test_healthy_signals_produce_no_violations() -> None:
    sig = {"caption_text_dropped": 0, "doc_empty_tables": 0,
           "doc_figures_no_assetref": 0, "coverage": 0.82}
    assert pa._violations(sig) == []


def test_empty_table_and_missing_assetref_and_low_coverage_flag() -> None:
    sig = {"caption_text_dropped": 0, "doc_empty_tables": 1,
           "doc_figures_no_assetref": 1, "coverage": 0.30}
    v = pa._violations(sig)
    assert {"empty_table", "figure_missing_assetref", "coverage_low"} <= set(v)
