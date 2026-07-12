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
DOCMODEL_PARSER_VERSION = "docmodel-parser@7"
# 1.1.0: additive optional meta.macros (consumers ignore if unset).
DOCMODEL_SCHEMA_VERSION = "1.1.0"

__all__ = ["DOCMODEL_PARSER_VERSION", "DOCMODEL_SCHEMA_VERSION"]
