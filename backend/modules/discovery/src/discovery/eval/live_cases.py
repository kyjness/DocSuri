"""Known-item golden cases for the REAL corpus (as opposed to :mod:`discovery.eval.golden_set`,
which grades the 6-record synthetic fixture corpus and is explicitly not a quality model).

Each query describes its paper by CONCEPT, never by title. A title query is answered by BM25
alone, so it would score well while measuring nothing about fusion, query embedding, or rerank.

The paperIds were confirmed present by querying the live index (2026-08-15,
``docsuri-deploy-v1``, 119,185 chunks). Three intended entries — Adam, AlphaGo, AlphaFold —
are absent from this corpus and were dropped rather than left as guaranteed misses.

The last three cases are Korean queries against English papers: only the query embedding can
recall those, so they fail loudly if the vector leg is off (which is exactly what an embedding
throttle does, silently, at the HTTP layer).

Known-item recall is a FLOOR, not a quality model. Ranking a survey or a follow-up above the
seminal paper is not necessarily wrong, so a drop here is a prompt to look at what replaced it —
not a verdict. Widen ``relevant`` if a case turns out to have several defensible answers.
"""

from __future__ import annotations

from .golden_set import GoldenCase

LIVE_CASES: tuple[GoldenCase, ...] = (
    GoldenCase("self-attention architecture replacing recurrence for sequence transduction",
               {"1706.03762"}),
    GoldenCase("bidirectional pretraining with masked language modeling objective",
               {"1810.04805"}),
    GoldenCase("denoising diffusion probabilistic model for image generation", {"2006.11239"}),
    GoldenCase("latent space diffusion for high resolution image synthesis", {"2112.10752"}),
    GoldenCase("aligning language models with human preferences via reinforcement learning",
               {"2203.02155"}),
    GoldenCase("residual connections to train very deep networks and fix degradation",
               {"1512.03385"}),
    GoldenCase("generator and discriminator trained in a minimax adversarial game",
               {"1406.2661"}),
    GoldenCase("treating image patches as tokens for a transformer classifier", {"2010.11929"}),
    GoldenCase("few-shot in-context learning emerges at large language model scale",
               {"2005.14165"}),
    GoldenCase("low rank adapters for parameter efficient fine-tuning", {"2106.09685"}),
    GoldenCase("promptable foundation model for image segmentation", {"2304.02643"}),
    GoldenCase("soft alignment attention for neural machine translation", {"1409.0473"}),
    GoldenCase("learning to play video games from raw pixels with deep Q learning",
               {"1312.5602"}),
    GoldenCase("eliciting step by step reasoning by prompting with intermediate steps",
               {"2201.11903"}),
    GoldenCase("open weight foundation chat models with supervised fine-tuning", {"2307.09288"}),
    GoldenCase("encoder decoder with skip connections for biomedical image segmentation",
               {"1505.04597"}),
    GoldenCase("augmenting generation with retrieved documents for knowledge intensive tasks",
               {"2005.11401"}),
    # Cross-lingual (KO query → EN paper): recall here depends on the query embedding.
    GoldenCase("트랜스포머 셀프 어텐션 구조", {"1706.03762"}),
    GoldenCase("확산 모델을 이용한 이미지 생성", {"2006.11239"}),
    GoldenCase("사람 피드백을 이용한 언어모델 정렬", {"2203.02155"}),
)

__all__ = ["LIVE_CASES"]
