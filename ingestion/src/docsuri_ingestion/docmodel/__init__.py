"""doc-model production (BR-30 pivot): deterministic LaTeXML HTML -> structured doc-model.

Public surface:
  - ``parse_html_to_docmodel`` — pure parser (HTML -> validated ``DocModel``).
  - ``DocModelBuilder`` — lazy on-demand builder with (paperId, version) cache (D6).
"""

from __future__ import annotations

from docsuri_ingestion.docmodel.builder import (
    PARSER_VERSION,
    SCHEMA_VERSION,
    DocModelBuilder,
)
from docsuri_ingestion.docmodel.parser import parse_html_to_docmodel

__all__ = [
    "DocModelBuilder",
    "parse_html_to_docmodel",
    "PARSER_VERSION",
    "SCHEMA_VERSION",
]
