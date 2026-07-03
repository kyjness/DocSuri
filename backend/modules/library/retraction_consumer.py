"""U4 — PaperRetractedEvent consumer.

U1 emits a retraction signal when the corpus/index marks a paper as retracted. U4 preserves the
user's saved row but flags its metadata so readers can show the trust state without deleting
personal data.
"""

from __future__ import annotations

from docsuri_shared.events import PaperRetractedEvent

from .services.library import LibraryService


class PaperRetractedEventConsumer:
    def __init__(self, service: LibraryService) -> None:
        self._service = service

    def consume(self, payload: PaperRetractedEvent | dict) -> int:
        event = (
            payload
            if isinstance(payload, PaperRetractedEvent)
            else PaperRetractedEvent.model_validate(payload)
        )
        return self._service.mark_retracted(event)
