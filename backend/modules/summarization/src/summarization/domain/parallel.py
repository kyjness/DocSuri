"""map_bounded — bounded, order-preserving, fail-fast concurrent map (BR-S6/BR-S18).

The long-input translate (map-only chunks) and summary (map-reduce map phase) both fan out a
list of INDEPENDENT LLM calls and then fold the results back **in input order** (translate
re-injects by reading-order index; summary feeds partials to reduce in order). That is the same
shape everywhere, so it lives here once:

  • bounded — a per-request worker cap keeps concurrent Bedrock calls (and their token/min
    footprint) from tripping model throttling or spiking cost; the caller picks the cap.
  • order-preserving — results are returned aligned to ``items`` regardless of completion order,
    so the downstream merge stays deterministic (identical cache artifact to the serial path).
  • fail-fast — the first worker exception is re-raised (e.g. LlmUnavailable → the orchestrator's
    one-retry-then-abstain path), and remaining not-yet-started work is cancelled.

I/O-bound (network LLM calls) → threads are the right tool; the gateway stays synchronous (no
async rewrite). ``max_workers <= 1`` or a single item runs inline (no thread/executor overhead,
and an exact behavioral match to the prior serial loop — the rollback/testing switch).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TypeVar

T = TypeVar("T")
R = TypeVar("R")


def map_bounded(
    fn: Callable[[T], R], items: Sequence[T], *, max_workers: int
) -> list[R]:
    """Apply ``fn`` to each item concurrently (bounded), returning results in input order.

    Raises the first worker exception (fail-fast); pending work is cancelled on exit. Runs inline
    when ``max_workers <= 1`` or ``len(items) <= 1``."""
    n = len(items)
    if n == 0:
        return []
    if max_workers <= 1 or n == 1:
        return [fn(item) for item in items]
    # Cap workers at the item count so an oversized pool doesn't spawn idle threads.
    out: dict[int, R] = {}
    with ThreadPoolExecutor(max_workers=min(max_workers, n)) as pool:
        # submit + as_completed (not ``pool.map``): map yields strictly in input order, so a late
        # item's exception would be blocked behind slower earlier items. Consuming completions as
        # they finish makes the FIRST failing chunk abort immediately (true fail-fast), and the
        # ``except`` cancels not-yet-started futures so queued work (e.g. more Bedrock calls) stops
        # spending — in-flight ones can't be cancelled, but the pool starts no new ones. Results are
        # keyed by input index and re-assembled in order, so the return stays deterministic.
        futures = {pool.submit(fn, item): i for i, item in enumerate(items)}
        try:
            for fut in as_completed(futures):
                out[futures[fut]] = fut.result()  # re-raises the first failing completion
        except BaseException:
            for f in futures:
                f.cancel()
            raise
    return [out[i] for i in range(n)]
