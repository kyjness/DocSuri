from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Sequence
from dataclasses import replace
from datetime import datetime

from docsuri_shared.dtos import SourceTier

from docsuri_ingestion.domain.enums import FailureReason
from docsuri_ingestion.domain.errors import PermanentIngestionError, RetriableIngestionError
from docsuri_ingestion.domain.models import CategoryFilter, MetadataRecord, RawDocument
from docsuri_ingestion.full_text_extraction import (
    FullTextExtractionError,
    html_to_text,
    pdf_to_text,
)
from docsuri_ingestion.ports import RawContentStorePort
from docsuri_ingestion.resilience import RetryPolicy, TokenBucket, retry_with_policy
from docsuri_ingestion.xmlsafe import safe_fromstring

_log = logging.getLogger("docsuri.ingestion.arxiv")

ATOM_NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
OAI_NS = {
    "oai": "http://www.openarchives.org/OAI/2.0/",
    "arxiv": "http://arxiv.org/OAI/arXiv/",
}

# A complete arXiv HTML conversion yields tens of thousands of characters of plain text. A
# truncated ar5iv (LaTeXML) conversion — HTTP 200 but the LaTeX failed to convert past the
# abstract + a sentence — yields only ~1-2k. Below this floor the HTML source is treated as broken
# and the PDF text is preferred (both are valid full text, so a rare genuinely-short paper only
# loses the HTML rung, never the text). Trace: BR-29.
_MIN_HTML_FULLTEXT_CHARS = 3000


def _oai_set(category: str) -> str:
    """Map an arXiv category to its OAI-PMH setSpec. arXiv OAI sets use a colon hierarchy
    ``<archive>:<archive>:<CATEGORY>`` (e.g. ``cs.LG`` → ``cs:cs:LG``), NOT the dotted code —
    a dotted ``set=cs.LG`` returns ``badArgument: Set does not exist`` (HTTP 200, 0 records),
    which silently harvested nothing."""
    archive, _, sub = category.partition(".")
    return f"{archive}:{archive}:{sub}" if sub else archive


