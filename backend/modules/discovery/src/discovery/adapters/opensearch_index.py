"""OpenSearch read adapters — real ``VectorStoreAdapter`` + ``LexicalIndexAdapter``.

The reader mirror of U1's ``OpenSearchVectorIndex`` writer: the SAME index
(``docsuri-corpus-v1``), one store serving both k-NN (cosine, ``vector``) and BM25
(``title``/``abstract``/``lexicalTerms``) — hybrid retrieval (FR-2). Hits are
deserialized straight back into the shared ``IndexRecord`` (SSOT round-trip; no forked
shape). OpenSearch is one store, so ANY
query failure raises ``IndexUnavailable`` → the orchestrator fail-closes (INV-3/SEC-15);
there is no index fallback (only embedding has a fallback).

ports declares ``VectorStoreAdapter`` and ``LexicalIndexAdapter`` as two protocols; they are
exposed as two adapter objects but share one OpenSearch client via ``OpenSearchClientFactory``.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Sequence
from typing import Any

from docsuri_shared.vector_spec import IndexRecord
from pydantic import ValidationError

from ..ports.search_ports import IndexUnavailable, ScoredRecord
from .resilience import CircuitBreaker

_log = logging.getLogger(__name__)

# Bounded transient-retry for the single OpenSearch store. Search is a read (idempotent), and
# under heavy concurrent indexing (e.g. a corpus rebuild) the cluster returns brief transient
# failures — a shard relocating, a GC pause, a momentary timeout. A short retry absorbs most of
# those so one unlucky moment does not surface to the user as a 503; repeated failure still
# fail-closes (INV-3). Kept small so an added retry never blows the P50<3s search budget.
#
# Two guards keep the retry inside that budget on the slow/outage path the client's 10s connect-
# and-read ``timeout`` would otherwise stretch across three attempts (~30s):
#   1. Only *known-transient* failures are retried (see ``_is_transient``). A non-transient error
#      — a 4xx query error, an unexpected response shape — fail-closes on the first attempt rather
#      than burning three attempts on something a retry can't fix.
#   2. Retried searches carry a per-request timeout well below the client default, so even a
#      genuine ConnectionTimeout fails its attempt fast; worst-case fail-close is bounded to
#      ~MAX_ATTEMPTS * this + backoff instead of ~30s.
_SEARCH_MAX_ATTEMPTS = 3
_SEARCH_RETRY_BACKOFF_S = (0.1, 0.25)  # sleeps before attempt 2 and attempt 3
# Per-attempt cap. Raised from 2.0s: the k-NN (HNSW) graph of a freshly written or just-merged
# segment is loaded into native memory on the FIRST query that touches it, which takes a few
# seconds; a 2.0s cap made that cold load time out and the whole search fail-close (the observed
# "first search fails, works on retry" — worst during a corpus reindex, but it recurs after any
# merge / memory eviction / idle period, so it isn't only a backfill artifact). 5.0s absorbs a
# cold graph load on attempt 1; the small backoff'd retries still bound a genuine-outage tail.
_SEARCH_REQUEST_TIMEOUT_S = 5.0


def _is_transient(exc: BaseException) -> bool:
    """Whether an OpenSearch failure is a transient store blip a short retry can absorb (vs. a
    permanent error a retry can't fix). Classifies by the opensearch-py exception's own
    ``status_code`` — duck-typed, so this module still imports without the ``real`` extra:
    connection errors (``"N/A"``), read timeouts (``"TIMEOUT"``), and 5xx server errors (e.g. a
    503 for a relocating shard) are transient; a 4xx (bad query, auth, not-found) or any exception
    with no store status_code (an unexpected response shape, a programming bug) is not."""
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status >= 500  # 5xx — server-side transient
    return status in ("N/A", "TIMEOUT")  # connection error / read timeout


def _search_hits(
    client: Any,
    index: str,
    body: dict[str, Any],
    *,
    message: str,
    breaker: CircuitBreaker | None = None,
) -> list[dict[str, Any]]:
    """Run a search and return its hits, retrying transient store failures before fail-closing to
    ``IndexUnavailable``. Only known-transient failures are retried (``_is_transient``); anything
    else fail-closes on the first attempt. Each attempt carries a bounded ``request_timeout`` so a
    stuck call can't stretch the retry past the search latency budget.

    ``breaker`` is the store's circuit (nfr-design-patterns §1.2, shared by every adapter on the
    one OpenSearch store): OPEN → fail-closed immediately instead of burning the full
    retry+timeout budget on every request of a sustained outage. One ``_search_hits`` call —
    including its internal transient retries — counts as ONE breaker outcome.

    The raised ``IndexUnavailable`` chains ``from`` the underlying store error and records which
    query and how many attempts failed in its message, so the request-aware 503 handler logs the
    real cause correlated to the request id in one self-contained line (no timestamp join to a
    separate adapter log). The bare ``raise ... from exc`` previously discarded that cause, making
    a real outage indistinguishable from a transient blip."""
    if breaker is not None and not breaker.allow():
        raise IndexUnavailable(f"{message}: {breaker.name} circuit open — failing fast")
    last_exc: Exception | None = None
    attempt = 0
    for attempt in range(_SEARCH_MAX_ATTEMPTS):
        try:
            response = client.search(
                index=index, body=body, request_timeout=_SEARCH_REQUEST_TIMEOUT_S
            )
            hits = response["hits"]["hits"]
        except Exception as exc:  # noqa: BLE001 — one store; transient-tolerant then fail-closed
            last_exc = exc
            if not _is_transient(exc) or attempt == _SEARCH_MAX_ATTEMPTS - 1:
                break
            time.sleep(_SEARCH_RETRY_BACKOFF_S[attempt])
            continue
        if breaker is not None:
            breaker.record_success()
        return hits
    if breaker is not None:
        # Only an OUTAGE-shaped final error (transient class: connection/timeout/5xx) counts
        # toward opening the circuit. A 4xx or unexpected response shape means the store
        # RESPONDED — same rule as CircuitGuardedEmbedder — so a poisoned query or an index
        # misconfig fail-closes per-request without turning a healthy store into a fast-fail
        # 503 wall for every adapter sharing the breaker.
        if last_exc is not None and _is_transient(last_exc):
            breaker.record_failure()
        else:
            breaker.record_success()
    raise IndexUnavailable(f"{message} after {attempt + 1} attempt(s)") from last_exc
# arXiv version suffix ("v3"). paperId is stored version-less, so stripping the requested id's
# version lets the detail lookup resolve a paper indexed at a *different* version than the one
# asked for. Mirrors ingestion's normalize_arxiv_ref (ingestion/.../domain/ids.py); cross-module
# id parsing isn't shared yet, so this small strip is duplicated.
_VERSION_SUFFIX_RE = re.compile(r"v[1-9][0-9]*$", re.IGNORECASE)


def _hit_id(hit: dict[str, Any]) -> str:
    """Best-effort identifier for a hit, for drop diagnostics. Uses only id-shaped fields
    (never title/abstract/body) so a drop log can never leak indexed content (SEC-9/SEC-15)."""
    source = hit.get("_source") or {}
    return str(hit.get("_id") or source.get("chunkId") or source.get("paperId") or "<unknown>")


def _drift_fields(exc: ValidationError) -> list[str]:
    """Dotted field paths that failed validation — locations ONLY, never the offending values
    (a value would carry indexed content). Surfaces WHICH part of the contract drifted."""
    return sorted({".".join(str(p) for p in err["loc"]) for err in exc.errors()})


class OpenSearchClientFactory:
    """Builds the shared ``opensearch-py`` client (lazy import; the ``real`` extra)."""

    @staticmethod
    def build(
        *,
        endpoint: str,
        region_name: str | None = None,
        username: str | None = None,
        password: str | None = None,
        use_ssl: bool = True,
        verify_certs: bool = True,
    ) -> Any:
        from opensearchpy import OpenSearch

        # Auth order mirrors the U1 writer (ingestion.build_opensearch_client): basic-auth if
        # both creds are given (local/override), else SigV4 (``Urllib3AWSV4SignerAuth``, service
        # ``es``) when a region is set — the managed VPC domain authorizes the ECS task role by
        # resource policy, so signed requests are required — else unsigned (local open cluster).
        http_auth: Any
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
            hosts=[endpoint],
            http_auth=http_auth,
            use_ssl=use_ssl,
            verify_certs=verify_certs,
            timeout=10,
        )


def _to_scored(hits: list[dict[str, Any]]) -> list[ScoredRecord]:
    """Deserialize OpenSearch hits → (IndexRecord, store score), preserving rank order.

    A hit whose stored ``_source`` no longer satisfies the current ``IndexRecord`` contract
    (schema drift — e.g. a document indexed under an earlier vector-spec) is DROPPED and logged,
    NOT allowed to fail the whole query: one stale document must not turn the entire search into
    a 500 (this mirrors the assembler dropping a single malformed card rather than sinking the
    page — the read path was previously the only place missing that per-record tolerance). Each
    drop logs the hit id and the drifted field paths (locations only — never values, so indexed
    content can't leak); the per-call drop count makes corpus drift observable and falls to zero
    once a reindex completes. A genuine store/query outage is a separate failure mode the callers
    already map to ``IndexUnavailable`` (INV-3) before this function runs."""
    scored: list[ScoredRecord] = []
    dropped = 0
    for hit in hits:
        try:
            # ``.get(...) or {}`` — a missing ``_source`` (e.g. a stored_fields/_source-disabled
            # response) would raise KeyError on subscript, which is NOT a ValidationError and
            # would escape this guard into the caller's 500. Feeding {} instead routes it through
            # the SAME drop path (empty dict fails IndexRecord validation), upholding the
            # "one bad hit must not sink the query" invariant for the malformed-hit case too.
            record = IndexRecord.model_validate(hit.get("_source") or {})
        except ValidationError as exc:
            dropped += 1
            _log.warning(
                "discovery.search dropped non-conforming index record id=%s fields=%s",
                _hit_id(hit),
                _drift_fields(exc),
            )
            continue
        scored.append((record, float(hit.get("_score") or 0.0)))
    if dropped:
        _log.warning(
            "discovery.search dropped %d/%d hit(s) failing IndexRecord validation "
            "(schema drift — reindex pending)",
            dropped,
            len(hits),
        )
    return scored


class OpenSearchVectorStoreAdapter:
    """k-NN (ANN) reader over the shared OpenSearch index (cosine; FR-2).

    ``breaker`` (optional) is the ONE store circuit shared with the lexical/lookup adapters —
    OpenSearch is a single dependency, so any adapter's failures open it for all."""

    def __init__(
        self, client: Any, index_name: str, breaker: CircuitBreaker | None = None
    ) -> None:
        self._client = client
        self._index = index_name
        self._breaker = breaker

    def knn_search(
        self, vector: Sequence[float], top_k: int, abstract_only: bool = False
    ) -> list[ScoredRecord]:
        knn: dict[str, Any] = {"vector": list(vector), "k": top_k}
        if abstract_only:
            # Efficient k-NN filtering: restrict the ANN search to abstract chunks (lite scope).
            knn["filter"] = {"term": {"section": "abstract"}}
        body = {
            "size": top_k,
            "query": {"knn": {"vector": knn}},
        }
        hits = _search_hits(
            self._client,
            self._index,
            body,
            message="OpenSearch k-NN query failed",
            breaker=self._breaker,
        )
        return _to_scored(hits)


class OpenSearchPaperLookupAdapter:
    """Single-document reader over the shared OpenSearch index — one record for a paper id
    (matched on ``paperId`` or display ``arxivId``). Powers the paper-detail metadata endpoint."""

    def __init__(
        self, client: Any, index_name: str, breaker: CircuitBreaker | None = None
    ) -> None:
        self._client = client
        self._index = index_name
        self._breaker = breaker

    def fetch_paper(self, paper_id: str) -> IndexRecord | None:
        # Match the version-less paperId, the exact display arxivId, OR the version-stripped id
        # against paperId — so a request for one version (e.g. ...v1) still resolves a paper
        # indexed at another (...v3), instead of 404-ing on an exact-version miss. size=1: any
        # chunk carries the paper-level metadata.
        bare_id = _VERSION_SUFFIX_RE.sub("", paper_id)
        body = {
            "size": 1,
            "query": {
                "bool": {
                    "should": [
                        {"term": {"paperId": paper_id}},
                        {"term": {"paperId": bare_id}},
                        {"term": {"arxivId": paper_id}},
                    ],
                    "minimum_should_match": 1,
                }
            },
        }
        hits = _search_hits(
            self._client,
            self._index,
            body,
            message="OpenSearch paper lookup failed",
            breaker=self._breaker,
        )
        if not hits:
            return None
        # A non-conforming stored record (schema drift) is treated like "not indexed": return
        # None → the route 404s and the detail page degrades to the arXiv id + link-out, rather
        # than 500-ing. The drop is logged (field paths only, no values) for drift visibility.
        try:
            return IndexRecord.model_validate(hits[0].get("_source") or {})
        except ValidationError as exc:
            _log.warning(
                "discovery.paper_lookup dropped non-conforming record id=%s fields=%s",
                _hit_id(hits[0]),
                _drift_fields(exc),
            )
            return None


class OpenSearchLexicalIndexAdapter:
    """BM25 reader over analyzed title, abstract, and chunk-body lexical fields (FR-2)."""

    def __init__(
        self, client: Any, index_name: str, breaker: CircuitBreaker | None = None
    ) -> None:
        self._client = client
        self._index = index_name
        self._breaker = breaker

    def bm25_search(
        self,
        terms: Sequence[str],
        top_k: int,
        fields: Sequence[str] = ("title", "abstract", "lexicalTerms"),
    ) -> list[ScoredRecord]:
        body = {
            "size": top_k,
            "query": {
                "multi_match": {
                    "query": " ".join(terms),
                    "fields": list(fields),
                }
            },
        }
        hits = _search_hits(
            self._client,
            self._index,
            body,
            message="OpenSearch BM25 query failed",
            breaker=self._breaker,
        )
        return _to_scored(hits)

    def phrase_search(
        self,
        phrase: str,
        top_k: int,
        paper_ids: Sequence[str] | None = None,
    ) -> list[ScoredRecord]:
        """정확 문구 매칭 — 초록(``abstract``)과 청크 원문(``lexicalTerms``)에서 연속된
        어구가 그대로 있는 청크만 반환한다(``multi_match``의 OR 매칭과 달리 순서·인접성을
        요구). 두 필드를 모두 훑는 이유: ``lexicalTerms``는 초록 청크에서 비어 있고
        (index_record 계약: "Empty for abstract chunks") 초록 원문은 ``abstract`` 필드에만
        있으므로, 한쪽만 매칭하면 초록에 있는 문장을 통째로 놓친다(``bm25_search``가 title/
        abstract/lexicalTerms를 함께 거는 것과 같은 이유). ``paper_ids``가 주어지면 그 논문
        들로만 제한한다 — 색인 ``paperId``는 버전 없는(bare) id이므로 호출측에서 버전 접미사를
        미리 제거해 넘겨야 한다(꼬리질문 좁히기, BR-EV-2 mixed/explicit 재사용과 동일한 목적)."""
        query: dict = {
            "bool": {
                "should": [
                    {"match_phrase": {"abstract": phrase}},
                    {"match_phrase": {"lexicalTerms": phrase}},
                ],
                "minimum_should_match": 1,
            }
        }
        if paper_ids:
            query["bool"]["filter"] = [{"terms": {"paperId": list(paper_ids)}}]
        body = {"size": top_k, "query": query}
        hits = _search_hits(
            self._client,
            self._index,
            body,
            message="OpenSearch phrase query failed",
            breaker=self._breaker,
        )
        return _to_scored(hits)
