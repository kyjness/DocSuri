from __future__ import annotations

import hashlib
import re

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
