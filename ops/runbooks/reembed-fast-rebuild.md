# Fast corpus re-embed rebuild

Rebuild the whole `docsuri-corpus` vector index into a fresh index in **hours, not days**, by
reindexing from the existing index (not re-harvesting arXiv) and fanning the work across many
one-off ECS tasks, then atomically swapping the read alias. No arXiv fetch, no PDF parse — every
field except `vector` is copied straight from the live index.

Two modes:

| Mode | When | Bedrock? | Steps |
|------|------|----------|-------|
| **A — copy** | reshard / index corruption / same embedding model | no | provision → **copy** → finalize → cutover |
| **B — re-embed** | embedding model or dimension change | yes | provision → **reembed** (×N shards) → finalize → cutover |

The steps live in `docsuri_ingestion.reembed` and dispatch through the worker entrypoint exactly
like the v4 migration (`python -m docsuri_ingestion.worker <step>`), so they run as one-off ECS
`run-task`s on the existing `WorkerTaskDef` — no new service, queue, or task definition.

## Why it's fast (and safe)

- **Source = the existing index**, read once (mode A, server-side `_reindex slices=auto`) or via
  sliced scroll (mode B). No 1-req/3s arXiv token bucket, no pdfplumber.
- **Target is offline** (`number_of_replicas=0`, `refresh_interval=-1`) until finalize → minimal
  write amplification. Live reads keep serving the old index the whole time.
- **Fan-out** is `run-task` count, independent of the ingestion service's `max_capacity=1` cap
  (that cap exists to protect arXiv + OpenSearch during harvest backfills; this path harvests
  nothing).
- Floor is Bedrock embed throughput (mode B) — request a `cohere.embed-v4` quota bump first.

## Prerequisites

1. **Resize the OpenSearch domain up** for the rebuild window (cost-no-object → e.g.
   `r6g.2xlarge.search` ×4). This is a blue/green, online change in `ops/cdk/stacks/search_stack.py`
   (`data_nodes`, instance type) — `cdk deploy Docsuri-Search`. Revert after cutover.
2. **Bedrock quota / the embed-v4 daily-cap reality** (mode B): `cohere.embed-v4` is
   `INFERENCE_PROFILE`-only (no on-demand-by-id, no Provisioned Throughput, no Batch), so every
   invoke goes through the global cross-region profile — gated by a **non-adjustable 432M
   tokens/day** cap (= 300k tokens/min). The full corpus (~500M–1.4B embed-tokens) therefore takes
   **2–4 days regardless of fan-out** — the cap is account-wide, so N parallel tasks just throttle
   each other to the same aggregate. You can still raise the per-minute TPM (a support case, not an
   auto-grant), but it can't beat the daily wall. So run **one** task with
   `DOCSURI_REEMBED_TARGET_TPM` set below the per-minute cap (e.g. `250000`): client-side pacing
   holds throughput under both caps so it grinds continuously without throttle-storming, and turns
   on mget-skip resumability so a killed multi-day task can be relaunched without re-embedding. Only
   leave it `0` (unpaced fast path) when you truly have headroom — a small corpus or a big approved
   bump.
3. Confirm env: the target index name defaults to `docsuri-corpus-v3`
   (`DOCSURI_OPENSEARCH_INDEX_REEMBED`); the source defaults to the live alias `docsuri-corpus`
   (`DOCSURI_REEMBED_SOURCE`). For mode B set `DOCSURI_BEDROCK_MODEL_ID` to the **new** model.
4. Deploy the ingestion task definition that writes `DOCSURI_OPENSEARCH_INDEX=docsuri-corpus`
   (the alias), not a concrete backing index. Otherwise new papers after cutover keep landing in
   the old index and disappear from search.

## Config (all `DOCSURI_*` env on the run-task container override)

