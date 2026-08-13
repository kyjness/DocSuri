"""Build the foundational-paper arXiv ID list for the ⑧-2 deployment corpus.

WHY THIS EXISTS. The corpus is harvested by DATE WINDOW, and a date window structurally
misses the papers everyone cites. Measured on the local development corpus (29,915 papers,
2025=68% / 2024=23%): of ten representative foundational papers only Transformer was
present — BERT, GPT-3, LLaMA, RAG, ResNet, InstructGPT, Chain-of-Thought, LoRA and Bahdanau
attention were all absent. The pre-2023 tail that does exist (~1,300 papers) is not the
canon; it is arbitrary old papers whose v2/v3 revision happened to land inside the window.

Growing the window does not fix this, so the list has to be named explicitly. That is what
this script produces. Decision record:
``aidlc-docs/inception/requirements/requirement-verification-questions-corpus-and-deployment.md``
(Q4=C) — 4,500-paper ceiling = ~1,500 foundational + ~3,000 recent.

TWO SIGNALS, DELIBERATELY. Neither alone is trustworthy:

  A. Citation count (Semantic Scholar, ``sort=citationCount:desc``). Broad and reproducible,
     but rewards age and rewards tooling papers — the raw top of "machine learning" is
     scikit-learn, XGBoost, PyTorch. Software a field uses is not prior art a novelty check
     reasons about.
  B. Survey reference frequency. A paper cited by many independent recent surveys of a
     subfield is what that subfield treats as its own foundation, which is exactly the
     relation U12 needs. Narrow on its own (survey choice skews it) and costs one request
     per survey.

A paper carried by both signals is the safe core; the rest is filled by rank. The merged
score is deliberately simple — the point is a defensible, re-runnable list, not a ranking
model.

ARXIV-ONLY. Papers with no arXiv id are dropped even when they top the citation list
(LIBSVM, Dropout/JMLR, Deep Learning/Nature, AlphaFold). Only arXiv rides the good rung of
the parse ladder (``ar5iv HTML → arXiv PDF → GROBID``); a publisher PDF is ``PDF → GROBID →
exclude`` and ⑧-1.7 measured ~50% of those blocked at 403. Chasing them would spend the
batch on papers that mostly fail to parse. The dropped ones are reported so the loss is
visible rather than silent.

RATE LIMIT. No S2 API key is configured, so the unauthenticated pool applies (~100 requests
per 5 minutes, shared). Every response is cached under ``--cache`` so a re-run costs nothing;
delete the cache dir to force a refresh.

Usage:
    python tools/local/build_foundational_list.py --out reports/foundational-papers.tsv
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import math
import pathlib
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from docsuri_ingestion.adapters.arxiv import ATOM_NS
from docsuri_ingestion.domain.ids import normalize_arxiv_ref
from docsuri_ingestion.http_limits import user_agent
from docsuri_ingestion.resilience import RetryPolicy, retry_with_policy
from docsuri_ingestion.xmlsafe import safe_fromstring

S2 = "https://api.semanticscholar.org/graph/v1"

# Bucket targets from Q4=C. Tier 1 is the cross-field canon (papers any subfield may need to
# cite); tier 2 mirrors the measured composition of the recent slice — 200 random 2025 corpus
# papers queried against the arXiv API gave primary categories cs.LG 52% / cs.CV 9% /
# cs.CL 7% / cs.AI 5.5%, cross-listed cs.LG 96.5% / cs.AI 36.5% / cs.CV 13.5% / cs.CL 12.5%.
#
# cs.CL is weighted ABOVE its 7% share on purpose: its foundational papers are cited from
# outside it. Transformer is a cs.CL primary and most cs.LG papers cite it, so a share
# proportional to cs.CL's own volume would under-supply the whole corpus.
# SEVERAL PHRASES PER BUCKET, because the S2 query is a literal phrase match and a field's
# name is not in every important paper's text. Measured: "natural language processing" sorted
# by citations does not contain LLaMA-2, ReAct or Self-Consistency anywhere in its first 1,000
# rows, while "large language model" has them at ranks 2, 5 and 11. One phrase per bucket
# silently excluded the current generation of the very subfield the corpus is being built for.
BUCKETS = (
    # (name, target, queries, note)
    ("canon", 300, (), "cross-field canon — filled from the global top by merged score"),
    (
        "cs.CL",
        550,
        (
            "large language model",
            "natural language processing",
            "language model pretraining",
            "instruction tuning",
            "retrieval augmented generation",
        ),
        "NLP/LLM — the recent slice's main axis",
    ),
    (
        "cs.AI",
        350,
        ("artificial intelligence", "llm agent", "chain of thought reasoning", "tool use"),
        "agents · reasoning · planning",
    ),
    (
        "cs.LG",
        200,
        ("machine learning", "deep learning", "representation learning"),
        "ML foundations that NLP/AI work keeps citing",
    ),
    ("cs.CV", 100, ("computer vision", "vision language model"), "multimodal cross-over only"),
)
# Surveys cost one request each and their reference sets overlap heavily between sibling
# phrases, so only the first few phrases of a bucket are mined for them.
SURVEY_PHRASES_PER_BUCKET = 2

# Surveys older than this rarely reflect what a subfield currently treats as its foundation;
# newer than ~1 year they have not accumulated enough references to be worth a request.
SURVEY_YEARS = "2019-2025"
# Foundational work predates the recent slice by construction. The upper bound keeps the list
# from filling with 2025 papers that are merely popular, which the recent slice already covers.
#
# TWO AGE BANDS, because absolute citation count is not comparable across them. Ranking one
# pooled list by citations lets 2015-2018 win every slot — a 2023 paper cannot accumulate
# 20,000 citations no matter how load-bearing it is. Measured: a single-band run produced a
# list with Transformer/BERT/GPT-3 but WITHOUT LLaMA-2, Self-Consistency, ReAct or RoPE, which
# is exactly the prior art an agent/reasoning novelty question needs. Giving the recent band
# its own quota per bucket is what puts them back.
CANDIDATE_YEARS = "2012-2021"
RECENT_BAND_YEARS = "2022-2024"
RECENT_BAND_SHARE = 0.35
SURVEYS_PER_BUCKET = 12
# S2 caps /references paging; one page is plenty — a survey's first 1000 references cover it.
REFERENCE_LIMIT = 1000

_SURVEY_RE = re.compile(r"\b(survey|review|overview|systematic)\b", re.IGNORECASE)

# No single arXiv primary category may take more than this share of the canon tier. Without a
# ceiling the tier came out 46.7% cs.CV (see the canon block in main()); vision's 2014-2017
# papers dominate any citation-ordered list and would crowd out the fields the recent slice is
# actually made of. Held-back papers are not dropped — they fall through to their own bucket.
#
# 0.15, not the earlier 0.30: the recent slice was narrowed to cs.CL + cs.AI, so vision is now
# peripheral. The vision papers NLP work actually cites (ViT, CLIP) are multimodal and reach the
# tier on their own merits; YOLO and FPN should not.
CANON_CATEGORY_CAP = 0.15
ARXIV_API = "https://export.arxiv.org/api/query"

# Both APIs answer 429/5xx when they want the caller to slow down; everything else is a real
# error and must propagate. One policy, one predicate — three hand-rolled loops disagreed about
# the backoff and about whether exhaustion raises.
_HTTP_RETRY = RetryPolicy(max_attempts=6, base_delay_seconds=8.0, factor=1.6, jitter_ratio=0.1)
_RETRIABLE_STATUS = frozenset({429, 500, 502, 503, 504})

# Pages per (query, band). Measured on a full cold run: 28 of 71 search requests returned nothing
# that reached the final list, and the query "tool use" alone burned 24 of them paging into rows
# no bucket ever wanted. No chain needed a row past rank ~1,700, and 24 of the 28 needed nothing
# past rank 700 — so three pages is generous, not tight.
MAX_PAGES_PER_QUERY = 3

# A paper reaching the list on survey votes alone needs more than a coincidence. Measured: of the
# 162 survey-only papers admitted at >=2, only 2 had exactly 2 votes — so the looser threshold
# bought 2 papers in 1,500 while inflating the metadata lookup from ~1,400 ids to ~5,700.
MIN_SURVEY_VOTES = 3


def _http_retriable(exc: Exception) -> bool:
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code in _RETRIABLE_STATUS
    return isinstance(exc, urllib.error.URLError | TimeoutError)


# Inter-request pacing for the unauthenticated S2 pool (~100 requests / 5 min, shared). Set
# from --pause in main(); slept only after a REAL request, so cache hits stay free and a re-run
# still costs nothing. Losing this sleep un-paced ~180 requests straight into 429 backoff.
_PAUSE = 3.5


def _fetch(url: str, *, timeout: int = 90) -> bytes:
    """One GET with the package's outbound identity, retried on the shared policy."""

    def once() -> bytes:
        # Rebuilt per attempt: urllib records redirect state on the Request object, so reusing
        # one across retries trips its "infinite loop" guard on the second try.
        req = urllib.request.Request(url, headers={"User-Agent": user_agent()})
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return resp.read()

    def note(attempt: int, exc: Exception) -> None:
        code = getattr(exc, "code", None) or type(exc).__name__
        print(f"    [{code}] 재시도 {attempt}", file=sys.stderr)

    body = retry_with_policy(_HTTP_RETRY, once, retriable=_http_retriable, on_retry=note)
    time.sleep(_PAUSE)
    return body


