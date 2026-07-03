"""Shared doc-model cache contract constants."""

from __future__ import annotations

# @2: formula LaTeX is sanitized of non-math layout markup and carries e-print preamble
# macros on meta.macros (a bump invalidates cached doc-models so they rebuild).
# @3: retroactive bump for the PR #318 parser fixes (multipanel figure splitting +
# algorithm-listing rendering) that shipped without one — cached pre-fix doc-models
# never self-heal otherwise (builder cache hit and reader freshness check both key
# on this constant, and the content-blind dedup gate skips re-embedding regardless).
DOCMODEL_PARSER_VERSION = "docmodel-parser@3"
# 1.1.0: additive optional meta.macros (consumers ignore if unset).
DOCMODEL_SCHEMA_VERSION = "1.1.0"

__all__ = ["DOCMODEL_PARSER_VERSION", "DOCMODEL_SCHEMA_VERSION"]
