"""Cheap, deterministic token estimate shared across the input-shaping domain.

A single ~4-chars/token heuristic backs the length route (single-call vs map-reduce),
the map-reduce chunker, and the structured-translator chunker — they must agree so a body
the router calls "single-call" isn't re-measured larger downstream. Real caps are a runtime
tune; this only needs to be consistent, not exact.
"""

from __future__ import annotations

CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // CHARS_PER_TOKEN)
