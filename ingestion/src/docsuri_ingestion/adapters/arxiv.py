from __future__ import annotations

import logging
import time
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
from docsuri_ingestion.resilience import RetryPolicy, TokenBucket

_log = logging.getLogger("docsuri.ingestion.arxiv")

ATOM_NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
OAI_NS = {
    "oai": "http://www.openarchives.org/OAI/2.0/",
    "arxiv": "http://arxiv.org/OAI/arXiv/",
}


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
            "https://arxiv.org/html",
            "https://ar5iv.labs.arxiv.org/html",
        ),
        timeout_seconds: float = 30.0,
        rate_limiter: TokenBucket | None = None,
        oai_retry_policy: RetryPolicy | None = None,
    ) -> None:
        self._atom_base_url = atom_base_url
        self._oai_base_url = oai_base_url
        self._pdf_base_url = pdf_base_url.rstrip("/")
        self._html_base_urls = tuple(base.rstrip("/") for base in html_base_urls)
        # Map each HTML base to its doc-model source tier (Q6 ladder): ar5iv vs native arXiv HTML.
        self._html_source_tiers = tuple(
            (base, SourceTier.ar5iv if "ar5iv" in base else SourceTier.native_html)
            for base in self._html_base_urls
        )
        self._timeout_seconds = timeout_seconds
        self._rate_limiter = rate_limiter or TokenBucket(rate_per_second=0.33)
        # Harvest pagination is long-running (hours); tolerate transient arXiv blips with
        # generous backoff before giving up. ~2,4,8,16,32s ≈ 62s total across 6 attempts.
        self._oai_retry_policy = oai_retry_policy or RetryPolicy(
            max_attempts=6, base_delay_seconds=2.0
        )

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
        license_el = ET.fromstring(body).find(".//arxiv:license", OAI_NS)
        if license_el is not None and license_el.text:
            return replace(record, license_url=license_el.text.strip())
        return record

    def fetch_full_text(self, metadata: MetadataRecord) -> RawDocument:
        """Acquire full-text plain text (BR-29): arXiv HTML first, PDF text fallback.

        HTML is the preferred *source* — it converts to the cleanest plain text — and PDF
        text extraction is the fallback when HTML is unavailable. Only normalized plain text
        is produced/stored (the viewer renders plain text with anchor highlighting). Never
        decodes a compressed payload as text (the #139 e-print defect).
        """
        arxiv_id = metadata.identifier.arxiv_id
        html, html_url = self._try_get_html(arxiv_id)
        if html is not None:
            text = html_to_text(html)
            if text:
                return RawDocument(metadata=metadata, text=text, source_url=html_url)

        pdf_url = f"{self._pdf_base_url}/{arxiv_id}"
        pdf = self._get_bytes(pdf_url, params=None, stage="fetch_full_text")
        try:
            text = pdf_to_text(pdf)
        except FullTextExtractionError as exc:
            raise PermanentIngestionError(
                "full text extraction could not parse the PDF payload",
                reason=FailureReason.PARSE_FAILURE,
                stage="fetch_full_text",
            ) from exc
        if not text:
            raise PermanentIngestionError(
                "full text extraction yielded empty text",
                reason=FailureReason.PARSE_FAILURE,
                stage="fetch_full_text",
            )
        return RawDocument(
            metadata=metadata, text=text, source_url=pdf_url, content_type="text/plain"
        )

    def fetch_html_source(self, arxiv_id: str) -> tuple[str, SourceTier] | None:
        """Fetch deterministic-parseable HTML for the doc-model (BR-30, Q6 ladder).

        Walks the configured HTML bases (native arXiv HTML → ar5iv) and returns the first
        ``(html, source_tier)`` that yields HTML, or ``None`` when no rung produced HTML
        (the builder maps that to ``source_unavailable``). e-print/PDF rungs are additive.
        """
        for base, tier in self._html_source_tiers:
            html = self._get_html_at(base, arxiv_id)
            if html:
                return html, tier
        return None

    def _try_get_html(self, arxiv_id: str) -> tuple[str | None, str]:
        """Best-effort HTML fetch across configured bases (arXiv native → ar5iv).

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
        """GET one HTML base; ``None`` on any non-200, non-HTML, or transport error."""
        import httpx

        url = f"{base}/{arxiv_id}"
        self._rate_limiter.acquire()
        try:
            with httpx.Client(timeout=self._timeout_seconds, follow_redirects=True) as client:
                response = client.get(url)
        except httpx.HTTPError:
            return None
        content_type = response.headers.get("content-type", "").lower()
        if response.status_code == 200 and "html" in content_type:
            return response.text
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
            body = self._fetch_oai_page(params)
            yield from parse_oai_records(body)
            token = parse_oai_resumption_token(body)
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
        policy = self._oai_retry_policy
        for attempt in range(1, policy.max_attempts + 1):
            try:
                return self._get_text(self._oai_base_url, params=params, stage="harvest_seed")
            except RetriableIngestionError:
                if attempt >= policy.max_attempts:
                    raise
                _log.warning("harvest page fetch failed (attempt %d), retrying", attempt)
                time.sleep(policy.delay_for_attempt(attempt))
        raise AssertionError("unreachable")  # pragma: no cover

    def _get_text(self, url: str, *, params: dict[str, str] | None, stage: str) -> str:
        return self._get_bytes(url, params=params, stage=stage).decode("utf-8", errors="replace")

    def _get_bytes(self, url: str, *, params: dict[str, str] | None, stage: str) -> bytes:
        import httpx

        self._rate_limiter.acquire()
        try:
            with httpx.Client(timeout=self._timeout_seconds, follow_redirects=True) as client:
                response = client.get(url, params=params)
        except httpx.TimeoutException as exc:
            raise RetriableIngestionError(
                "arXiv request timed out",
                reason=FailureReason.TIMEOUT,
                stage=stage,
            ) from exc
        except httpx.HTTPError as exc:
            raise RetriableIngestionError(
                "arXiv request failed",
                reason=FailureReason.FETCH_FAILURE,
                stage=stage,
            ) from exc

        if response.status_code == 404:
            raise PermanentIngestionError(
                "arXiv resource not found",
                reason=FailureReason.FETCH_FAILURE,
                stage=stage,
            )
        if response.status_code == 429 or response.status_code >= 500:
            raise RetriableIngestionError(
                f"arXiv returned retriable status {response.status_code}",
                reason=FailureReason.RATE_LIMITED
                if response.status_code == 429
                else FailureReason.FETCH_FAILURE,
                stage=stage,
            )
        if response.status_code >= 400:
            raise PermanentIngestionError(
                f"arXiv returned permanent status {response.status_code}",
                reason=FailureReason.FETCH_FAILURE,
                stage=stage,
            )
        return response.content


def parse_atom_feed(body: str) -> list[MetadataRecord]:
    try:
        root = ET.fromstring(body)
    except ET.ParseError as e:
        raise PermanentIngestionError(
            f"Failed to parse XML Atom feed: {e}",
            reason=FailureReason.PARSE_FAILURE,
            stage="parse_atom_feed",
        ) from e
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
    try:
        root = ET.fromstring(body)
    except ET.ParseError as e:
        raise PermanentIngestionError(
            f"Failed to parse XML OAI records: {e}",
            reason=FailureReason.PARSE_FAILURE,
            stage="parse_oai_records",
        ) from e
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
    try:
        root = ET.fromstring(body)
    except ET.ParseError as e:
        raise PermanentIngestionError(
            f"Failed to parse XML OAI resumption token: {e}",
            reason=FailureReason.PARSE_FAILURE,
            stage="parse_oai_resumption_token",
        ) from e
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
