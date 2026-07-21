"""Bounded HTTP reads and failure mapping for untrusted external fetches (NFR §0.5).

The worker pulls arXiv HTML/PDF, GROBID TEI, and — for Semantic Scholar / OpenAlex — PDFs from
arbitrary third-party hosts named in API responses. None of those have a trustworthy
Content-Length, so a hostile/oversized body could exhaust worker memory before any parser runs.
``read_capped`` reads a *streamed* httpx response with a hard byte ceiling and aborts past it.

``raise_for_fetch_status`` and ``http_failures_as_ingestion_errors`` put every outbound fetch on
one failure taxonomy, so "which HTTP outcome is retriable" is decided once rather than per
adapter.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING

from .domain.enums import FailureReason
from .domain.errors import PermanentIngestionError, RetriableIngestionError

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


def raise_for_fetch_status(status_code: int, *, stage: str, source_label: str) -> None:
    """Map an HTTP status onto the failure taxonomy: 429/5xx retriable, other 4xx permanent.

    429 carries RATE_LIMITED so budget/pacing signals stay distinguishable from a plain outage.
    """
    if status_code == 429 or status_code >= 500:
        raise RetriableIngestionError(
            f"{source_label} returned {status_code}",
            reason=FailureReason.RATE_LIMITED
            if status_code == 429
            else FailureReason.FETCH_FAILURE,
            stage=stage,
        )
    if status_code >= 400:
        raise PermanentIngestionError(
            f"{source_label} returned {status_code}",
            reason=FailureReason.FETCH_FAILURE,
            stage=stage,
        )


@contextmanager
def http_failures_as_ingestion_errors(
    *,
    stage: str,
    timeout_message: str,
    failure_message: str,
    rejected_message: str = "response rejected by the fetch guards",
    also_rejected: tuple[type[Exception], ...] = (),
) -> Iterator[None]:
    """Translate httpx transport faults and body rejections into ingestion errors.

    Transport faults are transient by definition (retriable); a body the guards refuse — over the
    size cap, or ``also_rejected`` such as an SSRF-blocked host — is permanent, since retrying
    fetches the same oversized or non-public target again.

    ``rejected_message`` only surfaces for callers that actually run a guard (``read_capped`` or an
    ``also_rejected`` type), so it is defaulted rather than required: a caller reading a small,
    authenticated, fixed endpoint has no rejection path to name.
    """
    import httpx

    try:
        yield
    except httpx.TimeoutException as exc:
        raise RetriableIngestionError(
            timeout_message, reason=FailureReason.TIMEOUT, stage=stage
        ) from exc
    except httpx.HTTPError as exc:
        raise RetriableIngestionError(
            failure_message, reason=FailureReason.FETCH_FAILURE, stage=stage
        ) from exc
    except (ResponseTooLargeError, *also_rejected) as exc:
        raise PermanentIngestionError(
            rejected_message, reason=FailureReason.FETCH_FAILURE, stage=stage
        ) from exc
