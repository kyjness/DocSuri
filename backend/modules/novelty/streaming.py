from __future__ import annotations

from collections.abc import Iterable

from .models import ProgressEvent


def encode_sse(event: ProgressEvent) -> str:
    return f"event: progress\ndata: {event.model_dump_json()}\n\n"


def sse_snapshot(events: Iterable[ProgressEvent]):
    for event in events:
        yield encode_sse(event)
