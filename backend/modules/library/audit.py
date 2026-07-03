"""U4 Library — audit event + default sink (SEC-13, BR-L10).

Services emit an ``AuditEvent`` on every mutating op (save/delete, add/remove, clear). The
payload is deliberately minimal and carries NO sensitive or internal fields (SEC-9): no query
text, no meta snapshot, no owner userId in the clear — only the action, the entity kind, the
entity id, and an opaque owner reference. The default ``InMemoryAuditSink`` keeps events in a
ring buffer for tests/dev; production swaps in a sink that forwards to U6/ops.
"""

from __future__ import annotations

import hashlib
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True, slots=True)
class AuditEvent:
    action: str  # e.g. "saved_search.create", "library.remove", "history.clear"
    entity_type: str  # "saved_search" | "library_item" | "history"
    entity_id: str | None  # id of the affected row (None for bulk e.g. clear)
    owner_ref: str  # opaque owner reference (NOT exposed externally, SEC-9)
    at: datetime


class InMemoryAuditSink:
    """Default sink — a bounded ring buffer. Satisfies the ``AuditSink`` port structurally."""

    def __init__(self, maxlen: int = 1024) -> None:
        self._events: deque[AuditEvent] = deque(maxlen=maxlen)

    def record(self, event: AuditEvent) -> None:
        self._events.append(event)

    @property
    def events(self) -> list[AuditEvent]:
        return list(self._events)


def make_event(action: str, entity_type: str, entity_id: str | None, owner_ref: str) -> AuditEvent:
    # Hash the owner_ref (user_id) to mask/tokenize it in internal audit payloads (SEC-9).
    # ponytail: unsalted SHA256 is fine for an internal-only ring buffer (never on the wire);
    # upgrade to keyed HMAC if owner_ref ever needs true de-identification (rainbow-resistant).
    opaque_ref = hashlib.sha256(owner_ref.encode("utf-8")).hexdigest()
    return AuditEvent(
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        owner_ref=opaque_ref,
        at=datetime.now(UTC),
    )
