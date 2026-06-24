# U8 Citation Graph — Configuration

**Unit**: U8 Citation Graph  
**Stage**: CONSTRUCTION -> Infrastructure Design  
**Date**: 2026-06-21

| Name | Default | Purpose |
| --- | --- | --- |
| `CITATION_GRAPH_ENABLED` | `false` | Enables U8 endpoints. |
| `SEMANTIC_SCHOLAR_API_KEY` | unset | Optional provider API key. |
| `CITATION_GRAPH_REDIS_PREFIX` | `citation_graph:v1:` | Reserved for the Redis production snapshot adapter; current code uses process-local in-memory keys. |
| `CITATION_GRAPH_SNAPSHOT_TTL_SECONDS` | `604800` | 7-day snapshot TTL. |
| `CITATION_GRAPH_PROVIDER_TIMEOUT_SECONDS` | `2` | Semantic Scholar timeout target. |
| `CITATION_GRAPH_PROVIDER_RETRIES` | `1` | Maximum retry count. |
| `CITATION_GRAPH_MAX_VISIBLE_NODES` | `50` | Hard response node cap. |
| `CITATION_GRAPH_CONTRACT_TESTS` | unset | Enables opt-in real provider contract tests. |

Production should set `CITATION_GRAPH_ENABLED=true` only after backend route tests and fixture-provider tests pass.
