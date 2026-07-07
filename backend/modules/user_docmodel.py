from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote
from uuid import NAMESPACE_URL, UUID, uuid5

from docsuri_shared.dtos import DocModel

USER_DOCMODEL_VERSION = 1
USER_DOCMODEL_MODULES = frozenset({"evidence", "novelty"})
USER_DOCMODEL_MAX_BYTES = 10 * 1024 * 1024
USER_DOCMODEL_PDF_CONTENT_TYPE = "application/pdf"
EVIDENCE_PDF_DEGRADED_NOTICE = "[첨부 안내] PDF 본문을 해석하지 못해 첨부 근거는 제외했습니다."
NOVELTY_PDF_DEGRADED_REASON = "manuscript_pdf_parse_unavailable"


@dataclass(frozen=True, slots=True)
class UserDocModelRef:
    job_id: str
    paper_id: str
    version: int
    object_key: str
    module: str
    owner_id: str
    record_ref: str
    attachment_id: str

    def payload(self) -> dict[str, Any]:
        return {
            "jobId": self.job_id,
            "kind": "BUILD_USER_DOC_MODEL",
            "paperId": self.paper_id,
            "version": self.version,
            "objectKey": self.object_key,
            "module": self.module,
            "ownerId": self.owner_id,
            "recordRef": self.record_ref,
            "correlationId": None,
            "eventId": None,
        }


def user_docmodel_ref(
    *,
    owner_id: str,
    scope_id: str,
    attachment_id: str,
    object_key: str,
    module: str,
) -> UserDocModelRef:
    if module not in USER_DOCMODEL_MODULES:
        raise ValueError("unsupported user doc-model module")
    clean_attachment_id = _handle(attachment_id, fallback="attachment")
    doc_uuid = uuid5(NAMESPACE_URL, f"docsuri:userdoc:{owner_id}:{scope_id}:{clean_attachment_id}")
    job_id = f"userdoc-{doc_uuid}"
    return UserDocModelRef(
        job_id=job_id,
        paper_id=f"userdoc:{doc_uuid}",
        version=USER_DOCMODEL_VERSION,
        object_key=object_key,
        module=module,
        owner_id=owner_id,
        record_ref=f"upload:{owner_id}:{job_id}:{clean_attachment_id}",
        attachment_id=clean_attachment_id,
    )


def ref_from_attachment(
    *,
    owner_id: str,
    scope_id: str,
    attachment_id: str,
    object_key: str,
    module: str,
    paper_id: str | None = None,
    record_ref: str | None = None,
) -> UserDocModelRef:
    object_key = str(object_key or "")
    paper_id = str(paper_id) if paper_id is not None else None
    record_ref = str(record_ref) if record_ref is not None else None
    if paper_id or record_ref:
        if not paper_id or not record_ref:
            raise ValueError("paperId and recordRef must be supplied together")
        clean_attachment_id = _handle(attachment_id, fallback="attachment")
        job_id = _job_id_from_paper_id(paper_id)
        ref = UserDocModelRef(
            job_id=job_id,
            paper_id=paper_id,
            version=USER_DOCMODEL_VERSION,
            object_key=object_key,
            module=module,
            owner_id=owner_id,
            record_ref=record_ref,
            attachment_id=clean_attachment_id,
        )
        _validate_userdoc_ref(ref, validate_object_key=True)
        return ref

    ref = user_docmodel_ref(
        owner_id=owner_id,
        scope_id=scope_id,
        attachment_id=attachment_id,
        object_key=object_key,
        module=module,
    )
    _validate_userdoc_ref(ref, validate_object_key=True)
    return ref


def object_key_for_upload(
    *,
    module: str,
    owner_id: str,
    scope_id: str,
    attachment_id: str,
    file_name: str,
) -> str:
    if module == "novelty":
        prefix = os.getenv("DOCSURI_NOVELTY_ARTIFACT_PREFIX", "novelty/")
    else:
        prefix = os.getenv("DOCSURI_USER_DOCUMENT_PREFIX", "uploads/")
        if not prefix.rstrip("/").endswith(module):
            prefix = f"{prefix.rstrip('/')}/{module}/"
    safe_name = _safe_filename(file_name) or "document.pdf"
    return (
        f"{prefix.strip('/')}/{_handle(owner_id)}/{_handle(scope_id)}/"
        f"{_handle(attachment_id, fallback='attachment')}/{safe_name}"
    )


