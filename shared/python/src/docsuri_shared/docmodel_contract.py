"""Shared doc-model cache contract constants."""

from __future__ import annotations

# @2: formula LaTeX is sanitized of non-math layout markup and carries e-print preamble
# macros on meta.macros (a bump invalidates cached doc-models so they rebuild).
DOCMODEL_PARSER_VERSION = "docmodel-parser@2"
# 1.1.0: additive optional meta.macros (consumers ignore if unset).
DOCMODEL_SCHEMA_VERSION = "1.1.0"

__all__ = ["DOCMODEL_PARSER_VERSION", "DOCMODEL_SCHEMA_VERSION"]
