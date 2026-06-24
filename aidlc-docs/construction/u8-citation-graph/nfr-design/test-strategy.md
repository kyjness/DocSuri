# U8 Citation Graph — Test Strategy

**Unit**: U8 Citation Graph  
**Stage**: CONSTRUCTION -> NFR Design  
**Date**: 2026-06-21

Default CI uses fixture providers only and must not call Semantic Scholar.

| Type | Coverage |
| --- | --- |
| Unit | request bounds, cache hit/miss, provider degradation, saveability checks |
| Property | depth <= 2, nodes <= 50, duplicate folding idempotence, cycle stop, unresolved isolation |
| DTO | citation response serialize/deserialize roundtrip |
| Integration | FastAPI auth guard, in-memory snapshot seam behavior, U4 save gateway fixture |

Real Semantic Scholar contract tests are marker/env-gated and excluded from default CI.

Fixtures only need: one root with 3 references, duplicate ID, cycle A -> B -> A, unresolved reference, timeout/rate-limit states.