| Env | Default | Meaning |
|-----|---------|---------|
| `DOCSURI_OPENSEARCH_INDEX_REEMBED` | `docsuri-corpus-v3` | rebuild target index |
| `DOCSURI_REEMBED_SOURCE` | (alias `docsuri-corpus`) | index/alias to read from |
| `DOCSURI_REEMBED_SHARDS` | `6` | target primary shards (good for both bulk write and k-NN serve) |
| `DOCSURI_REEMBED_SHARD` / `DOCSURI_REEMBED_SHARD_COUNT` | `0` / `1` | this task's sliced-scroll slice / total slices (mode B fan-out) |
| `DOCSURI_REEMBED_BATCH_SIZE` | `96` | scroll page = embed batch (≤96, Bedrock Cohere limit) |
| `DOCSURI_REEMBED_MIN_DOCUMENTS` | `1` | finalize floor; a good rebuild sets this near the known corpus size (~1.5M) |
| `DOCSURI_REEMBED_COPY_RPS` | `-1` | mode A `_reindex` throttle; `-1` = unlimited |
| `DOCSURI_REEMBED_DIMENSION` | (frozen 1024) | embedding + target-index vector width; set `1536` for Cohere v4's default (mode B only) |
| `DOCSURI_REEMBED_TARGET_TPM` | `0` (off) | mode B pacing: >0 caps client-side embed throughput to this many tokens/min (set below the Bedrock per-minute cap, e.g. `250000`) so a binding, non-adjustable daily quota never throttle-storms — and enables mget-skip resumability. `0` = unpaced (needs quota headroom). |
| `DOCSURI_RAW_CACHE_MODE` | `off` | B3 raw cache: `off` (live path, byte-identical) / `prefer` (cache→HTTP, write-back) / `only` (cache-only, no arXiv — used by `reparse`) |
| `DOCSURI_RAW_CACHE_PREFIX` | `raw` | S3 prefix for cached source bytes (`{prefix}/{paperId}/v{version}/{tier}`) |
| `DOCSURI_ARXIV_BULK_BUCKET` | `arxiv` | requester-pays bulk-PDF bucket (`s3://arxiv/pdf/`) that `raw_backfill` streams |
| `DOCSURI_RAW_BACKFILL_MONTHS` | (all) | optional YYMM csv (e.g. `2501,2502`) sharding the bulk prime by submission month |

## Run order

All commands are one-off `aws ecs run-task` on the worker task def, overriding the `worker`
container `command` (and env for the reembed step). Skeleton:

```sh
aws ecs run-task --cluster <cluster> --task-definition <WorkerTaskDef> --launch-type FARGATE \
  --network-configuration '{...worker subnets + SG...}' \
  --overrides '{"containerOverrides":[{"name":"worker","command":["<step>"],
                 "environment":[{"name":"DOCSURI_REEMBED_SHARD","value":"<i>"},
                                {"name":"DOCSURI_REEMBED_SHARD_COUNT","value":"<N>"}]}]}'
```

1. **provision** — `command:["reembed_provision"]`. Creates the tuned target (idempotent).
2. **freeze writes** — pause the bulk ingestion writer before loading: disable the scheduled tick
   or scale `docsuri-ingestion` to zero, then wait for the main ingestion queue/running tasks to
   drain. Reads stay online through the old alias; doc-model-only workers can keep running.
3. **load**:
   - Mode A: `command:["reembed_copy"]` — one task; server-side `_reindex`, polls to completion.
   - Mode B: launch **N** tasks `command:["reembed"]`, each with `DOCSURI_REEMBED_SHARD=i`
     (i = 0..N-1) and `DOCSURI_REEMBED_SHARD_COUNT=N`. Pick N from Bedrock RPM headroom
     (≈ RPM / per-task RPM; 24–100 is typical). Each task scrolls its slice, re-embeds, bulk-writes.
4. **finalize** — `command:["reembed_finalize"]`. Restores `replicas=1` + `refresh_interval=1s`,
   force-merges, and **gates on `DOCSURI_REEMBED_MIN_DOCUMENTS`** — set it to the expected count so
   a truncated rebuild can't cut over. Run only after all mode-B tasks exit 0.
5. **cutover** — `command:["reembed_cutover"]`. Atomically repoints the `docsuri-corpus` alias to
   the target. Search now serves the new vectors.
6. Resume the bulk ingestion writer; it writes through the alias and follows the new backing index.
7. Revert the domain resize; optionally delete the old index once verified.

## Dimension change (Cohere v4 default = 1536)

Cohere Embed v4 defaults to **1536** dims; the live corpus is pinned to **1024**. Re-embedding to
the default is a **dimension change**, which means **mode B only** (old 1024 vectors can't be copied
into a 1536 mapping — `reembed_copy` refuses it) and:

1. Set `DOCSURI_REEMBED_DIMENSION=1536` on the `reembed_provision` and `reembed` tasks. The target
   index mapping and the Bedrock `output_dimension` both follow it — the frozen `vector_spec`
   (still 1024) is intentionally **not** touched yet, so daily ingest and the live reader keep
   working against the old index during the (hours-long) build.
2. **⚠️ Cutover is a coordinated release, not just `reembed_cutover`.** The U2 reader embeds queries
   from the SAME `vector_spec`; pointing the alias at a 1536 index while the reader still queries at
   1024 = every search violates the same-space invariant (`assert_same_space`) → broken results.
   At cutover you MUST, together: bump `shared/vector-spec` (SPEC_VERSION `v2`→`v3`, DIMENSIONS
   `1024`→`1536`, drop the `output_dimension` pin so it uses the default), regenerate, and deploy
   BOTH the reader (discovery) and writer images, THEN run `reembed_cutover`. Rollback = redeploy
   the old images + re-point the alias to the 1024 index.

For a same-model reshard/corruption rebuild, leave `DOCSURI_REEMBED_DIMENSION` unset (mode A).

