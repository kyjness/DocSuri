"""Test-only Fixtures/Stubs (real-first: NO Production Mock Adapter ships — Q14/TD-S12).

These doubles live in test code only; they are not shipped adapters. They let the domain
core and orchestrator be exercised deterministically without Bedrock/S3/Redis/RDS.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from summarization.domain.assembler import ResultAssembler
from summarization.domain.glossary import GlossaryResolver
from summarization.domain.grounding import GroundingValidator
from summarization.domain.length_router import LengthRouter
from summarization.domain.models import (
    Anchor,
    AnchorTarget,
    SummaryCacheKey,
    SummaryDraft,
    TranslationSegmentsResult,
)
from summarization.domain.refiner import InputRefiner
from summarization.domain.source_selector import SourceSelector
from summarization.domain.structured_translator import StructuredTranslator
from summarization.ports.ports import LlmUnavailable
from summarization.service.orchestrator import SummarizationOrchestrationService

SAMPLE_PAPER = """INTRODUCTION
We propose a new method for representation learning. Our approach improves accuracy.

5.2 Results
Our model achieves 95.3% accuracy on ImageNet, outperforming the baseline.

Table 1: Accuracy comparison. Our method reaches 95.3% accuracy.

Appendix A
Additional supplementary results and ablations are provided here.

References
[1] Some citation. 2020.

Copyright 2025 The Authors. All rights reserved.
"""


def tiny_doc(*, title: str = "Introduction", paragraph: str = "We propose a model."):
    """A minimal valid doc-model (one section, title + paragraph) for translate-path tests."""
    from docsuri_shared.dtos import DocModel

    return DocModel.model_validate(
        {
            "meta": {
                "paperId": "2401.1",
                "version": 1,
                "title": "Sample",
                "provenance": {
                    "sourceTier": "native_html",
                    "parserVersion": "test",
                    "schemaVersion": "1",
                    "generatedAt": "1970-01-01T00:00:00Z",
                },
            },
            "fullText": f"{title}\n\n{paragraph}".strip(),
            "sections": [
                {
                    "id": "s1",
                    "title": title,
                    "blocks": [{"id": "s1.p1", "type": "paragraph", "text": paragraph}],
                }
            ],
        }
    )


def valid_draft() -> SummaryDraft:
    return SummaryDraft(
        tldr="We propose a new method for representation learning.",
        contributions=("A new representation-learning method",),
        method="Our approach improves accuracy.",
        results="Our model achieves 95.3% accuracy on ImageNet.",
        limitations="Evaluated on ImageNet only.",
        reproducibility={"code": "", "data": ""},
        anchors=(
            Anchor(field_name="results", target=AnchorTarget.SECTION,
                   span="95.3% accuracy on ImageNet", label="5.2 Results"),
        ),
    )


@dataclass
class StubLlm:
    draft: SummaryDraft | None = None
    raise_n: int = 0  # raise LlmUnavailable for the first N calls
    empty: bool = False  # emit empty translations (→ empty_translation abstain)
    kept_terms: tuple[str, ...] = ("BERT",)
    _calls: int = 0

    def summarize(self, refined, request, glossary) -> SummaryDraft:
        self._calls += 1
        if self._calls <= self.raise_n:
            raise LlmUnavailable("stub outage")
        return self.draft or valid_draft()

    def translate_segments(self, segments, request, glossary) -> TranslationSegmentsResult:
        self._calls += 1
        if self._calls <= self.raise_n:
            raise LlmUnavailable("stub outage")
        # Deterministic: prefix each segment's text so the source structure/id mapping is
        # verifiable; ``empty`` simulates a blank generation for the abstain path.
        translations = (
            {} if self.empty else {s.id: f"번역:{s.text}" for s in segments}
        )
        return TranslationSegmentsResult(translations=translations, kept_terms=self.kept_terms)


@dataclass
class StubStore:
    data: dict[str, dict] = field(default_factory=dict)
    puts: int = 0

    def get(self, key: SummaryCacheKey) -> dict | None:
        return self.data.get(key.object_path())

    def put(self, key: SummaryCacheKey, payload: dict) -> None:
        self.puts += 1
        self.data[key.object_path()] = payload


@dataclass
class StubFullText:
    text: str | None = SAMPLE_PAPER

    def get_full_text(self, paper_id: str, version: int) -> str | None:
        return self.text


@dataclass
class _Budget:
    degrade_mode: str = "normal"
    circuit_state: str = "closed"
    tier: str = "normal"


@dataclass
class StubCostGuard:
    budget: _Budget = field(default_factory=_Budget)

    def get_budget_state(self) -> _Budget:
        return self.budget


class StubObservability:
    def __init__(self) -> None:
        self.metrics: list[tuple[str, float, dict]] = []

    def emit_metric(self, name, value, tags) -> None:
        self.metrics.append((name, value, dict(tags)))

    def emit_log(self, entry) -> None:
        pass

    def start_span(self, name, context):
        return None

    def audit_append(self, event) -> None:
        pass


def make_orchestrator(
    *,
    llm: StubLlm | None = None,
    store: StubStore | None = None,
    full_text: StubFullText | None = None,
    cost_guard: StubCostGuard | None = None,
    observability: StubObservability | None = None,
    doc_model_reader=None,
    doc_model_build_queue=None,
    map_reduce_summarizer=None,
    summary_job_queue=None,
) -> SummarizationOrchestrationService:
    llm = llm or StubLlm()
    return SummarizationOrchestrationService(
        store=store or StubStore(),
        source_selector=SourceSelector(full_text or StubFullText()),
        refiner=InputRefiner(),
        glossary_resolver=GlossaryResolver(None),
        length_router=LengthRouter(),
        llm=llm,
        grounding=GroundingValidator(),
        assembler=ResultAssembler(),
        cost_guard=cost_guard or StubCostGuard(),
        observability=observability or StubObservability(),
        model_ver="test-model",
        doc_model_reader=doc_model_reader,
        doc_model_build_queue=doc_model_build_queue,
        map_reduce_summarizer=map_reduce_summarizer,
        summary_job_queue=summary_job_queue,
        structured_translator=StructuredTranslator(llm),
    )
