"""Job identity for the ``SummaryJobQueuePort`` adapters.

A client polling `/api/summarize` re-sends the same request every few seconds while the job runs,
and each poll reaches an enqueue call. Without a guard every poll would start another generation
of the same artifact — billed LLM work thrown away, since the store write-through means only one
result can win. Both queue adapters therefore collapse repeats by this key, so it lives here
rather than in either of them.

The fields are exactly those that select a cache entry, minus the ones the request cannot vary:
two requests with the same key produce the same artifact, so running both is pure waste. The
abstract text is deliberately excluded — it is payload, not identity, and including it would let a
whitespace difference slip a duplicate job through.
"""

from __future__ import annotations

from ..domain.models import SummaryRequest


def summary_job_dedup_key(request: SummaryRequest, user_id: str) -> str:
    return "|".join(
        [
            user_id,
            request.paper_id,
            str(request.version),
            request.task.value,
            request.persona.value,
            request.scope.value,
            request.target_lang.value,
        ]
    )
