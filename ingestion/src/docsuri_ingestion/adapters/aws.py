from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from docsuri_shared.dtos import DocModel
from docsuri_shared.vector_spec import EMBEDDING_SPEC
from pydantic import ValidationError

from docsuri_ingestion.domain.enums import FailureReason
from docsuri_ingestion.domain.errors import (
    PermanentIngestionError,
    RetriableIngestionError,
    ValidationViolationError,
)
from docsuri_ingestion.domain.models import IndexRecordBatch, IndexStats, ParsedPaper, Tombstone
from docsuri_ingestion.ports import QueueMessage
from docsuri_ingestion.settings import IngestionSettings

_log = logging.getLogger(__name__)

# Cohere Embed on Bedrock accepts at most 96 texts per invoke_model call. Public because the
# re-embed runner pages against the same ceiling.
BEDROCK_EMBED_BATCH_LIMIT = 96


def build_s3_client(client: Any = None) -> Any:
    """A boto3 S3 client, reusing the caller's when it has one.

    Every store below takes an optional client so a runtime that wires several of them against the
    SAME bucket pays for one. Building a client is session + loader + endpoint resolution and its
    own connection pool, and this module builds four of them under one worker — the cost the
    runtime's raw-cache comment already names, applied to a single store and none of its siblings.
    Omitting it keeps each store standalone, which is how the one-off tools construct them.

    ``build_`` to match ``build_opensearch_client`` below, the file's other adapter-side factory —
    and to stay clear of ``s3_client``, which is the name the backend's own adapters give the
    injected client PARAMETER. One spelling should not mean both the factory and its argument.
    """
    if client is not None:
        return client
    import boto3

    return boto3.client("s3")


class S3FullTextStore:
    def __init__(
        self,
        *,
        bucket: str,
        prefix: str = "full-text",
        kms_key_id: str | None = None,
        client: Any = None,
    ) -> None:
        self._client = build_s3_client(client)
        self._bucket = bucket
        self._prefix = prefix.strip("/")
        self._kms_key_id = kms_key_id

    def put_full_text(self, paper: ParsedPaper) -> str:
        return s3_put(
            self._client,
            bucket=self._bucket,
            key=f"{self._prefix}/{paper.paper_id}/v{paper.version}.txt",
            body=paper.full_text.encode("utf-8"),
            content_type="text/plain; charset=utf-8",
            kms_key_id=self._kms_key_id,
            metadata={
                "paper-id": paper.paper_id,
                "version": str(paper.version),
                "license": paper.license_url,
            },
        )


class S3DocModelStore:
    """BR-30 doc-model cache on S3 (Infra §1.1b): ``doc-model/{paperId}/v{version}.json``.

    Same single bucket as full-text/assets, separate ``doc-model/`` prefix; image bytes are
    NOT stored here (the JSON references webp assets by assetId). SSE-KMS when a key is set,
    else SSE-S3. ``get`` returns ``None`` on a cache miss; ``remove`` drops every cached
    version for a paper (version-change / tombstone invalidation).
    """

    def __init__(
        self,
        *,
        bucket: str,
        prefix: str = "doc-model",
        kms_key_id: str | None = None,
        client: Any = None,
    ) -> None:
        self._client = build_s3_client(client)
        self._bucket = bucket
        self._prefix = prefix.strip("/")
        self._kms_key_id = kms_key_id

    def _key(self, paper_id: str, version: int) -> str:
        return f"{self._prefix}/{paper_id}/v{version}.json"

    def get(self, paper_id: str, version: int) -> DocModel | None:
        raw = s3_get_or_none(
            self._client, bucket=self._bucket, key=self._key(paper_id, version)
        )
        if raw is None:
            return None
        try:
            return DocModel.model_validate_json(raw)
        except ValidationError:
            # An artifact cached under an older schema (e.g. pre-``fullText``) no longer
            # deserializes. Treat it as a cache miss so the builder rebuilds and re-caches a
            # valid doc-model, rather than crashing the job. The builder's parserVersion gate
            # already forces a rebuild on version drift; this covers the harder schema break.
            return None

    def put(self, doc: DocModel) -> str:
        return s3_put(
            self._client,
            bucket=self._bucket,
            key=self._key(doc.meta.paperId, doc.meta.version),
            # exclude_none keeps optional fields off the wire; consumers ignore unknowns.
            body=doc.model_dump_json(exclude_none=True).encode("utf-8"),
            content_type="application/json; charset=utf-8",
            kms_key_id=self._kms_key_id,
            metadata={
                "paper-id": doc.meta.paperId,
                "version": str(doc.meta.version),
                "parser-version": doc.meta.provenance.parserVersion,
                "schema-version": doc.meta.provenance.schemaVersion,
            },
        )

    def remove(self, paper_id: str) -> None:
        paginator = self._client.get_paginator("list_objects_v2")
        keys: list[dict[str, str]] = []
        for page in paginator.paginate(Bucket=self._bucket, Prefix=f"{self._prefix}/{paper_id}/"):
            keys.extend({"Key": obj["Key"]} for obj in page.get("Contents", []))
        for start in range(0, len(keys), 1000):  # DeleteObjects caps at 1000 keys per call
            self._client.delete_objects(
                Bucket=self._bucket, Delete={"Objects": keys[start : start + 1000]}
            )