class ArxivHttpSource:
    def __init__(
        self,
        *,
        atom_base_url: str = "https://export.arxiv.org/api/query",
        oai_base_url: str = "https://oaipmh.arxiv.org/oai",
        pdf_base_url: str = "https://arxiv.org/pdf",
        html_base_urls: Sequence[str] = (
            # ar5iv (LaTeXML) ONLY: its HTML is what the doc-model parser's LaTeX/macro
            # sanitizer is built and tested against. Native arXiv HTML (arxiv.org/html) was
            # removed from BOTH ladders (doc-model and full text) on 2026-08-10 (BR-29/BR-30
            # 개정): operational review kept finding broken renders, and when its LaTeXML run
            # fails the raw TeX (\includegraphics, \thefigure …) lands verbatim in the plain
            # text the search index chunks. Papers without an ar5iv build take the PDF rung.
            "https://ar5iv.labs.arxiv.org/html",
        ),
        timeout_seconds: float = 30.0,
        rate_limiter: TokenBucket | None = None,
        oai_retry_policy: RetryPolicy | None = None,
        raw_store: RawContentStorePort | None = None,
        raw_cache_mode: str = "off",
    ) -> None:
        self._atom_base_url = atom_base_url
        self._oai_base_url = oai_base_url
        self._pdf_base_url = pdf_base_url.rstrip("/")
        # Every configured base serves the single HTML rung of the Q6 ladder, and that rung is
        # ar5iv-tier by definition — the native_html tier has no producer since 2026-08-10.
        self._html_base_urls = tuple(base.rstrip("/") for base in html_base_urls)
        self._timeout_seconds = timeout_seconds
        self._rate_limiter = rate_limiter or TokenBucket(rate_per_second=0.33)
        # Harvest pagination is long-running (hours); tolerate transient arXiv blips with
        # generous backoff before giving up. ~2,4,8,16,32s ≈ 62s total across 6 attempts.
        self._oai_retry_policy = oai_retry_policy or RetryPolicy(
            max_attempts=6, base_delay_seconds=2.0
        )
        # B3 raw-content cache. Default off → fetch_full_text hits arXiv exactly as before.
        self._raw_store = raw_store
        self._raw_cache_mode = raw_cache_mode
        # Single-entry HTML memo, keyed (base, arxiv_id) — mirrors the asset source's e-print
        # memo. Ingesting one paper asks for its HTML twice: fetch_full_text takes the plain-text
        # rung and discards the markup, then the doc-model builder asks for the ar5iv source. At
        # 1 request per 3s that second GET doubled the wall-clock cost of every fresh paper.
        # A miss is memoized too, so a paper with no ar5iv build is not re-requested.
        self._html_memo: tuple[tuple[str, str], str | None] | None = None

    def harvest_seed(self, category_filter: CategoryFilter) -> Iterable[MetadataRecord]:
        for category in category_filter.categories:
            yield from self._oai_list_records(category, category_filter)

    def fetch_incremental(
        self, since: datetime, categories: Sequence[str]
    ) -> Iterable[MetadataRecord]:
        query = "+OR+".join(f"cat:{category}" for category in categories)
        params = {
            "search_query": query,
            "sortBy": "lastUpdatedDate",
            "sortOrder": "ascending",
            "start": "0",
            "max_results": "100",
        }
        body = self._get_text(self._atom_base_url, params=params, stage="fetch_incremental")
        for record in parse_atom_feed(body):
            if record.updated_at > since:
                yield record

    def fetch_metadata(self, arxiv_ref: str) -> MetadataRecord:
        params = {"id_list": arxiv_ref, "max_results": "1"}
        body = self._get_text(self._atom_base_url, params=params, stage="fetch_metadata")
        records = parse_atom_feed(body)
        if not records:
            raise PermanentIngestionError(
                "arXiv metadata not found",
                reason=FailureReason.FETCH_FAILURE,
                stage="fetch_metadata",
            )
        record = records[0]
        # The Atom API no longer reliably exposes <arxiv:license>; backfill from OAI-PMH
        # GetRecord so strict-OA gating sees the real license instead of None.
        if record.license_url is None:
            record = self._enrich_license_from_oai(record)
        return record

    def _enrich_license_from_oai(self, record: MetadataRecord) -> MetadataRecord:
        # ponytail: bare-id heuristic — strip the "vN" version suffix; arXiv versions are
        # always a trailing "v<digits>", so split on the last "v" is safe for both new
        # ("2401.12345v2") and legacy ("hep-ph/9901001") ids.
        ref = record.arxiv_ref
        bare_id = ref.rsplit("v", 1)[0] if "v" in ref else ref
        params = {
            "verb": "GetRecord",
            "metadataPrefix": "arXiv",
            "identifier": f"oai:arXiv.org:{bare_id}",
        }
        body = self._get_text(self._oai_base_url, params=params, stage="fetch_license")
        try:
            license_el = safe_fromstring(body).find(".//arxiv:license", OAI_NS)
        except ET.ParseError:
            # Best-effort backfill: a malformed OAI response must not escape the failure
            # taxonomy and crash the worker. Degrade to the unenriched record — license stays
            # None → strict-OA reject downstream (fail-closed, BR-1/BR-18).
            _log.warning("license enrichment got malformed OAI XML for %s", bare_id)
            return record
        if license_el is not None and license_el.text:
            return replace(record, license_url=license_el.text.strip())
        return record

    def fetch_full_text(self, metadata: MetadataRecord) -> RawDocument:
        """Acquire full-text plain text (BR-29): arXiv HTML first, PDF text fallback.

        HTML is the preferred *source* — it converts to the cleanest plain text — and PDF
        text extraction is the fallback when HTML is unavailable. Only normalized plain text
        is produced/stored (the viewer renders plain text with anchor highlighting). Never
        decodes a compressed payload as text (the #139 e-print defect). The B3 raw cache is
        transparent: ``off`` fetches from arXiv exactly as before; ``prefer``/``only`` read the S3
        raw cache first (``only`` never fetches) — see ``_acquire_html`` / ``_acquire_pdf``.
        """
        arxiv_id = metadata.identifier.arxiv_id
        html, html_url, html_tier = self._acquire_html(metadata)
        html_text = html_to_text(html) if html else ""
        # A COMPLETE HTML conversion is the preferred source. A truncated one (ar5iv LaTeXML
        # failure — HTTP 200 but only the abstract + a sentence, below the floor) is worse than
        # the PDF text, so fall through to PDF and keep the short HTML only if the PDF is
        # unavailable too (better a fragment than nothing).
        if html_text and len(html_text) >= _MIN_HTML_FULLTEXT_CHARS:
            return RawDocument(
                metadata=metadata, text=html_text, source_url=html_url, source_tier=html_tier
            )

        pdf_url = f"{self._pdf_base_url}/{arxiv_id}"
        try:
            pdf = self._acquire_pdf(metadata)
            # pdf is None only for an ``only``-mode cache miss — treat it as the PDF-unavailable
            # branch (empty text → short-HTML fallback, else the terminal empty-text error).
            text = pdf_to_text(pdf) if pdf is not None else ""
        except (PermanentIngestionError, FullTextExtractionError) as exc:
            # The PDF is PERMANENTLY unavailable (404/4xx from _get_bytes) or unparseable
            # (FullTextExtractionError): a truncated HTML body beats failing the paper — keep the
            # short HTML "only if the PDF is unavailable too" (better a fragment than nothing).
            # RetriableIngestionError (429/5xx/timeout) is deliberately NOT caught here: it
            # propagates so a later retry can still recover the full PDF instead of prematurely
            # settling for the fragment.
            if html_text:
                return RawDocument(
                    metadata=metadata, text=html_text, source_url=html_url, source_tier=html_tier
                )
            if isinstance(exc, PermanentIngestionError):
                raise
            raise PermanentIngestionError(
                "full text extraction could not parse the PDF payload",
                reason=FailureReason.PARSE_FAILURE,
                stage="fetch_full_text",
            ) from exc
        if text:
            return RawDocument(
                metadata=metadata,
                text=text,
                source_url=pdf_url,
                content_type="text/plain",
                source_tier=SourceTier.pdf,
            )
        if html_text:  # PDF empty/absent — fall back to the (short) HTML text rather than erroring.
            return RawDocument(
                metadata=metadata, text=html_text, source_url=html_url, source_tier=html_tier
            )
        raise PermanentIngestionError(
            "full text extraction yielded empty text",
            reason=FailureReason.PARSE_FAILURE,
            stage="fetch_full_text",
        )

    def _acquire_html(self, metadata: MetadataRecord) -> tuple[str | None, str, SourceTier]:
        """HTML source honoring the raw cache mode (B3). ``off`` is byte-identical to the old
        ``_try_get_html`` path; ``prefer`` reads cache→HTTP and writes back a fetch; ``only`` reads
        cache and NEVER hits the network. The HTML rung is ar5iv-only (BR-29 2026-08-10), so the
        returned tier is always ``ar5iv``; a raw cache written before the native removal may still
        hold a ``native_html`` object, which is deliberately ignored — re-serving it would re-admit
        the removed rung through the cache."""
        mode, store = self._raw_cache_mode, self._raw_store
        pid, ver = metadata.paper_id, metadata.version
        if mode in ("prefer", "only") and store is not None:
            cached = store.get_raw(pid, ver, SourceTier.ar5iv.value)
            if cached:
                text = cached.decode("utf-8")
                # Prime the memo so the doc-model rung reads the cached bytes too; it calls
                # _get_html_at directly and would otherwise go to the network in cache mode.
                if self._html_base_urls:
                    self._html_memo = (
                        (self._html_base_urls[0], metadata.identifier.arxiv_id),
                        text,
                    )
                return text, f"cache://{SourceTier.ar5iv.value}", SourceTier.ar5iv
            if mode == "only":
                return None, "", SourceTier.ar5iv
        html, url = self._try_get_html(metadata.identifier.arxiv_id)
        if html and mode == "prefer" and store is not None:
            store.put_raw(
                pid, ver, SourceTier.ar5iv.value, html.encode("utf-8"),
                content_type="text/html; charset=utf-8",
            )
        return html, url, SourceTier.ar5iv

    def _acquire_pdf(self, metadata: MetadataRecord) -> bytes | None:
        """PDF bytes honoring the raw cache mode (B3). ``only`` never hits the network (returns
        ``None`` on a miss); ``prefer`` reads cache→HTTP and caches a fetch; ``off`` fetches exactly
        as before, letting _get_bytes' exceptions propagate to fetch_full_text's fallback ladder."""
        mode, store = self._raw_cache_mode, self._raw_store
        pid, ver = metadata.paper_id, metadata.version
        if mode in ("prefer", "only") and store is not None:
            cached = store.get_raw(pid, ver, "pdf")
            if cached:
                return cached
            if mode == "only":
                return None
        pdf = self._get_bytes(
            f"{self._pdf_base_url}/{metadata.identifier.arxiv_id}",
            params=None,
            stage="fetch_full_text",
        )
        if mode == "prefer" and store is not None:
            store.put_raw(pid, ver, "pdf", pdf, content_type="application/pdf")
        return pdf

    def fetch_html_source(self, arxiv_id: str) -> tuple[str, SourceTier] | None:
        """Fetch deterministic-parseable HTML for the doc-model (BR-30, Q6 ladder).

        Doc-model source is **ar5iv only** — since 2026-08-10 the same is true of the full-text
        ladder, so there is no native rung anywhere for this to guard against. When ar5iv yields
        nothing this returns ``None`` → the builder moves down the ladder (PDF/GROBID).
        """
        for base in self._html_base_urls:
            html = self._get_html_at(base, arxiv_id)
            if html:
                return html, SourceTier.ar5iv
        return None

    def _try_get_html(self, arxiv_id: str) -> tuple[str | None, str]:
        """Best-effort HTML fetch across the configured (ar5iv) bases.

        HTML is preferred-but-optional — not every paper compiles to HTML — so any non-200,
        non-HTML, or transport error degrades to ``None`` (→ PDF fallback) rather than raising.
        """
        last_url = ""
        for base in self._html_base_urls:
            last_url = f"{base}/{arxiv_id}"
            html = self._get_html_at(base, arxiv_id)
            if html is not None:
                return html, last_url
        return None, last_url

    def _get_html_at(self, base: str, arxiv_id: str) -> str | None:
        """One HTML base, memoized; ``None`` on any non-200, non-HTML, or transport error."""
        key = (base, arxiv_id)
        # Load the slot ONCE. Reading self._html_memo three times (None-check, key, value) lets a
        # concurrent writer swap papers between the key check and the value read, which would
        # return another paper's HTML under this id — silently indexing the wrong body. One load
        # of the immutable tuple is atomic, so the key and the value always belong together.
        memo = self._html_memo
        if memo is not None and memo[0] == key:
            return memo[1]
        html = self._fetch_html_at(base, arxiv_id)
        self._html_memo = (key, html)
        return html

    def _fetch_html_at(self, base: str, arxiv_id: str) -> str | None:
        import httpx

        url = f"{base}/{arxiv_id}"
        from docsuri_ingestion.http_limits import ResponseTooLargeError, read_capped

        self._rate_limiter.acquire()
        try:
            with (
                httpx.Client(timeout=self._timeout_seconds, follow_redirects=True) as client,
                client.stream("GET", url) as response,
            ):
                content_type = response.headers.get("content-type", "").lower()
                if response.status_code == 200 and "html" in content_type:
                    return read_capped(response).decode("utf-8", errors="replace")
                return None
        except (httpx.HTTPError, ResponseTooLargeError):
            return None

    def _oai_list_records(
        self,
        category: str,
        category_filter: CategoryFilter,
    ) -> Iterable[MetadataRecord]:
        params = {
            "verb": "ListRecords",
            "metadataPrefix": "arXiv",
            "set": _oai_set(category),
            "from": category_filter.updated_after.date().isoformat(),
            "until": category_filter.updated_before.date().isoformat(),
        }
        while True:
            # Parse the page once and read both records and the resumption token off the same
            # tree — this ran the XML parser twice per page over a multi-hour harvest.
            root = _parse_xml(
                self._fetch_oai_page(params), stage="parse_oai_records", label="OAI records"
            )
            yield from _oai_records_from(root)
            token = _oai_token_from(root)
            if not token:
                return
            params = {"verb": "ListRecords", "resumptionToken": token}

    def _fetch_oai_page(self, params: dict[str, str]) -> str:
        """Fetch one OAI ListRecords page, retrying transient failures with backoff.

        This runs inside the harvest_seed generator, so a RetriableIngestionError raised here
        propagates past backfill's per-paper try/except and aborts the whole multi-hour run
        (the timeout-mid-pagination crash). Retry transient blips in-place; if they persist past
        the policy, abort loudly — a re-run resumes via idempotent upserts rather than silently
        dropping a page of papers."""
        return retry_with_policy(
            self._oai_retry_policy,
            lambda: self._get_text(self._oai_base_url, params=params, stage="harvest_seed"),
            retriable=lambda exc: isinstance(exc, RetriableIngestionError),
            on_retry=lambda attempt, _exc: _log.warning(
                "harvest page fetch failed (attempt %d), retrying", attempt
            ),
        )

    def _get_text(self, url: str, *, params: dict[str, str] | None, stage: str) -> str:
        return self._get_bytes(url, params=params, stage=stage).decode("utf-8", errors="replace")

    def _get_bytes(self, url: str, *, params: dict[str, str] | None, stage: str) -> bytes:
        import httpx

        from docsuri_ingestion.http_limits import (
            http_failures_as_ingestion_errors,
            raise_for_fetch_status,
            read_capped,
        )

        self._rate_limiter.acquire()
        with http_failures_as_ingestion_errors(
            stage=stage,
            timeout_message="arXiv request timed out",
            failure_message="arXiv request failed",
            rejected_message="arXiv response exceeded size cap",
        ):
            with (
                httpx.Client(timeout=self._timeout_seconds, follow_redirects=True) as client,
                client.stream("GET", url, params=params) as response,
            ):
                raise_for_fetch_status(response.status_code, stage=stage, source_label="arXiv")
                return read_capped(response)


