# U8 Citation Graph — Deployment Topology

**Unit**: U8 Citation Graph  
**Stage**: CONSTRUCTION -> Infrastructure Design  
**Date**: 2026-06-21

```text
User
  -> existing frontend / paper-detail branch
  -> U6 gateway
  -> existing FastAPI backend
     -> snapshot cache seam (in-memory now, Redis target)
     -> Semantic Scholar Graph API
     -> U4 Library
     -> U6 telemetry
```

## Runtime

U8 ships as backend module code inside the current backend deployment. It is guarded by `CITATION_GRAPH_ENABLED`.

## Network

Backend requires outbound HTTPS to Semantic Scholar Graph API. Provider credentials remain server-side.

## Scaling

U8 scales with the existing backend worker count. Current in-memory snapshots are per-process and reset on restart, so they reduce repeat reads only within a worker. Redis should replace the seam before relying on shared cache-hit rate or quota reduction. If provider traffic becomes material, add provider-specific throttling before adding a new service.
