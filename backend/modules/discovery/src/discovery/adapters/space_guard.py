"""Reader-side embedding-space guard (u2 business-rules §6 / nfr-design-patterns §1.1, N1).

The design's same-space invariant: the active index's embedding manifest is validated ONCE
against the reader's compiled embedding identity when the read path is wired; a mismatch
disables the vector leg (lexical-only fallback + alarm) instead of silently returning
semantically contaminated neighbors. The dimension guard in the embedders cannot catch a
same-dimension/different-model swap (e.g. OpenAI 1024-dim queries against a Cohere 1024-dim
index — exactly the solo-local provider switch), which is why the manifest check exists.

The manifest is ``mappings._meta.embedding`` (``{"provider", "model", "dimensions"}``),
stamped by whichever writer created the index (``docsuri_shared.index_spec.papers_index_body``).
A legacy index without the stamp cannot be verified — that is logged, not failed, so
pre-manifest local indices keep serving (they get stamped on their next rebuild).
"""

from __future__ import annotations

import logging
from typing import Any

from ..ports.search_ports import EmbeddingUnavailable

_log = logging.getLogger(__name__)


def read_embedding_manifest(client: Any, index: str) -> tuple[str, dict[str, Any] | None]:
    """``(status, manifest)`` for the active index — status ∈ ``"ok"`` / ``"absent"`` /
    ``"unreadable"``. The two None cases are deliberately distinct: an index WITHOUT a stamp
    (legacy) is a different operator signal than a store that could not be asked (boot-time
    outage) — conflating them would log "no manifest" about an index that has one.

    ``index`` may be an alias — the mapping response is keyed by the concrete index name(s),
    so the first entry is taken (the read alias points at exactly one index by cutover rule).
    Best-effort either way: the guard must never block wiring (availability first)."""
    try:
        response = client.indices.get_mapping(index=index)
        first = next(iter(response.values()))
        mappings = first["mappings"]
    except Exception:  # noqa: BLE001 — store unreachable/unexpected shape at wiring time
        return "unreadable", None
    manifest = mappings.get("_meta", {}).get("embedding") if isinstance(mappings, dict) else None
    if isinstance(manifest, dict):
        return "ok", manifest
    return "absent", None


def embedding_space_mismatch(
    manifest: dict[str, Any] | None, reader_identity: dict[str, Any]
) -> str | None:
    """A human-readable mismatch description, or None when the spaces agree (or cannot be
    compared). Only keys present on BOTH sides are compared — a partial legacy manifest
    verifies what it can instead of false-alarming on missing fields."""
    if manifest is None:
        return None
    mismatched = [
        f"{key}: index={manifest[key]!r} reader={reader_identity[key]!r}"
        for key in ("provider", "model", "dimensions")
        if key in manifest and key in reader_identity and manifest[key] != reader_identity[key]
    ]
    return "; ".join(mismatched) or None


class MismatchedSpaceEmbedder:
    """Sentinel EmbeddingAdapter wired when the manifest check fails: every call raises
    ``EmbeddingUnavailable``, so the orchestrator's tested per-request fallback serves
    lexical-only (DegradedResultDTO with the banner) — the design's "disable the vector leg"
    outcome with zero new domain code. The alarm is the wiring-time log; per-request noise is
    kept out of the hot path."""

    def __init__(self, reason: str) -> None:
        self._reason = reason

    def embed_query(self, text: str) -> list[float]:  # noqa: ARG002
        raise EmbeddingUnavailable(
            f"embedding space mismatch — vector leg disabled: {self._reason}"
        )


def guard_embedding_space(
    client: Any, index: str, reader_identity: dict[str, Any], embedder: Any
) -> Any:
    """Wiring-time check: return ``embedder`` when the index manifest matches (or cannot be
    verified — logged with the accurate cause), or a ``MismatchedSpaceEmbedder`` (+ ERROR
    alarm log) on a mismatch."""
    status, manifest = read_embedding_manifest(client, index)
    if status == "unreadable":
        _log.warning(
            "discovery: could not read index %s mapping at wiring time — same-space "
            "invariant UNVERIFIED for this process (vector-spec §4); if the index carries a "
            "mismatched manifest, restart once the store is reachable to re-run the guard",
            index,
        )
        return embedder
    if status == "absent":
        _log.warning(
            "discovery: index %s carries no embedding manifest (_meta.embedding) — "
            "same-space invariant unverified (vector-spec §4); it will be stamped on the "
            "next index rebuild",
            index,
        )
        return embedder
    mismatch = embedding_space_mismatch(manifest, reader_identity)
    if mismatch is None:
        return embedder
    _log.error(
        "discovery: embedding space MISMATCH on index %s (%s) — disabling the vector leg, "
        "search degrades to lexical-only until the corpus is re-embedded or the reader "
        "provider/model is corrected (vector-spec §4; u2 business-rules §6)",
        index,
        mismatch,
    )
    return MismatchedSpaceEmbedder(mismatch)
