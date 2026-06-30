"""HybridRetriever — FR-2 / Q2=A (BR-4; PBT-07).

k-NN ∥ BM25 → Reciprocal Rank Fusion (scale-invariant) → PaperId-level dedup (one record
per paper; many chunks per paper in the index). Idempotent + resultset-preserving (PBT-07):
the output PaperId set equals the union of input PaperId sets, each exactly once.

In lexical-only mode (cost degrade or embedding fallback) only BM25 runs. Any store error
raises ``IndexUnavailable`` (OpenSearch = one store for both k-NN and BM25) → fail-closed.
"""

from __future__ import annotations

from .models import Candidate, CandidateSet, QueryPlan, RetrievalMode, SearchScope

# BM25 field sets by scope. LITE matches the paper's "card" text only (title+abstract) for a
# fast, high-precision human search; FULL adds the per-chunk body (``lexicalTerms``) so the
# agent can find concepts that appear only deep in the body. Trace: FR-2.
_LITE_FIELDS = ("title", "abstract")
_FULL_FIELDS = ("title", "abstract", "lexicalTerms")

# k-NN/BM25 candidate breadth before fusion (> top-N so ranking has headroom). NFR/Infra tune.
# Raised for full-body multi-chunk indexing: one paper now spans many chunks, so a fixed
# slice collapses onto fewer distinct papers after PaperId dedup — over-fetch to refill top-N.
RETRIEVAL_TOP_K = 150
# RRF constant (standard default). NFR/Infra tune.
RRF_K = 60


class HybridRetriever:
    def __init__(self, vector_store, lexical_index) -> None:
        # Typed as ports.VectorStoreAdapter / LexicalIndexAdapter; duck-typed for mock/real.
        self._vector_store = vector_store
        self._lexical_index = lexical_index

    def retrieve(self, plan: QueryPlan, degradation) -> CandidateSet:  # noqa: ARG002
        result_lists = []
        full = plan.scope is SearchScope.FULL
        # Both scopes run k-NN (cross-lingual); scope changes only its breadth. LITE restricts the
        # vector search to abstract chunks (one per paper — fast, paper-level semantic match);
        # FULL searches every chunk (body included) for deep recall.
        if plan.mode is RetrievalMode.HYBRID and plan.embedding_vector is not None:
            result_lists.append(
                self._vector_store.knn_search(
                    plan.embedding_vector, RETRIEVAL_TOP_K, abstract_only=not full
                )
            )
        fields = _FULL_FIELDS if full else _LITE_FIELDS
        result_lists.append(
            self._lexical_index.bm25_search(plan.lexical_terms, RETRIEVAL_TOP_K, fields=fields)
        )

        fused = _reciprocal_rank_fusion(result_lists)
        mode = RetrievalMode.HYBRID if len(result_lists) > 1 else RetrievalMode.LEXICAL_ONLY
        return CandidateSet(candidates=fused, retrieval_mode=mode)


def _reciprocal_rank_fusion(result_lists) -> tuple[Candidate, ...]:
    """Merge ranked lists by RRF and dedup by PaperId (BR-4; PBT-07).

    Per list, a paper contributes only its BEST chunk's rank — max, not sum — so a paper with
    many weakly-matching body chunks can't out-stack a paper with one strong hit (full-body
    length bias). Those per-list bests are then SUMMED across the k-NN and BM25 lists, which
    preserves the hybrid corroboration RRF is for. One record kept per PaperId: the globally
    highest-scoring chunk's record. Sorted by (-score, paperId) so ties are deterministic.
    """
    scores: dict[str, float] = {}
    best_record: dict[str, object] = {}
    best_contribution: dict[str, float] = {}
    for results in result_lists:
        per_list_best: dict[str, float] = {}
        for rank, (record, _store_score) in enumerate(results):
            pid = record.paperId
            contribution = 1.0 / (RRF_K + rank + 1)
            if pid not in per_list_best or contribution > per_list_best[pid]:
                per_list_best[pid] = contribution
            if pid not in best_contribution or contribution > best_contribution[pid]:
                best_contribution[pid] = contribution
                best_record[pid] = record
        for pid, contribution in per_list_best.items():
            scores[pid] = scores.get(pid, 0.0) + contribution
    ordered = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    return tuple(
        Candidate(record=best_record[pid], retrieval_score=score) for pid, score in ordered
    )