def _parse_xml(body: str, *, stage: str, label: str) -> ET.Element:
    """Parse an untrusted arXiv/OAI XML body into the failure taxonomy.

    ``safe_fromstring`` forbids DTD/entity expansion (NFR §0.5); a malformed body is a permanent
    parse failure, never a retry. The license-enrichment path deliberately does NOT use this — it
    degrades to the unenriched record instead of raising.
    """
    try:
        return safe_fromstring(body)
    except ET.ParseError as e:
        raise PermanentIngestionError(
            f"Failed to parse XML {label}: {e}",
            reason=FailureReason.PARSE_FAILURE,
            stage=stage,
        ) from e


def parse_atom_feed(body: str) -> list[MetadataRecord]:
    root = _parse_xml(body, stage="parse_atom_feed", label="Atom feed")
    records: list[MetadataRecord] = []
    for entry in root.findall("atom:entry", ATOM_NS):
        arxiv_ref = _required_text(entry, "atom:id", ATOM_NS).rsplit("/", 1)[-1]
        title = _required_text(entry, "atom:title", ATOM_NS)
        abstract = _required_text(entry, "atom:summary", ATOM_NS)
        authors = tuple(
            author.findtext("atom:name", default="", namespaces=ATOM_NS).strip()
            for author in entry.findall("atom:author", ATOM_NS)
        )
        categories = tuple(
            node.attrib["term"]
            for node in entry.findall("atom:category", ATOM_NS)
            if node.attrib.get("term")
        )
        license_url = entry.findtext("arxiv:license", default=None, namespaces=ATOM_NS)
        records.append(
            MetadataRecord(
                arxiv_ref=arxiv_ref,
                title=title,
                authors=tuple(author for author in authors if author),
                abstract=abstract,
                categories=categories,
                updated_at=datetime.fromisoformat(_required_text(entry, "atom:updated", ATOM_NS)),
                published_at=datetime.fromisoformat(
                    _required_text(entry, "atom:published", ATOM_NS)
                ),
                license_url=license_url,
                primary_category=categories[0] if categories else None,
            )
        )
    return records


