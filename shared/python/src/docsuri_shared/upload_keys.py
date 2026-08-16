"""The path-segment grammar of a user-upload S3 key — one definition for producer and consumer.

A user document lands in S3 under a key whose segments name the owner, the scope and the
attachment (``uploads/<module>/<owner>/<scope>/<attachment>/<file>``). The backend BUILDS those
keys when it accepts an upload; the ingestion worker CHECKS a queued job's key against the owner
that job claims before it reads a single byte. That check is only sound if both sides derive the
owner segment the same way — and until this module existed each side carried its own copy of the
rule, which agreed by inspection and by nothing else. A change to the fallback, the length cap or
the character class on one side would have had the worker rejecting every job the backend
enqueued, as an "invalid payload", with nothing pointing at the real cause.

So the rule lives here and both import it. This is a contract, not a utility: it is deliberately
one function, and it is not a general slug helper — ``_safe_filename`` in the backend shares the
character class but not the replacement or the cap, and stays where it is.
"""

from __future__ import annotations

import re

__all__ = ["key_segment"]

# What a segment may carry; anything else collapses to a single ``-``.
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_LEN = 128


def key_segment(value: str | None, *, fallback: str = "x") -> str:
    """``value`` as a key path segment: unsafe runs → ``-``, edges trimmed, capped, never empty.

    ``fallback`` is what an input that reduces to nothing becomes (``""``, ``"-"``, ``"///"``);
    the producer names it per segment (``"attachment"`` for the attachment id) so an empty id is
    still a readable path rather than a bare ``x``.
    """
    handle = _UNSAFE.sub("-", (value or "").strip()).strip("-")
    return (handle or fallback)[:_MAX_LEN]
