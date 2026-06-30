"""Bounded HTTP body reads for untrusted external fetches (NFR §0.5 "size limit").

The worker pulls arXiv HTML/PDF, GROBID TEI, and — for Semantic Scholar / OpenAlex — PDFs from
arbitrary third-party hosts named in API responses. None of those have a trustworthy
Content-Length, so a hostile/oversized body could exhaust worker memory before any parser runs.
``read_capped`` reads a *streamed* httpx response with a hard byte ceiling and aborts past it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    import httpx

# PDFs/tarballs are the large payloads; 64 MiB comfortably covers real arXiv papers while
# capping a decompression/oversize attack.
# ponytail: single global ceiling; split per-content-type only if a legitimate fetch is rejected.
MAX_RESPONSE_BYTES = 64 * 1024 * 1024


class ResponseTooLargeError(Exception):
    """Raised when a response body exceeds the byte cap mid-stream."""


def read_capped(response: httpx.Response, *, max_bytes: int = MAX_RESPONSE_BYTES) -> bytes:
    """Read a streamed response body, raising ``ResponseTooLargeError`` past ``max_bytes``.

    The caller must open the response with ``client.stream(...)`` (lazy body) so the cap can
    abort before the whole payload is buffered.
    """
    total = 0
    chunks: list[bytes] = []
    for chunk in response.iter_bytes():
        total += len(chunk)
        if total > max_bytes:
            raise ResponseTooLargeError(f"response body exceeded {max_bytes} byte cap")
        chunks.append(chunk)
    return b"".join(chunks)