def _oai_authors(metadata: ET.Element) -> tuple[str, ...]:
    """arXiv OAI authors are nested ``<authors><author><keyname>/<forenames>`` elements,
    NOT a flat comma-joined text field — build "forenames keyname" per author."""
    names: list[str] = []
    for author in metadata.findall("arxiv:authors/arxiv:author", OAI_NS):
        forenames = author.findtext("arxiv:forenames", default="", namespaces=OAI_NS).strip()
        keyname = author.findtext("arxiv:keyname", default="", namespaces=OAI_NS).strip()
        full = " ".join(part for part in (forenames, keyname) if part)
        if full:
            names.append(full)
    return tuple(names)


def _build_oai_record(metadata: ET.Element) -> MetadataRecord:
    categories = tuple(_required_text(metadata, "arxiv:categories", OAI_NS).split())
    created = datetime.fromisoformat(_required_text(metadata, "arxiv:created", OAI_NS))
    updated_text = metadata.findtext("arxiv:updated", default=None, namespaces=OAI_NS)
    return MetadataRecord(
        arxiv_ref=_required_text(metadata, "arxiv:id", OAI_NS),
        title=_required_text(metadata, "arxiv:title", OAI_NS),
        authors=_oai_authors(metadata),
        abstract=_required_text(metadata, "arxiv:abstract", OAI_NS),
        categories=categories,
        updated_at=datetime.fromisoformat(updated_text) if updated_text else created,
        published_at=created,
        license_url=metadata.findtext("arxiv:license", default=None, namespaces=OAI_NS),
        primary_category=categories[0] if categories else None,
    )