class S3RawContentStore:
    """Raw upstream-byte cache on S3 (B3 fast re-parse): ``{prefix}/{paperId}/v{version}/{tier}``.

    Same single bucket as full-text/doc-model, separate ``raw/`` prefix. Caches the exact source
    bytes per tier (``pdf`` / ``ar5iv`` / ``native_html``) so a full re-parse can rebuild the search
    index from the cache instead of re-hitting arXiv's 1-req/3s limit. SSE-KMS when a key is set,
    else SSE-S3; ``get_raw`` returns ``None`` on a cache miss (mirrors S3DocModelStore.get).
    """

    def __init__(
        self,
        *,
        bucket: str,
        prefix: str = "raw",
        kms_key_id: str | None = None,
        client: Any = None,
    ) -> None:
        self._client = build_s3_client(client)
        self._bucket = bucket
        self._prefix = prefix.strip("/")
        self._kms_key_id = kms_key_id

    def _key(self, paper_id: str, version: int, tier: str) -> str:
        return f"{self._prefix}/{paper_id}/v{version}/{tier}"

    def put_raw(
        self,
        paper_id: str,
        version: int,
        tier: str,
        data: bytes,
        *,
        content_type: str = "application/octet-stream",
    ) -> str:
        return s3_put(
            self._client,
            bucket=self._bucket,
            key=self._key(paper_id, version, tier),
            body=data,
            content_type=content_type,
            kms_key_id=self._kms_key_id,
            metadata={"paper-id": paper_id, "version": str(version), "tier": tier},
        )

    def get_raw(self, paper_id: str, version: int, tier: str) -> bytes | None:
        return s3_get_or_none(
            self._client, bucket=self._bucket, key=self._key(paper_id, version, tier)
        )


class S3UserDocumentSource:
    """Read producer-uploaded PDF bytes for BUILD_USER_DOC_MODEL jobs.

    The queue payload carries only an object key; the bucket remains deployment configuration.
    Backend upload validation is not trusted as the sole guard, so the worker enforces a hard byte
    cap before handing data to pdfplumber.
    """

    def __init__(
        self, *, bucket: str, max_bytes: int = 10 * 1024 * 1024, client: Any = None
    ) -> None:
        self._client = build_s3_client(client)
        self._bucket = bucket
        self._max_bytes = max_bytes

    def fetch_pdf(self, object_key: str) -> bytes:
        from botocore.exceptions import ClientError

        if not object_key:
            raise PermanentIngestionError(
                "empty user document object key",
                reason=FailureReason.VALIDATION_VIOLATION,
                stage="s3",
            )
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=object_key)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code in _S3_MISSING_CODES:
                raise PermanentIngestionError(
                    "user document object not found",
                    reason=FailureReason.FETCH_FAILURE,
                    stage="s3",
                ) from exc
            raise RetriableIngestionError(
                "user document fetch failed",
                reason=FailureReason.DEPENDENCY_UNAVAILABLE,
                stage="s3",
            ) from exc

        length = response.get("ContentLength")
        if isinstance(length, int) and length > self._max_bytes:
            raise PermanentIngestionError(
                "user document exceeds maximum size",
                reason=FailureReason.VALIDATION_VIOLATION,
                stage="s3",
            )
        data = response["Body"].read(self._max_bytes + 1)
        if len(data) > self._max_bytes:
            raise PermanentIngestionError(
                "user document exceeds maximum size",
                reason=FailureReason.VALIDATION_VIOLATION,
                stage="s3",
            )
        return data


