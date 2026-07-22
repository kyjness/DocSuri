from __future__ import annotations

import pytest

from docsuri_ingestion.domain.enums import DedupDecision, JobKind
from docsuri_ingestion.domain.models import IngestionJob
from docsuri_ingestion.runtime import _optional_reader, build_local_runtime


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


def _boom() -> object:
    raise ImportError("docling is not installed")


def test_auto_uses_the_reader_when_its_extra_is_installed() -> None:
    """The PDF path is the weakest one and the only path non-arXiv sources take, so a reader that
    is present is used without anyone having to name it in the environment."""
    sentinel = object()

    assert _optional_reader("auto", "docling", lambda: sentinel) is sentinel
    assert _optional_reader(None, "docling", lambda: sentinel) is None


def test_auto_falls_back_to_the_old_behaviour_without_the_extra() -> None:
    """The models are optional extras — an environment without them keeps GROBID's cells rather
    than failing to boot."""
    assert _optional_reader("auto", "docling", _boom) is None


def test_naming_the_reader_makes_a_missing_extra_fatal() -> None:
    """Asking for it explicitly is a promise the deployment relies on; silently running without it
    would leave tables mangled with nothing to show for the request."""
    with pytest.raises(ImportError):
        _optional_reader("docling", "docling", _boom)


def test_off_is_off_and_a_typo_is_not_silently_off() -> None:
    sentinel = object()

    for value in ("off", "none", "false", "0", "disabled", ""):
        assert _optional_reader(value, "docling", lambda: sentinel) is None
    with pytest.raises(ValueError, match="unknown reader"):
        _optional_reader("dockling", "docling", lambda: sentinel)
