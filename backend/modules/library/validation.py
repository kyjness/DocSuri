"""U4 Library — validation, normalization, cursor codec, entity↔DTO mapping.

This module IS the ``UserDataDTOAndValidation`` component (application-design U4): SEC-5 input
validation, query normalization (BR-L1), the opaque keyset cursor codec (BR-L8), and the
internal-entity → wire-DTO mapping that strips every internal field (SEC-9 non-disclosure —
``owner_id``/``normalized_query``/``dedupe_key`` never reach the wire).
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import unicodedata
from collections.abc import Callable
from datetime import datetime
from typing import TypeVar
from uuid import uuid4

from backend.modules.accounts.models import Principal

from .models import HistoryEntry, LibraryItem, SavedSearch, ValidationException
from .schemas import (
    HistoryEntry as HistoryEntryDTO,
)
from .schemas import (
    LibraryItemCreateDTO,
    LibraryItemDTO,
    LibraryItemMeta,
    PageParams,
    SavedSearchCreateDTO,
    SavedSearchDTO,
)

# SEC-5 bounds (BR-L8 / brief §4) -------------------------------------------------------------
MAX_QUERY_LEN = 500
MAX_LABEL_LEN = 200
MAX_ARXIV_LEN = 64
DEFAULT_PAGE_LIMIT = 20
MAX_PAGE_LIMIT = 100

# arXiv ID forms: modern (YYMM.NNNNN[vN]) and legacy (archive[.SS]/NNNNNNN[vN]).
_ARXIV_NEW = re.compile(r"^\d{4}\.\d{4,5}(v\d+)?$")
_ARXIV_LEGACY = re.compile(r"^[a-z][a-z\-]*(\.[A-Z]{2})?/\d{7}(v\d+)?$")

# Keyset cursor key: (sort_instant, id). Pages are most-recent-first.
CursorKey = tuple[datetime, str]


# ── Normalization (BR-L1) ────────────────────────────────────────────────────
def normalize_query(query: str) -> str:
    """NFC → strip → collapse internal whitespace → casefold. The dedup identity for saved
    searches (BR-L1) and a stable basis for the history dedupe key."""
    nfc = unicodedata.normalize("NFC", query)
    collapsed = re.sub(r"\s+", " ", nfc).strip()
    return collapsed.casefold()


def normalize_arxiv_id(arxiv_id: str) -> str:
    """NFC + strip; preserves the display form (incl. version). The library idempotency key
    component (BR-L3)."""
    return unicodedata.normalize("NFC", arxiv_id).strip()


def dedupe_key(owner_id: str, request_id: str, query: str) -> str:
    """Deterministic exactly-once key for at-least-once history delivery (BR-L7/INV-L3)."""
    basis = f"{owner_id}|{request_id}|{query}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


# ── SEC-5 validators ─────────────────────────────────────────────────────────
def validate_query(query: str) -> str:
    q = query.strip() if query is not None else ""
    if not q:
        raise ValidationException("query must not be empty")
    if len(query) > MAX_QUERY_LEN:
        raise ValidationException(f"query exceeds {MAX_QUERY_LEN} characters")
    return q


def validate_label(label: str | None) -> str | None:
    if label is None:
        return None
    if len(label) > MAX_LABEL_LEN:
        raise ValidationException(f"label exceeds {MAX_LABEL_LEN} characters")
    stripped = label.strip()
    return stripped or None


def validate_arxiv_id(arxiv_id: str) -> str:
    norm = normalize_arxiv_id(arxiv_id)
    if not norm or len(norm) > MAX_ARXIV_LEN:
        raise ValidationException("invalid arXiv id length")
    if not (_ARXIV_NEW.match(norm) or _ARXIV_LEGACY.match(norm)):
        raise ValidationException("invalid arXiv id format")
    return norm


def validate_limit(limit: int | None) -> int:
    if limit is None:
        return DEFAULT_PAGE_LIMIT
    if limit < 1:
        raise ValidationException("limit must be >= 1")
    if limit > MAX_PAGE_LIMIT:
        raise ValidationException(f"limit exceeds the maximum page size of {MAX_PAGE_LIMIT}")
    return limit


def validate_meta(meta: object) -> LibraryItemMeta:
    """Validate the wire ``meta`` (Any) against the refined ``LibraryItemMeta`` shape (BR-L5)."""
    try:
        if isinstance(meta, LibraryItemMeta):
            return meta
        return LibraryItemMeta.model_validate(meta)
    except Exception as exc:  # pydantic ValidationError → generalized SEC-5 422
        raise ValidationException(f"invalid library item meta: {exc}") from exc


# ── Cursor codec (BR-L8 — opaque keyset cursor) ──────────────────────────────
def encode_cursor(key: CursorKey) -> str:
    instant, item_id = key
    payload = json.dumps({"ts": instant.isoformat(), "id": item_id}, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")


def decode_cursor(cursor: str | None) -> CursorKey | None:
    if cursor is None:
        return None
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii"))
        obj = json.loads(raw)
        return datetime.fromisoformat(obj["ts"]), str(obj["id"])
    except Exception as exc:  # tampered / garbage cursor → 422 (not a 500)
        raise ValidationException("invalid pagination cursor") from exc


# ── Entity → DTO mapping (SEC-9: internal fields never serialized) ────────────
def to_saved_dto(entity: SavedSearch) -> SavedSearchDTO:
    return SavedSearchDTO(
        id=entity.id, query=entity.query, label=entity.label, createdAt=entity.created_at
    )


def to_library_dto(entity: LibraryItem) -> LibraryItemDTO:
    return LibraryItemDTO(
        id=entity.id,
        arXivId=entity.arxiv_id,
        meta=entity.meta.model_dump(exclude_none=True),
        addedAt=entity.added_at,
    )


def to_history_dto(entity: HistoryEntry) -> HistoryEntryDTO:
    return HistoryEntryDTO(
        id=entity.id,
        query=entity.query,
        executedAt=entity.executed_at,
        resultCount=entity.result_count,
    )


# ── Keyset pagination assembly (BR-L8) ────────────────────────────────────────
_E = TypeVar("_E")
_P = TypeVar("_P")


def build_page(
    list_page: Callable[[str, int, CursorKey | None], list[_E]],
    owner_id: str,
    params: PageParams,
    key_of: Callable[[_E], CursorKey],
    to_dto: Callable[[_E], object],
    page_ctor: Callable[..., _P],
) -> _P:
    """Assemble a most-recent-first page DTO. Fetches ``limit + 1`` rows to detect a further
    page, trims to ``limit``, and emits ``nextCursor`` only when more rows remain (BR-L8).
    Validation errors (bad limit / tampered cursor) raise ``ValidationException`` → 422.
    """
    limit = validate_limit(params.limit)
    after = decode_cursor(params.cursor)
    rows = list_page(owner_id, limit + 1, after)
    has_more = len(rows) > limit
    rows = rows[:limit]
    items = [to_dto(r) for r in rows]
    next_cursor = encode_cursor(key_of(rows[-1])) if (has_more and rows) else None
    return page_ctor(items=items, nextCursor=next_cursor)


class UserDataDTOAndValidation:
    @staticmethod
    def validate_and_map(
        dto: SavedSearchCreateDTO | LibraryItemCreateDTO,
        principal: Principal,
    ) -> SavedSearch | LibraryItem:
        if isinstance(dto, SavedSearchCreateDTO):
            query = validate_query(dto.query)
            label = validate_label(dto.label)
            normalized = normalize_query(query)
            return SavedSearch(
                id=str(uuid4()),
                owner_id=principal.user_id,
                query=query,
                normalized_query=normalized,
                label=label,
            )
        elif isinstance(dto, LibraryItemCreateDTO):
            arxiv_id = validate_arxiv_id(dto.arXivId)
            meta = validate_meta(dto.meta)
            return LibraryItem(
                id=str(uuid4()),
                owner_id=principal.user_id,
                arxiv_id=arxiv_id,
                meta=meta,
            )
        else:
            raise ValidationException("Unsupported DTO type")
