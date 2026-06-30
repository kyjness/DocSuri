"""SEC-8 / SEC-9 / SEC-12 invariants encoded directly against the generated models.

These pin the security shape of the contracts so a future schema edit that would leak
an internal field, an owner userId, or a password into a response fails CI loudly.
"""

from __future__ import annotations

import pytest
from conftest import valid_card_dict
from pydantic import ValidationError

from docsuri_shared import dtos

# Card may expose ONLY these fields (dtos.md §1.1 = IndexRecord card projection + relevance;
# Phase 2 Q2 adds source-neutral sourceName/sourceUrl).
CARD_ALLOWED = {
    "title", "authors", "year", "arxivId", "abstractSnippet", "relevance", "arxivUrl",
    "sourceName", "sourceUrl",
}
# Internal IndexRecord fields that must never appear on a card (SEC-9; blockRefs/sourceProvenance
# stay internal per Phase 2 Q3 — only the derived sourceName/sourceUrl are projected).
INDEX_INTERNAL = {
    "vector",
    "lexicalTerms",
    "chunkId",
    "section",
    "categories",
    "paperId",
    "version",
    "abstract",
    "blockRefs",
    "sourceProvenance",
}

RESPONSE_DTOS = [
    dtos.SearchResultPageDTO,
    dtos.AbstainDTO,
    dtos.DegradedResultDTO,
    dtos.ValidationErrorDTO,
    dtos.ResultMeta,
    dtos.ResultCardVM,
    dtos.SignupResult,
    dtos.SessionInfo,
    dtos.SavedSearchDTO,
    dtos.SavedSearchPageDTO,
    dtos.LibraryItemDTO,
    dtos.LibraryPageDTO,
    dtos.HistoryEntry,
    dtos.HistoryPageDTO,
]
U4_OWNED_ITEM_DTOS = [
    dtos.SavedSearchDTO,
    dtos.LibraryItemDTO,
    dtos.HistoryEntry,
    dtos.SavedSearchPageDTO,
    dtos.LibraryPageDTO,
    dtos.HistoryPageDTO,
]


def test_card_exposes_exactly_the_projected_fields():
    assert set(dtos.ResultCardVM.model_fields) == CARD_ALLOWED


def test_card_has_no_internal_index_fields():
    assert INDEX_INTERNAL.isdisjoint(dtos.ResultCardVM.model_fields)


def test_card_rejects_each_internal_field():
    # SEC-9: extra='forbid' must reject every internal field by name.
    for internal in INDEX_INTERNAL:
        with pytest.raises(ValidationError):
            dtos.ResultCardVM.model_validate({**valid_card_dict(), internal: "x"})


@pytest.mark.parametrize("model", U4_OWNED_ITEM_DTOS, ids=lambda m: m.__name__)
def test_owner_userId_not_in_u4_dtos(model):
    # SEC-8/SEC-9: ownership is server-enforced; owner userId is never in the body.
    assert "userId" not in model.model_fields


@pytest.mark.parametrize("model", RESPONSE_DTOS, ids=lambda m: m.__name__)
def test_no_password_in_responses(model):
    # SEC-12/SEC-3: plaintext password is request-input-only, never in a response.
    assert "password" not in model.model_fields


def test_request_dtos_carry_password_input_only():
    assert "password" in dtos.SignupRequest.model_fields
    assert "password" in dtos.LoginRequest.model_fields