class UserDocModelCoordinator:
    def __init__(
        self,
        *,
        bucket: str,
        s3_client: Any,
        build_queue: Any | None = None,
        doc_model_reader: Any | None = None,
        max_bytes: int = USER_DOCMODEL_MAX_BYTES,
        poll_timeout_seconds: float = 1.5,
        poll_interval_seconds: float = 0.25,
    ) -> None:
        self._bucket = bucket
        self._s3 = s3_client
        self._build_queue = build_queue
        self._reader = doc_model_reader
        self._max_bytes = max_bytes
        self._poll_timeout = max(0.0, poll_timeout_seconds)
        self._poll_interval = max(0.01, poll_interval_seconds)

    def upload_pdf(
        self,
        ref: UserDocModelRef,
        pdf: bytes,
        *,
        file_name: str,
        content_type: str = USER_DOCMODEL_PDF_CONTENT_TYPE,
    ) -> None:
        if not self._bucket:
            raise ValueError("user document bucket is not configured")
        if content_type.lower().split(";", 1)[0].strip() != USER_DOCMODEL_PDF_CONTENT_TYPE:
            raise ValueError("only PDF uploads are supported")
        if not pdf or len(pdf) > self._max_bytes:
            raise ValueError("PDF upload is empty or exceeds the 10MB limit")
        self._s3.put_object(
            Bucket=self._bucket,
            Key=ref.object_key,
            Body=pdf,
            ContentType=USER_DOCMODEL_PDF_CONTENT_TYPE,
            Metadata={
                "paper-id": ref.paper_id,
                "record-ref": ref.record_ref,
                "owner-id": ref.owner_id,
                "file-name": quote(file_name, safe="")[:240],
            },
        )

    def enqueue_build(self, ref: UserDocModelRef) -> None:
        if self._build_queue is None:
            return
        enqueue = getattr(self._build_queue, "enqueue_user_build", None)
        if enqueue is None:
            return
        enqueue(
            job_id=ref.job_id,
            paper_id=ref.paper_id,
            version=ref.version,
            object_key=ref.object_key,
            module=ref.module,
            owner_id=ref.owner_id,
            record_ref=ref.record_ref,
        )

    def poll_doc_model(self, ref: UserDocModelRef) -> DocModel | None:
        if self._reader is None:
            return None
        deadline = time.monotonic() + self._poll_timeout
        while True:
            try:
                doc = self._reader.get_doc_model(ref.paper_id, ref.version)
            except Exception:  # noqa: BLE001 — best-effort readiness: a reader failure degrades, never 500s (contract).
                return None
            if doc is not None:
                return doc
            now = time.monotonic()
            if now >= deadline:
                return None
            time.sleep(min(self._poll_interval, max(0.0, deadline - now)))

    def peek_doc_model(self, ref: UserDocModelRef) -> DocModel | None:
        """Single non-blocking readiness check (no sleep) for a worker's early retry gate.
        Returns None when the doc-model is not built yet, or the reader is absent/erroring."""
        if self._reader is None:
            return None
        try:
            return self._reader.get_doc_model(ref.paper_id, ref.version)
        except Exception:  # noqa: BLE001 — best-effort peek; a reader failure reads as "not ready".
            return None

    def enqueue_and_poll(self, ref: UserDocModelRef) -> DocModel | None:
        self.enqueue_build(ref)
        return self.poll_doc_model(ref)


def _userdoc_build_queue_url() -> str | None:
    """Where BUILD_USER_DOC_MODEL jobs are enqueued.

    Prefer the dedicated user-PDF build queue (GROBID Option B: its worker carries the GROBID
    sidecar) and fall back to the shared doc-model build queue so an un-split deployment — one
    where DOCSURI_USERDOC_BUILD_QUEUE_URL is not yet set — still enqueues exactly as before.
    """
    return os.getenv("DOCSURI_USERDOC_BUILD_QUEUE_URL") or os.getenv(
        "DOCSURI_DOCMODEL_BUILD_QUEUE_URL"
    )


