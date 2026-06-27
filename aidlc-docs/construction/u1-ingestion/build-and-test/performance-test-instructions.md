# Performance Test Instructions — U1 Corpus

## Scope

No separate load-test harness is introduced in this stage. Use existing worker telemetry and bounded backfill batches first.

## Metrics To Capture

- Papers ingested per hour by source.
- DocModel build latency by source tier.
- GROBID request latency and error rate.
- Embedding batch latency.
- OpenSearch bulk upsert latency and candidate document count.
- DLQ count by `failureStage`.
- Bedrock/OpenSearch cost and throttling events.

## Backfill Test

1. Start with a small AI/ML date window.
2. Keep `DOCSURI_CORPUS_SOURCES=ARXIV` for the first run.
3. Record baseline throughput and error rate.
4. Enable Semantic Scholar/OpenAlex only after GROBID sidecar stability is confirmed.
5. Validate candidate generation before alias cutover.

## Pass Criteria

- No unbounded retry loop.
- DLQ payloads retain `sourceName`, `failureStage`, `canonicalKey`, `paperId`, and `version`.
- Candidate generation has nonzero document count before alias switch.
- Cost guard and source throttling keep dependency failures from cascading.

## Deferred

Dedicated stress tooling is deferred until production corpus volume or budget pressure shows the current worker telemetry is insufficient.
