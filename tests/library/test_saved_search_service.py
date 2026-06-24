"""U4 — SavedSearchService unit tests (US-L1/FR-8): dedup, quota, owner-scoping, rerun."""

from __future__ import annotations

import pytest

from backend.modules.library.models import NotFoundError, QuotaExceededError, ValidationException
from backend.modules.library.schemas import SavedSearchCreateDTO
from backend.modules.library.services import saved_search as ss_mod


def test_save_returns_dto_with_aware_timestamp(make_services, make_principal):
    saved, _lib, _hist, _repo, _audit = make_services()
    p = make_principal()
    dto = saved.save(p, SavedSearchCreateDTO(query="diffusion models", label="gen"))
    assert dto.query == "diffusion models"
    assert dto.label == "gen"
    assert dto.createdAt.tzinfo is not None  # timezone-aware (BR style)


def test_save_is_idempotent_on_normalized_query(make_services, make_principal):
    """BR-L1: re-saving the same query (after NFC/trim/collapse/casefold) returns the same row."""
    saved, _l, _h, _repo, _a = make_services()
    p = make_principal()
    a = saved.save(p, SavedSearchCreateDTO(query="Transformer  Attention"))
    b = saved.save(p, SavedSearchCreateDTO(query="  transformer attention ", label="relabel"))
    assert a.id == b.id  # deduped
    assert b.label == "relabel"  # label updated in place


def test_save_enforces_quota(make_services, make_principal, monkeypatch):
    """BR-L2: per-owner cap → QuotaExceededError."""
    monkeypatch.setattr(ss_mod, "MAX_SAVED_PER_OWNER", 2)
    saved, _l, _h, _repo, _a = make_services()
    p = make_principal()
    saved.save(p, SavedSearchCreateDTO(query="q1"))
    saved.save(p, SavedSearchCreateDTO(query="q2"))
    with pytest.raises(QuotaExceededError):
        saved.save(p, SavedSearchCreateDTO(query="q3"))


def test_empty_query_rejected(make_services, make_principal):
    saved, _l, _h, _repo, _a = make_services()
    p = make_principal()
    with pytest.raises(ValidationException):
        saved.save(p, SavedSearchCreateDTO(query="   "))


def test_overlong_query_rejected(make_services, make_principal):
    saved, _l, _h, _repo, _a = make_services()
    p = make_principal()
    with pytest.raises(ValidationException):
        saved.save(p, SavedSearchCreateDTO(query="x" * 501))


def test_list_is_owner_scoped(make_services, make_principal):
    """INV-L1: a list never returns another owner's rows (shared repo, two owners)."""
    saved, _l, _h, repo, _a = make_services()
    a, b = make_principal(), make_principal()
    saved.save(a, SavedSearchCreateDTO(query="alpha"))
    saved.save(b, SavedSearchCreateDTO(query="beta"))
    from backend.modules.library.schemas import PageParams

    page_a = saved.list(a, PageParams(limit=10))
    assert len(page_a.items) == 1
    assert page_a.items[0].query == "alpha"


def test_delete_cross_owner_is_generalized_notfound(make_services, make_principal):
    """SEC-9/INV-L4: deleting another owner's row → NotFound (existence not disclosed)."""
    saved, _l, _h, _repo, _a = make_services()
    owner, attacker = make_principal(), make_principal()
    created = saved.save(owner, SavedSearchCreateDTO(query="private"))
    with pytest.raises(NotFoundError):
        saved.delete(attacker, created.id)
    # still present for the real owner
    saved.delete(owner, created.id)  # no raise


def test_delete_missing_is_notfound(make_services, make_principal):
    saved, _l, _h, _repo, _a = make_services()
    p = make_principal()
    with pytest.raises(NotFoundError):
        saved.delete(p, "00000000-0000-0000-0000-000000000000")


@pytest.mark.asyncio
async def test_rerun_goes_through_gateway(make_services, make_principal):
    """INV-L2: rerun returns the gateway-fronted search result (stub → empty page)."""
    saved, _l, _h, _repo, _a = make_services()
    p = make_principal()
    created = saved.save(p, SavedSearchCreateDTO(query="rerun me"))
    result = await saved.rerun(p, created.id)
    assert result.root.meta.resultCount == 0  # stub gateway returns an empty page


@pytest.mark.asyncio
async def test_rerun_cross_owner_notfound(make_services, make_principal):
    saved, _l, _h, _repo, _a = make_services()
    owner, attacker = make_principal(), make_principal()
    created = saved.save(owner, SavedSearchCreateDTO(query="x"))
    with pytest.raises(NotFoundError):
        await saved.rerun(attacker, created.id)


def test_audit_owner_ref_is_masked(make_services, make_principal):
    import hashlib
    saved, _l, _h, _repo, audit = make_services()
    p = make_principal()
    saved.save(p, SavedSearchCreateDTO(query="audit test"))
    
    events = audit.events
    assert len(events) > 0
    event = events[-1]
    expected_hash = hashlib.sha256(p.user_id.encode("utf-8")).hexdigest()
    assert event.owner_ref == expected_hash
    assert event.owner_ref != p.user_id