class BedrockCohereEmbeddingPort:
    def __init__(
        self,
        *,
        model_id: str,
        region_name: str | None = None,
        output_dimension: int | None = None,
    ) -> None:
        import boto3

        self._client = boto3.client("bedrock-runtime", region_name=region_name)
        self._model_id = model_id
        # Cohere Embed v3 (multilingual/english) is a DIFFERENT request shape than v4: fixed
        # 1024-dim (no output_dimension param — sending it 400s) and a 512-token input cap (needs
        # truncate). v4 keeps the output_dimension pin. Detect by the model id suffix.
        self._is_v3 = "-v3" in model_id
        # Defaults to the frozen spec width (1024). A re-embed to a different space (e.g. Cohere
        # v4's 1536 default) overrides it so the request pin + length check match the new vectors.
        self._output_dimension = output_dimension or EMBEDDING_SPEC.dimensions

    def embed_documents(
        self,
        texts: list[str] | tuple[str, ...],
        *,
        correlation_id: str | None = None,
    ) -> list[list[float]]:
        del correlation_id
        if EMBEDDING_SPEC.input_type_writer != "search_document":
            raise RuntimeError("Bedrock writer must use search_document input type")
        # Cohere Embed on Bedrock caps a single request at 96 texts; a long paper chunks well past
        # that (block-level chunking, ~91 chunks median and up to max_chunks_per_paper=512).
        # Sub-batch and concatenate IN ORDER — the assembler zips chunk_ids↔vectors with
        # strict=True, so order must be preserved.
        vectors: list[list[float]] = []
        for start in range(0, len(texts), BEDROCK_EMBED_BATCH_LIMIT):
            vectors.extend(self._embed_batch(texts[start : start + BEDROCK_EMBED_BATCH_LIMIT]))
        return vectors

    def _embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        # Cohere v3 hard-rejects any text > 2048 CHARS (Bedrock input validation, applied BEFORE the
        # token-level truncate), so cap client-side; else one long chunk 400s the whole batch.
        payload_texts = [t[:2048] for t in texts] if self._is_v3 else list(texts)
        body = {
            "texts": payload_texts,
            "input_type": EMBEDDING_SPEC.input_type_writer,
            "embedding_types": ["float"],
        }
        if self._is_v3:
            # v3 is fixed 1024-dim (no output_dimension); truncate=END also caps tokens (<=512).
            body["truncate"] = "END"
        else:
            # Cohere Embed v4 defaults to 1536-dim; pin to the configured width (the frozen 1024 for
            # the live path, or a re-embed override e.g. 1536) so vectors match the target mapping.
            body["output_dimension"] = self._output_dimension
        response = self._client.invoke_model(
            modelId=self._model_id,
            body=json.dumps(body).encode("utf-8"),
            accept="application/json",
            contentType="application/json",
        )
        payload = json.loads(response["body"].read().decode("utf-8"))
        vectors = payload.get("embeddings", [])
        if isinstance(vectors, dict):
            vectors = vectors.get("float", [])
        for vector in vectors:
            if len(vector) != self._output_dimension:
                raise ValidationViolationError(
                    f"Bedrock returned vector dimension {len(vector)}, "
                    f"expected {self._output_dimension}",
                    stage="embed",
                )
        return vectors


# S3 error codes that mean "no such object" rather than a real fault. get_object reports a
# missing key differently depending on whether the caller holds s3:ListBucket, so all three
# spellings must count as a miss.
_S3_MISSING_CODES = frozenset({"NoSuchKey", "404", "NotFound"})


def s3_put(
    client: Any,
    *,
    bucket: str,
    key: str,
    body: bytes,
    content_type: str,
    kms_key_id: str | None,
    metadata: dict[str, str] | None = None,
) -> str:
    """PUT an encrypted object and return its ``s3://`` URI.

    Server-side encryption is KMS when a key is configured and SSE-S3 otherwise; keeping that
    branch here means no writer can accidentally ship an unencrypted object.
    """
    kwargs: dict[str, Any] = {
        "Bucket": bucket,
        "Key": key,
        "Body": body,
        "ContentType": content_type,
        "ServerSideEncryption": "aws:kms" if kms_key_id else "AES256",
    }
    if metadata:
        kwargs["Metadata"] = metadata
    if kms_key_id:
        kwargs["SSEKMSKeyId"] = kms_key_id
    client.put_object(**kwargs)
    return f"s3://{bucket}/{key}"


