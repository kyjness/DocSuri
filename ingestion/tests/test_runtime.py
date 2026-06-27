from __future__ import annotations

from docsuri_ingestion.domain.enums import DedupDecision, JobKind
from docsuri_ingestion.domain.models import IngestionJob
from docsuri_ingestion.runtime import build_local_runtime


def test_local_runtime_indexes_with_docmodel_block_refs() -> None:
    runtime = build_local_runtime()

    result = runtime.pipeline.ingest_one(
        IngestionJob(
            job_id="local-docmodel",
            kind=JobKind.INCREMENTAL,
            arxiv_ref="2401.00001v1",
        )
    )

    assert result is DedupDecision.NEW
    records = runtime.pipeline._vector_index.records  # noqa: SLF001
    assert records
    assert all(record.blockRefs for record in records.values())
