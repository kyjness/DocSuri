"""Drift guards for the block -> text rule.

Three places answer "which fields of a block carry renderable text": the fullText projection,
the doc-model builder's truncation gate (both via ``block_text_parts``), and the chunker's
``_docmodel_block_text`` (which reads validated blocks instead of dicts, because it runs on the
chunking hot path). A new block type — or a new text-bearing field on an existing one — must not
land in one and be forgotten in the others.
"""

from __future__ import annotations

import typing

from docsuri_shared.dtos import Block

from docsuri_ingestion.docmodel.builder import _non_abstract_body_len
from docsuri_ingestion.docmodel.parser import _project_full_text, block_text_parts
from docsuri_ingestion.processors import _docmodel_block_text

# One populated block per type in the DocModel union, each carrying text that must survive
# projection. Keyed by the block's ``type`` discriminator.
_POPULATED_BLOCKS: dict[str, dict] = {
    "paragraph": {"id": "s1.p1", "type": "paragraph", "text": "Paragraph prose."},
    "code": {"id": "s1.c1", "type": "code", "text": "print('hello')"},
    "formula": {"id": "s1.f1", "type": "formula", "latex": "E = mc^{2}"},
    "list": {
        "id": "s1.l1",
        "type": "list",
        "ordered": False,
        "items": [{"text": "first item"}, {"text": "second item"}],
    },
    "figure": {
        "id": "s1.fig1",
        "type": "figure",
        "assetRef": {"assetId": "asset-1", "type": "figure", "ordinal": 0},
        "anchorLabel": "Figure 1",
        "caption": "A plot.",
    },
    "table": {
        "id": "s1.t1",
        "type": "table",
        "anchorLabel": "Table 1",
        "caption": "Main results.",
        "rows": [{"cells": [{"text": "Group"}, {"text": "Acc"}]}],
    },
}


def _union_block_types() -> set[str]:
    """The ``type`` discriminator of every member of the DocModel Block union."""
    members = typing.get_args(Block.model_fields["root"].annotation)
    return {typing.get_args(m.model_fields["type"].annotation)[0] for m in members}


def test_block_projection_covers_every_block_type() -> None:
    # If this fails, the DocModel Block union gained a type: add it to _POPULATED_BLOCKS and
    # teach block_text_parts + _docmodel_block_text how to read its text.
    assert _union_block_types() == set(_POPULATED_BLOCKS)

    for kind, block in _POPULATED_BLOCKS.items():
        parts = block_text_parts(block)
        assert parts, f"block_text_parts yields nothing for {kind!r}"
        assert any(part.strip() for part in parts), f"{kind!r} projected to blank text"

        validated = Block.model_validate(block).root
        assert _docmodel_block_text(validated).strip(), (
            f"_docmodel_block_text yields nothing for {kind!r}"
        )


def test_truncation_gate_counts_the_same_fragments_as_full_text() -> None:
    # The gate must measure what the doc-model actually carries. Anchor labels and table cells
    # are body text, so they count — a paper whose body is mostly tables is not "truncated".
    sections = [
        {"id": "s1", "title": "Abstract", "blocks": [_POPULATED_BLOCKS["paragraph"]]},
        {"id": "s2", "title": "Results", "blocks": list(_POPULATED_BLOCKS.values())},
    ]

    class _Doc:
        def model_dump(self, mode: str = "json") -> dict:
            del mode
            return {"sections": sections}

    body_len = _non_abstract_body_len(_Doc())
    expected = sum(
        len(part) for block in _POPULATED_BLOCKS.values() for part in block_text_parts(block)
    )
    assert body_len == expected

    # The abstract section is excluded, so its paragraph is not double counted.
    assert body_len < len(_project_full_text(sections))

    # Anchor labels reach the gate — this is the behaviour that changed when the gate stopped
    # keeping its own field list and started measuring the projection's fragments.
    assert "Table 1" in "".join(block_text_parts(_POPULATED_BLOCKS["table"]))
    assert "Figure 1" in "".join(block_text_parts(_POPULATED_BLOCKS["figure"]))
