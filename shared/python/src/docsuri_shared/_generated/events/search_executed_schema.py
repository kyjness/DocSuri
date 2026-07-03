# DO NOT EDIT. Generated from the JSON Schema SSOT in shared/ by tools/generate.py.
# Change the schema and regenerate (§5-B); never hand-edit.

from __future__ import annotations

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class SearchExecutedEvent(BaseModel):
    """
    🔒 FROZEN (events.md §2; component-methods.md publishSearchExecuted/recordSearch signatures). History-write event published AFTER a successful search response. Producer: U2.SearchOrchestrationService.publishSearchExecuted(userId, requestId, query, timestamp, resultCount) -> void. Consumer: U4.SearchHistoryService.recordSearch(event) -> void (subscribes the shared event bus, records asynchronously). ⚠️ Published/consumed OUTSIDE the synchronous P50<3s search path (NFR-P1) — does NOT block the search response (component-dependency.md). Delivery: at-least-once → U4 MUST record idempotently (e.g. same userId+requestId+query on re-delivery MUST NOT create a duplicate row). No internal fields exposed (SEC-9): no owner scores, no debug. Trace: FR-10, NFR-P1, US-L3.
    """

    model_config = ConfigDict(
        extra='forbid',
    )
    userId: str = Field(
        ...,
        description='User who executed the search (owner key — drives U4 history owner-scoping). Trace: events.md §2, FR-10.',
    )
    requestId: str = Field(
        ...,
        description='Unique search request identifier. U4 uses it with userId and query for at-least-once idempotency, so intentional repeated searches do not collide with event redelivery. Trace: events.md §2, BR-L7, INV-L3.',
    )
    query: str = Field(
        ..., description='The executed query string. Trace: events.md §2.'
    )
    timestamp: AwareDatetime = Field(
        ...,
        description='Search execution time (timestamp; serialized as RFC 3339 / ISO 8601 date-time — concrete wire format is Infra Design). Trace: events.md §2.',
    )
    resultCount: int = Field(
        ..., description='Number of results returned (int). Trace: events.md §2.'
    )
