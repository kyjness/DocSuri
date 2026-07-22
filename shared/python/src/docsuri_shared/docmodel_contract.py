"""Shared doc-model cache contract constants."""

from __future__ import annotations

# @2: formula LaTeX is sanitized of non-math layout markup and carries e-print preamble
# macros on meta.macros (a bump invalidates cached doc-models so they rebuild).
# @3: retroactive bump for the PR #318 parser fixes (multipanel figure splitting +
# algorithm-listing rendering) that shipped without one — cached pre-fix doc-models
# never self-heal otherwise (builder cache hit and reader freshness check both key
# on this constant, and the content-blind dedup gate skips re-embedding regardless).
# @4: doc-model HTML source is ar5iv-only + MathML <semantics> renders presentation only
# (drops the annotation-xml double-output). Both change fullText for the same paper, so old
# @2/@3 caches (incl. LaTeX-garbled algorithm blocks on ar5iv) must rebuild.
# @5: formula LaTeX is sanitized of a broader set of never-math markup that leaks into alttext and
# (under KaTeX throwOnError=false) collapses the WHOLE formula to raw source text: pgf/xcolor
# colour selection (\definecolor, \color[model]{spec}), \eqref/\ref/\cite-family cross-references
# and citations, \mathversion font switches, \leafmode, and \mbox/\hbox (rewritten to \text).
# Changes stored LaTeX, so affected caches must rebuild.
# @6: two more formula/listing fidelity fixes. Formula: ``\big{(}``/``\Big{]}`` sizing commands
# whose delimiter LaTeXML brace-wrapped are unwrapped (KaTeX rejects the braced form and collapses
# the whole formula). Code/algorithm listings: the content-MathML ``<annotation-xml>`` is dropped
# alongside the TeX ``<annotation>`` so an inline symbol no longer triples into
# "ηm"+"subscript"+"𝜂𝑚". Both change stored output, so affected caches must rebuild.
# @7: listings-in-math and box-command leak fixes for papers embedding \lstinline via a custom box
# macro (arXiv:2410.14706 \cybertron → \Colorbox{colour}{\lstinline{…}}). Body text: an unexpanded
# ``\Colorbox`` ``ltx_ERROR`` node and its loose ``{colour}`` argument are dropped instead of
# leaking
# as literal source. Formula alttext: the ``\Colorbox``/``\lstinline``/``\lst@…`` listings machinery
# and residual ``{ltx_lst_*}`` class tags are stripped so the boxed identifiers render rather than
# collapsing the whole formula. Both change stored output, so affected caches must rebuild.
# @8: a table whose rows could not be reconstructed keeps its caption instead of being dropped
# whole (GROBID emits a bare <table/> when cell reconstruction fails; LaTeXML can emit a table
# figure with no tabular body). That adds a block, so later tables shift ordinal and their
# page-crop asset ids shift with them. The same rebuild also re-renders figure page-crops, which
# now recover the vector graphic GROBID reports no <graphic> for — cached doc-models otherwise
# keep both the missing caption and the caption-only figure images.
# @9: one generation covering a completeness pass over both paths — every item below changes
# stored output (block counts, ordinals, or fullText), so cached doc-models and their crops must
# rebuild.
# - HTML path: a paragraph LaTeXML emitted as ``<span class="ltx_p">`` (what it does inside a
#   minipage / inline-sectional block, where HTML forbids <p>) is kept instead of dropped —
#   measured on real papers that silently lost whole "Finding N:"/"Assumption N:" subsections
#   (34 body paragraphs on arXiv:2503.02879, 18 on arXiv:2505.19488).
# - HTML path: two figures set side by side share one <figure> container with a numbered caption
#   on each panel; that container now yields one block per panel instead of one block total
#   (which dropped the second figure and left the first unlabelled, hence unmatchable to a
#   page-crop). A caption-less float holding several images — a funder logo strip — yields no
#   block at all, since nothing can ever image it.
# - PDF path: captions are read one column segment at a time, so a caption the two-column merge
#   buried mid-line is found, and a table captioned ABOVE its rows is cropped; a table's crop
#   grows over its unruled rows instead of stopping at the ruled band.
# - PDF path: algorithm listings become CodeBlocks carrying extracted text AND their crop. GROBID
#   has no algorithm concept — it files a listing as <formula> elements — so a listing used to be
#   reachable only as an image: readable, but absent from search and unquotable.
# - PDF path: formulas can carry `latexOcr`, LaTeX read back out of their page crop, indexed for
#   search and never rendered; and a table GROBID merged into unusable cells can be re-read from
#   the page when every rebuilt number verifies against the printed text.
DOCMODEL_PARSER_VERSION = "docmodel-parser@9"
# 1.1.0: additive optional meta.macros (consumers ignore if unset).
# 1.2.0: two additive optional fields for the PDF path, both keeping an approximation searchable
# without letting it become what the reader sees. CodeBlock.assetRef — a listing the path could
# only approximate as text also carries its page crop. FormulaBlock.latexOcr — an equation that
# exists only as pixels, searchable but never a render source (the crop stays what is displayed).
DOCMODEL_SCHEMA_VERSION = "1.2.0"

__all__ = ["DOCMODEL_PARSER_VERSION", "DOCMODEL_SCHEMA_VERSION"]
