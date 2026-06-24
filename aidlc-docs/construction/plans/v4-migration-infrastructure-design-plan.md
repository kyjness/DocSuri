# Infrastructure Design Plan - v4-migration

## Design Execution Plan

- [x] Analyze NFR Design (Logical Components) to map to infrastructure.
- [x] Determine Deployment Environment for the migration scripts.
- [x] Determine Storage Infrastructure (AWS OpenSearch index configuration for `docsuri-corpus-v2`).
- [x] Determine Networking/Alias Infrastructure for zero-downtime cutover.
- [x] Ask clarification questions to resolve ambiguities in backfill execution and cutover triggers.

## Clarification Questions

To ensure a robust Infrastructure design for the migration, please answer the following questions:

### Question 1
How should the OpenSearch alias cutover (from `v1` to `v2` index) be triggered once the backfill is complete?

A) **Manual Cutover**: A developer/operator manually updates the alias via a provided CLI script or AWS Console after verifying data parity.
B) **Automated Cutover**: The backfill script automatically swaps the alias as its final step upon successful completion.
C) Other (please describe after [Answer]: tag below)

[Answer]: B. The backfill script automatically swaps the alias as its final step upon successful completion.

### Question 2
Where will the historical data backfill script be executed?

A) **Local Execution**: Run locally from a developer/operator machine with appropriate AWS credentials (simplest for a one-off migration).
B) **ECS/Fargate Task**: Run as a containerized task in AWS ECS (good for long-running, stable network environment).
C) **AWS Lambda + SQS**: A distributed serverless architecture where each historical document is sent to an SQS queue and processed by Lambda (highly scalable but more complex to set up).
D) Other (please describe after [Answer]: tag below)

[Answer]: A. Run locally from a developer/operator machine with appropriate AWS credentials (simplest for a one-off migration).
