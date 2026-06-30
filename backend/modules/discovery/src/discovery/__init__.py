"""U2 Discovery — synchronous search read path (Track 3, mock-first).

Pipeline (business-logic-model.md §1): validate → expand → retrieve (hybrid RRF) →
rank (baseline top-N) → [grounding enforce — invoked by the U6 gateway seam, NOT here] →
map decision → assemble. The orchestrator (:mod:`discovery.service.orchestrator`) splits
the pipeline at the grounding seam (``plan_and_retrieve`` / ``finalize``) so the U2 domain
core never calls ``enforce`` (INV-1); the gateway/router applies the injected hook.

External contracts come from :mod:`docsuri_shared` (DTOs/events/vector-spec/ports) — never
forked. Real adapters (OpenSearch/Bedrock) are interfaces only here; mocks live in
:mod:`discovery.mocks` (MR-1/4). SEC-9: cards expose only the projected fields
(Phase 2 Q2 adds source-neutral sourceName/sourceUrl; blockRefs/sourceProvenance stay internal).
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
