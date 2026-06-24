# U8 Citation Graph — Patterns

**Unit**: U8 Citation Graph  
**Stage**: CONSTRUCTION -> NFR Design  
**Date**: 2026-06-21

## Cache-First Read

Validate auth and bounds, read the snapshot store unless `refresh=true`, return usable snapshot immediately, and call provider only on miss/refresh/uncovered expansion. Current code uses process-local in-memory TTL; Redis is the production adapter target.

## Lazy 2-Hop Expansion

Initial read returns root 1-hop references. A 2-hop request must include `expandNodeId`; only that node is fetched and merged.

## Bounded Traversal

`CitationTreeBuilder` is the final enforcement point:

- `depthReturned <= 2`
- `visibleNodeCount <= 50`
- duplicate canonical IDs folded
- cycles represented as folded edges, not new nodes

## Provider Degradation

| Provider Result | Response |
| --- | --- |
| success | `Success` or `Partial` |
| timeout/error + cache | cached `Partial` |
| timeout/error without cache | `Unavailable` |
| 429/quota + cache | `RateLimited` with cached tree |
| 429/quota without cache | `RateLimited` |

Client-visible states are limited to `Success`, `Partial`, `Unavailable`, `RateLimited`, and `InvalidRequest`.