def parse_oai_records(body: str) -> list[MetadataRecord]:
    return _oai_records_from(_parse_xml(body, stage="parse_oai_records", label="OAI records"))


def _oai_records_from(root: ET.Element) -> list[MetadataRecord]:
    records: list[MetadataRecord] = []
    for metadata in root.findall(".//oai:metadata/arxiv:arXiv", OAI_NS):
        # A single malformed record must not abort the harvest: parse_oai_records runs inside
        # the harvest_seed generator, so a raise here propagates past backfill's per-paper
        # try/except and kills the whole run (the #authors crash). Skip-and-continue instead.
        try:
            records.append(_build_oai_record(metadata))
        except (PermanentIngestionError, ValueError, KeyError) as exc:
            _log.warning("skipping malformed OAI record: %s", exc)
            continue
    return records


def parse_oai_resumption_token(body: str) -> str | None:
    return _oai_token_from(
        _parse_xml(body, stage="parse_oai_resumption_token", label="OAI resumption token")
    )


def _oai_token_from(root: ET.Element) -> str | None:
    token = root.findtext(".//oai:resumptionToken", default="", namespaces=OAI_NS).strip()
    return token or None


def _required_text(element: ET.Element, path: str, namespaces: dict[str, str]) -> str:
    value = element.findtext(path, default="", namespaces=namespaces).strip()
    if not value:
        raise PermanentIngestionError(
            f"missing arXiv field {path}",
            reason=FailureReason.VALIDATION_VIOLATION,
            stage="parse_metadata",
        )
    return value
