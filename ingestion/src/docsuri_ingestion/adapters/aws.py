from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from docsuri_shared.dtos import DocModel
from docsuri_shared.vector_spec import DIMENSIONS, EMBEDDING_SPEC
from pydantic import ValidationError

from docsuri_ingestion.domain.enums import FailureReason
from docsuri_ingestion.domain.errors import RetriableIngestionError, ValidationViolationError
from docsuri_ingestion.domain.models import IndexRecordBatch, IndexStats, ParsedPaper, Tombstone
from docsuri_ingestion.ports import QueueMessage

_log = logging.getLogger(__name__)

# Cohere Embed on Bedrock accepts at most 96 texts per invoke_model call.
_BEDROCK_EMBED_BATCH_LIMIT = 96


class S3FullTextStore:
    def __init__(
        self, *, bucket: str, prefix: str = "full-text", kms_key_id: str | None = None
    ) -> None:
        import boto3

        self._client = boto3.client("s3")
        self._bucket = bucket
        self._prefix = prefix.strip("/")
        self._kms_key_id = kms_key_id

    def put_full_text(self, paper: ParsedPaper) -> str:
        key = f"{self._prefix}/{paper.paper_id}/v{paper.version}.txt"
        kwargs: dict[str, Any] = {
            "Bucket": self._bucket,
            "Key": key,
            "Body": paper.full_text.encode("utf-8"),
            "ContentType": "text/plain; charset=utf-8",
            "ServerSideEncryption": "aws:kms" if self._kms_key_id else "AES256",
            "Metadata": {
                "paper-id": paper.paper_id,
                "version": str(paper.version),
                "license": paper.license_url,
            },
        }
        if self._kms_key_id:
            kwargs["SSEKMSKeyId"] = self._kms_key_id
        self._client.put_object(**kwargs)
        return f"s3://{self._bucket}/{key}"


class S3DocModelStore:
    """BR-30 doc-model cache on S3 (Infra §1.1b): ``doc-model/{paperId}/v{version}.json``.

    Same single bucket as full-text/assets, separate ``doc-model/`` prefix; image bytes are
    NOT stored here (the JSON references webp assets by assetId). SSE-KMS when a key is set,
    else SSE-S3. ``get`` returns ``None`` on a cache miss; ``remove`` drops every cached
    version for a paper (version-change / tombstone invalidation).
    """

    def __init__(
        self, *, bucket: str, prefix: str = "doc-model", kms_key_id: str | None = None
    ) -> None:
        import boto3

        self._client = boto3.client("s3")
        self._bucket = bucket
        self._prefix = prefix.strip("/")
        self._kms_key_id = kms_key_id

    def _key(self, paper_id: str, version: int) -> str:
        return f"{self._prefix}/{paper_id}/v{version}.json"

    def get(self, paper_id: str, version: int) -> DocModel | None:
        from botocore.exceptions import ClientError

        try:
            response = self._client.get_object(
                Bucket=self._bucket, Key=self._key(paper_id, version)
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"NoSuchKey", "404", "NotFound"}:
                return None
            raise
        try:
            return DocModel.model_validate_json(response["Body"].read())
        except ValidationError:
            # An artifact cached under an older schema (e.g. pre-``fullText``) no longer
            # deserializes. Treat it as a cache miss so the builder rebuilds and re-caches a
            # valid doc-model, rather than crashing the job. The builder's parserVersion gate
            # already forces a rebuild on version drift; this covers the harder schema break.
            return None

    def put(self, doc: DocModel) -> str:
        key = self._key(doc.meta.paperId, doc.meta.version)
        kwargs: dict[str, Any] = {
            "Bucket": self._bucket,
            "Key": key,
            # exclude_none keeps optional fields off the wire; consumers ignore unknowns.
            "Body": doc.model_dump_json(exclude_none=True).encode("utf-8"),
            "ContentType": "application/json; charset=utf-8",
            "ServerSideEncryption": "aws:kms" if self._kms_key_id else "AES256",
            "Metadata": {
                "paper-id": doc.meta.paperId,
                "version": str(doc.meta.version),
                "parser-version": doc.meta.provenance.parserVersion,
                "schema-version": doc.meta.provenance.schemaVersion,
            },
        }
        if self._kms_key_id:
            kwargs["SSEKMSKeyId"] = self._kms_key_id
        self._client.put_object(**kwargs)
        return f"s3://{self._bucket}/{key}"

    def remove(self, paper_id: str) -> None:
        paginator = self._client.get_paginator("list_objects_v2")
        keys: list[dict[str, str]] = []
        for page in paginator.paginate(Bucket=self._bucket, Prefix=f"{self._prefix}/{paper_id}/"):
            keys.extend({"Key": obj["Key"]} for obj in page.get("Contents", []))
        for start in range(0, len(keys), 1000):  # DeleteObjects caps at 1000 keys per call
            self._client.delete_objects(
                Bucket=self._bucket, Delete={"Objects": keys[start : start + 1000]}
            )


