"""API↔client DTOs (dtos.md). Generated from ``shared/dtos/*.schema.json``.

Re-exported here under their canonical contract names so consumers import
``docsuri_shared.dtos`` and never reach into ``_generated`` (which is codegen-owned).

Producers: U2 (search), U3 (accounts), U4 (library). Consumer: U5.
SEC-9/SEC-8/SEC-12 invariants (no internal fields, no owner userId in bodies,
password input-only) are enforced by the schemas (``additionalProperties: false`` ⇒
pydantic ``extra='forbid'``) and checked by ``tests/test_security_invariants.py``.

Exception (FR-29/BR-A12): the U3 public-auth INPUT DTOs — SignupRequest, LoginRequest,
PasswordResetRequest, PasswordResetConfirm — intentionally use ``additionalProperties: true``
(pydantic default ``extra='ignore'``) so a stray body field from front/back version skew is
ignored instead of 422-ing the whole auth flow. Their RESPONSE DTOs stay ``extra='forbid'``.
"""

from __future__ import annotations

# U3 — Accounts/Auth (accounts.schema.json)
from ._generated.dtos.accounts_schema import (
    LoginRequest,
    PasswordResetConfirm,
    PasswordResetRequest,
    SessionInfo,
    SignupRequest,
    SignupResult,
)

# DocModel pivot (docmodel.schema.json) — U1 producer / U7 + rich-view consumers.
# The doc-model AssetRef is a distinct shape (no runtime `url`), so it is re-exported
# under an explicit alias to avoid clobbering the summarization AssetRef above.
from ._generated.dtos.docmodel_schema import (
    AssetRef as DocModelAssetRef,
)
from ._generated.dtos.docmodel_schema import (
    Block,
    BuildingDTO,
    CodeBlock,
    DocModel,
    DocModelMeta,
    DocModelRequest,
    DocModelResponse,
    DocModelResultDTO,
    FigureBlock,
    FormulaBlock,
    ListBlock,
    ListItem,
    ParagraphBlock,
    Provenance,
    Section,
    SourceTier,
    SourceUnavailableDTO,
    TableBlock,
    TableCell,
    TableRow,
)
from ._generated.dtos.docmodel_schema import (
    LicenseUnavailableDTO as DocModelLicenseUnavailableDTO,
)

# U4 — Saved searches / Library / History (library.schema.json)
from ._generated.dtos.library_schema import (
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

# U10 — My Page subscription (mypage.schema.json, mock — no real PG/billing)
from ._generated.dtos.mypage_schema import (
    SubscriptionDTO,
    SubscriptionPlan,
    SubscriptionStatusValue,
)

# U2 — Discovery/Search (search.schema.json)
from ._generated.dtos.search_schema import (
    AbstainDTO,
    DegradationMode,
    DegradedResultDTO,
    ResultCardVM,
    ResultMeta,
    SearchRequest,
    SearchResponse,
    SearchResultPageDTO,
    ValidationErrorDTO,
)

# U7 — Summarization (summarization.schema.json)
from ._generated.dtos.summarization_schema import (
    Anchor,
    AnchorTarget,
    AssetRef,
    PaperAssetsResponse,
    Persona,
    Reproducibility,
    SummarizeScope,
    SummarizeTask,
    SummaryDraft,
    SummaryRequest,
    SummaryResponse,
    SummaryResultDTO,
    TranslationDraft,
)

__all__ = [
    # search
    "SearchRequest",
    "SearchResponse",
    "SearchResultPageDTO",
    "AbstainDTO",
    "DegradedResultDTO",
    "ValidationErrorDTO",
    "ResultCardVM",
    "ResultMeta",
    "DegradationMode",
    # accounts
    "SignupRequest",
    "SignupResult",
    "LoginRequest",
    "SessionInfo",
    "PasswordResetRequest",
    "PasswordResetConfirm",
    # library
    "PageParams",
    "SavedSearchCreateDTO",
    "SavedSearchDTO",
    "SavedSearchPageDTO",
    "LibraryItemCreateDTO",
    "LibraryItemDTO",
    "LibraryPageDTO",
    "HistoryEntry",
    "HistoryPageDTO",
    "SearchResultSetDTO",
    # summarization
    "SummaryRequest",
    "SummaryResponse",
    "SummaryResultDTO",
    "SummaryDraft",
    "TranslationDraft",
    "Anchor",
    "AnchorTarget",
    "Persona",
    "SummarizeScope",
    "SummarizeTask",
    "Reproducibility",
    # summarization — FR-17 figure/table assets
    "AssetRef",
    "PaperAssetsResponse",
    # doc-model pivot (docmodel.schema.json)
    "DocModel",
    "DocModelMeta",
    "DocModelRequest",
    "DocModelResponse",
    "DocModelResultDTO",
    "BuildingDTO",
    "SourceUnavailableDTO",
    "DocModelLicenseUnavailableDTO",
    "Provenance",
    "SourceTier",
    "Section",
    "Block",
    "ParagraphBlock",
    "TableBlock",
    "TableRow",
    "TableCell",
    "FormulaBlock",
    "FigureBlock",
    "ListBlock",
    "ListItem",
    "CodeBlock",
    "DocModelAssetRef",
    # mypage (mypage.schema.json, mock subscription)
    "SubscriptionDTO",
    "SubscriptionPlan",
    "SubscriptionStatusValue",
]
