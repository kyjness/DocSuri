# Deployment Architecture - Cohere v4 Migration

## Topology and Networking
- **Local Execution**: The backfill script runs locally and authenticates to AWS. It calls the `embed-multilingual-v4.0` Bedrock API and connects to the OpenSearch endpoint (either via public/authorized network access or via a bastion host depending on the existing networking setup).

## IAM Roles and Permissions
- The local execution role and the ECS Task Role for U1 Ingestion require `bedrock:InvokeModel` on `arn:aws:bedrock:*:*:foundation-model/cohere.embed-multilingual-v4.0`.
- Both roles also require OpenSearch data plane permissions to write documents and (for the local script) to create indices and manage aliases.

## Migration Lifecycle
1. **Provision**: Run a Python setup script to create the `docsuri-corpus-v2` index.
2. **Dual-write**: Deploy U1 Code updates to ECS so live ingestion starts dual-writing to both v1 and v2.
3. **Backfill**: Run the local script to iterate over the arXiv source, embed with Bedrock, and write to v2.
4. **Cutover**: The local script automatically swaps the OpenSearch alias upon completion.
5. **Cleanup**: Deploy code updates to remove v3 dual-write logic and eventually delete `docsuri-corpus-v1`.
