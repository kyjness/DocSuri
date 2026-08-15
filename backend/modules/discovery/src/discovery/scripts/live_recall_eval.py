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

Contaminated cases are RETRIED (``--retries``), not just excluded. Excluding was inherited from
the serving path's ``max_attempts: 1`` — which exists because LITE has a P50<3s budget that a
backoff would blow. This script has no such budget, so it paid the serving path's price for
nothing and silently shrank its own sample. A retry converts contamination from "excluded" into
"slower", and the retry re-runs BOTH arms: re-running only the failed arm would compare two arms
measured under different throttle conditions, which is the same unfairness as trap 3.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

from docsuri_shared.dtos import AbstainDTO, DegradedResultDTO, SearchRequest

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
    if isinstance(root, DegradedResultDTO):
        warns.append(f"degraded to {root.mode.value}")  # ``mode`` is top-level on this DTO
    elif not isinstance(root, AbstainDTO) and not ids:
        # Anything else without cards (validation error, unknown shape) is not a measurement.
        # An ABSTAIN is: the grounding gate judged the results unusable, and that IS the read
        # path's answer for this query — score it as a miss, don't retry it into the exclusion
        # bin, or recall is inflated on exactly the queries that matter.
        warns.append(f"non-page response {type(root).__name__}")
    return ids, warns


def _rank(ids: list[str], relevant: set[str]) -> int | None:
    """Display-only: position of the first relevant paper, for the per-case columns."""
    return next((i for i, p in enumerate(ids, 1) if p in relevant), None)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--compare", action="store_true", help="paired rerank ON/OFF")
    ap.add_argument("--gap", type=float, default=5.0, help="seconds between calls (throttle)")
    ap.add_argument("-k", type=int, default=10, help="recall@k")
    ap.add_argument(
        "--retries", type=int, default=3, help="re-runs of a contaminated case (0 = exclude only)"
    )
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
    stuck: list[tuple[str, str]] = []  # cases still contaminated after every retry
    pending = [True]  # first call of the run has nothing to space against

    def pace(extra: float) -> None:
        if pending[0]:
            pending[0] = False
            return
        time.sleep(args.gap + extra)

    # Only the arm that reaches Bedrock needs spacing. ON runs first in each pair and pays the
    # embedding + rerank calls; OFF then reuses the shared EmbeddingCache and has no reranker,
    # so it touches only OpenSearch — sleeping before it protected nothing and doubled the run.
    def needs_gap(label: str) -> bool:
        return label == arms[0]

    for case in LIVE_CASES:
        done: tuple[dict[str, float], dict[str, int | None]] | None = None
        last_warn = ""
        for attempt in range(args.retries + 1):
            # A contaminated attempt means the quota is already empty and the steady-state gap is
            # what emptied it — retrying at the same spacing just re-trips it. Back off further.
            backoff = 0.0 if attempt == 0 else args.gap * 2**attempt
            scores: dict[str, float] = {}
            ranks: dict[str, int | None] = {}
            warns: list[str] = []
            for label in arms:
                if needs_gap(label):
                    pace(backoff)
                bundle.orchestrator._reranker = reranker if label == "ON" else None
                ids, w = _ask(bundle, hook, case.query, cap)
                # recall@k over the whole relevant set — a case with several defensible answers
                # (which live_cases invites) would be miscounted by a single-target hit test.
                scores[label] = recall_at_k(ids, case.relevant, args.k)
                ranks[label] = _rank(ids, case.relevant)
                warns += w
            bundle.orchestrator._reranker = reranker
            if not warns:
                done = (scores, ranks)
                break
            last_warn = warns[0]
            if attempt < args.retries:
                # Name the cause on every retry, not only on the final exclusion — the watched
                # loggers don't propagate, so this line is the only place the operator sees it.
                print(
                    f"  재시도 {attempt + 1}/{args.retries}  "
                    f"{case.query[:40]}  ↳ {last_warn[:60]}"
                )
        if done is None:
            stuck.append((case.query, last_warn))
            print(f"  오염  {case.query[:56]}\n        ↳ {last_warn[:88]}")
        else:
            clean.append(done[0])
            cols = "  ".join(f"{lb} {str(done[1][lb] or '-'):>3}" for lb in arms)
            print(f"  {cols}   {case.query[:56]}")

    # Name what was dropped. A shrunken sample reported only as an average reads as "measured
    # everything" — the number of cases the run could not measure changes how the average is read.
    if stuck:
        print(f"\n재시도 {args.retries}회로도 못 살린 케이스 {len(stuck)}건 — 집계에서 제외:")
        for query, warn in stuck:
            print(f"  - {query[:52]}  ↳ {warn[:64]}")
    print(f"\n측정 {len(clean)}건 / 전체 {len(LIVE_CASES)}건")
    if not clean:
        print("비교 가능한 쌍이 없다 — --gap·--retries 를 늘리거나 쿼터 상향이 필요하다")
        return 1
    for label in arms:
        mean = sum(s[label] for s in clean) / len(clean)
        print(f"  {label:<3} recall@{args.k} {mean:.3f}  ({len(clean)}건 평균)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
