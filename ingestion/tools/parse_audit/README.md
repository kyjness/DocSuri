# parse-audit

Offline tools that measure what the u1 parsers actually recover from real papers — used to verify
the `fix/u1-parse-completeness` pass. With the AWS deployment retired, this is where "does a real
document parse without loss?" gets answered.

All of it is local and free: ar5iv / arXiv are public and paced politely, GROBID and Docling run in
a local container / process. Nothing embeds, calls an LLM, or touches AWS.

## The two audits

**ar5iv (HTML) path — A/B against the merge base.** The same cached HTML is parsed by two checkouts
and the per-paper metrics are diffed; a regression is a paper that parses into *less* than before.
Run over a RANDOM sample so it can show an unbroken paper stayed unbroken, not only that a known
hole was filled.

```bash
cd ingestion
CACHE=/tmp/parse-audit

# 1. cache a random sample's sources (once)
uv run python tools/parse_audit/corpus_sample.py \
    --manifest ~/data/docsuri-data/docmodel-manifest.tsv \
    --count 150 --seed 20260721 --cache $CACHE --html --email you@example.com

# 2. measure with THIS branch's parser
uv run python tools/parse_audit/measure_html.py --cache $CACHE --out after.jsonl

# 3. measure with the base parser (a worktree of the merge target)
git worktree add /tmp/base develop
( cd /tmp/base/ingestion && uv run python "$OLDPWD/tools/parse_audit/measure_html.py" \
    --cache $CACHE --out "$OLDPWD/before.jsonl" )

# 4. the verdict
uv run python tools/parse_audit/diff.py before.jsonl after.jsonl
```

**PDF/GROBID path — against the ar5iv yardstick.** For non-arXiv sources and uploads. Needs GROBID:

```bash
docker run -d --rm --name grobid -p 8070:8070 lfoppiano/grobid:0.8.0

# add --pdf to the sample so PDFs are cached too, then:
uv run python tools/parse_audit/pdf_grobid_audit.py --cache $CACHE --out pdf_audit.jsonl

# table re-read (needs the tables extra + the TEI cache the line above wrote):
uv run --extra tables python tools/parse_audit/table_repair_audit.py --cache $CACHE --out repair_audit.jsonl
```

## Files

| file | what it does |
|---|---|
| `corpus_sample.py` | random sample from the corpus manifest → cache ar5iv HTML / arXiv PDF |
| `measure_html.py` | parse cached HTML with the importable parser → per-paper metrics jsonl |
| `diff.py` | A/B diff of two metric dumps — reports losses (regressions) and gains |
| `pdf_grobid_audit.py` | TEI → DocModel vs the same paper's ar5iv parse (needs GROBID) |
| `table_repair_audit.py` | real Docling repair path — merged/empty tables before vs after (needs GROBID + `tables` extra) |
| `_common.py` | shared metric helpers (kept self-contained so both checkouts measure identically) |

The `corpus_sample.py` cache and all `*.jsonl` outputs are scratch — write them outside the repo.