## Full re-parse (B3 — bulk PDF)

Modes A/B reindex from the existing index — they can't pick up a **parser change** (e.g. a
`PARSER_VERSION` bump), because every field except `vector` is copied from what the old parser
already produced. B3 rebuilds the SEARCH index by **re-parsing the corpus from cached source
bytes**, without hitting arXiv's 1-req/3s limit: prime a raw-byte cache in bulk from arXiv's
requester-pays S3, then re-parse cache-only into the offline re-embed index and reuse the existing
`reembed_finalize` → `reembed_cutover` alias swap.

The two new steps (`raw_backfill`, `reparse`) dispatch through the worker entrypoint exactly like
the other steps (`python -m docsuri_ingestion.worker <step>`).

### Sequence

1. **raw_backfill** — `command:["raw_backfill"]`. Harvests the corpus target set from OAI-PMH, then
   streams the `s3://arxiv/pdf/` bulk tarballs (requester-pays) and caches every target PDF to
   `S3RawContentStore` (`{DOCSURI_RAW_CACHE_PREFIX}/{paperId}/v{version}/pdf`). Shard by submission
   month with `DOCSURI_RAW_BACKFILL_MONTHS=2501,2502,…` (one run-task per month band) to bound each
   task's tar scan. Idempotent; re-runs re-cache by key. Watch `targets_missed` in the logs.
2. **reembed_provision** — `command:["reembed_provision"]`. Creates the tuned OFFLINE target index
   (same step as modes A/B). For a parser-only rebuild leave `DOCSURI_REEMBED_DIMENSION` unset.
3. **reparse** — launch a **fleet** of `command:["reparse"]` run-tasks, each with
   `DOCSURI_RAW_CACHE_MODE=only` and `DOCSURI_OPENSEARCH_INDEX_REEMBED=<target>`. Each task harvests
   OAI metadata (cheap, paged) and re-runs the ingest pipeline, which writes to the offline target
   and fetches source bytes **cache-only** (no arXiv fetch, no rate limit, no `sleep`). Fan out by
   slicing the corpus window across tasks via `DOCSURI_BACKFILL_START`/`DOCSURI_BACKFILL_END`
   sub-windows. `DOCSURI_BEDROCK_MODEL_ID` must be set (each chunk is re-embedded).
4. **reembed_finalize** — `command:["reembed_finalize"]`. Restores prod index settings, force-merges,
   and gates on `DOCSURI_REEMBED_MIN_DOCUMENTS`. Run only after all `reparse` tasks exit 0.
5. **reembed_cutover** — `command:["reembed_cutover"]`. Atomically repoints the `docsuri-corpus`
   alias to the target. Revert the domain resize afterward.

### Caveats (B3-specific)

- **PDF fidelity, not ar5iv HTML.** The bulk prime caches PDFs, so re-parsed chunks come from PDF
  text extraction, not the cleaner ar5iv HTML rung. Full-text search quality is fine; the exact
  chunk text can differ from an HTML-sourced build.
- **Doc-models are NOT rebuilt.** Doc-models are HTML-only and lazy — this path does not touch them.
  They self-heal on demand via the reader's `BUILD_DOC_MODEL` job (which can reuse the Part-A cache
  when `DOCSURI_RAW_CACHE_MODE=prefer` is enabled on the live worker), not through B3.
- **blockRefs are absent/degraded** for PDF-sourced chunks (blockRefs come from the structured HTML
  doc-model, which PDF parsing doesn't produce). The viewer/citation-tree wiring that depends on
  blockRefs is degraded for papers rebuilt from PDF until their doc-model is (lazily) rebuilt.

## Idempotency & rollback

- Every step is re-runnable. `provision` skips an existing target; `reembed`/`reembed_copy` overwrite
  by `_id` (`chunkId`), so a re-run or a redelivered task converges, never duplicates.
- A mode-B shard that dies just gets relaunched with the same `DOCSURI_REEMBED_SHARD`.
- **Rollback after cutover**: re-point the alias back to the previous index with a one-off
  `reembed_cutover` where `DOCSURI_OPENSEARCH_INDEX_REEMBED=<previous index>`. Instant; the old
  index is untouched until you delete it.

## Caveats

- The worker task def bundles the GROBID sidecar (~20 GB image) — it starts idle on every reembed
  task (no parse work) and just adds cold-start. Acceptable for a one-off; not worth a separate
  task def.
- Long abstracts (> `max_chunk_chars`, rare) split into multiple abstract chunks; mode B re-embeds
  the full `abstract` field for each such sub-chunk. Negligible for a model change (text is
  re-embedded anyway) and irrelevant to mode A. Body chunks reproduce exactly (`lexicalTerms`).
- Mode B `skipped_empty` in the logs counts docs whose stored embed text was empty (should be ~0);
  investigate if non-trivial before cutover.
