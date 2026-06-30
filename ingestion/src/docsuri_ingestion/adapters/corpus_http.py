from __future__ import annotations

import ipaddress
import json
import socket
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

from docsuri_ingestion.corpus_sources import SourcePaperRecord
from docsuri_ingestion.domain.enums import FailureReason, SourceName
from docsuri_ingestion.domain.errors import PermanentIngestionError, RetriableIngestionError

# Hops to follow for an attacker-influenced PDF URL, validating each target host (SSRF guard).
_MAX_PDF_REDIRECTS = 5


class SsrfBlockedError(Exception):
    """Raised when a fetch target resolves to a non-public address (BR-18 / SEC-15)."""

_FIELDS_OF_STUDY = "Computer Science"
_QUERY_TERMS = {
    "cs.AI": "artificial intelligence",
    "cs.CL": "natural language processing",
    "cs.CV": "computer vision",
    "cs.LG": "machine learning",
    "stat.ML": "machine learning",
}


# ponytail: bounded retry for transient 429/5xx during multi-page harvests — the bulk endpoints
# page for a long time, so one transient blip must not abort the whole run. A sustained rate-limit
# (e.g. unauthenticated SS) still surfaces after the cap. Linear backoff is enough at this volume;
# swap for exponential + jitter if a real API key lets us push throughput.
_MAX_GET_JSON_RETRIES = 5
_RETRY_BACKOFF_SECONDS = 2.0
# ponytail: SS API keys are capped at ~1 req/s cumulative across all endpoints; pace bulk-search
# pages just under it. The bulk endpoint is the only SS API call in the harvest (PDF fetch hits the
# publisher host, not the API), so a per-page sleep is enough to stay compliant single-threaded.
_SS_REQUEST_INTERVAL_SECONDS = 1.1


def _get_json_retrying(
    url: str,
    *,
    params: dict[str, str],
    headers: dict[str, str] | None,
    timeout_seconds: float,
    transport: object | None,
    stage: str,
) -> dict[str, Any]:
    """``_get_json`` that retries transient failures (429/5xx/timeout -> RetriableIngestionError)
    with linear backoff. Permanent errors (other 4xx, parse) propagate immediately. Used for the
    paged harvest calls so a single transient page failure mid-pagination doesn't discard the
    whole accumulated run."""
    attempt = 0
    while True:
        try:
            return _get_json(
                url,
                params=params,
                headers=headers,
                timeout_seconds=timeout_seconds,
                transport=transport,
                stage=stage,
            )
        except RetriableIngestionError:
            attempt += 1
            if attempt > _MAX_GET_JSON_RETRIES:
                raise
            time.sleep(_RETRY_BACKOFF_SECONDS * attempt)


class SemanticScholarCorpusSource:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = "https://api.semanticscholar.org/graph/v1",
        timeout_seconds: float = 30.0,
        transport: object | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    def fetch_incremental(
        self,
        since: datetime,
        categories: Sequence[str],
        until: datetime | None = None,
    ) -> list[SourcePaperRecord]:
        records: list[SourcePaperRecord] = []
        token: str | None = None
        # Server-side publication-year bound: the bulk endpoint has no date filter but accepts a
        # `year` range, cutting the harvest from "all of CS, all years" to the window's years —
        # decisive at 1 req/s. _in_window still refines to the exact date span.
        year_filter = f"{since.year}-{until.year}" if until else f"{since.year}-"
        while True:
            params = {
                "query": _query(categories),
                "fields": ",".join(
                    (
                        "paperId",
                        "title",
                        "abstract",
                        "authors",
                        "year",
                        "publicationDate",
                        "externalIds",
                        "openAccessPdf",
                        "isOpenAccess",
                    )
                ),
                "fieldsOfStudy": _FIELDS_OF_STUDY,
                "year": year_filter,
                # /paper/search/bulk rejects `limit` (it returns up to 1000/page and paginates
                # via `token`) and has no `updated` field — either makes the request 400. The
                # `year` range bounds it server-side; _in_window refines to the exact date span.
            }
            if token:
                params["token"] = token
            payload = _get_json_retrying(
                f"{self._base_url}/paper/search/bulk",
                params=params,
                headers={"x-api-key": self._api_key} if self._api_key else None,
                timeout_seconds=self._timeout_seconds,
                transport=self._transport,
                stage="semantic_scholar",
            )
            for item in payload.get("data", []) or []:
                record = _semantic_record(item)
                if record and _in_window(record, since, until):
                    records.append(record)
            token = payload.get("token")
            if not token:
                return records
            # Pace pages to honour the SS key's ~1 req/s cumulative cap (only between pages, so
            # single-page tests don't sleep). 429s still happen under contention — the retry above
            # absorbs those.
            time.sleep(_SS_REQUEST_INTERVAL_SECONDS)

    def fetch_pdf(self, record: SourcePaperRecord) -> bytes:
        if not record.pdf_url:
            raise PermanentIngestionError(
                "Semantic Scholar record has no PDF URL",
                reason=FailureReason.FETCH_FAILURE,
                stage="source",
            )
        return _get_bytes(
            record.pdf_url,
            timeout_seconds=self._timeout_seconds,
            transport=self._transport,
            stage="semantic_scholar_pdf",
        )


