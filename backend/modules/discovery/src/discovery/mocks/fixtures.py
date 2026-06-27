"""Deterministic index fixtures (MR-2). Includes multi-chunk papers (PaperId dedup, PBT-07)
and a QT-2 eval set with Korean↔English cross-lingual cases (TD-3).

The mock "embedding" is a tiny bag-of-keywords vector where Korean and English synonyms map
to the SAME dimension (cross-lingual), so k-NN matches a Korean query to an English paper —
while BM25 (English title/abstract/lexicalTerms) does not, which is exactly why hybrid
needs the embedding.
This is a deterministic stand-in for real cross-lingual embeddings, not a quality model.
"""

from __future__ import annotations

from docsuri_shared.ids import chunk_id
from docsuri_shared.vector_spec import DIMENSIONS, ArxivCategory, IndexRecord

# Keyword → embedding dimension. KO/EN synonyms share a dim (cross-lingual). Substring match.
KEYWORD_DIMS: dict[str, int] = {
    "diffusion": 0, "확산": 0,
    "protein": 1, "단백질": 1,
    "structure": 2, "구조": 2,
    "language": 3, "model": 3, "언어": 3, "모델": 3, "llm": 3,
    "vision": 4, "비전": 4, "이미지": 4,
    "transformer": 5, "트랜스포머": 5,
    "reinforcement": 6, "강화": 6, "rl": 6,
}


def embed(text: str) -> list[float]:
    """Deterministic bag-of-keywords vector (length = DIMENSIONS). Shared by query + records."""
    vector = [0.0] * DIMENSIONS
    for token in text.lower().split():
        for keyword, dim in KEYWORD_DIMS.items():
            if keyword in token:
                vector[dim] = 1.0
    return vector


def _record(
    paper_id: str,
    *,
    ordinal: int,
    title: str,
    authors: list[str],
    year: int,
    abstract: str,
    keywords: list[str],
    category: str,
) -> IndexRecord:
    snippet = abstract[:160]
    return IndexRecord(
        chunkId=chunk_id(paper_id, ordinal),
        paperId=paper_id,
        version=1,
        vector=embed(" ".join(keywords)),
        section="abstract" if ordinal == 0 else f"body-{ordinal}",
        lexicalTerms=abstract.lower(),
        blockRefs=[],
        title=title,
        authors=authors,
        year=year,
        arxivId=f"{paper_id}v1",
        abstract=abstract,
        abstractSnippet=snippet,
        arxivUrl=f"https://arxiv.org/abs/{paper_id}",
        categories=[ArxivCategory(category)],
    )


# Corpus fixtures. Paper 2401.00001 has TWO chunks → exercises PaperId dedup (PBT-07).
RECORDS: list[IndexRecord] = [
    _record(
        "2401.00001", ordinal=0,
        title="Diffusion Models for Protein Structure Prediction",
        authors=["A. Researcher", "B. Scientist"], year=2024,
        abstract="We apply diffusion models to predict protein structure from sequence.",
        keywords=["diffusion", "protein", "structure"], category="cs.LG",
    ),
    _record(
        "2401.00001", ordinal=1,
        title="Diffusion Models for Protein Structure Prediction",
        authors=["A. Researcher", "B. Scientist"], year=2024,
        abstract="Method section: the diffusion process over protein backbone structure.",
        keywords=["diffusion", "protein", "structure"], category="cs.LG",
    ),
    _record(
        "2401.00002", ordinal=0,
        title="Large Language Models as Few-Shot Learners",
        authors=["C. Author"], year=2023,
        abstract="A large language model performs tasks from few examples.",
        keywords=["language", "model"], category="cs.CL",
    ),
    _record(
        "2401.00003", ordinal=0,
        title="Vision Transformers at Scale",
        authors=["D. Vision"], year=2022,
        abstract="Scaling vision transformer architectures for image recognition.",
        keywords=["vision", "transformer"], category="cs.CV",
    ),
    _record(
        "2401.00004", ordinal=0,
        title="Reinforcement Learning for Robotic Control",
        authors=["E. Robot"], year=2023,
        abstract="Reinforcement learning policies for robotic manipulation.",
        keywords=["reinforcement"], category="cs.AI",
    ),
    _record(
        "2401.00005", ordinal=0,
        title="Protein Folding with Deep Learning",
        authors=["F. Fold"], year=2024,
        abstract="Deep models predict protein folding and 3D structure.",
        keywords=["protein", "structure"], category="stat.ML",
    ),
]

# QT-2 relevance eval set (Recall@10 target is for REAL adapters; here it documents the
# cross-lingual cases the mock supports via k-NN). (query, expected top paperId).
EVAL_CASES: list[tuple[str, str]] = [
    ("diffusion models for protein structure prediction", "2401.00001"),
    ("확산 모델 단백질 구조 예측", "2401.00001"),  # Korean → English paper (cross-lingual)
    ("large language models few shot", "2401.00002"),
    ("강화 학습 로보틱스", "2401.00004"),  # Korean
]
