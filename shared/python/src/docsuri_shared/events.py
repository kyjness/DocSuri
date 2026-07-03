"""Event-backbone payloads (events.md). Generated from ``shared/events/*.schema.json``.

All events are async, at-least-once → consumers MUST be idempotent (events.md §1).
The per-group union models (``IngestionEvent`` / ``IncidentEvent``) are convenience root
models for "parse any event in this group"; the named member models are the concrete
payloads producers emit.

There is deliberately NO ``AccountSignal`` union: ``SignupAbuseSignal`` and
``AuthFailureSignal`` are structurally identical ({reason, timestamp?}), so a shape-based
union could never discriminate them (it would always resolve to the first). Account
signals are distinguished by event TOPIC, not payload shape — consume the specific
member type for the topic you subscribe to.

``SearchExecutedEvent`` is 🔒 FROZEN (U2 producer ↔ U4 consumer).
"""

from __future__ import annotations

# U3 account/auth signals (account-signals.schema.json) — no union (see module docstring)
from ._generated.events.account_signals_schema import (
    AccountCreated,
    AccountDeleted,
    AuthFailureSignal,
    SignupAbuseSignal,
)

# U6 AI incidents (incidents.schema.json)
from ._generated.events.incidents_schema import (
    Class as IncidentClass,
)
from ._generated.events.incidents_schema import (
    ClassifiedIncident,
    OpsAlert,
    Severity,
)
from ._generated.events.incidents_schema import (
    U6AiIncidentEvents as IncidentEvent,
)

# U1 ingestion backbone (ingestion.schema.json)
from ._generated.events.ingestion_schema import (
    IngestError,
    IngestionFailureSignal,
    NewArxivEvent,
)
from ._generated.events.ingestion_schema import (
    U1IngestionBackboneEvents as IngestionEvent,
)

# U1 → U4 (paper-retracted.schema.json)
from ._generated.events.paper_retracted_schema import PaperRetractedEvent

# U2 → U4 (search-executed.schema.json) — 🔒 FROZEN
from ._generated.events.search_executed_schema import SearchExecutedEvent

__all__ = [
    # frozen
    "SearchExecutedEvent",
    "PaperRetractedEvent",
    # ingestion
    "NewArxivEvent",
    "IngestionFailureSignal",
    "IngestError",
    "IngestionEvent",
    # accounts (no union — structurally identical members; discriminate by topic)
    "AccountCreated",
    "SignupAbuseSignal",
    "AuthFailureSignal",
    "AccountDeleted",
    # incidents
    "ClassifiedIncident",
    "OpsAlert",
    "Severity",
    "IncidentClass",
    "IncidentEvent",
]