def _cached_by_id(
    store: pathlib.Path, ids: list[str], fetch: "callable", chunk: int
) -> dict[str, Any]:
    """Resolve ids through one accumulating PER-ID store, fetching only what is missing.

    Per id, not per batch. A batch-keyed cache is invalidated wholesale by an edit that leaves
    99% of the answers still valid — change a bucket target and every chunk reshuffles, so all
    of them miss although every record is already on disk. Written after each chunk so an
    interrupted run keeps what it fetched.
    """
    known: dict[str, Any] = json.loads(store.read_text(encoding="utf-8")) if store.exists() else {}
    todo = [i for i in ids if i not in known]
    if todo:
        print(f"  캐시 {len(ids) - len(todo)}편 재사용, 신규 조회 {len(todo)}편")
    for i in range(0, len(todo), chunk):
        batch = todo[i : i + chunk]
        try:
            known.update(fetch(batch))
        except Exception as exc:  # noqa: BLE001 — partial knowledge beats losing the whole run
            print(f"    조회 포기({type(exc).__name__}) — 남은 편은 미상으로 진행", file=sys.stderr)
            break
        store.write_text(json.dumps(known), encoding="utf-8")
    return {i: known[i] for i in ids if i in known}


def arxiv_primary_categories(ids: list[str], cache: pathlib.Path) -> dict[str, str]:
    """arXiv id -> primary category. Only the canon ceiling reads this."""

    def fetch(batch: list[str]) -> dict[str, str]:
        url = f"{ARXIV_API}?id_list={','.join(batch)}&max_results={len(batch)}"
        root = safe_fromstring(_fetch(url))
        out: dict[str, str] = {}
        for entry in root.findall("atom:entry", ATOM_NS):
            raw = (entry.findtext("atom:id", "", ATOM_NS) or "").rsplit("/", 1)[-1]
            pc = entry.find("arxiv:primary_category", ATOM_NS)
            if not raw or pc is None:
                continue
            try:
                paper_id = normalize_arxiv_ref(raw).paper_id
            except ValueError:
                continue
            out[paper_id] = pc.get("term") or "?"
        return out

    # Flat id -> category, which is also the shape the existing cache file already holds.
    return _cached_by_id(cache / "arxiv-categories.json", ids, fetch, chunk=100)


