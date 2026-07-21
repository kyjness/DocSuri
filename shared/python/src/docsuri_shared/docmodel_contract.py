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
# @9: a paragraph LaTeXML emitted as ``<span class="ltx_p">`` (which is what it does inside a
# minipage / inline-sectional block, where HTML forbids <p>) is kept instead of dropped. Measured
# on real papers, that silently lost whole "Finding N:"/"Assumption N:" subsections — 34 body
# paragraphs on arXiv:2503.02879, 18 on arXiv:2505.19488. Recovering them adds blocks, shifts the
# per-section paragraph ids after each recovered one, and changes fullText, so caches must rebuild.
# @10: two figure-float fixes on the HTML path, both changing how many FigureBlocks a document
# has (so every later figure's ordinal and asset id shifts). Two figures set side by side share
# one LaTeXML <figure> container with a numbered caption on each panel; that container used to
# yield ONE block, dropping the second figure from the document and leaving the first unlabelled
# (hence unmatchable to a page-crop). And a caption-less float holding several images — a funder
# logo strip — no longer yields a block at all, since nothing can ever image it.
# @11: algorithm listings on the PDF/GROBID path. GROBID has no algorithm concept — it files a
# listing as one or more <formula> elements, sometimes promoting its heading to the section title
# — so a listing was reachable only as a page-crop image: readable, but absent from search and
# unquotable. A listing now becomes a CodeBlock carrying its extracted text AND its crop. Formula
# ordinals after a converted listing shift, so cached doc-models and their crops must rebuild.
# @12: formulas on the PDF/GROBID path can carry `latexOcr` — LaTeX read back out of their page
# crop, indexed for search and never rendered. That changes fullText (an equation contributes text
# where it contributed none), so cached doc-models must rebuild to gain it.
DOCMODEL_PARSER_VERSION = "docmodel-parser@12"
# 1.1.0: additive optional meta.macros (consumers ignore if unset).
# 1.2.0: additive optional CodeBlock.assetRef — a listing the PDF path could only approximate as
# text also carries its page crop, so the text stays searchable while the image renders faithfully.
# 1.3.0: additive optional FormulaBlock.latexOcr — an approximation of an equation that exists
# only as pixels, searchable but never a render source (the crop stays what is displayed).
DOCMODEL_SCHEMA_VERSION = "1.3.0"

__all__ = ["DOCMODEL_PARSER_VERSION", "DOCMODEL_SCHEMA_VERSION"]