def s3_get_or_none(client: Any, *, bucket: str, key: str) -> bytes | None:
    """Object bytes, or None when the key is absent — an absent cache entry is a miss, not a
    fault. Every other ClientError propagates so real S3 faults stay retriable."""
    from botocore.exceptions import ClientError

    try:
        response = client.get_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in _S3_MISSING_CODES:
            return None
        raise
    return response["Body"].read()


def admin_client_from_settings(settings: IngestionSettings):
    """Admin OpenSearch client for the one-off migrate/re-embed entrypoints.

    Lives beside ``build_opensearch_client`` rather than in either entrypoint: migrate imports
    reembed for its step table, so a copy in one of them cannot be imported by the other.
    """
    if not settings.opensearch_endpoint:
        raise SystemExit("DOCSURI_OPENSEARCH_ENDPOINT is required")
    local = settings.env == "local"
    # TLS is NOT decided here — ``build_opensearch_client`` reads it off the endpoint scheme.
    return build_opensearch_client(
        endpoint=settings.opensearch_endpoint,
        region_name=None if local else settings.aws_region,
    )


def build_opensearch_client(
    *,
    endpoint: str,
    region_name: str | None = None,
    username: str | None = None,
    password: str | None = None,
    use_ssl: bool | None = None,
    verify_certs: bool | None = None,
):
    """Build an opensearch-py client. Auth order: basic-auth if both creds are given
    (local/override), else SigV4 (``Urllib3AWSV4SignerAuth``, service ``es``) when a region
    is set — the managed VPC domain authorizes the ECS task role by resource policy, so signed
    requests are required — else unsigned (local clusters with an open policy).

    TLS is READ OFF THE ENDPOINT unless the caller overrides it. Three call sites each decided
    this separately and one of them did not decide at all: the pipeline writer took the
    ``use_ssl=True`` default and spoke TLS to an ``http://`` cluster, so every ``_bulk`` died with
    ``WRONG_VERSION_NUMBER`` — on the batch path, where it is a whole run's worth of papers
    parsed and then dropped at the last step. The endpoint string already says which it is, so it
    is the one thing asked."""
    from opensearchpy import OpenSearch

    plain_http = endpoint.startswith("http://")
    use_ssl = (not plain_http) if use_ssl is None else use_ssl
    verify_certs = (not plain_http) if verify_certs is None else verify_certs

    if username and password:
        http_auth = (username, password)
    elif region_name:
        import boto3
        from opensearchpy import Urllib3AWSV4SignerAuth

        http_auth = Urllib3AWSV4SignerAuth(
            boto3.Session().get_credentials(), region_name, "es"
        )
    else:
        http_auth = None
    return OpenSearch(
        hosts=[endpoint], http_auth=http_auth, use_ssl=use_ssl, verify_certs=verify_certs
    )