class OpenAlexCorpusSource:
    def __init__(
        self,
        *,
        base_url: str = "https://api.openalex.org",
        timeout_seconds: float = 30.0,
        transport: object | None = None,
        mailto: str | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._transport = transport
        self._mailto = mailto

    def fetch_incremental(
        self,
        since: datetime,
        categories: Sequence[str],
        until: datetime | None = None,
    ) -> list[SourcePaperRecord]:
        records: list[SourcePaperRecord] = []
        cursor = "*"
        while cursor:
            # Window by publication_date, not updated_date: updated_date range queries are
            # hard-rate-limited by OpenAlex (429 on the first page, even polite-pool) AND
            # publication date is what a "papers from year N" corpus actually means. updated_date
            # is just when OpenAlex last touched the record.
            filters = [
                f"from_publication_date:{since.date().isoformat()}",
                "open_access.is_oa:true",
                "type:article",
            ]
            if until is not None:
                filters.append(f"to_publication_date:{until.date().isoformat()}")
            params = {
                "filter": ",".join(filters),
                "search": _query(categories),
                "per-page": "100",
                "cursor": cursor,
                "select": ",".join(
                    (
                        "id",
                        "ids",
                        "doi",
                        "display_name",
                        "abstract_inverted_index",
                        "authorships",
                        "publication_year",
                        "publication_date",
                        "updated_date",
                        "primary_location",
                        "locations",
                    )
                ),
            }
            if self._mailto:
                params["mailto"] = self._mailto  # OpenAlex polite pool — higher, steadier limits
            payload = _get_json_retrying(
                f"{self._base_url}/works",
                params=params,
                headers=None,
                timeout_seconds=self._timeout_seconds,
                transport=self._transport,
                stage="openalex",
            )
            for item in payload.get("results", []) or []:
                record = _openalex_record(item)
                if record and _in_window(record, since, until):
                    records.append(record)
            cursor = (payload.get("meta") or {}).get("next_cursor")
        return records

    def fetch_pdf(self, record: SourcePaperRecord) -> bytes:
        if not record.pdf_url:
            raise PermanentIngestionError(
                "OpenAlex record has no PDF URL",
                reason=FailureReason.FETCH_FAILURE,
                stage="source",
            )
        return _get_bytes(
            record.pdf_url,
            timeout_seconds=self._timeout_seconds,
            transport=self._transport,
            stage="openalex_pdf",
        )


def _semantic_record(item: dict[str, Any]) -> SourcePaperRecord | None:
    pdf = item.get("openAccessPdf") or {}
    license_url = _license_url(pdf.get("license"))
    pdf_url = _https_url(pdf.get("url"))
    if not pdf_url or not license_url or not item.get("isOpenAccess"):
        return None
    external_ids = item.get("externalIds") or {}
    return SourcePaperRecord(
        source_name=SourceName.SEMANTIC_SCHOLAR,
        source_id=str(item.get("paperId") or ""),
        title=str(item.get("title") or ""),
        abstract=str(item.get("abstract") or ""),
        authors=tuple(
            str(author.get("name"))
            for author in item.get("authors", []) or []
            if author.get("name")
        ),
        published_at=_parse_date(item.get("publicationDate")),
        updated_at=_parse_date(item.get("updated")),
        year=_int_or_none(item.get("year")),
        pdf_url=pdf_url,
        license_url=license_url,
        doi=external_ids.get("DOI"),
        arxiv_id=external_ids.get("ArXiv"),
    )


def _openalex_record(item: dict[str, Any]) -> SourcePaperRecord | None:
    location = item.get("primary_location") or {}
    pdf_url = _https_url(location.get("pdf_url")) or _first_pdf_url(item.get("locations") or [])
    license_url = _license_url(location.get("license"))
    if not pdf_url or not license_url:
        return None
    ids = item.get("ids") or {}
    return SourcePaperRecord(
        source_name=SourceName.OPENALEX,
        source_id=str(item.get("id") or ""),
        title=str(item.get("display_name") or ""),
        abstract=_abstract_text(item.get("abstract_inverted_index") or {}),
        authors=tuple(_openalex_authors(item)),
        published_at=_parse_date(item.get("publication_date")),
        # Leave updated_at unset so the client-side _in_window + queue guard window by
        # published_at, matching the server-side publication_date filter (and uniform with SS,
        # which has no updated timestamp). Filtering on updated_date here would drop 2025 papers
        # whose OpenAlex record was merely touched later.
        updated_at=None,
        year=_int_or_none(item.get("publication_year")),
        pdf_url=pdf_url,
        html_url=_https_url(location.get("landing_page_url")),
        license_url=license_url,
        doi=item.get("doi") or ids.get("doi"),
        arxiv_id=_arxiv_id(ids.get("arxiv")),
    )


def _openalex_authors(item: dict[str, Any]) -> list[str]:
    authors = []
    for authorship in item.get("authorships", []) or []:
        author = authorship.get("author") or {}
        name = author.get("display_name")
        if name:
            authors.append(str(name))
    return authors


def _get_json(
    url: str,
    *,
    params: dict[str, str],
    headers: dict[str, str] | None,
    timeout_seconds: float,
    transport: object | None,
    stage: str,
) -> dict[str, Any]:
    return _response_json(
        _request(
            url,
            params=params,
            headers=headers,
            timeout_seconds=timeout_seconds,
            transport=transport,
            stage=stage,
        ),
        stage,
    )


def _get_bytes(
    url: str, *, timeout_seconds: float, transport: object | None, stage: str
) -> bytes:
    """Fetch a PDF from an attacker-influenced URL with an SSRF host guard + size cap.

    The URL comes from third-party API data (Semantic Scholar / OpenAlex), so each hop's host is
    validated against public addresses before connecting (BR-18 / SEC-15) and the body is capped
    (NFR §0.5). Auto-redirects are off so a redirect can't bypass the per-hop check; we follow
    manually. The host check is skipped when a test transport is injected (no real network).
    """
    import httpx

    from docsuri_ingestion.http_limits import ResponseTooLargeError, read_capped

    try:
        with httpx.Client(
            timeout=timeout_seconds, follow_redirects=False, transport=transport
        ) as client:
            current = url
            for _ in range(_MAX_PDF_REDIRECTS + 1):
                # Pin the connection to the validated IP (skipped under an injected test transport,
                # which has no real network): the host we validate and the socket we open hit the
                # same address, so a rebinding DNS answer can't slip a private IP past the guard.
                # Host header + SNI keep the original hostname so TLS cert verification still checks
                # the name, not the literal IP.
                if transport is None:
                    host, ip = _assert_public_host(current)
                    target = _pin_url(current, ip)
                    send = {"headers": {"Host": host}, "extensions": {"sni_hostname": host}}
                else:
                    target, send = current, {}
                with client.stream("GET", target, **send) as response:
                    location = response.headers.get("location")
                    if response.is_redirect and location:
                        current = urljoin(current, location)
                        continue
                    _raise_for_corpus_status(response.status_code, stage)
                    return read_capped(response)
    except httpx.TimeoutException as exc:
        raise RetriableIngestionError(
            "external corpus request timed out", reason=FailureReason.TIMEOUT, stage=stage
        ) from exc
    except httpx.HTTPError as exc:
        raise RetriableIngestionError(
            "external corpus request failed",
            reason=FailureReason.FETCH_FAILURE,
            stage=stage,
        ) from exc
    except (ResponseTooLargeError, SsrfBlockedError) as exc:
        raise PermanentIngestionError(
            "external corpus PDF rejected (too large or non-public host)",
            reason=FailureReason.FETCH_FAILURE,
            stage=stage,
        ) from exc
    raise PermanentIngestionError(
        "external corpus PDF exceeded redirect limit",
        reason=FailureReason.FETCH_FAILURE,
        stage=stage,
    )


def _assert_public_host(url: str) -> tuple[str, str]:
    """Resolve a fetch URL's host, reject any private/loopback/link-local/reserved address, and
    return ``(host, pinned_ip)``. Connecting to the returned IP (instead of re-resolving) closes
    the DNS-rebinding window between this check and the socket connect (BR-18 / SEC-15)."""
    host = urlsplit(url).hostname
    if not host:
        raise SsrfBlockedError(f"fetch URL has no host: {url!r}")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise SsrfBlockedError(f"cannot resolve host {host!r}") from exc
    pinned: str | None = None
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise SsrfBlockedError(f"host {host!r} resolves to non-public address {ip}")
        if pinned is None:
            pinned = str(ip)
    if pinned is None:
        raise SsrfBlockedError(f"host {host!r} resolved to no address")
    return host, pinned


def _pin_url(url: str, ip: str) -> str:
    """Rewrite ``url`` to target a validated ``ip``, preserving scheme/port/path/query. The host
    is dropped from the netloc (it travels in the Host header + TLS SNI instead). IPv6 is
    bracketed."""
    parts = urlsplit(url)
    netloc = f"[{ip}]" if ":" in ip else ip
    if parts.port is not None:
        netloc = f"{netloc}:{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path or "/", parts.query, ""))


def _raise_for_corpus_status(status_code: int, stage: str) -> None:
    if status_code == 429 or status_code >= 500:
        raise RetriableIngestionError(
            f"external corpus source returned {status_code}",
            reason=FailureReason.RATE_LIMITED
            if status_code == 429
            else FailureReason.FETCH_FAILURE,
            stage=stage,
        )
    if status_code >= 400:
        raise PermanentIngestionError(
            f"external corpus source returned {status_code}",
            reason=FailureReason.FETCH_FAILURE,
            stage=stage,
        )


def _request(
    url: str,
    *,
    params: dict[str, str] | None,
    headers: dict[str, str] | None,
    timeout_seconds: float,
    transport: object | None,
    stage: str,
) -> bytes:
    import httpx

    from docsuri_ingestion.http_limits import ResponseTooLargeError, read_capped

    try:
        with (
            httpx.Client(
                timeout=timeout_seconds, follow_redirects=True, transport=transport
            ) as client,
            client.stream("GET", url, params=params, headers=headers) as response,
        ):
            _raise_for_corpus_status(response.status_code, stage)
            return read_capped(response)  # metadata JSON is capped too (NFR §0.5)
    except httpx.TimeoutException as exc:
        raise RetriableIngestionError(
            "external corpus request timed out", reason=FailureReason.TIMEOUT, stage=stage
        ) from exc
    except httpx.HTTPError as exc:
        raise RetriableIngestionError(
            "external corpus request failed",
            reason=FailureReason.FETCH_FAILURE,
            stage=stage,
        ) from exc
    except ResponseTooLargeError as exc:
        raise PermanentIngestionError(
            "external corpus metadata exceeded size cap",
            reason=FailureReason.FETCH_FAILURE,
            stage=stage,
        ) from exc


def _response_json(raw: bytes, stage: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise PermanentIngestionError(
            "external corpus source returned invalid JSON",
            reason=FailureReason.PARSE_FAILURE,
            stage=stage,
        ) from exc
    if not isinstance(payload, dict):
        raise PermanentIngestionError(
            "external corpus source returned non-object JSON",
            reason=FailureReason.PARSE_FAILURE,
            stage=stage,
        )
    return payload


def _query(categories: Sequence[str]) -> str:
    terms = sorted({_QUERY_TERMS.get(category, category) for category in categories})
    return " ".join(terms) or "machine learning"


def _in_window(
    record: SourcePaperRecord,
    since: datetime,
    until: datetime | None,
) -> bool:
    timestamp = record.updated_at or record.published_at or since
    return timestamp > since and (until is None or timestamp <= until)


def _first_pdf_url(locations: list[dict[str, Any]]) -> str | None:
    for location in locations:
        pdf_url = _https_url(location.get("pdf_url"))
        if pdf_url:
            return pdf_url
    return None


def _https_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if value.startswith(("https://", "http://")):
        return value
    return None


def _license_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if "creativecommons.org" in normalized or "arxiv.org/licenses/nonexclusive" in normalized:
        return value.strip()
    cc = normalized.replace("_", "-").replace(" ", "-")
    if cc in {"cc-by", "ccby"}:
        return "https://creativecommons.org/licenses/by/4.0/"
    if cc in {"cc-by-sa", "ccbysa"}:
        return "https://creativecommons.org/licenses/by-sa/4.0/"
    if cc in {"cc0", "cc-zero"}:
        return "https://creativecommons.org/publicdomain/zero/1.0/"
    return None


def _parse_date(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        text = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _int_or_none(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _abstract_text(inverted: dict[str, list[int]]) -> str:
    words: list[tuple[int, str]] = []
    for word, positions in inverted.items():
        for position in positions:
            words.append((position, word))
    return " ".join(word for _, word in sorted(words))


def _arxiv_id(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return value.rstrip("/").rsplit("/", 1)[-1]
