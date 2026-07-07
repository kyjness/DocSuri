"""Regression tests for PR2 user doc-model coordinator fixes (review of #392)."""

from __future__ import annotations

from urllib.parse import unquote

import pytest

from backend.modules.user_docmodel import (
    UserDocModelCoordinator,
    _userdoc_build_queue_url,
    object_key_for_upload,
    ref_from_attachment,
    user_docmodel_ref,
)


def _ref():
    return user_docmodel_ref(
        owner_id="acct-1",
        scope_id="scope-1",
        attachment_id="att-1",
        object_key="uploads/evidence/acct-1/scope-1/att-1/doc.pdf",
        module="evidence",
    )


class _RaisingReader:
    def get_doc_model(self, paper_id, version):
        raise RuntimeError("simulated AccessDenied / throttle / parse error")


class _CapturingS3:
    def __init__(self):
        self.calls: list[dict] = []

    def put_object(self, **kwargs):
        self.calls.append(kwargs)


def test_poll_doc_model_degrades_when_reader_raises() -> None:
    # get_doc_model raises on non-miss S3 errors; readiness polling must degrade to None,
    # never propagate and 500 the async evidence/research request paths (best-effort contract).
    coord = UserDocModelCoordinator(
        bucket="b",
        s3_client=_CapturingS3(),
        doc_model_reader=_RaisingReader(),
        poll_timeout_seconds=0.0,
        poll_interval_seconds=0.01,
    )

    assert coord.poll_doc_model(_ref()) is None


def test_userdoc_build_queue_url_prefers_dedicated_then_falls_back(monkeypatch) -> None:
    # GROBID Option B routing: user-PDF builds prefer the dedicated userdoc queue (its worker
    # carries the GROBID sidecar). With only the shared doc-model queue set, an un-split
    # deployment still enqueues there (backward compatible). Neither set → no queue.
    monkeypatch.delenv("DOCSURI_USERDOC_BUILD_QUEUE_URL", raising=False)
    monkeypatch.setenv("DOCSURI_DOCMODEL_BUILD_QUEUE_URL", "https://sqs/docmodel")
    assert _userdoc_build_queue_url() == "https://sqs/docmodel"

    monkeypatch.setenv("DOCSURI_USERDOC_BUILD_QUEUE_URL", "https://sqs/userdoc")
    assert _userdoc_build_queue_url() == "https://sqs/userdoc"

    monkeypatch.delenv("DOCSURI_USERDOC_BUILD_QUEUE_URL", raising=False)
    monkeypatch.delenv("DOCSURI_DOCMODEL_BUILD_QUEUE_URL", raising=False)
    assert _userdoc_build_queue_url() is None


def test_upload_pdf_metadata_is_ascii_for_unicode_filename() -> None:
    # S3 object metadata must be US-ASCII; a Korean filename must not make put_object throw.
    s3 = _CapturingS3()
    coord = UserDocModelCoordinator(bucket="b", s3_client=s3)

    coord.upload_pdf(_ref(), b"%PDF-1.4 body", file_name="논문 초안.pdf")

    file_name_meta = s3.calls[0]["Metadata"]["file-name"]
    assert file_name_meta.isascii()
    assert unquote(file_name_meta) == "논문 초안.pdf"


def test_ref_from_attachment_accepts_server_issued_evidence_object_key() -> None:
    object_key = object_key_for_upload(
        module="evidence",
        owner_id="acct-1",
        scope_id="att-1",
        attachment_id="att-1",
        file_name="doc.pdf",
    )
    ref = user_docmodel_ref(
        owner_id="acct-1",
        scope_id="att-1",
        attachment_id="att-1",
        object_key=object_key,
        module="evidence",
    )

    hydrated = ref_from_attachment(
        owner_id="acct-1",
        scope_id="request-1",
        attachment_id="att-1",
        object_key=object_key,
        module="evidence",
        paper_id=ref.paper_id,
        record_ref=ref.record_ref,
    )

    assert hydrated.object_key == object_key
    assert hydrated.paper_id == ref.paper_id
    assert hydrated.record_ref == ref.record_ref


def test_ref_from_attachment_rejects_cross_owner_evidence_object_key() -> None:
    object_key = object_key_for_upload(
        module="evidence",
        owner_id="acct-1",
        scope_id="att-1",
        attachment_id="att-1",
        file_name="doc.pdf",
    )
    ref = user_docmodel_ref(
        owner_id="acct-1",
        scope_id="att-1",
        attachment_id="att-1",
        object_key=object_key,
        module="evidence",
    )
    forged_key = object_key_for_upload(
        module="evidence",
        owner_id="acct-2",
        scope_id="att-1",
        attachment_id="att-1",
        file_name="doc.pdf",
    )

    with pytest.raises(ValueError, match="objectKey"):
        ref_from_attachment(
            owner_id="acct-1",
            scope_id="request-1",
            attachment_id="att-1",
            object_key=forged_key,
            module="evidence",
            paper_id=ref.paper_id,
            record_ref=ref.record_ref,
        )


def test_ref_from_attachment_rejects_wrong_attachment_evidence_object_key() -> None:
    object_key = object_key_for_upload(
        module="evidence",
        owner_id="acct-1",
        scope_id="att-1",
        attachment_id="att-1",
        file_name="doc.pdf",
    )
    ref = user_docmodel_ref(
        owner_id="acct-1",
        scope_id="att-1",
        attachment_id="att-1",
        object_key=object_key,
        module="evidence",
    )
    forged_key = object_key_for_upload(
        module="evidence",
        owner_id="acct-1",
        scope_id="att-2",
        attachment_id="att-2",
        file_name="doc.pdf",
    )

    with pytest.raises(ValueError, match="objectKey"):
        ref_from_attachment(
            owner_id="acct-1",
            scope_id="request-1",
            attachment_id="att-1",
            object_key=forged_key,
            module="evidence",
            paper_id=ref.paper_id,
            record_ref=ref.record_ref,
        )
