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
import pathlib
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

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
_ARXIV_NS = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}


def arxiv_primary_categories(ids: list[str], cache: pathlib.Path) -> dict[str, str]:
    """arXiv id -> primary category, cached PER PAPER in one accumulating file.

    Per paper, not per batch: the batch composition changes whenever the bucket targets change,
    so a batch-keyed cache is invalidated wholesale by an edit that leaves 99% of the answers
    still valid — and arXiv throttles (503, then read timeouts) long before a re-fetch finishes.
    """
    import xml.etree.ElementTree as ET

    store = cache / "arxiv-categories.json"
    known: dict[str, str] = json.loads(store.read_text(encoding="utf-8")) if store.exists() else {}
    todo = [i for i in ids if i not in known]
    if todo:
        print(f"  캐시 {len(ids) - len(todo)}편 재사용, 신규 조회 {len(todo)}편")
    for i in range(0, len(todo), 100):
        batch = todo[i : i + 100]
        url = f"{ARXIV_API}?id_list={','.join(batch)}&max_results=100"
        # arXiv answers 503 (then plain read timeouts) when it wants the caller to back off, so
        # this needs the same retry the S2 path has. The Request is rebuilt per attempt on
        # purpose: urllib records redirect state on the object, so reusing one across retries
        # trips its "infinite loop" guard on the second try.
        root = None
        for attempt in range(6):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "docsuri-corpus/1.0"})
                with urllib.request.urlopen(req, timeout=90) as resp:
                    root = ET.fromstring(resp.read())
                break
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
                code = getattr(exc, "code", None)
                if code is not None and code not in (429, 500, 502, 503, 504):
                    raise
                wait = 10.0 * (attempt + 1)
                print(f"    [arXiv {code or 'timeout'}] 대기 {wait:.0f}s", file=sys.stderr)
                time.sleep(wait)
        if root is None:
            # Partial knowledge is fine — the caller only uses this for the canon ceiling, and
            # an unknown category simply does not count against any cap. Failing the whole run
            # over a throttle would throw away the S2 work already done.
            print("    arXiv 조회 포기 — 남은 편은 카테고리 미상으로 진행", file=sys.stderr)
            break
        for entry in root.findall("a:entry", _ARXIV_NS):
            pid = entry.find("a:id", _ARXIV_NS)
            pc = entry.find("arxiv:primary_category", _ARXIV_NS)
            if pid is None or pc is None:
                continue
            m = re.search(r"abs/(.+?)(?:v\d+)?$", pid.text or "")
            if m:
                known[m.group(1)] = pc.get("term") or "?"
        store.write_text(json.dumps(known), encoding="utf-8")
        time.sleep(3.0)
    return {i: known[i] for i in ids if i in known}


def canon_target_lookup(buckets: tuple) -> int:
    """How far down the ranking to resolve categories — the ceiling can push the canon tier
    well past its own size before it fills, so look up a generous multiple of it."""
    return buckets[0][1] * 4


def _get(url: str, params: dict, cache: pathlib.Path, pause: float) -> dict:
    """One cached GET. Retries 429/5xx with linear backoff; raises on anything else."""
    qs = urllib.parse.urlencode(params)
    key = hashlib.sha256(f"{url}?{qs}".encode()).hexdigest()[:24]
    hit = cache / f"{key}.json"
    if hit.exists():
        return json.loads(hit.read_text(encoding="utf-8"))

    last: Exception | None = None
    for attempt in range(6):
        try:
            req = urllib.request.Request(f"{url}?{qs}", headers={"User-Agent": "docsuri-corpus/1.0"})
            with urllib.request.urlopen(req, timeout=90) as resp:
                payload = json.loads(resp.read())
            hit.write_text(json.dumps(payload), encoding="utf-8")
            time.sleep(pause)
            return payload
        except urllib.error.HTTPError as exc:  # noqa: PERF203
            last = exc
            if exc.code not in (429, 500, 502, 503, 504):
                raise
            wait = pause * (attempt + 1) * 4
            print(f"    [{exc.code}] 대기 {wait:.0f}s", file=sys.stderr)
            time.sleep(wait)
        except (urllib.error.URLError, TimeoutError) as exc:
            last, _ = exc, time.sleep(pause * (attempt + 1) * 2)
    raise RuntimeError(f"S2 요청 실패: {url}?{qs}") from last


def _arxiv_id(paper: dict) -> str | None:
    return ((paper or {}).get("externalIds") or {}).get("ArXiv")


def collect_by_citation(
    query: str, cache: pathlib.Path, pause: float, want: int, years: str = CANDIDATE_YEARS
) -> list[dict]:
    """Signal A — the citation-count top of one query within one age band, arXiv rows only."""
    out: list[dict] = []
    dropped = 0
    token = None
    while len(out) < want:
        params = {
            "query": f'"{query}"',
            "fieldsOfStudy": "Computer Science",
            "fields": "paperId,title,year,citationCount,externalIds",
            "sort": "citationCount:desc",
            "year": years,
        }
        if token:
            params["token"] = token
        page = _get(f"{S2}/paper/search/bulk", params, cache, pause)
        rows = page.get("data") or []
        if not rows:
            break
        for p in rows:
            if _arxiv_id(p):
                out.append(p)
            else:
                dropped += 1
        token = page.get("token")
        if not token:
            break
    print(f"    인용수 상위 {len(out)}편 수집 (arXiv 없어 제외 {dropped}편)")
    return out[:want]


