from __future__ import annotations

import hashlib
import re

from docsuri_shared.dtos import SourceTier

from .enums import SourceName

_WS_RE = re.compile(r"\s+")


def canonical_key(
    *,
    title: str,
    year: int,
    doi: str | None = None,
    arxiv_id: str | None = None,
    first_author: str | None = None,
) -> str:
    """Canonical paper key priority: DOI -> arXiv id -> normalized title/author/year."""
    if doi and doi.strip():
        return "doi:" + doi.strip().lower()
    if arxiv_id and arxiv_id.strip():
        return "arxiv:" + _strip_arxiv_version(arxiv_id.strip().lower())
    normalized = "|".join(
        (
            _normalize(title),
            _normalize(first_author or ""),
            str(year),
        )
    )
    return "title:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]


# Stored ``winning_source_tier`` vocabulary (canonical dedup ledger, migrate.audit). arXiv text
# is labelled by which rung produced it; a non-arXiv source that won dedup is labelled by its
# name plus the extractor that read its PDF.
ARXIV_HTML_TIER = "ARXIV_HTML"
ARXIV_PDF_TIER = "ARXIV_PDF"


def arxiv_tier_label(source_tier: SourceTier | None) -> str:
    """Stored tier label for arXiv-sourced text: the PDF rung, or either HTML rung.

    Reads the tier the fetch adapter recorded on the RawDocument. Consumers used to re-derive it
    by looking for ``/pdf/`` in the source URL, which is not something a URL is required to carry
    — the raw-content cache serves ``cache://<tier>``, and the PDF base URL is configurable.
    """
    return ARXIV_PDF_TIER if source_tier is SourceTier.pdf else ARXIV_HTML_TIER


def grobid_tier_label(source_name: SourceName) -> str:
    """Stored tier label for a non-arXiv source whose PDF was structured by GROBID."""
    return f"{source_name.value}_GROBID"


def source_priority(source_name: SourceName) -> int:
    """Canonical-winner precedence from a source name: lower wins (BR-C1, BR-C3).

    The name-keyed and tier-keyed views of the same ordering; ``source_priority_from_tier``
    derives it from a stored tier string when only that is available.
    """
    return {
        SourceName.ARXIV: 0,
        SourceName.SEMANTIC_SCHOLAR: 1,
        SourceName.OPENALEX: 2,
    }[source_name]


def source_priority_from_tier(source_tier: str) -> int:
    """Canonical-winner precedence from a stored source tier: lower wins (BR-C1, BR-C3).

    arXiv (any tier) > Semantic Scholar > OpenAlex. The control-plane guarded upsert mirrors
    this exact ordering in SQL, so keep the two in sync if the source set changes.
    """
    normalized = source_tier.upper()
    if "ARXIV" in normalized or source_tier in {"native_html", "ar5iv", "eprint_latex", "pdf"}:
        return 0
    if "SEMANTIC_SCHOLAR" in normalized:
        return 1
    return 2


def _normalize(value: str) -> str:
    return _WS_RE.sub(" ", value).strip().lower()


def _strip_arxiv_version(value: str) -> str:
    base, marker, suffix = value.rpartition("v")
    return base if marker and suffix.isdigit() else value
