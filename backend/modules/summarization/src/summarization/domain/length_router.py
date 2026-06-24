"""LengthRouter — single-call vs map-reduce vs over-cap branch (BR-S6 / Q3).

Shape only: the concrete token budget / chunk size are runtime tunes (NFR/Code-gen). The
default budget keeps the common paper (~13K, up to ~40K tokens) on the single-call path.
The MAP_REDUCE band (CONTEXT_BUDGET~INPUT_CAP) is the long-paper path: when enabled it runs
section-aware map-reduce as a background job (BR-S8, MapReduceSummarizer + summary worker),
so the request is dispatched (``pending``) rather than blocking. Beyond INPUT_CAP (OVER_CAP)
the extreme outlier is rejected (``input_too_long``) — not partial-summarized.
"""

from __future__ import annotations

from enum import StrEnum

# Conservative defaults (tunable). Single call for the vast majority; cap bounds outliers.
DEFAULT_CONTEXT_BUDGET_TOKENS = 40_000
DEFAULT_INPUT_CAP_TOKENS = 120_000


class LengthRoute(StrEnum):
    SINGLE = "single"
    MAP_REDUCE = "map_reduce"
    OVER_CAP = "over_cap"  # beyond the input cap → explicit degrade/abstain


class LengthRouter:
    def __init__(
        self,
        *,
        context_budget: int = DEFAULT_CONTEXT_BUDGET_TOKENS,
        input_cap: int = DEFAULT_INPUT_CAP_TOKENS,
    ) -> None:
        self._budget = context_budget
        self._cap = input_cap

    def route(self, token_count: int) -> LengthRoute:
        if token_count > self._cap:
            return LengthRoute.OVER_CAP
        if token_count > self._budget:
            return LengthRoute.MAP_REDUCE
        return LengthRoute.SINGLE
