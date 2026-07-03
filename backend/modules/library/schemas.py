"""U4 Library — wire DTOs.

The request/response DTOs are the SHARED single source of truth: U4 *imports* them from
``docsuri_shared.dtos`` (generated from ``shared/dtos/library.schema.json``) and re-exports for
local use. U4 MUST NOT redefine them — forking the SSOT is exactly the defect to avoid. The only
U4-authored type here is ``LibraryItemMeta``: the typed shape that refines the shared
``LibraryItemDTO.meta`` (which the schema declares ``Any`` and explicitly defers "to U4 FD").
Validating ``meta`` locally keeps U4 correct whether or not the regenerated bindings are
installed yet.
"""

from __future__ import annotations

from typing import Annotated

# Re-export the shared SSOT DTOs (do not fork) -------------------------------------------------
from docsuri_shared.dtos import (
    HistoryEntry,
    HistoryPageDTO,
    LibraryItemCreateDTO,
    LibraryItemDTO,
    LibraryPageDTO,
    PageParams,
    SavedSearchCreateDTO,
    SavedSearchDTO,
    SavedSearchPageDTO,
    SearchResultSetDTO,
)
from docsuri_shared.events import PaperRetractedEvent
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

__all__ = [
    "HistoryEntry",
    "HistoryPageDTO",
    "LibraryItemCreateDTO",
    "LibraryItemDTO",
    "LibraryItemMeta",
    "LibraryPageDTO",
    "PageParams",
    "PaperRetractedEvent",
    "SavedSearchCreateDTO",
    "SavedSearchDTO",
    "SavedSearchPageDTO",
    "SearchResultSetDTO",
]


class LibraryItemMeta(BaseModel):
    """Refined shape of ``LibraryItemDTO.meta`` (BR-L5). A bounded snapshot of the result card
    (mirrors the U2 ``ResultCardVM`` card fields, dtos.md §1.1) so the library renders a card
    without the live index (availability isolation, NFR-R1). SEC-5 bounds reject oversized input;
    ``extra='forbid'`` mirrors the shared-contract discipline.
    """

    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., min_length=1, max_length=500, description="Paper title (FR-4).")
    authors: list[Annotated[str, StringConstraints(max_length=200)]] = Field(
        default_factory=list,
        max_length=50,
        description="Author display names (<=50 entries, each <=200 chars). Trace: FR-4.",
    )
    year: int | None = Field(
        None, ge=1900, le=2100, description="Publication year (arXiv era). Trace: FR-4."
    )
    arxivId: str = Field(
        ..., min_length=1, max_length=64, description="Display arXiv ID (card field). Trace: FR-4."
    )
    abstractSnippet: str | None = Field(
        None, max_length=1000, description="Abstract excerpt for the card (FR-4)."
    )
    arxivUrl: str | None = Field(
        None, max_length=512, description="Resolvable arXiv link (FR-4/FR-5)."
    )
    retracted: bool = Field(
        False,
        description="True after U4 consumes PaperRetractedEvent for this paper (BR-L5).",
    )
