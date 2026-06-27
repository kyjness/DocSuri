"""Embedding contract constants + IndexRecord (vector-spec.md — 🔒 FROZEN).

``IndexRecord`` is generated from ``shared/vector-spec/index-record.schema.json``.
The embedding *config* (model/dims/metric/...) is NOT a per-record shape, so it is
not codegen'd — it lives in ``shared/vector-spec/vector-spec.yaml`` and is mirrored
here as constants. ``tests/test_vector_spec.py`` asserts the two never drift.

INVARIANT (vector-spec.md §4): the single writer (U1) and single reader (U2) consume
the SAME ``specVersion`` / ``model`` / ``dimensions`` / ``distanceMetric``. Any change
to ``specVersion`` / ``model`` / ``dimensions`` is a one-way, full-corpus re-embed.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from ._generated.vector_spec.index_record_schema import ArxivCategory, DocModelBlockRef, IndexRecord

__all__ = [
    "ArxivCategory",
    "DocModelBlockRef",
    "IndexRecord",
    "VectorSpec",
    "EMBEDDING_SPEC",
    "SPEC_VERSION",
    "MODEL",
    "DIMENSIONS",
    "DISTANCE_METRIC",
    "NORMALIZE",
    "INPUT_TYPE_WRITER",
    "INPUT_TYPE_READER",
    "assert_same_space",
]

# Mirror of shared/vector-spec/vector-spec.yaml (guarded by tests/test_vector_spec.py).
SPEC_VERSION = "v2"
MODEL = "Cohere Embed v4 (Bedrock)"
DIMENSIONS = 1024
DISTANCE_METRIC = "cosine"
NORMALIZE = True
# inputType ASYMMETRY (Cohere v3 required param): writer embeds documents, reader the query.
INPUT_TYPE_WRITER = "search_document"  # U1 — IndexRecord.vector
INPUT_TYPE_READER = "search_query"  # U2 — HybridRetriever query embedding


@dataclass(frozen=True, slots=True)
class VectorSpec:
    """Immutable embedding-space descriptor. Writer and reader must share one of these."""

    spec_version: str
    model: str
    dimensions: int
    distance_metric: str
    normalize: bool
    input_type_writer: str
    input_type_reader: str


EMBEDDING_SPEC = VectorSpec(
    spec_version=SPEC_VERSION,
    model=MODEL,
    dimensions=DIMENSIONS,
    distance_metric=DISTANCE_METRIC,
    normalize=NORMALIZE,
    input_type_writer=INPUT_TYPE_WRITER,
    input_type_reader=INPUT_TYPE_READER,
)


# Fields that define the embedding SPACE (must match between writer and reader).
# input_type_* are intentionally asymmetric ROLES (writer=search_document /
# reader=search_query), so they are excluded from the same-space comparison.
_SPACE_FIELDS = ("spec_version", "model", "dimensions", "distance_metric", "normalize")


def assert_same_space(writer: VectorSpec, reader: VectorSpec) -> None:
    """Enforce the writer↔reader same-space invariant (vector-spec.md §4).

    Compares the FULL space identity (specVersion, model, dimensions, distanceMetric,
    normalize) — NOT just specVersion — so it catches the silent failure mode where the
    model or dimensions changed but specVersion was not bumped. A mismatch means the
    index was written in a different embedding space than the one being queried → search
    is invalid → a full re-embed is required. CI/deploy SHOULD call this to fail fast.
    """
    mismatched = [
        f.name
        for f in dataclasses.fields(VectorSpec)
        if f.name in _SPACE_FIELDS and getattr(writer, f.name) != getattr(reader, f.name)
    ]
    if mismatched:
        raise ValueError(
            f"VectorSpec mismatch on {', '.join(mismatched)} — index inconsistent, full "
            f"re-embed required (vector-spec.md §4). writer={writer} reader={reader}"
        )
