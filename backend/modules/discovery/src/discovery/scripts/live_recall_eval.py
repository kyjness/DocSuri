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

from docsuri_shared.dtos import SearchRequest, SearchResultPageDTO

from ..adapters.settings import DiscoverySettings
from ..api import run_search
from ..domain.models import AuthSession, RequestContext
from ..eval import recall_at_k
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


def _build():
    settings = DiscoverySettings.from_env()
    if not settings.search_enabled:
        raise SystemExit("read path not configured — source .env first")
    return build_real_orchestrator(settings)


def _ask(bundle, hook, query: str, cap: _Contamination) -> tuple[list[str], list[str]]:
    cap.msgs.clear()
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


def _rank(ids: list[str], relevant: set[str]) -> int | None:
    """Display-only: position of the first relevant paper, for the per-case columns."""
    return next((i for i, p in enumerate(ids, 1) if p in relevant), None)


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
    # ONE bundle for both arms. Building a second one would give each arm its own
    # EmbeddingCache and its own wiring-time index-mapping read, so every query would be
    # embedded twice — doubling exposure to the embedding throttle this script exists to
    # detect. The arms differ only in whether a reranker is attached, so swap that instead.
    bundle = _build()
    reranker = bundle.orchestrator._reranker
    arms = ["ON", "OFF"] if args.compare else ["ON"]
    if args.compare and reranker is None:
        print("리랭커가 배선되지 않았다 — --compare 는 DOCSURI_RERANK_MODEL_ARN 이 필요하다")
        return 1

    clean: list[dict[str, float]] = []
    first_call = True
    for case in LIVE_CASES:
        scores: dict[str, float] = {}
        ranks: dict[str, int | None] = {}
        warns: list[str] = []
        for label in arms:
            if not first_call:
                time.sleep(args.gap)   # space calls; nothing to space before the first
            first_call = False
            bundle.orchestrator._reranker = reranker if label == "ON" else None
            ids, w = _ask(bundle, hook, case.query, cap)
            # recall@k over the whole relevant set — a case with several defensible answers
            # (which live_cases invites) would be miscounted by a single-target hit test.
            scores[label] = recall_at_k(ids, case.relevant, args.k)
            ranks[label] = _rank(ids, case.relevant)
            warns += w
        bundle.orchestrator._reranker = reranker
        if warns:
            print(f"  오염  {case.query[:56]}\n        ↳ {warns[0][:88]}")
        else:
            clean.append(scores)
            cols = "  ".join(f"{lb} {str(ranks[lb] or '-'):>3}" for lb in arms)
            print(f"  {cols}   {case.query[:56]}")

    dirty = len(LIVE_CASES) - len(clean)
    print(f"\n정상 쌍 {len(clean)}건 / 오염 {dirty}건 (오염은 집계 제외)")
    if not clean:
        print("비교 가능한 쌍이 없다 — --gap 을 늘리거나 쿼터 상향이 필요하다")
        return 1
    for label in arms:
        mean = sum(s[label] for s in clean) / len(clean)
        print(f"  {label:<3} recall@{args.k} {mean:.3f}  ({len(clean)}건 평균)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
