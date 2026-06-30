from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from .adapters.grobid import _tei_to_text
from .domain.enums import FailureReason, SourceName
from .domain.errors import PermanentIngestionError
from .domain.models import MetadataRecord
from .ports import ArxivSourcePort


@dataclass(frozen=True, slots=True)
class SourcePaperRecord:
    source_name: SourceName
    source_id: str
    title: str
    abstract: str = ""
    authors: tuple[str, ...] = ()
    categories: tuple[str, ...] = ()
    updated_at: datetime | None = None
    published_at: datetime | None = None
    year: int | None = None
    pdf_url: str | None = None
    html_url: str | None = None
    license_url: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    version: int = 1

    def to_payload(self) -> dict[str, Any]:
        return {
            "sourceName": self.source_name.value,
            "sourceId": self.source_id,
            "title": self.title,
            "abstract": self.abstract,
            "authors": list(self.authors),
            "categories": list(self.categories),
            "updatedAt": self.updated_at.isoformat() if self.updated_at else None,
            "publishedAt": self.published_at.isoformat() if self.published_at else None,
            "year": self.year,
            "pdfUrl": self.pdf_url,
            "htmlUrl": self.html_url,
            "licenseUrl": self.license_url,
            "doi": self.doi,
            "arxivId": self.arxiv_id,
            "version": self.version,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> SourcePaperRecord:
        try:
            source_name = SourceName(payload["sourceName"])
            source_id = str(payload["sourceId"])
            title = str(payload["title"])
        except (KeyError, TypeError, ValueError) as exc:
            raise PermanentIngestionError(
                "invalid source record payload",
                reason=FailureReason.POISON_EVENT,
                stage="queue",
            ) from exc
        return cls(
            source_name=source_name,
            source_id=source_id,
            title=title,
            abstract=str(payload.get("abstract") or ""),
            authors=tuple(str(v) for v in payload.get("authors") or ()),
            categories=tuple(str(v) for v in payload.get("categories") or ()),
            updated_at=_parse_datetime(payload.get("updatedAt")),
            published_at=_parse_datetime(payload.get("publishedAt")),
            year=_parse_optional_int(payload.get("year")),
            pdf_url=payload.get("pdfUrl"),
            html_url=payload.get("htmlUrl"),
            license_url=payload.get("licenseUrl"),
            doi=payload.get("doi"),
            arxiv_id=payload.get("arxivId"),
            version=int(payload.get("version") or 1),
        )


@dataclass(frozen=True, slots=True)
class CorpusTextCandidate:
    source_name: SourceName
    source_id: str
    source_tier: str
    payload_kind: str
    text: str
    source_url: str
    # Raw GROBID TEI (non-arXiv PDF path) for the structured doc-model parser; None when the
    # source is arXiv (HTML/PDF text path) or GROBID is not in play.
    tei: str | None = None
    # The source PDF bytes already fetched for the GROBID call, retained in-memory so the
    # (gated, best-effort) figure/formula crop step reuses them instead of re-fetching — which
    # also guarantees the crop renders against the SAME bytes the TEI coordinates were computed
    # from. None when not from the PDF/GROBID path. In-memory only: the candidate is never
    # serialized (the queue job carries the SourcePaperRecord, not this candidate).
    pdf: bytes | None = None


@runtime_checkable
class GrobidPort(Protocol):
    def extract_tei(self, pdf: bytes) -> str: ...


@runtime_checkable
class ExternalCorpusSourcePort(Protocol):
    def fetch_incremental(
        self,
        since: datetime,
        categories: Sequence[str],
        until: datetime | None = None,
    ) -> Iterable[SourcePaperRecord]: ...

    def fetch_pdf(self, record: SourcePaperRecord) -> bytes: ...


class CorpusSourceAdapterSet:
    """Small source boundary for phase-1 Corpus collection.

    Existing arXiv code already handles HTML-first/PDF fallback. Semantic Scholar and OpenAlex
    enter through the PDF->GROBID boundary; raw PDF bytes are consumed in-memory and never
    returned as an artifact.
    """

    def __init__(
        self,
        *,
        arxiv: ArxivSourcePort,
        grobid: GrobidPort | None = None,
        semantic_scholar: ExternalCorpusSourcePort | None = None,
        openalex: ExternalCorpusSourcePort | None = None,
    ) -> None:
        self._arxiv = arxiv
        self._grobid = grobid
        self._external: dict[SourceName, ExternalCorpusSourcePort] = {}
        if semantic_scholar is not None:
            self._external[SourceName.SEMANTIC_SCHOLAR] = semantic_scholar
        if openalex is not None:
            self._external[SourceName.OPENALEX] = openalex

    def fetch_arxiv_text(self, metadata: MetadataRecord) -> CorpusTextCandidate:
        raw = self._arxiv.fetch_full_text(metadata)
        tier = "ARXIV_PDF" if "/pdf/" in raw.source_url else "ARXIV_HTML"
        return CorpusTextCandidate(
            source_name=SourceName.ARXIV,
            source_id=metadata.arxiv_ref,
            source_tier=tier,
            payload_kind="HTML" if tier == "ARXIV_HTML" else "PDF",
            text=raw.text,
            source_url=raw.source_url,
        )

    def is_configured(self, source_name: SourceName) -> bool:
        return source_name is SourceName.ARXIV or source_name in self._external

    def fetch_incremental(
        self,
        source_name: SourceName,
        since: datetime,
        categories: Sequence[str],
        until: datetime | None = None,
    ) -> Iterable[SourcePaperRecord]:
        provider = self._external_provider(source_name)
        return provider.fetch_incremental(since, categories, until)

    def extract_record_text(self, record: SourcePaperRecord) -> CorpusTextCandidate:
        provider = self._external_provider(record.source_name)
        pdf = provider.fetch_pdf(record)
        return self.extract_pdf_text(record, pdf)

    def fetch_record_pdf(self, record: SourcePaperRecord) -> bytes:
        """Re-fetch the source PDF bytes for the (gated, best-effort) asset crop path.

        Kept separate from ``extract_record_text`` so the text/doc-model contract never carries
        raw PDF bytes; the bytes are consumed in-memory by the crop renderer and never stored."""
        return self._external_provider(record.source_name).fetch_pdf(record)

    def extract_pdf_text(self, record: SourcePaperRecord, pdf: bytes) -> CorpusTextCandidate:
        if record.source_name not in {SourceName.SEMANTIC_SCHOLAR, SourceName.OPENALEX}:
            raise PermanentIngestionError(
                "PDF+GROBID path is only for non-arXiv sources",
                reason=FailureReason.VALIDATION_VIOLATION,
                stage="source",
            )
        if self._grobid is None:
            raise PermanentIngestionError(
                "GROBID adapter is not configured",
                reason=FailureReason.DEPENDENCY_UNAVAILABLE,
                stage="grobid",
            )
        # One GROBID call yields the structured TEI; the flat text projection is derived from it
        # (the doc-model parser consumes the TEI, withdrawal/scan paths consume the text).
        tei = self._grobid.extract_tei(pdf)
        text = _tei_to_text(tei).strip()
        if not text:
            raise PermanentIngestionError(
                "GROBID returned empty text",
                reason=FailureReason.PARSE_FAILURE,
                stage="grobid",
            )
        return CorpusTextCandidate(
            source_name=record.source_name,
            source_id=record.source_id,
            source_tier=f"{record.source_name.value}_GROBID",
            payload_kind="PDF",
            text=text,
            source_url=record.pdf_url or "",
            tei=tei,
            pdf=pdf,
        )

    def _external_provider(self, source_name: SourceName) -> ExternalCorpusSourcePort:
        provider = self._external.get(source_name)
        if provider is None:
            raise PermanentIngestionError(
                f"{source_name.value} adapter is not configured",
                reason=FailureReason.DEPENDENCY_UNAVAILABLE,
                stage="source",
            )
        return provider


def _parse_datetime(value: object) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError as exc:
            raise PermanentIngestionError(
                "invalid source record datetime",
                reason=FailureReason.POISON_EVENT,
                stage="queue",
            ) from exc
    raise PermanentIngestionError(
        "invalid source record datetime",
        reason=FailureReason.POISON_EVENT,
        stage="queue",
    )


def _parse_optional_int(value: object) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise PermanentIngestionError(
            "invalid source record integer",
            reason=FailureReason.POISON_EVENT,
            stage="queue",
        ) from exc
