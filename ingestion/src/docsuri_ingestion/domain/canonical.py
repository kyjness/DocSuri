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


def _normalize(value: str) -> str:
    return _WS_RE.sub(" ", value).strip().lower()


def _strip_arxiv_version(value: str) -> str:
    base, marker, suffix = value.rpartition("v")
    return base if marker and suffix.isdigit() else value