def canon_target_lookup(buckets: tuple) -> int:
    """How far down the ranking to resolve categories — the ceiling can push the canon tier
    well past its own size before it fills, so look up a generous multiple of it."""
    return buckets[0][1] * 4


def _get(url: str, params: dict, cache: pathlib.Path, page: int = 0) -> dict:
    """One cached GET.

    The cache key deliberately EXCLUDES the pagination token and uses the page ordinal instead.
    S2's token is opaque 128-char scroll state; if it is not byte-identical between runs the
    token-keyed cache misses every page past the first, which is 43 of the 71 search requests a
    cold run makes. The (url, params-without-token, page) triple is deterministic.
    """
    stable = {k: v for k, v in params.items() if k != "token"}
    qs = urllib.parse.urlencode(sorted(stable.items()))
    key = hashlib.sha256(f"{url}?{qs}#p{page}".encode()).hexdigest()[:24]
    hit = cache / f"{key}.json"
    if hit.exists():
        return json.loads(hit.read_text(encoding="utf-8"))
    payload = json.loads(_fetch(f"{url}?{urllib.parse.urlencode(params)}"))
    hit.write_text(json.dumps(payload), encoding="utf-8")
    return payload


def _arxiv_id(paper: dict) -> str | None:
    return ((paper or {}).get("externalIds") or {}).get("ArXiv")


