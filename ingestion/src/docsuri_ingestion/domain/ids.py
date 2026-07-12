from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

_ARXIV_URL_PREFIX_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?arxiv\.org/(?:abs|pdf)/", re.IGNORECASE
)
_ARXIV_PREFIX_RE = re.compile(r"^arxiv:", re.IGNORECASE)
_PDF_SUFFIX_RE = re.compile(r"\.pdf$", re.IGNORECASE)
_VERSION_RE = re.compile(r"^(?P<paper_id>.+?)v(?P<version>[1-9][0-9]*)$", re.IGNORECASE)
_NEW_STYLE_RE = re.compile(r"^[0-9]{4}\.[0-9]{4,5}$")
_OLD_STYLE_RE = re.compile(r"^[a-z-]+(?:\.[A-Z]{2})?/[0-9]{7}$", re.IGNORECASE)
_NEW_STYLE_YEAR_RE = re.compile(r"^(?P<yy>[0-9]{2})[0-9]{2}\.[0-9]{4,5}$")


@dataclass(frozen=True, slots=True)
class ArxivIdentifier:
    paper_id: str
    version: int

    @property
    def arxiv_id(self) -> str:
        return f"{self.paper_id}v{self.version}"

    @property
    def abs_url(self) -> str:
        return f"https://arxiv.org/abs/{self.arxiv_id}"


def normalize_arxiv_ref(raw_ref: str, *, default_version: int = 1) -> ArxivIdentifier:
    """Normalize arXiv URLs, refs, and versioned IDs to `(paper_id, version)`.

    `paper_id` is always versionless. A versionless input is accepted only with the
    explicit default version used by schedule/event fetches after metadata resolution.
    """
    if not raw_ref or not raw_ref.strip():
        raise ValueError("arXiv reference must be non-empty")

    ref = raw_ref.strip()
    ref = _ARXIV_URL_PREFIX_RE.sub("", ref)
    ref = _ARXIV_PREFIX_RE.sub("", ref)
    ref = _PDF_SUFFIX_RE.sub("", ref)
    ref = ref.strip("/")

    match = _VERSION_RE.match(ref)
    if match:
        paper_id = match.group("paper_id")
        version = int(match.group("version"))
    else:
        paper_id = ref
        version = default_version

    if not _is_valid_paper_id(paper_id):
        raise ValueError(f"invalid arXiv paper id: {raw_ref!r}")
    if version < 1:
        raise ValueError(f"invalid arXiv version: {version}")
    return ArxivIdentifier(paper_id=paper_id, version=version)


def year_from_paper_id(paper_id: str) -> int | None:
    """Submission year from a new-style arXiv id (YYMM.NNNNN → 20YY), or None.

    The id's YYMM prefix is the true submission month/year, so it is authoritative for the
    search year facet — unlike the metadata date, which can fall back to a re-touched
    ``updated_at`` and mis-bucket ~12% of papers (issue #436). Returns None for old-style and
    non-arXiv (``src-…``) ids, where the caller keeps the date-derived year. New-style ids began
    2007-04, so the 20YY expansion is unambiguous for every id this matches.
    """
    m = _NEW_STYLE_YEAR_RE.match(paper_id)
    return 2000 + int(m.group("yy")) if m else None


def content_fingerprint(paper_id: str, version: int) -> str:
    """Return the BR-4 fingerprint derived from paperId + version."""
    identifier = normalize_arxiv_ref(f"{paper_id}v{version}")
    payload = f"{identifier.paper_id}:v{identifier.version}".encode()
    return hashlib.sha256(payload).hexdigest()


def _is_valid_paper_id(paper_id: str) -> bool:
    return bool(_NEW_STYLE_RE.match(paper_id) or _OLD_STYLE_RE.match(paper_id))