class OpenSearchVectorIndex:
    def __init__(
        self,
        *,
        endpoint: str,
        index_name: str,
        region_name: str | None = None,
        username: str | None = None,
        password: str | None = None,
        stats_ttl_seconds: float = 60.0,
        use_ssl: bool | None = None,
        verify_certs: bool | None = None,
    ) -> None:
        # None → read off the endpoint scheme, so a plain-HTTP local cluster needs no extra
        # argument at the call site (which is exactly where it was forgotten).
        self._client = build_opensearch_client(
            endpoint=endpoint,
            region_name=region_name,
            username=username,
            password=password,
            use_ssl=use_ssl,
            verify_certs=verify_certs,
        )
        self._index_name = index_name
        self._stats_cache = IndexStatsTtlCache(ttl_seconds=stats_ttl_seconds)
        self._last_write_timestamp: datetime | None = None

    def bulk_upsert(self, batch: IndexRecordBatch) -> None:
        lines: list[str] = []
        for record in batch.records:
            lines.append(json.dumps({"index": {"_index": self._index_name, "_id": record.chunkId}}))
            lines.append(json.dumps(record.model_dump(mode="json")))
        body = "\n".join(lines) + "\n"
        response = self._client.bulk(body=body)
        failures = collect_bulk_failures(response)
        if failures:
            # Surface WHY each item was rejected (id + status + error type + truncated reason).
            # Without this the per-item reason from the bulk response was discarded, so a hard
            # write block (mapping conflict, strict-dynamic, parse error) was invisible — only
            # the retry/backlog symptom showed. WARNING (not the document body) so a mapper
            # error that echoes the offending value can't dump indexed content to logs.
            _log.warning(
                "OpenSearch bulk_upsert rejected %d/%d item(s): %s",
                len(failures),
                len(batch.records),
                _bulk_failure_summary(failures),
            )
            raise RetriableIngestionError(
                f"OpenSearch bulk had {len(failures)} failed item(s)",
                reason=FailureReason.BULK_INDEX_PARTIAL_FAILURE,
                stage="index",
            )
        self._record_write()
        self._stats_cache.invalidate()

    def _delete_by_query(self, query: dict, *, stage: str, label: str = "") -> None:
        """Run a refreshing delete_by_query and fail retriably on partial deletion.

        ``conflicts="proceed"`` keeps the sweep going past concurrent writes, so any reported
        failure or version conflict means chunks survived that should not have — retriable
        rather than silently accepted."""
        response = self._client.delete_by_query(
            index=self._index_name,
            body={"query": query},
            refresh=True,
            conflicts="proceed",
        )
        failures = response.get("failures", [])
        version_conflicts = response.get("version_conflicts", 0)
        if failures or version_conflicts > 0:
            raise RetriableIngestionError(
                f"OpenSearch delete_by_query{label} had {len(failures)} failures and "
                f"{version_conflicts} version conflicts",
                reason=FailureReason.BULK_INDEX_PARTIAL_FAILURE,
                stage=stage,
            )
        self._record_write()
        self._stats_cache.invalidate()

    def tombstone_paper(self, tombstone: Tombstone) -> None:
        # Version ordering is guarded by ControlPlaneStore. The index operation deletes
        # all existing chunks for the paper that won that CAS.
        self._delete_by_query(
            {"term": {"paperId": tombstone.paper_id}},
            stage="index_tombstone",
        )

    def delete_stale_chunks(self, paper_id: str, keep_chunk_ids: set[str]) -> None:
        if not keep_chunk_ids:
            return
        self._delete_by_query(
            {
                "bool": {
                    "filter": [{"term": {"paperId": paper_id}}],
                    "must_not": [{"terms": {"chunkId": sorted(keep_chunk_ids)}}],
                }
            },
            stage="index_delete_stale",
            label=" (stale)",
        )

    def index_stats(self) -> IndexStats:
        return self._stats_cache.get_or_refresh(self._index_name, self._fetch_stats)

    def validate_generation(self, *, min_documents: int = 1) -> IndexStats:
        """Validate a candidate generation before alias cutover."""
        stats = self._fetch_stats()
        if stats.total_documents < min_documents:
            raise ValidationViolationError(
                "OpenSearch generation validation failed: too few documents",
                stage="index_generation",
            )
        return stats

    def switch_alias(
        self,
        *,
        alias_name: str,
        target_index: str | None = None,
        previous_index: str | None = None,
    ) -> None:
        """Atomically point ``alias_name`` at ``target_index`` after external validation."""
        target = target_index or self._index_name
        actions: list[dict[str, dict[str, str]]] = []
        existing = self._client.indices.get_alias(name=alias_name, ignore=[404])
        if isinstance(existing, dict):
            for index in existing:
                if previous_index is None or index == previous_index:
                    actions.append({"remove": {"index": index, "alias": alias_name}})
        actions.append({"add": {"index": target, "alias": alias_name}})
        self._client.indices.update_aliases(body={"actions": actions})

    def _fetch_stats(self) -> IndexStats:
        count = int(self._client.count(index=self._index_name).get("count", 0))
        return IndexStats(
            status="HEALTHY",
            timestamp=datetime.now(UTC),
            index_name=self._index_name,
            total_documents=count,
            vector_count=count,
            last_write_timestamp=self._last_write_timestamp,
            dependencies={"opensearch": "UP"},
        )

    def _record_write(self) -> None:
        self._last_write_timestamp = datetime.now(UTC)