def collect_by_citation(query: str, cache: pathlib.Path, want: int, years: str) -> list[dict]:
    """Signal A — the citation-count top of one query within one age band, arXiv rows only."""
    out: list[dict] = []
    dropped = 0
    token = None
    for page in range(MAX_PAGES_PER_QUERY):
        if len(out) >= want:
            break
        params = {
            "query": f'"{query}"',
            "fieldsOfStudy": "Computer Science",
            "fields": "paperId,title,year,citationCount,externalIds",
            "sort": "citationCount:desc",
            "year": years,
        }
        if token:
            params["token"] = token
        body = _get(f"{S2}/paper/search/bulk", params, cache, page)
        rows = body.get("data") or []
        if not rows:
            break
        for p in rows:
            if _arxiv_id(p):
                out.append(p)
            else:
                dropped += 1
        token = body.get("token")
        if not token:
            break
    print(f"    인용수 상위 {len(out)}편 수집 (arXiv 없어 제외 {dropped}편)")
    return out[:want]


def collect_survey_refs(
    query: str, cache: pathlib.Path, mined: set[str]
) -> collections.Counter:
    """Signal B — how many INDEPENDENT recent surveys cite each paper.

    ``mined`` carries the survey ids already counted in this run. Sibling phrases of a bucket
    return heavily overlapping survey sets — measured, 62 distinct surveys filled 96 phrase
    slots — so without it a third of the votes are the same survey counted twice and the signal
    stops meaning "independent surveys".
    """
    params = {
        "query": f'"{query}" survey',
        "fieldsOfStudy": "Computer Science",
        "fields": "paperId,title,year,citationCount",
        "sort": "citationCount:desc",
        "year": SURVEY_YEARS,
    }
    body = _get(f"{S2}/paper/search/bulk", params, cache)
    surveys = [p for p in (body.get("data") or []) if _SURVEY_RE.search(p.get("title") or "")]
    surveys = [p for p in surveys if p.get("paperId") not in mined][:SURVEYS_PER_BUCKET]

    freq: collections.Counter = collections.Counter()
    for survey in surveys:
        mined.add(survey["paperId"])
        refs = _get(
            f"{S2}/paper/{survey['paperId']}/references",
            {"fields": "title,year,citationCount,externalIds", "limit": REFERENCE_LIMIT},
            cache,
        )
        seen: set[str] = set()
        for item in refs.get("data") or []:
            aid = _arxiv_id(item.get("citedPaper") or {})
            # Count each paper once per survey — a survey citing it five times is still one vote.
            if aid and aid not in seen:
                seen.add(aid)
                freq[aid] += 1
    print(f"    서베이 {len(surveys)}편 → 참고문헌 {len(freq)}편 집계")
    return freq


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="reports/foundational-papers.tsv")
    ap.add_argument("--cache", default=".cache/s2-foundational")
    ap.add_argument("--pause", type=float, default=3.5, help="요청 간격(초) — 미인증 풀 기준")
    args = ap.parse_args()

    global _PAUSE
    _PAUSE = args.pause
    cache = pathlib.Path(args.cache)
    cache.mkdir(parents=True, exist_ok=True)

    # arxiv_id -> merged record
    pool: dict[str, dict] = {}
    survey_votes: collections.Counter = collections.Counter()

    canon_target = BUCKETS[0][1]
    mined_surveys: set[str] = set()
    for name, target, queries, _note in BUCKETS:
        for qi, query in enumerate(queries):
            print(f"[{name}] '{query}'")
            # Sized to what the fill can actually consume: the bucket's own slots plus whatever
            # the canon tier may take off the top. `target * 2` per query AND per band asked for
            # 11,000 candidates for a 550-slot bucket, which is what drove the wasted paging.
            for band in (CANDIDATE_YEARS, RECENT_BAND_YEARS):
                want = canon_target + (
                    int(target * RECENT_BAND_SHARE) if band == RECENT_BAND_YEARS else target
                )
                rows = collect_by_citation(query, cache, want=want, years=band)
                for p in rows:
                    aid = _arxiv_id(p)
                    rec = pool.setdefault(
                        aid,
                        {
                            "arxiv_id": aid,
                            "title": (p.get("title") or "").replace("\t", " ").strip(),
                            "year": p.get("year") or 0,
                            "citations": p.get("citationCount") or 0,
                            "buckets": set(),
                        },
                    )
                    rec["buckets"].add(name)
            if qi < SURVEY_PHRASES_PER_BUCKET:
                survey_votes.update(collect_survey_refs(query, cache, mined_surveys))

    # Survey-only papers are worth keeping: being cited by several surveys is the stronger
    # signal of the two, and such a paper can sit below the citation cut of every query.
    missing = [
        a for a, v in survey_votes.items() if a not in pool and v >= MIN_SURVEY_VOTES
    ]
    print(f"\n서베이에서만 나온 논문 {len(missing)}편 — 메타데이터 보강")
    for aid, p in s2_metadata(missing, cache).items():
        pool[aid] = {
            "arxiv_id": aid,
            "title": (p.get("title") or "").replace("\t", " ").strip(),
            "year": p.get("year") or 0,
            "citations": p.get("citationCount") or 0,
            "buckets": set(),
        }

    for aid, rec in pool.items():
        rec["surveys"] = survey_votes.get(aid, 0)
        # Citations span five orders of magnitude, so rank on their log; survey votes are a
        # small integer and are weighted to matter — three surveys should outrank a 10x
        # citation gap, because tooling papers win on citations and lose on surveys.
        rec["score"] = math.log10(rec["citations"] + 10) + 1.5 * rec["surveys"]

    ranked = sorted(pool.values(), key=lambda r: (-r["score"], -r["citations"]))

    # Primary categories are needed only for the canon ceiling, so look them up for the head of
    # the ranking rather than all ~6,000 candidates.
    # The ceiling can push the tier well past its own size before it fills, so resolve a
    # generous multiple of it — a smaller head leaves those entries category-unknown.
    head = [r["arxiv_id"] for r in ranked[: canon_target * 4]]
    print(f"\narXiv 1차 카테고리 조회 {len(head)}편 (canon 상한 판정용)")
    categories = arxiv_primary_categories(head, cache)

    # Canon is filled by score, with a per-primary-category ceiling. Both halves were learned
    # the hard way and each failed once:
    #
    #  - Score alone put 46.7% cs.CV into the tier against a recent slice measured at 52%
    #    cs.LG / 9% cs.CV, because the score rewards old-and-heavily-cited and that describes
    #    2014-2017 vision (ResNet at 236k citations). COCO, YOLO and FPN are canonical INSIDE
    #    vision and useless to a novelty question about graph networks.
    #  - Gating on "surfaced by 2+ topic queries" as a breadth proxy was WORSE and was reverted:
    #    it measures query-top overlap, not cross-field citation. ResNet sits in the vision
    #    query's top but not in the machine-learning query's top 2,100, so 8 of 10 reference
    #    foundational papers (Transformer, GPT-3, ResNet, LLaMA, RAG, Bahdanau, InstructGPT,
    #    CoT) dropped out, and what overlapped two queries was the middling-in-both papers —
    #    the tier filled with XAI surveys and GELU.
    #
    # The ceiling attacks the skew directly and leaves the ordering that was already right.
    chosen: dict[str, str] = {}
    cap = int(canon_target * CANON_CATEGORY_CAP)
    per_cat: collections.Counter = collections.Counter()
    deferred: list[dict] = []
    for rec in ranked:
        if len(chosen) >= canon_target:
            break
        cat = categories.get(rec["arxiv_id"], "?")
        if per_cat[cat] >= cap:
            deferred.append(rec)
            continue
        chosen[rec["arxiv_id"]] = "canon"
        per_cat[cat] += 1
    # Papers held back by the ceiling are still foundational. Any that the tier still has room
    # for come back here (and are counted, so the line below describes the tier as it ended up
    # rather than only its first pass); the rest fall through to their own subject bucket.
    for rec in deferred:
        if len(chosen) >= canon_target:
            break
        chosen[rec["arxiv_id"]] = "canon"
        per_cat[categories.get(rec["arxiv_id"], "?")] += 1
    print("[canon] 분야 구성: " + " · ".join(f"{k} {v}" for k, v in per_cat.most_common(6)))
    recent_from = int(RECENT_BAND_YEARS.split("-")[0])
    for name, target, _queries, _note in BUCKETS[1:]:
        quota = int(target * RECENT_BAND_SHARE)
        eligible = [
            r for r in ranked if name in r["buckets"] and r["arxiv_id"] not in chosen
        ]
        # `ranked` is already in score order, so slicing keeps that order inside each band. The
        # recent band goes first up to its quota — the older band always wins on absolute
        # citations and would otherwise consume the bucket before a 2023 paper is reached.
        recent = [r for r in eligible if r["year"] >= recent_from][:quota]
        picked = (recent + [r for r in eligible if r["year"] < recent_from])[:target]
        for rec in picked:
            chosen[rec["arxiv_id"]] = name
        n_recent = sum(1 for r in picked if r["year"] >= recent_from)
        print(f"[{name}] 배정 {len(picked)}/{target} (2022~ {n_recent}편, 할당 {quota})")

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        fh.write("arxiv_id\tbucket\tyear\tcitations\tsurveys\tbuckets\tscore\ttitle\n")
        for rec in ranked:
            b = chosen.get(rec["arxiv_id"])
            if not b:
                continue
            # ``buckets`` = how many subject buckets surfaced this paper. Diagnostic only — the
            # canon tier is decided by score + CANON_CATEGORY_CAP, not by this count.
            fh.write(
                f"{rec['arxiv_id']}\t{b}\t{rec['year']}\t{rec['citations']}\t"
                f"{rec['surveys']}\t{len(rec['buckets'])}\t{rec['score']:.3f}\t{rec['title']}\n"
            )
    print(f"\n총 {len(chosen)}편 → {out}")
    return 0


def s2_metadata(ids: list[str], cache: pathlib.Path) -> dict[str, dict]:
    """S2 metadata for arXiv ids, through the same per-id store as the arXiv lookup."""

    def fetch(batch: list[str]) -> dict[str, dict]:
        body = json.dumps({"ids": [f"ARXIV:{a}" for a in batch]}).encode()

        def once() -> list[dict]:
            # Rebuilt per attempt — the same rule _fetch documents: urllib records redirect
            # state on the Request object and trips its loop guard on a reused one.
            req = urllib.request.Request(
                f"{S2}/paper/batch?fields=paperId,title,year,citationCount,externalIds",
                data=body,
                headers={"Content-Type": "application/json", "User-Agent": user_agent()},
            )
            with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310
                return [p for p in json.loads(resp.read()) if p]

        rows = retry_with_policy(_HTTP_RETRY, once, retriable=_http_retriable)
        time.sleep(_PAUSE)
        return {aid: p for p in rows if (aid := _arxiv_id(p))}

    return _cached_by_id(cache / "s2-metadata.json", ids, fetch, chunk=400)


if __name__ == "__main__":
    raise SystemExit(main())