def build_default_user_docmodel_coordinator() -> UserDocModelCoordinator | None:
    upload_bucket = (
        os.getenv("DOCSURI_USER_DOCUMENT_BUCKET")
        or os.getenv("DOCSURI_NOVELTY_ARTIFACT_BUCKET")
        or os.getenv("DOCSURI_DOCMODEL_BUCKET")
        or os.getenv("DOCSURI_SUMMARY_BUCKET")
    )
    if not upload_bucket:
        return None
    docmodel_bucket = (
        os.getenv("DOCSURI_DOCMODEL_BUCKET")
        or os.getenv("DOCSURI_SUMMARY_BUCKET")
        or upload_bucket
    )
    import boto3

    region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION", "ap-northeast-2")
    s3 = boto3.client("s3", region_name=region)
    reader = None
    try:
        from summarization.adapters.s3_docmodel import S3DocModelReader

        reader = S3DocModelReader(bucket=docmodel_bucket, region_name=region)
    except ModuleNotFoundError:
        reader = None
    queue = None
    queue_url = _userdoc_build_queue_url()
    if queue_url:
        from summarization.adapters.sqs_docmodel_build import SqsDocModelBuildQueue

        queue = SqsDocModelBuildQueue(queue_url=queue_url, region_name=region)
    return UserDocModelCoordinator(
        bucket=upload_bucket,
        s3_client=s3,
        build_queue=queue,
        doc_model_reader=reader,
        poll_timeout_seconds=_float_env("DOCSURI_USER_DOCMODEL_POLL_TIMEOUT_MS", 1500) / 1000,
        poll_interval_seconds=_float_env("DOCSURI_USER_DOCMODEL_POLL_INTERVAL_MS", 250) / 1000,
    )


def _validate_userdoc_ref(ref: UserDocModelRef, *, validate_object_key: bool = False) -> None:
    if ref.module not in USER_DOCMODEL_MODULES:
        raise ValueError("unsupported user doc-model module")
    if not ref.job_id.startswith("userdoc-") or not ref.paper_id.startswith("userdoc:"):
        raise ValueError("invalid user document identity")
    if ref.job_id != _job_id_from_paper_id(ref.paper_id):
        raise ValueError("invalid user document identity")
    expected = f"upload:{ref.owner_id}:{ref.job_id}:{ref.attachment_id}"
    if ref.record_ref != expected:
        raise ValueError("invalid upload recordRef")
    if validate_object_key:
        _validate_userdoc_object_key(ref)


def _validate_userdoc_object_key(ref: UserDocModelRef) -> None:
    expected_prefix = _expected_object_key_prefix(ref)
    if not ref.object_key.startswith(expected_prefix):
        raise ValueError("invalid upload objectKey")


def _expected_object_key_prefix(ref: UserDocModelRef) -> str:
    owner = _handle(ref.owner_id)
    attachment = _handle(ref.attachment_id, fallback="attachment")
    if ref.module == "novelty":
        prefix = os.getenv("DOCSURI_NOVELTY_ARTIFACT_PREFIX", "novelty/").strip("/")
        return f"{prefix}/{owner}/"

    prefix = os.getenv("DOCSURI_USER_DOCUMENT_PREFIX", "uploads/")
    if not prefix.rstrip("/").endswith(ref.module):
        prefix = f"{prefix.rstrip('/')}/{ref.module}/"
    return f"{prefix.strip('/')}/{owner}/{attachment}/{attachment}/"


def _job_id_from_paper_id(paper_id: str) -> str:
    if not paper_id.startswith("userdoc:"):
        raise ValueError("invalid user document identity")
    raw_uuid = paper_id.removeprefix("userdoc:")
    UUID(raw_uuid)
    return f"userdoc-{raw_uuid}"


_SAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_filename(value: str) -> str:
    name = _SAFE_CHARS.sub("_", (value or "").strip()).strip("._")
    return name[:160]


def _handle(value: str, *, fallback: str = "x") -> str:
    handle = _SAFE_CHARS.sub("-", (value or "").strip()).strip("-")
    return (handle or fallback)[:128]


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default