class IndexStatsTtlCache:
    def __init__(self, *, ttl_seconds: float) -> None:
        self._ttl = timedelta(seconds=ttl_seconds)
        self._value: IndexStats | None = None
        self._expires_at = datetime.min.replace(tzinfo=UTC)

    def get_or_refresh(self, index_name: str, refresh: Any) -> IndexStats:
        now = datetime.now(UTC)
        if self._value is not None and now < self._expires_at:
            return self._value
        fresh = refresh()
        # Checked BEFORE it is stored. Caching first and raising after meant the guard fired
        # exactly once: every call inside the TTL then took the hit branch above and returned the
        # mismatched stats silently, which is the opposite of what a guard is for.
        if fresh.index_name != index_name:
            raise RuntimeError("index stats cache returned mismatched index")
        self._value = fresh
        self._expires_at = now + self._ttl
        return self._value

    def invalidate(self) -> None:
        self._expires_at = datetime.min.replace(tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class SqsMessage:
    message_id: str
    receipt_handle: str
    body: dict[str, Any]


class SqsQueue:
    def __init__(
        self,
        *,
        queue_url: str,
        dlq_url: str,
        region_name: str | None = None,
        wait_time_seconds: int = 20,
    ) -> None:
        import boto3

        self._client = boto3.client("sqs", region_name=region_name)
        self._queue_url = queue_url
        self._dlq_url = dlq_url
        # Per-instance long-poll window. The main ingestion queue keeps the 20s default; the
        # priority doc-model queue is built with 0 (short poll) so an empty doc-model queue never
        # blocks the loop from getting back to the backfill queue (worker.py polls doc-model first).
        self._wait_time_seconds = wait_time_seconds

    def send_job(self, job) -> None:
        self._client.send_message(
            QueueUrl=self._queue_url,
            MessageBody=json.dumps(
                {"type": "ingest_paper", **job.to_payload()}
            ),
        )

    def receive_messages(self, max_messages: int = 10) -> list[SqsMessage]:
        response = self._client.receive_message(
            QueueUrl=self._queue_url,
            MaxNumberOfMessages=max_messages,
            WaitTimeSeconds=self._wait_time_seconds,
        )
        messages = []
        for message in response.get("Messages", []):
            raw_body = message["Body"]
            try:
                body = json.loads(raw_body)
            except json.JSONDecodeError:
                body = {"type": "invalid", "rawBody": raw_body}
            if not isinstance(body, dict):
                body = {"type": "invalid", "rawBody": raw_body}
            messages.append(
                SqsMessage(
                    message_id=message["MessageId"],
                    receipt_handle=message["ReceiptHandle"],
                    body=body,
                )
            )
        return messages

    def ack(self, message: QueueMessage) -> None:
        self._client.delete_message(
            QueueUrl=self._queue_url,
            ReceiptHandle=message.receipt_handle,
        )

    def send_to_dlq(self, payload: dict[str, Any], *, reason: str) -> None:
        self._client.send_message(
            QueueUrl=self._dlq_url,
            MessageBody=json.dumps({"reason": reason, "payload": payload}),
        )

    def parse_new_arxiv_event(self, payload: dict[str, Any]):
        from docsuri_shared.events import NewArxivEvent

        return NewArxivEvent.model_validate(payload)


def collect_bulk_failures(response: dict[str, Any]) -> list[dict[str, Any]]:
    if not response.get("errors"):
        return []
    failures: list[dict[str, Any]] = []
    for item in response.get("items", []):
        operation = next(iter(item.values()))
        status = int(operation.get("status", 500))
        if status >= 300:
            failures.append(operation)
    return failures


def _bulk_failure_summary(
    failures: list[dict[str, Any]], *, limit: int = 5
) -> list[dict[str, Any]]:
    """Compact, log-safe view of bulk per-item failures: id + status + error type + a TRUNCATED
    reason.

    DECISION (records the review tradeoff): unlike the U2 read path — which logs field paths ONLY,
    never values (SEC-9) — the write path deliberately keeps a truncated ``reason``. An OpenSearch
    mapper error names the failing field ONLY inside ``reason`` (there is no separate structured
    field for it), so dropping the reason would collapse diagnosis to a bare error type and defeat
    the whole point of surfacing the rejection. The value a reason may echo is public arXiv corpus
    metadata (non-sensitive) and this is an internal ops log — so the asymmetry is an accepted,
    bounded tradeoff: capped at 200 chars (keeps the leading ``field [X] of type [Y]`` prefix,
    trims long value previews) and to the first few items so one bad batch can't flood the log."""
    summary: list[dict[str, Any]] = []
    for operation in failures[:limit]:
        error = operation.get("error") or {}
        reason = str(error.get("reason", ""))
        if len(reason) > 200:
            reason = reason[:200] + "…"
        summary.append(
            {
                "id": operation.get("_id"),
                "status": operation.get("status"),
                "type": error.get("type"),
                "reason": reason,
            }
        )
    return summary
