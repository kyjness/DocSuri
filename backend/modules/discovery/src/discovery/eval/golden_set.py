"""QT-2 relevance golden set — labeled queries over the deterministic fixture corpus.

Each ``GoldenCase`` pins a query to the set of paperIds a correct search MUST surface
(``relevant``) OR marks the query as out-of-domain junk that MUST abstain (``expect_abstain``,
US-D6 / F2 — near-noise k-NN neighbors are not "관련 논문"). The paperIds are drawn from
``discovery.mocks.fixtures.RECORDS`` so the set is self-contained and deterministic.

The corpus + mock embedding are coarse bag-of-keywords stand-ins (see fixtures.py), so this
is a *wiring + regression* golden set, not a quality model — the Recall@10 ≥ 0.7 bar it
enforces here is the portable contract that the SAME runner will later apply to the real
adapters against the live corpus (that is where the number earns its keep). Cross-lingual
(KO→EN) cases are included because the query embedding, not BM25, is what makes them recall.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class GoldenCase:
    """One labeled relevance case.

    ``relevant`` is the expected set of relevant paperIds (empty for junk). ``expect_abstain``
    marks an out-of-domain query that MUST reach the no-match empty page (US-D6) — for those,
    ``relevant`` is empty and recall is undefined (they are excluded from the recall metric and
    asserted on the abstain path instead). ``note`` is the human-review anchor (why this label).
    """

    query: str
    relevant: frozenset[str] = field(default_factory=frozenset)
    expect_abstain: bool = False
    note: str = ""


# Target from US-D3 acceptance ("Recall@10 ≥ 0.7"). Kept next to the set it grades.
RECALL_TARGET = 0.7


# --- in-domain queries with expected relevant paperIds (graded by Recall@10) ----------------
RELEVANT_CASES: tuple[GoldenCase, ...] = (
    GoldenCase(
        query="diffusion models for protein structure prediction",
        relevant=frozenset({"2401.00001", "2401.00005"}),
        note="both protein-structure papers; 00001 also adds diffusion",
    ),
    GoldenCase(
        query="확산 모델 단백질 구조 예측",
        relevant=frozenset({"2401.00001", "2401.00005"}),
        note="Korean → English papers (cross-lingual k-NN, BM25 cannot match)",
    ),
    GoldenCase(
        query="protein folding structure",
        relevant=frozenset({"2401.00001", "2401.00005"}),
        note="structure-of-proteins concept, both papers",
    ),
    GoldenCase(
        query="large language models few shot",
        relevant=frozenset({"2401.00002"}),
        note="LLM few-shot paper",
    ),
    GoldenCase(
        query="vision transformer image recognition",
        relevant=frozenset({"2401.00003"}),
        note="ViT paper",
    ),
    GoldenCase(
        query="reinforcement learning robotic control",
        relevant=frozenset({"2401.00004"}),
        note="RL-for-robotics paper",
    ),
    GoldenCase(
        query="강화 학습 로보틱스",
        relevant=frozenset({"2401.00004"}),
        note="Korean → English RL paper (cross-lingual)",
    ),
)


# --- out-of-domain junk queries that MUST abstain (US-D6 / F2) -------------------------------
# Two flavors, both must terminate on the empty page:
#   1. zero-signal junk — no keyword overlap at all → no candidates (abstains with the floor OFF).
#   2. near-noise junk  — a single tangential keyword yields a low positive k-NN score, so the
#      k-NN "nearest neighbor for ANY query" behavior falsely surfaces cards UNLESS the relevance
#      floor abstains it. This is exactly the case the floor exists for.
JUNK_CASES: tuple[GoldenCase, ...] = (
    GoldenCase(
        query="quantum cryptography lattice hardness",
        expect_abstain=True,
        note="zero-signal: no corpus keyword → no candidates, empty page regardless of floor",
    ),
    GoldenCase(
        query="the structure of the universe in cosmology",
        expect_abstain=True,
        note="near-noise: only 'structure' matches → low k-NN score; floor must abstain it",
    ),
)
