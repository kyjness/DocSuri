"""Unit tests for the real EventBridge SearchExecuted publisher (fake client)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from docsuri_shared.events import SearchExecutedEvent

from discovery.adapters.event_publisher import EventBridgeEventPublisher


class FakeEvents:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.calls: list[list[dict]] = []
        self.error = error

    def put_events(self, *, Entries):  # noqa: N803
        if self.error is not None:
            raise self.error
        self.calls.append(Entries)


def _event() -> SearchExecutedEvent:
    return SearchExecutedEvent(
        userId="u1",
        requestId="req-1",
        query="diffusion",
        timestamp=datetime.now(UTC),
        resultCount=3,
    )


def test_publish_sends_one_eventbridge_entry() -> None:
    fake = FakeEvents()
    executor = ThreadPoolExecutor(max_workers=1)
    pub = EventBridgeEventPublisher(event_bus_name="docsuri-bus", client=fake, executor=executor)

    pub.publish_search_executed(_event())
    executor.shutdown(wait=True)  # drain the fire-and-forget send

    assert len(fake.calls) == 1
    entry = fake.calls[0][0]
    assert entry["DetailType"] == "SearchExecuted"
    assert entry["EventBusName"] == "docsuri-bus"
    assert '"requestId":"req-1"' in entry["Detail"]
    assert '"query":"diffusion"' in entry["Detail"]


def test_publish_swallows_send_errors() -> None:
    # History is best-effort (BR-14) — a bus failure must NEVER surface to the response path.
    fake = FakeEvents(error=RuntimeError("bus down"))
    executor = ThreadPoolExecutor(max_workers=1)
    pub = EventBridgeEventPublisher(event_bus_name="b", client=fake, executor=executor)

    pub.publish_search_executed(_event())  # must not raise
    executor.shutdown(wait=True)
