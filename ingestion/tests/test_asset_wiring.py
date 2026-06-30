"""FR-17 application wiring: assets are best-effort and never block indexing (BR-27)."""

from __future__ import annotations

from types import SimpleNamespace

from docsuri_ingestion.adapters.local import (
    CapturingObservabilityHub,
    FakeArxivSource,
    FakeEmbeddingPort,
    InMemoryControlPlaneStore,
    InMemoryFullTextStore,
    InMemoryQueue,
    InMemoryVectorIndex,
    sample_metadata,
)
from docsuri_ingestion.application import IngestionPipelineService
from docsuri_ingestion.corpus_sources import CorpusTextCandidate, SourcePaperRecord
from docsuri_ingestion.domain.assets import (
    AssetCropSpec,
    AssetManifest,
    ExtractedAsset,
    FigureTableAsset,
)
from docsuri_ingestion.domain.enums import (
    AssetSourceMode,
    AssetType,
    DedupDecision,
    JobKind,
    SourceName,
)
from docsuri_ingestion.domain.models import IngestionJob
from docsuri_ingestion.resilience import (
    IngestFailureHandler,
    IngestionResilienceService,
    RetryPolicy,
)


class FakeAssetSource:
    def fetch_eprint(self, metadata):
        return b"eprint"

    def fetch_pdf(self, metadata):
        return b"pdf"


class _Extracted:
    def __init__(self, assets, *, raises=False):
        self._assets = assets
        self._raises = raises

    def extract(self, *, paper_id, version, pdf, eprint, figure_specs=None):
        if self._raises:
            raise RuntimeError("boom")
        return self._assets


class RecordingAssetStore:
    def __init__(self):
        self.stored: list[tuple[str, int, int]] = []
        self.removed: list[str] = []

    def store_assets(self, paper_id, version, assets):
        self.stored.append((paper_id, version, len(assets)))
        return AssetManifest(paper_id=paper_id, version=version, assets=())

    def remove_assets(self, paper_id):
        self.removed.append(paper_id)


def _one_asset() -> ExtractedAsset:
    meta = FigureTableAsset(
        asset_id="a", paper_id="2401.00001", version=1, type=AssetType.FIGURE,
        ordinal=0, source_mode=AssetSourceMode.PAGE_CROP,
    )
    return ExtractedAsset(meta=meta, image=b"webp")


def _build(*, extractor=None, store=None, source=None):
    observability = CapturingObservabilityHub()
    resilience = IngestionResilienceService(
        observability,
        retry_policy=RetryPolicy(max_attempts=1, base_delay_seconds=0.0, jitter_ratio=0.0),
        timeout_seconds=2.0,
    )
    control = InMemoryControlPlaneStore()
    index = InMemoryVectorIndex()
    pipeline = IngestionPipelineService(
        arxiv=FakeArxivSource([sample_metadata()]),
        full_text_store=InMemoryFullTextStore(),
        embedding=FakeEmbeddingPort(),
        vector_index=index,
        control_plane=control,
        observability=observability,
        resilience=resilience,
        failure_handler=IngestFailureHandler(InMemoryQueue(), observability),
        asset_extractor=extractor,
        asset_store=store,
        asset_source=source,
    )
    return pipeline, index


def _job() -> IngestionJob:
    return IngestionJob(job_id="job-1", kind=JobKind.EVENT, arxiv_ref="2401.00001v1")


def test_assets_disabled_by_default_does_not_touch_asset_path() -> None:
    pipeline, index = _build()  # no asset components injected
    assert pipeline.ingest_one(_job()) is DedupDecision.NEW
    assert index.records  # indexing unaffected


def test_assets_stored_on_success() -> None:
    store = RecordingAssetStore()
    pipeline, index = _build(
        extractor=_Extracted((_one_asset(),)), store=store, source=FakeAssetSource()
    )
    assert pipeline.ingest_one(_job()) is DedupDecision.NEW
    assert index.records  # paper still indexed
    assert store.stored == [("2401.00001", 1, 1)]


def test_asset_failure_never_blocks_indexing() -> None:
    store = RecordingAssetStore()
    pipeline, index = _build(
        extractor=_Extracted((), raises=True), store=store, source=FakeAssetSource()
    )
    # Extractor raises, but the paper is still indexed successfully (BR-27).
    assert pipeline.ingest_one(_job()) is DedupDecision.NEW
    assert index.records
    assert store.stored == []  # store never reached, no crash


# --- non-arXiv (TEI) record asset path: PDF reuse vs re-fetch -------------------------------


class _SpyCorpusSources:
    """Records re-fetch calls so we can assert the crop step reuses the candidate's PDF bytes."""

    def __init__(self):
        self.fetch_calls = 0

    def fetch_record_pdf(self, record):
        self.fetch_calls += 1
        return b"REFETCHED"


def _record_asset_pipeline(store, corpus_sources):
    observability = CapturingObservabilityHub()
    resilience = IngestionResilienceService(
        observability,
        retry_policy=RetryPolicy(max_attempts=1, base_delay_seconds=0.0, jitter_ratio=0.0),
        timeout_seconds=2.0,
    )
    return IngestionPipelineService(
        arxiv=FakeArxivSource([sample_metadata()]),
        full_text_store=InMemoryFullTextStore(),
        embedding=FakeEmbeddingPort(),
        vector_index=InMemoryVectorIndex(),
        control_plane=InMemoryControlPlaneStore(),
        observability=observability,
        resilience=resilience,
        failure_handler=IngestFailureHandler(InMemoryQueue(), observability),
        asset_store=store,
        corpus_sources=corpus_sources,
    )


def _candidate(*, pdf: bytes | None) -> CorpusTextCandidate:
    return CorpusTextCandidate(
        source_name=SourceName.SEMANTIC_SCHOLAR,
        source_id="s2-1",
        source_tier="SEMANTIC_SCHOLAR_GROBID",
        payload_kind="PDF",
        text="t",
        source_url="u",
        tei="<TEI/>",
        pdf=pdf,
    )


_CROPS = (
    AssetCropSpec(
        asset_id="p:v1:figure:0", type=AssetType.FIGURE, ordinal=0, page=1, bbox=(0, 0, 10, 10)
    ),
)
_PAPER = SimpleNamespace(paper_id="p", version=1)
_RECORD = SourcePaperRecord(
    source_name=SourceName.SEMANTIC_SCHOLAR, source_id="s2-1", title="P", pdf_url="x"
)


def test_record_assets_reuse_candidate_pdf_without_refetch() -> None:
    spy = _SpyCorpusSources()
    pipeline = _record_asset_pipeline(RecordingAssetStore(), spy)
    pipeline._store_record_assets_best_effort(_PAPER, _RECORD, _candidate(pdf=b"%PDF"), _CROPS)
    assert spy.fetch_calls == 0  # reused candidate.pdf — no second download


def test_record_assets_refetch_when_candidate_has_no_pdf() -> None:
    spy = _SpyCorpusSources()
    pipeline = _record_asset_pipeline(RecordingAssetStore(), spy)
    pipeline._store_record_assets_best_effort(_PAPER, _RECORD, _candidate(pdf=None), _CROPS)
    assert spy.fetch_calls == 1  # fell back to re-fetch when bytes are unavailable
