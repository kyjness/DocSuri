"""doc-model production (BR-30 pivot): deterministic LaTeXML HTML -> structured doc-model.

Public surface:
  - ``parse_html_to_docmodel`` — pure parser (HTML -> validated ``DocModel``).
  - ``parse_text_to_docmodel`` — PDF/GROBID fallback text -> minimal ``DocModel``.
  - ``DocModelBuilder`` — eager/lazy builder with (paperId, version) cache (D6).
"""

from __future__ import annotations

from docsuri_ingestion.docmodel.builder import (
    PARSER_VERSION,
    SCHEMA_VERSION,
    DocModelBuilder,
)
from docsuri_ingestion.docmodel.parser import parse_html_to_docmodel, parse_text_to_docmodel

__all__ = [
    "DocModelBuilder",
    "parse_html_to_docmodel",
    "parse_text_to_docmodel",
    "PARSER_VERSION",
    "SCHEMA_VERSION",
]
