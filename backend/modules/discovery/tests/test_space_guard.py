"""Reader-side embedding-space guard (u2 business-rules §6 / nfr-design-patterns §1.1, N1).

The guard reads the active index's ``_meta.embedding`` manifest once at wiring time and, on a
mismatch with the reader identity, swaps in a sentinel embedder so every request degrades to
the tested lexical-only fallback instead of searching a foreign embedding space.
"""

from __future__ import annotations

import pytest

from discovery.adapters.space_guard import (
    MismatchedSpaceEmbedder,
    embedding_space_mismatch,
    guard_embedding_space,
    read_embedding_manifest,
)
from discovery.ports.search_ports import EmbeddingUnavailable

_READER = {"provider": "bedrock", "model": "cohere.embed-v4:0", "dimensions": 1024}


class _Indices:
    def __init__(self, mapping=None, error: Exception | None = None) -> None:
        self._mapping = mapping
        self._error = error

    def get_mapping(self, index):  # noqa: ARG002
        if self._error is not None:
            raise self._error
        return self._mapping


class _Client:
    def __init__(self, mapping=None, error: Exception | None = None) -> None:
        self.indices = _Indices(mapping, error)


def _mapping_with(meta: dict | None) -> dict:
    mappings: dict = {"properties": {}}
    if meta is not None:
        mappings["_meta"] = {"embedding": meta}
    # get_mapping responses are keyed by the CONCRETE index name even when queried by alias.
    return {"docsuri-corpus-v1": {"mappings": mappings}}


def test_read_manifest_resolves_alias_keyed_response() -> None:
    client = _Client(_mapping_with(_READER))
    assert read_embedding_manifest(client, "docsuri-corpus") == ("ok", _READER)


def test_read_manifest_distinguishes_absent_from_unreadable() -> None:
    # A stamp-less legacy index and a store outage at wiring time are different operator
    # signals — the guard must not claim "no manifest" about an index it could not ask.
    assert read_embedding_manifest(_Client(_mapping_with(None)), "idx") == ("absent", None)
    unreadable = _Client(error=RuntimeError("down"))
    assert read_embedding_manifest(unreadable, "idx") == ("unreadable", None)


def test_mismatch_detects_same_dim_different_model() -> None:
    # The scenario the dimension guard cannot catch, and it is a REAL one: Cohere Embed
    # Multilingual v3 and Embed v4 are both 1024-dimensional, so an index built with one and
    # queried with the other passes every shape check while the spaces are incompatible
    # (N1 / vector-spec §4).
    manifest = {"provider": "bedrock", "model": "cohere.embed-multilingual-v3", "dimensions": 1024}
    mismatch = embedding_space_mismatch(manifest, _READER)
    assert mismatch is not None and "model" in mismatch


def test_mismatch_none_when_manifest_matches_or_is_absent() -> None:
    assert embedding_space_mismatch(dict(_READER), _READER) is None
    assert embedding_space_mismatch(None, _READER) is None


def test_partial_manifest_compares_only_shared_keys() -> None:
    assert embedding_space_mismatch({"dimensions": 1024}, _READER) is None
    assert embedding_space_mismatch({"dimensions": 1536}, _READER) is not None


def test_guard_keeps_embedder_on_match_and_on_missing_manifest() -> None:
    embedder = object()
    matching = _Client(_mapping_with(_READER))
    assert guard_embedding_space(matching, "idx", _READER, embedder) is embedder
    # Legacy index without a manifest keeps serving (warned, not bricked).
    legacy = _Client(_mapping_with(None))
    assert guard_embedding_space(legacy, "idx", _READER, embedder) is embedder
    # Store unreachable at wiring time: availability first — serve, warn with the true cause.
    unreachable = _Client(error=RuntimeError("boot-time outage"))
    assert guard_embedding_space(unreachable, "idx", _READER, embedder) is embedder


def test_guard_swaps_in_sentinel_on_mismatch() -> None:
    manifest = {"provider": "bedrock", "model": "cohere.embed-v4", "dimensions": 1024}
    guarded = guard_embedding_space(_Client(_mapping_with(manifest)), "idx", _READER, object())
    assert isinstance(guarded, MismatchedSpaceEmbedder)
    with pytest.raises(EmbeddingUnavailable, match="space mismatch"):
        guarded.embed_query("확산 모델")
