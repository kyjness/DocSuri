"""Shared test fixtures/helpers for docsuri-shared."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# tests/ -> python/ -> shared/   (the language-neutral SSOT root)
SHARED_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIRS = ("vector-spec", "dtos", "events")


def all_schema_paths() -> list[Path]:
    paths: list[Path] = []
    for group in SCHEMA_DIRS:
        paths.extend(sorted((SHARED_ROOT / group).glob("*.schema.json")))
    return paths


def load_schema(rel: str) -> dict:
    return json.loads((SHARED_ROOT / rel).read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def shared_root() -> Path:
    return SHARED_ROOT


def valid_index_record_dict() -> dict:
    """A schema-valid IndexRecord payload (all required fields, 1024-dim vector)."""
    return {
        "chunkId": "2106.01234#0",
        "paperId": "2106.01234",
        "version": 1,
        "vector": [0.0] * 1024,
        "section": "abstract",
        "lexicalTerms": "transformer attention retrieval",
        "blockRefs": [],
        "title": "Attention Is All You Need",
        "authors": ["A. Vaswani", "N. Shazeer"],
        "year": 2017,
        "arxivId": "2106.01234v1",
        "abstract": "We propose the Transformer, a model architecture ...",
        "abstractSnippet": "We propose the Transformer ...",
        "arxivUrl": "https://arxiv.org/abs/2106.01234",
        "categories": ["cs.LG", "cs.CL"],
    }


def valid_card_dict() -> dict:
    """A schema-valid ResultCardVM payload (externally exposed fields; Phase 2 Q2 adds
    source-neutral sourceName/sourceUrl)."""
    return {
        "title": "Attention Is All You Need",
        "authors": ["A. Vaswani"],
        "year": 2017,
        "arxivId": "2106.01234v1",
        "abstractSnippet": "We propose the Transformer ...",
        "relevance": 0.92,
        "arxivUrl": "https://arxiv.org/abs/2106.01234",
        "sourceName": "arXiv",
        "sourceUrl": "https://arxiv.org/abs/2106.01234",
    }
