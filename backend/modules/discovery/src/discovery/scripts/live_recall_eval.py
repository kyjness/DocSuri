"""Score the real read path against ``eval.live_cases`` — manual, NOT a CI test.

Every query costs a Bedrock embedding call and (when the reranker is wired) a Bedrock rerank
call, so this is run by hand against a populated index. ``seed_local_opensearch`` is its
sibling: both are local operator scripts, not part of the suite.

Run it from the REPO ROOT under the backend project — the real U6 grounding hook
(``docsuri_ops``) is a backend dependency and is not installed in this module's own venv, and
the run must reflect the same grounding that serving does:

    set -a; source .env; set +a
    uv run --project backend python -m discovery.scripts.live_recall_eval
    uv run --project backend python -m discovery.scripts.live_recall_eval --compare  # ON/OFF

WHY IT LOOKS LIKE THIS — three traps, all of which produced confidently wrong numbers on the
first attempt (2026-08-15):

1. **Throttling is the norm, not the exception.** The per-account Bedrock rerank rate quota
   trips even at 5s spacing — 7 of 20 queries in the first honest run. A throttled rerank
   fails soft to the baseline order, so the arm silently stops being the arm you think it is.
2. **A throttled EMBEDDING is worse.** It degrades the request to lexical-only: the vector leg
   is simply off, and the response is a DegradedResultDTO that still carries cards. Score it
   as a normal result and you have measured BM25 while believing you measured hybrid search.
3. **Blocked arms are unfair.** Running all-OFF then all-ON hands the second arm a depleted
   token bucket, so it absorbs most of the throttling. Arms must be interleaved per query.

Hence: pair the arms per query, treat ANY warning or degraded response as contamination, and
aggregate only over clean pairs. Reporting a contaminated pair is worse than reporting nothing.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from dataclasses import replace

from docsuri_shared.dtos import SearchRequest, SearchResultPageDTO

from ..adapters.settings import DiscoverySettings
from ..api import run_search
from ..domain.models import AuthSession, RequestContext
from ..eval.live_cases import LIVE_CASES
from ..real_wiring import build_real_orchestrator

_WATCHED = (
    "discovery.service.orchestrator",
    "discovery.adapters.space_guard",
    "docsuri.discovery.api",
)


class _Contamination(logging.Handler):
    """Collects warnings emitted during one call. Non-empty ⇒ that result is not comparable."""

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.msgs: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.msgs.append(record.getMessage())


def _build(rerank: bool):
    settings = DiscoverySettings.from_env()
    if not settings.search_enabled:
        raise SystemExit("read path not configured — source .env first")
    if not rerank:
        settings = replace(settings, rerank_model_arn=None)
    return build_real_orchestrator(settings)


def _ask(bundle, hook, query: str, cap: _Contamination, gap: float) -> tuple[list[str], list[str]]:
    cap.msgs.clear()
    time.sleep(gap)
    resp = run_search(
        bundle.orchestrator, hook, SearchRequest(query=query),
        RequestContext(auth_session=AuthSession(user_id="eval"), request_id="eval"),
    )
    root = resp.root
    # Read cards off a degraded response too — dropping them would score the degrade as a
    # genuine miss. The degrade is recorded as contamination instead.
    ids = [c.arxivId.split("v")[0] for c in getattr(root, "cards", [])]
    warns = list(cap.msgs)
    if not isinstance(root, SearchResultPageDTO):
        warns.append(f"degraded to {getattr(getattr(root, 'meta', None), 'mode', '?')}")
    return ids, warns


def _rank(ids: list[str], paper_id: str) -> int | None:
    return next((i for i, p in enumerate(ids, 1) if p == paper_id), None)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--compare", action="store_true", help="paired rerank ON/OFF")
    ap.add_argument("--gap", type=float, default=5.0, help="seconds between calls (throttle)")
    ap.add_argument("-k", type=int, default=10, help="recall@k")
    args = ap.parse_args(argv)

    cap = _Contamination()
    for name in _WATCHED:
        lg = logging.getLogger(name)
        lg.setLevel(logging.WARNING)   # basicConfig on root would mask these entirely
        lg.addHandler(cap)
        lg.propagate = False
    logging.getLogger().setLevel(logging.CRITICAL)

    from docsuri_ops.grounding import GroundingEnforcementHook

    hook = GroundingEnforcementHook()
    arms = [("ON", _build(True))] + ([("OFF", _build(False))] if args.compare else [])

    clean: list[tuple[str, dict[str, int | None]]] = []
    dirty = 0
    for case in LIVE_CASES:
        paper_id = next(iter(case.relevant))
        ranks: dict[str, int | None] = {}
        warns: list[str] = []
        for label, bundle in arms:
            ids, w = _ask(bundle, hook, case.query, cap, args.gap)
            ranks[label] = _rank(ids, paper_id)
            warns += w
        if warns:
            dirty += 1
            print(f"  오염  {case.query[:56]}\n        ↳ {warns[0][:88]}")
        else:
            clean.append((case.query, ranks))
            cols = "  ".join(f"{lb} {str(ranks[lb] or '-'):>3}" for lb, _ in arms)
            print(f"  {cols}   {case.query[:56]}")

    print(f"\n정상 쌍 {len(clean)}건 / 오염 {dirty}건 (오염은 집계 제외)")
    if not clean:
        print("비교 가능한 쌍이 없다 — --gap 을 늘리거나 쿼터 상향이 필요하다")
        return 1
    for label, _ in arms:
        hits = sum(1 for _, r in clean if r[label] and r[label] <= args.k)
        print(f"  {label:<3} recall@{args.k} {hits}/{len(clean)} = {hits / len(clean):.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
