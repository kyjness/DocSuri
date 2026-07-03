# Throttled DocModel Rebuild Code Generation Plan

## Unit Context
- Unit: U1 Corpus ingestion / operations stabilization
- Goal: make the existing ingestion worker drain rebuild jobs slowly enough that live OpenSearch search remains healthy.
- Application code stays in the workspace root; this file is the AI-DLC execution checklist only.

## Steps
1. [x] Add worker throttle settings for max SQS messages per poll and loop delay.
2. [x] Apply those settings in the ingestion worker loop for both DocModel and main queues.
3. [x] Set production defaults in CDK worker environment.
4. [x] Add focused regression coverage for configured polling limits.
5. [x] Run targeted validation.