def collect_survey_refs(query: str, cache: pathlib.Path, pause: float) -> collections.Counter:
    """Signal B — how many independent recent surveys of this topic cite each paper."""
    params = {
        "query": f'"{query}" survey',
        "fieldsOfStudy": "Computer Science",
        "fields": "paperId,title,year,citationCount",
        "sort": "citationCount:desc",
        "year": SURVEY_YEARS,
    }
    page = _get(f"{S2}/paper/search/bulk", params, cache, pause)
    surveys = [p for p in (page.get("data") or []) if _SURVEY_RE.search(p.get("title") or "")]
    surveys = surveys[:SURVEYS_PER_BUCKET]

    freq: collections.Counter = collections.Counter()
    for s in surveys:
        refs = _get(
            f"{S2}/paper/{s['paperId']}/references",
            {"fields": "title,year,citationCount,externalIds", "limit": REFERENCE_LIMIT},
            cache,
            pause,
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

    cache = pathlib.Path(args.cache)
    cache.mkdir(parents=True, exist_ok=True)

    # arxiv_id -> merged record
    pool: dict[str, dict] = {}
    survey_votes: collections.Counter = collections.Counter()

    for name, target, queries, _note in BUCKETS:
        for qi, query in enumerate(queries):
            print(f"[{name}] '{query}'")
            # Over-collect: the bucket fill drops anything the canon tier already took.
            for band in (CANDIDATE_YEARS, RECENT_BAND_YEARS):
                rows = collect_by_citation(query, cache, args.pause, want=target * 2, years=band)
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
                survey_votes.update(collect_survey_refs(query, cache, args.pause))

    # Survey-only papers are worth keeping: being cited by several surveys is the stronger
    # signal of the two, and such a paper can sit below the citation cut of every query.
    missing = [a for a, v in survey_votes.items() if a not in pool and v >= 2]
    print(f"\n서베이에서만 나온 논문 {len(missing)}편 — 메타데이터 보강")
    for i in range(0, len(missing), 400):
        chunk = missing[i : i + 400]
        got = _post_batch(chunk, cache, args.pause)
        for p in got:
            aid = _arxiv_id(p)
            if not aid:
                continue
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
        import math

        rec["score"] = math.log10(rec["citations"] + 10) + 1.5 * rec["surveys"]

    ranked = sorted(pool.values(), key=lambda r: (-r["score"], -r["citations"]))

    # Primary categories are needed only for the canon ceiling, so look them up for the head of
    # the ranking rather than all ~6,000 candidates.
    head = [r["arxiv_id"] for r in ranked[: canon_target_lookup(BUCKETS)]]
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
    canon_target = BUCKETS[0][1]
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
    # Papers held back by the ceiling are still foundational — they fall through to their own
    # subject bucket below rather than being dropped.
    if len(chosen) < canon_target:
        for rec in deferred:
            if len(chosen) >= canon_target:
                break
            chosen[rec["arxiv_id"]] = "canon"
    print("[canon] 분야 구성: " + " · ".join(f"{k} {v}" for k, v in per_cat.most_common(6)))
    recent_from = int(RECENT_BAND_YEARS.split("-")[0])
    for name, target, query, _note in BUCKETS[1:]:
        quota = int(target * RECENT_BAND_SHARE)
        # Recent band first, up to its quota — otherwise the older band, which always wins on
        # absolute citations, would consume the whole bucket before a 2023 paper is reached.
        n = recent = 0
        for want_recent in (True, False):
            for rec in ranked:
                if n >= target:
                    break
                is_recent = rec["year"] >= recent_from
                if is_recent is not want_recent:
                    continue
                if want_recent and recent >= quota:
                    break
                if rec["arxiv_id"] in chosen or name not in rec["buckets"]:
                    continue
                chosen[rec["arxiv_id"]] = name
                n += 1
                recent += is_recent
        print(f"[{name}] 배정 {n}/{target} (2022~ {recent}편, 할당 {quota})")

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        fh.write("arxiv_id\tbucket\tyear\tcitations\tsurveys\ttopics\tscore\ttitle\n")
        for rec in ranked:
            b = chosen.get(rec["arxiv_id"])
            if not b:
                continue
            # ``topics`` = how many of the topic queries surfaced this paper. It is the canon
            # gate, so keep it in the output: a reviewer can re-derive the tier from the file.
            fh.write(
                f"{rec['arxiv_id']}\t{b}\t{rec['year']}\t{rec['citations']}\t"
                f"{rec['surveys']}\t{len(rec['buckets'])}\t{rec['score']:.3f}\t{rec['title']}\n"
            )
    print(f"\n총 {len(chosen)}편 → {out}")
    return 0


def _post_batch(ids: list[str], cache: pathlib.Path, pause: float) -> list[dict]:
    """S2 batch lookup by ArXiv id. POST, so it is cached by request-body hash."""
    body = json.dumps({"ids": [f"ARXIV:{a}" for a in ids]}).encode()
    key = hashlib.sha256(body).hexdigest()[:24]
    hit = cache / f"batch-{key}.json"
    if hit.exists():
        return json.loads(hit.read_text(encoding="utf-8"))
    req = urllib.request.Request(
        f"{S2}/paper/batch?fields=paperId,title,year,citationCount,externalIds",
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "docsuri-corpus/1.0"},
    )
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                payload = [p for p in json.loads(resp.read()) if p]
            hit.write_text(json.dumps(payload), encoding="utf-8")
            time.sleep(pause)
            return payload
        except urllib.error.HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504):
                raise
            time.sleep(pause * (attempt + 1) * 4)
    return []


if __name__ == "__main__":
    raise SystemExit(main())
