"""Search latency-budget contract (QA 2026-07-10 F1) — the repo's first latency assertion.

The BFF forwards ``/api/search`` with a 30s hop (``SEARCH_GATEWAY_TIMEOUT_MS``,
frontend/app/bff/[...path]/route.ts); the browser client mirrors it (``SEARCH_TIMEOUT_MS``,
frontend/lib/api/apiClient.ts). This test pins the BACKEND's defined cold-path budget under
that ceiling so nobody re-creates the F1 incident by bumping one adapter timeout in isolation
(the original 504: embed read 10s + k-NN cold-load retries alone could exceed the old 10s hop).

The "cold path" here is the worst SUCCESSFUL novel-query chain observed live:
  embed (slow but capped) → k-NN attempt 1 times out on a cold HNSW graph load, attempt 2
  succeeds → BM25 single attempt → rerank (capped, fail-soft).
Fail-CLOSED tails (all retries exhausted) surface as an explicit 503 through the BFF rather
than a discarded-response 504, so they are deliberately not part of this sum.
"""

from __future__ import annotations

from discovery.adapters.bedrock_embedding import _READ_TIMEOUT_S as EMBED_READ_S
from discovery.adapters.bedrock_rerank import _READ_TIMEOUT_S as RERANK_READ_S
from discovery.adapters.opensearch_index import (
    _SEARCH_REQUEST_TIMEOUT_S,
    _SEARCH_RETRY_BACKOFF_S,
)

# Must match frontend SEARCH_GATEWAY_TIMEOUT_MS / SEARCH_TIMEOUT_MS (30_000). Cross-language,
# so the value is pinned here by convention — change all three together.
_BFF_SEARCH_HOP_S = 30.0


def test_cold_path_budget_fits_inside_the_bff_search_hop() -> None:
    cold_path_s = (
        EMBED_READ_S  # query embed, slow-but-capped (timeout → tested lexical fallback)
        + _SEARCH_REQUEST_TIMEOUT_S  # k-NN attempt 1: cold graph load times out at the cap
        + _SEARCH_RETRY_BACKOFF_S[0]  # backoff before the retry
        + _SEARCH_REQUEST_TIMEOUT_S  # k-NN attempt 2: succeeds (graph now loading/loaded)
        + _SEARCH_REQUEST_TIMEOUT_S  # BM25, single attempt at the cap
        + RERANK_READ_S  # cross-encoder rerank, capped and fail-soft
    )
    # Margin for the stages without their own caps (grounding enforce, assembly, boosts) and
    # for the CloudFront->BFF leg. If this fails, either lower an adapter budget or raise the
    # frontend hops — never let the backend chain silently outgrow the hop again.
    assert cold_path_s <= _BFF_SEARCH_HOP_S - 3.0, (
        f"search cold-path budget {cold_path_s:.2f}s leaves <3s margin under the "
        f"{_BFF_SEARCH_HOP_S:.0f}s BFF search hop — retune the stage budgets"
    )
