"""U4 Library — domain entities, value objects, exceptions (technology-agnostic core).

These are the INTERNAL domain types — distinct from the wire DTOs in ``docsuri_shared.dtos``
(which U4 reuses, never forks, see ``schemas.py``). Entities carry internal-only fields
(``owner_id``, ``normalized_query``, ``dedupe_key``) that MUST NEVER be serialized to the wire
(SEC-9). The mapping internal→DTO lives in ``validation.py``.

Authority note: object-ownership decisions are NOT made here — they delegate to U3's
``AuthorizationGuard`` (SEC-8 single decision point). The ``owner_id`` field + every repository
query being owner-scoped is the data-layer backstop (INV-L1, defense-in-depth).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from .schemas import LibraryItemMeta


# ── Exceptions ────────────────────────────────────────────────────────────────
class DomainException(Exception):
    """Base domain exception for the Library module."""


class ValidationException(DomainException):
    """Input failed SEC-5 validation (maps to HTTP 422)."""


class QuotaExceededError(DomainException):
    """Per-owner storage cap reached (BR-L2 saved=200 / BR-L4 library=1000; maps to HTTP 409)."""


class GatewayUnavailableError(DomainException):
    """The gateway-fronted search path is unavailable for rerun (maps to HTTP 503)."""


class NotFoundError(DomainException):
    """Resource absent OR owned by another principal.

    SEC-9: cross-owner access is generalized to *not found* so existence is never disclosed.
    The controller maps this to HTTP 404 regardless of whether the row truly does not exist or
    is simply not the caller's.
    """


class AuthorizationError(DomainException):
    """Authorization denied (fail-closed). Controllers generalize to 404 for owned resources."""


def _now() -> datetime:
    """Timezone-aware UTC instant (avoids the deprecated naive ``datetime.utcnow()``)."""
    return datetime.now(UTC)


# ── Entities (internal) ───────────────────────────────────────────────────────
@dataclass
class SavedSearch:
    """A user's saved query (US-L1/FR-8). Deduped per (owner_id, normalized_query) — BR-L1."""

    id: str
    owner_id: str
    query: str
    normalized_query: str
    created_at: datetime = field(default_factory=_now)
    label: str | None = None


@dataclass
class LibraryItem:
    """A paper saved to the personal library (US-L2/FR-9). Idempotent per (owner_id, arxiv_id)
    — BR-L3/QT-4. ``meta`` is a snapshot preserved independent of the live index (BR-L5,
    availability isolation, NFR-R1)."""

    id: str
    owner_id: str
    arxiv_id: str
    meta: LibraryItemMeta
    added_at: datetime = field(default_factory=_now)


@dataclass
class HistoryEntry:
    """A recorded search execution (US-L3/FR-10). Sourced from the at-least-once
    ``SearchExecutedEvent`` (FROZEN); deduped per ``dedupe_key`` so re-delivery is exactly-once
    (BR-L7/INV-L3). Retention is a rolling most-recent 500 per owner (BR-L6)."""

    id: str
    owner_id: str
    query: str
    executed_at: datetime
    result_count: int
    dedupe_key: str
