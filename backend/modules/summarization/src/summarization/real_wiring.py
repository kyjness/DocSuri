"""real_wiring — assemble the orchestrator from real adapters (TD-S12, real-first).

The single shipped wiring: Bedrock LLM + S3/Redis store + S3 full-text + RDS glossary,
with the U6 cost-guard / observability hubs injected (single authority). No mock wiring
ships; tests build the orchestrator directly with Fixtures/Stubs.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from docsuri_shared.ports import (
    CostGuardCircuitBreaker,
    GroundingValidatorRegistry,
    ObservabilityHub,
    ValidatorRegistration,
)

from .adapters.bedrock_llm import BedrockLlmGateway
from .adapters.rds_glossary import RdsGlossaryRepository
from .adapters.s3_full_text import S3FullTextSource
from .adapters.s3_redis_store import S3RedisSummaryStore
from .adapters.settings import SummarizationSettings
from .domain.assembler import ResultAssembler
from .domain.glossary import GlossaryResolver
from .domain.grounding import GroundingValidator
from .domain.length_router import LengthRouter
from .domain.refiner import InputRefiner
from .domain.source_selector import SourceSelector
from .domain.structured_translator import StructuredTranslator
from .service.orchestrator import SummarizationOrchestrationService


@dataclass(frozen=True, slots=True)
class SummarizationBundle:
    orchestrator: SummarizationOrchestrationService
    settings: SummarizationSettings
    grounding_registry: GroundingValidatorRegistry


def build_grounding_registry(validator: GroundingValidator) -> GroundingValidatorRegistry:
    """Register U7's ``GroundingValidator`` in the shared grounding registry as the ``summary``
    domain with ``advisory`` authority (D3 / ports.md §2.1).

    U7 verifies document fidelity (SOFT anchor drop / fail-closed abstain) — it is NOT the
    system grounding gate. Enforcement authority is reserved for the ``search`` domain (U6),
    and the registry guard rejects any enforcement claim here. The orchestrator still calls
    ``validate`` directly (call seam unchanged); this registry is the governance catalog that
    records who owns which domain and who may enforce.
    """
    registry = GroundingValidatorRegistry()
    registry.register(
        ValidatorRegistration(
            domain="summary", authority="advisory", owner_unit="U7", validator=validator
        )
    )
    return registry


def build_real_orchestrator(
    settings: SummarizationSettings,
    *,
    cost_guard: CostGuardCircuitBreaker,
    observability: ObservabilityHub,
    abstract_lookup: Callable[[str], str | None] | None = None,
) -> SummarizationBundle:
    assert settings.s3_bucket is not None  # noqa: S101 — gated by summarization_enabled

    llm = BedrockLlmGateway(
        summary_model_id=settings.summary_model_id,
        translate_model_id=settings.translate_model_id,
        region_name=settings.region_name,
    )
    store = S3RedisSummaryStore(
        bucket=settings.s3_bucket,
        ttl_seconds=settings.redis_ttl_seconds,
        region_name=settings.region_name,
        redis_url=settings.redis_url,
    )
    full_text = S3FullTextSource(bucket=settings.s3_bucket, region_name=settings.region_name)
    glossary_repo = RdsGlossaryRepository(dsn=settings.database_url)

    # FR-17 assets (display-only). Wired only when enabled AND a DSN is present — otherwise
    # the orchestrator gets no reader and ``list_assets`` returns None → ``license_unavailable``.
    asset_reader = None
    if settings.assets_enabled and settings.database_url:
        from .adapters.rds_assets import RdsS3AssetReader

        asset_reader = RdsS3AssetReader(
            dsn=settings.database_url,
            signed_url_ttl_seconds=settings.asset_url_ttl_seconds,
        )

    # doc-model rich-view (BR-30, read-only). Wired only when enabled — otherwise the
    # orchestrator gets no reader and ``doc_model`` returns None → ``license_unavailable``.
    doc_model_reader = None
    doc_model_build_queue = None
    if settings.docmodel_viewer_enabled:
        from .adapters.s3_docmodel import S3DocModelReader

        doc_model_reader = S3DocModelReader(
            bucket=settings.s3_bucket, region_name=settings.region_name
        )
        # Lazy build trigger (BR-30/D6, boundary B): on a read miss the orchestrator enqueues a
        # BUILD_DOC_MODEL job onto U1's queue. Wired only when the queue URL is set — otherwise a
        # miss stays ``source_unavailable`` (no build triggered).
        if settings.docmodel_build_queue_url:
            from .adapters.sqs_docmodel_build import SqsDocModelBuildQueue

            doc_model_build_queue = SqsDocModelBuildQueue(
                queue_url=settings.docmodel_build_queue_url,
                region_name=settings.region_name,
            )

    # Long-input map-reduce summarizer (BR-S6, #135). Wired only when enabled — otherwise the
    # MAP_REDUCE band abstains (``input_too_long``), unchanged. Reuses the same LLM gateway.
    map_reduce_summarizer = None
    summary_job_queue = None
    if settings.map_reduce_enabled:
        from .domain.map_reduce import MapReduceSummarizer

        map_reduce_summarizer = MapReduceSummarizer(llm)
        # Async long-summary (BR-S8): when a queue URL is set, the API enqueues + returns pending
        # and the summarization worker produces the result. Unset → map-reduce runs inline.
        if settings.summary_job_queue_url:
            from .adapters.sqs_summary_job import SqsSummaryJobQueue

            summary_job_queue = SqsSummaryJobQueue(
                queue_url=settings.summary_job_queue_url,
                region_name=settings.region_name,
            )

    # Document-fidelity grounding gate (BR-S7). Built once so it can be both injected into the
    # orchestrator (the call seam) and registered in the shared grounding catalog (governance).
    grounding = GroundingValidator()

    orchestrator = SummarizationOrchestrationService(
        store=store,
        source_selector=SourceSelector(
            full_text, abstract_lookup=abstract_lookup, doc_model_reader=doc_model_reader
        ),
        refiner=InputRefiner(),
        glossary_resolver=GlossaryResolver(glossary_repo),
        length_router=LengthRouter(),
        llm=llm,
        grounding=grounding,
        assembler=ResultAssembler(),
        cost_guard=cost_guard,
        observability=observability,
        model_ver=settings.model_ver,
        asset_reader=asset_reader,
        doc_model_reader=doc_model_reader,
        doc_model_build_queue=doc_model_build_queue,
        map_reduce_summarizer=map_reduce_summarizer,
        summary_job_queue=summary_job_queue,
        # Structured translation (BR-S18) drives the translate path; reuses the same LLM gateway.
        structured_translator=StructuredTranslator(llm),
    )
    return SummarizationBundle(
        orchestrator=orchestrator,
        settings=settings,
        grounding_registry=build_grounding_registry(grounding),
    )
