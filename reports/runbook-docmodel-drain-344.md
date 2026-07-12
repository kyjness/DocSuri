# Runbook — doc-model DLQ drain + native_html backfill (#343 / #344)

> **Status**: unblocked by v1.13.0 (the #420 throttle is now live in prod). This is a
> **production mutation** — run deliberately, verify live depths first (the counts below are
> point-in-time from 2026-07-07 and will have moved). Owner: ingestion/ops (U1).

## Why this was gated

A bulk arXiv backfill on 3 worker tasks blew past arXiv's ~1-req/3s budget → OpenSearch +
ingestion-queue saturation → live search 503 (k-NN 2.0s timeout) and viewer/citation-tree
doc-model starvation. The fix (**PR #420**, shipped in **v1.13.0**) throttles the arXiv caller
to a single task and drops the burst step, so drains no longer refeed the DLQ. With that live,
the drain is safe to run.

Relevant knobs (already in code, no change needed):
- `docsuri-docmodel-builder` autoscale `min_capacity=0, max_capacity=1` — `ops/cdk/stacks/ingestion_stack.py:419`
- bulk ingestion worker autoscale `max_capacity=1` (was 3) — `ingestion_stack.py:395`
- **Do NOT raise either above 1 during the drain** — that is exactly what caused the search 503s.

## 0. Preconditions (verify, don't assume)

```bash
export AWS_PROFILE=AdministratorAccess-028317349537   # region ap-northeast-2
ACCT=028317349537 ; REGION=ap-northeast-2

# a) throttle actually live? desired/running should be <=1, max_capacity 1
aws ecs describe-services --cluster docsuri --services docsuri-docmodel-builder \
  --query 'services[0].{desired:desiredCount,running:runningCount}' --region $REGION

# b) current DLQ depth (was ~24)
aws sqs get-queue-attributes --region $REGION \
  --queue-url https://sqs.$REGION.amazonaws.com/$ACCT/docsuri-docmodel-dlq \
  --attribute-names ApproximateNumberOfMessages

# c) current native_html coverage in S3 (was 10,660 / 21,252)
aws s3 ls s3://docsuri-papers-fulltext-$ACCT/native_html/ --recursive --summarize \
  --region $REGION | tail -1
```

If the daily harvest is mid-freeze (reembed era disabled `docsuri-arxiv-daily` + set autoscale 0),
confirm you actually want steady-state back before step 3 — see [[project_reembed_v3_pivot]].

## 1. Drain the doc-model DLQ (re-enqueue to source)

The messages are reader-triggered doc-model builds that dead-lettered during the contention.
With the throttle live, redrive them back to the source queue so the single builder consumes them:

```bash
# SQS-native redrive (preferred — no custom script). Source = docsuri-docmodel-queue.
aws sqs start-message-move-task --region $REGION \
  --source-arn arn:aws:sqs:$REGION:$ACCT:docsuri-docmodel-dlq \
  --destination-arn arn:aws:sqs:$REGION:$ACCT:docsuri-docmodel-queue \
  --max-number-of-messages-per-second 1     # keep <=1/s so the single builder + arXiv budget hold
```

- If a message is a **poison record** (build fails deterministically, not from contention), it will
  bounce back to the DLQ after `maxReceiveCount`. Pull one and inspect before assuming the drain
  "didn't work": `aws sqs receive-message --queue-url .../docsuri-docmodel-dlq`.
- **PARSER_VERSION caveat**: if any of these are stale doc-models that a parser fix should self-heal,
  a re-run only heals when the cache key changed — bump `PARSER_VERSION` (@N) *before* re-enqueue or
  the cache-hit + dedup skips the rebuild for free. See [[project_docmodel_reembed_gap]].

## 2. Re-parse native_html-sourced papers (TRACED 2026-07-07 — read before running)

> **What "native_html 10,660/21,252" actually is** (traced 2026-07-07): NOT an S3 `raw/` coverage
> gap — the live `raw/` prefix is **empty** (0 objects), and the figure is nowhere in code. It is
> the **`source_tier` distribution**: ~10,660 of ~21,252 corpus papers were sourced from the
> native_html rung. Those are **re-parse targets** — the doc-model builder rebuilds native_html
> sources (`_REBUILD_SOURCE_TIERS={native_html}`, `docmodel/builder.py:42,334`) because raw TeX/pgf
> leaks into fullText. Live corpus denominator is now **23,512** full-text papers (grew past 21,252).
> Exact current count: run the **`migrate.py audit` step** (#344) — a read-only report of the
> `source_tier` distribution from the canonical Postgres dedup ledger. Any `winning_source_tier`
> WITHOUT a `_GROBID` suffix is an un-re-parsed target; the step prints the total and the
> not-yet-re-parsed count. This is the pre-drain target confirmation this section demands:
> ```bash
> aws ecs run-task --cluster docsuri --launch-type FARGATE --region $REGION \
>   --task-definition docsuri-ingestion \
>   --overrides '{"containerOverrides":[{"name":"worker","command":["python","-m","docsuri_ingestion.worker","audit"]}]}' \
>   --network-configuration '<same subnets/SG as the docsuri-ingestion service>'
> # then read the "audit: N papers; M not yet _GROBID re-parsed" line from the task logs
> ```
>
> **The earlier draft command (`migrate.py --backfill-native-html --bounded`) was WRONG — no such
> flag exists.** The goal is the B3 re-parse pipeline, not a bare raw_backfill: prime pdf bytes
> (`raw_backfill`) **→ `reparse`**. Because `raw/` is empty, the prime is a real prerequisite.

The runner is a **positional step** on the worker entrypoint, not a flag:

```bash
# In-VPC ECS run-task on the ingestion task-def. Shard by submission month to bound each task.
aws ecs run-task --cluster docsuri --launch-type FARGATE --region $REGION \
  --task-definition docsuri-ingestion \
  --overrides '{"containerOverrides":[{"name":"worker",
     "command":["python","-m","docsuri_ingestion.worker","raw_backfill"],
     "environment":[{"name":"DOCSURI_RAW_BACKFILL_MONTHS","value":"2501,2502"},
                    {"name":"DOCSURI_BACKFILL_START","value":"2025-01-01"},
                    {"name":"DOCSURI_BACKFILL_END","value":"2025-03-01"}]}]}' \
  --network-configuration '<same subnets/SG as the docsuri-ingestion service>'
```

**Caveats that make this NOT a fire-and-forget:**
- **Requester-pays**: `raw_backfill` streams arXiv's `s3://arxiv/pdf/` bulk tarballs with
  `RequestPayer=requester` — **we pay** the transfer for every month tar scanned. Shard tightly.
- **Idempotent but NOT incremental** (`raw_backfill.py:97`): a re-run re-downloads and re-caches
  the whole target window — it does **not** skip already-cached papers. "Resume" = run only the
  **missing month shards** via `DOCSURI_RAW_BACKFILL_MONTHS`, or you re-pay for work already done.
- **Tier mismatch to confirm first**: this step caches the **`pdf`** tier
  (`raw_backfill.py:88`). The "native_html 10,660/21,252" figure is a *different* tier's coverage.
  **Before running, confirm the target with the `migrate.py audit` step above** (source_tier
  distribution + not-yet-`_GROBID` count) and which step actually fills it — it may be `backfill`
  (v4 embed) or `reparse`, not `raw_backfill`. Don't run a multi-thousand-paper, requester-pays
  sweep against an unverified target.
- Lower k-NN 503 risk than the embedding backfill (writes S3, not OpenSearch), but the
  `harvest_seed` OAI-PMH call is still arXiv-rate-limited — keep it to one task.

## 3. Restore steady state (only after the drain settles)

1. Re-enable the daily harvest if it was frozen: `aws events enable-rule --name docsuri-arxiv-daily`
   (cron `0 6 * * ? *` = 15:00 KST -> enqueues `{"action":"schedule_tick"}`).
2. Confirm autoscale is back to the **code default `max_capacity=1`** (not 0 from a freeze). No CDK
   change should be needed — if live differs from code, `cdk deploy Docsuri-Ingestion` reconciles.

## 4. Verify

- DLQ depth -> **0** (step 0b re-run).
- `native_html/` object count -> matches corpus (~21k), step 0c.
- **Live search latency nominal** (no k-NN 2.0s timeouts) throughout — this is the canary the
  whole throttle exists to protect. Watch it during step 1–2; if it climbs, pause the move task
  (`aws sqs cancel-message-move-task`).

## #344 queue separation — ALREADY IMPLEMENTED (decision resolved)

Verified in `ops/cdk/stacks/ingestion_stack.py` (deployed): reader-triggered doc-model builds are
already on a **dedicated priority queue with a dedicated worker**, isolated from bulk backfill:

| Work | Queue | Worker (`QUEUE_MODE`) | Notes |
|---|---|---|---|
| Bulk corpus / backfill | `docsuri-ingestion-queue` | `docsuri-ingestion` (`bulk`, max 1) | GROBID; drains docmodel queue *first* for redundancy |
| Reader doc-model (viewer/tree) | **`docsuri-docmodel-queue`** (priority) | `docsuri-docmodel-builder` (`docmodel`, max 1) | lean cpu512/mem1024, **consumes ONLY this queue**, no GROBID (`ingestion_stack.py:344-385`) |
| User PDF | `docsuri-userdoc-queue` | `docsuri-userdoc-builder` (GROBID, max 2) | |

So a large backfill in `docsuri-ingestion-queue` cannot starve reader builds — they land in the
separate `docsuri-docmodel-queue` served by its own worker. **No further separation work is
needed.** `max_capacity=1` stays because arXiv's ~1-req/3s politeness limiter is process-local
(two tasks double the caller rate → 503/429 → DLQ), NOT because of queue contention
(`ingestion_stack.py:390-417`). The only remaining #344 work is the operational drain above.
