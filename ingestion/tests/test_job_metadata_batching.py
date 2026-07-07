"""Harvest-supplied metadata rides inside the job payload (skip per-paper fetch_metadata)."""

from datetime import UTC, datetime

from hypothesis import given
from hypothesis import strategies as st

from docsuri_ingestion.domain.enums import JobKind
from docsuri_ingestion.domain.models import IngestionJob, MetadataRecord
from docsuri_ingestion.worker import job_from_payload


def _record() -> MetadataRecord:
    return MetadataRecord(
        arxiv_ref="2501.00001v2",
        title="A Paper",
        authors=("A. Author", "B. Author"),
        abstract="An abstract.",
        categories=("cs.LG", "stat.ML"),
        updated_at=datetime(2025, 1, 2, tzinfo=UTC),
        published_at=datetime(2025, 1, 1, tzinfo=UTC),
        license_url="http://creativecommons.org/licenses/by/4.0/",
        primary_category="cs.LG",
    )


def test_metadata_record_payload_round_trip() -> None:
    record = _record()
    assert MetadataRecord.from_payload(record.to_payload()) == record


def test_metadata_record_payload_round_trip_without_optionals() -> None:
    record = MetadataRecord(
        arxiv_ref="2501.00002",
        title="T",
        authors=("A",),
        abstract="",
        categories=("cs.AI",),
        updated_at=datetime(2025, 1, 3, tzinfo=UTC),
    )
    assert MetadataRecord.from_payload(record.to_payload()) == record


def test_job_payload_carries_arxiv_metadata_through_queue() -> None:
    record = _record()
    job = IngestionJob(
        job_id="seed-1",
        kind=JobKind.SEED_REBUILD,
        arxiv_ref=record.arxiv_ref,
        arxiv_metadata=record.to_payload(),
    )
    parsed = job_from_payload(job.to_payload())
    assert parsed.arxiv_metadata == record.to_payload()
    assert MetadataRecord.from_payload(parsed.arxiv_metadata) == record


def test_job_payload_omits_absent_metadata() -> None:
    job = IngestionJob(job_id="seed-2", kind=JobKind.SEED_REBUILD, arxiv_ref="2501.00003")
    payload = job.to_payload()
    assert "arxivMetadata" not in payload
    assert job_from_payload(payload).arxiv_metadata is None


_HANDLE_TEXT = st.text(
    alphabet=st.sampled_from(tuple("abcdefghijklmnopqrstuvwxyz0123456789-_")),
    min_size=1,
    max_size=32,
)


@st.composite
def _user_docmodel_job_strategy(draw):
    owner_id = draw(_HANDLE_TEXT)
    job_id = f"userdoc-{draw(st.uuids())}"
    attachment_id = draw(_HANDLE_TEXT)
    filename = draw(_HANDLE_TEXT)
    return IngestionJob(
        job_id=job_id,
        kind=JobKind.BUILD_USER_DOC_MODEL,
        paper_id=f"userdoc:{draw(st.uuids())}",
        version=1,
        object_key=f"uploads/{owner_id}/{job_id}/{attachment_id}/{filename}.pdf",
        module=draw(st.sampled_from(("evidence", "novelty"))),
        owner_id=owner_id,
        record_ref=f"upload:{owner_id}:{job_id}:{attachment_id}",
    )


@given(_user_docmodel_job_strategy())
def test_user_docmodel_job_payload_round_trip(job: IngestionJob) -> None:
    payload = job.to_payload()

    assert "arxivRef" not in payload
    assert job_from_payload(payload) == job
