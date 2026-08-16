"""Reader-side embedding-space guard (u2 business-rules §6 / nfr-design-patterns §1.1, N1).

The design's same-space invariant: the active index's embedding manifest is validated ONCE
against the reader's compiled embedding identity when the read path is wired; a mismatch
disables the vector leg (lexical-only fallback + alarm) instead of silently returning
semantically contaminated neighbors. The dimension guard in the embedders cannot catch a
same-dimension/different-model swap, which is why the manifest check exists — and the live case
is not hypothetical: Cohere Embed Multilingual v3 and Embed v4 are BOTH 1024-dimensional, so
re-pointing ``DOCSURI_BEDROCK_MODEL_ID`` at the other one passes every shape check and degrades
only into wrong neighbours.

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


# Bedrock cross-region inference profiles: ``global.``/``us.``/``eu.``/``apac.`` prefixes on an
# otherwise identical model id. They route the request to more regions — in exchange the account's
# daily token allowance doubles — and return the SAME vectors from the SAME model (verified
# byte-for-byte across all three ids for cohere.embed-v4). The routing prefix is therefore not a
# space difference, and comparing it as one would disable the vector leg over a delivery detail.
# Stripping it here rather than re-stamping every index keeps the manifest describing the model
# that actually made the vectors.
_ROUTING_PREFIXES = ("global.", "us.", "eu.", "apac.", "us-gov.")


def _same_space_model(model: Any) -> Any:
    if not isinstance(model, str):
        return model
    for prefix in _ROUTING_PREFIXES:
        if model.startswith(prefix):
            return model[len(prefix) :]
    return model


def embedding_space_mismatch(
    manifest: dict[str, Any] | None, reader_identity: dict[str, Any]
) -> str | None:
    """A human-readable mismatch description, or None when the spaces agree (or cannot be
    compared). Only keys present on BOTH sides are compared — a partial legacy manifest
    verifies what it can instead of false-alarming on missing fields.

    ``model`` is compared with its cross-region routing prefix stripped (see ``_ROUTING_PREFIXES``);
    everything the guard exists to catch — v3 vs v4, a provider swap, a dimension change — still
    differs after stripping."""
    if manifest is None:
        return None
    normalize = {"model": _same_space_model}
    mismatched = []
    for key in ("provider", "model", "dimensions"):
        if key not in manifest or key not in reader_identity:
            continue
        as_space = normalize.get(key, lambda value: value)
        if as_space(manifest[key]) != as_space(reader_identity[key]):
            mismatched.append(f"{key}: index={manifest[key]!r} reader={reader_identity[key]!r}")
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
