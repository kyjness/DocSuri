"""docsuri_shared — Python binding for the DocSuri shared contracts.

The language-neutral JSON Schema in ``shared/{vector-spec,dtos,events}`` is the source
of truth (§5-B); the pydantic models in :mod:`docsuri_shared.dtos` /
:mod:`docsuri_shared.events` / :mod:`docsuri_shared.vector_spec` are GENERATED from it
(``tools/generate.py``). :mod:`docsuri_shared.ports` and :mod:`docsuri_shared.ids` are
hand-authored from ``ports.md`` / ``vector-spec.md`` (behavior a schema cannot express).

Import the namespaced modules for full contracts::

    from docsuri_shared import dtos, events, ports, vector_spec
    from docsuri_shared.ids import chunk_id

The most load-bearing names are re-exported at the top level for convenience.
"""

from __future__ import annotations

from . import docmodel_contract, dtos, events, ids, ports, vector_spec
from .docmodel_contract import DOCMODEL_PARSER_VERSION, DOCMODEL_SCHEMA_VERSION
from .ids import chunk_id, paper_id_prefix
from .vector_spec import (
    DIMENSIONS,
    EMBEDDING_SPEC,
    SPEC_VERSION,
    DocModelBlockRef,
    IndexRecord,
    VectorSpec,
    assert_same_space,
)

__all__ = [
    # submodules
    "dtos",
    "events",
    "ports",
    "vector_spec",
    "docmodel_contract",
    "ids",
    # doc-model cache contract
    "DOCMODEL_PARSER_VERSION",
    "DOCMODEL_SCHEMA_VERSION",
    # vector-spec (FROZEN)
    "IndexRecord",
    "DocModelBlockRef",
    "VectorSpec",
    "EMBEDDING_SPEC",
    "SPEC_VERSION",
    "DIMENSIONS",
    "assert_same_space",
    # ids
    "chunk_id",
    "paper_id_prefix",
]