class BedrockCohereEmbeddingPort:
    def __init__(self, *, model_id: str, region_name: str | None = None) -> None:
        import boto3

        self._client = boto3.client("bedrock-runtime", region_name=region_name)
        self._model_id = model_id

    def embed_documents(
        self,
        texts: list[str] | tuple[str, ...],
        *,
        correlation_id: str | None = None,
    ) -> list[list[float]]:
        del correlation_id
        if EMBEDDING_SPEC.input_type_writer != "search_document":
            raise RuntimeError("Bedrock writer must use search_document input type")
        # Cohere Embed on Bedrock caps a single request at 96 texts; a long paper can chunk
        # past that (max_chunks_per_paper=128). Sub-batch and concatenate IN ORDER — the
        # assembler zips chunk_ids↔vectors with strict=True, so order must be preserved.
        vectors: list[list[float]] = []
        for start in range(0, len(texts), _BEDROCK_EMBED_BATCH_LIMIT):
            vectors.extend(self._embed_batch(texts[start : start + _BEDROCK_EMBED_BATCH_LIMIT]))
        return vectors

    def _embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        body = {
            "texts": list(texts),
            "input_type": EMBEDDING_SPEC.input_type_writer,
            "embedding_types": ["float"],
            # Cohere Embed v4 defaults to 1536-dim; pin to the index/spec width so vectors
            # match docsuri-corpus-v2's mapping (v3 returned EMBEDDING_SPEC.dimensions implicitly).
            "output_dimension": EMBEDDING_SPEC.dimensions,
        }
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
            if len(vector) != DIMENSIONS:
                raise ValidationViolationError(
                    f"Bedrock returned vector dimension {len(vector)}, expected {DIMENSIONS}",
                    stage="embed",
                )
        return vectors


def build_opensearch_client(
    *,
    endpoint: str,
    region_name: str | None = None,
    username: str | None = None,
    password: str | None = None,
    use_ssl: bool = True,
    verify_certs: bool = True,
):
    """Build an opensearch-py client. Auth order: basic-auth if both creds are given
    (local/override), else SigV4 (``Urllib3AWSV4SignerAuth``, service ``es``) when a region
    is set — the managed VPC domain authorizes the ECS task role by resource policy, so signed
    requests are required — else unsigned (local clusters with an open policy)."""
    from opensearchpy import OpenSearch

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
    ) -> None:
        self._client = build_opensearch_client(
            endpoint=endpoint,
            region_name=region_name,
            username=username,
            password=password,
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

    def tombstone_paper(self, tombstone: Tombstone) -> None:
        # Version ordering is guarded by ControlPlaneStore. The index operation deletes
        # all existing chunks for the paper that won that CAS.
        response = self._client.delete_by_query(
            index=self._index_name,
            body={"query": {"term": {"paperId": tombstone.paper_id}}},
            refresh=True,
            conflicts="proceed",
        )
        failures = response.get("failures", [])
        version_conflicts = response.get("version_conflicts", 0)
        if failures or version_conflicts > 0:
            raise RetriableIngestionError(
                f"OpenSearch delete_by_query had {len(failures)} failures and "
                f"{version_conflicts} version conflicts",
                reason=FailureReason.BULK_INDEX_PARTIAL_FAILURE,
                stage="index_tombstone",
            )
        self._record_write()
        self._stats_cache.invalidate()

    def delete_stale_chunks(self, paper_id: str, keep_chunk_ids: set[str]) -> None:
        if not keep_chunk_ids:
            return
        response = self._client.delete_by_query(
            index=self._index_name,
            body={
                "query": {
                    "bool": {
                        "filter": [{"term": {"paperId": paper_id}}],
                        "must_not": [{"terms": {"chunkId": sorted(keep_chunk_ids)}}],
                    }
                }
            },
            refresh=True,
            conflicts="proceed",
        )
        failures = response.get("failures", [])
        version_conflicts = response.get("version_conflicts", 0)
        if failures or version_conflicts > 0:
            raise RetriableIngestionError(
                f"OpenSearch delete_by_query (stale) had {len(failures)} failures and "
                f"{version_conflicts} version conflicts",
                reason=FailureReason.BULK_INDEX_PARTIAL_FAILURE,
                stage="index_delete_stale",
            )
        self._record_write()
        self._stats_cache.invalidate()

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
        self._value = refresh()
        self._expires_at = now + self._ttl
        if self._value.index_name != index_name:
            raise RuntimeError("index stats cache returned mismatched index")
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
