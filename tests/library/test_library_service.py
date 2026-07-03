"""U4 — LibraryService unit tests (US-L2/FR-9): idempotent add, meta snapshot, quota, scoping."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from backend.modules.library.models import NotFoundError, QuotaExceededError, ValidationException
from backend.modules.library.retraction_consumer import PaperRetractedEventConsumer
from backend.modules.library.schemas import LibraryItemCreateDTO, PageParams
from backend.modules.library.services import library as lib_mod
from docsuri_shared.events import PaperRetractedEvent

META = {
    "title": "Attention Is All You Need",
    "arxivId": "1706.03762",
    "authors": ["A"],
    "year": 2017,
}


def test_add_returns_dto_with_snapshot(make_services, make_principal):
    _s, lib, _h, _repo, _a = make_services()
    p = make_principal()
    dto = lib.add(p, LibraryItemCreateDTO(arXivId="1706.03762", meta=META))
    assert dto.arXivId == "1706.03762"
    assert dto.meta["title"] == "Attention Is All You Need"
    assert dto.meta["retracted"] is False
    assert dto.addedAt.tzinfo is not None


def test_add_is_idempotent_and_meta_is_preserved(make_services, make_principal):
    """BR-L3/QT-4: re-add returns the existing row; the original snapshot is preserved."""
    _s, lib, _h, _repo, _a = make_services()
    p = make_principal()
    first = lib.add(p, LibraryItemCreateDTO(arXivId="1706.03762", meta=META))
    second = lib.add(
        p,
        LibraryItemCreateDTO(
            arXivId="1706.03762",
            meta={"title": "DIFFERENT", "arxivId": "1706.03762"},
        ),
    )
    assert first.id == second.id
    assert second.meta["title"] == "Attention Is All You Need"  # snapshot unchanged


def test_invalid_arxiv_id_rejected(make_services, make_principal):
    _s, lib, _h, _repo, _a = make_services()
    p = make_principal()
    with pytest.raises(ValidationException):
        lib.add(p, LibraryItemCreateDTO(arXivId="not-an-id", meta=META))


def test_invalid_meta_rejected(make_services, make_principal):
    """BR-L5/SEC-5: meta missing the required title fails validation."""
    _s, lib, _h, _repo, _a = make_services()
    p = make_principal()
    with pytest.raises(ValidationException):
        lib.add(p, LibraryItemCreateDTO(arXivId="1706.03762", meta={"arxivId": "1706.03762"}))


def test_add_enforces_quota(make_services, make_principal, monkeypatch):
    monkeypatch.setattr(lib_mod, "MAX_LIBRARY_PER_OWNER", 1)
    _s, lib, _h, _repo, _a = make_services()
    p = make_principal()
    lib.add(p, LibraryItemCreateDTO(arXivId="1706.03762", meta=META))
    with pytest.raises(QuotaExceededError):
        lib.add(
            p,
            LibraryItemCreateDTO(
                arXivId="2401.00001",
                meta={**META, "arxivId": "2401.00001"},
            ),
        )


def test_remove_cross_owner_notfound(make_services, make_principal):
    _s, lib, _h, _repo, _a = make_services()
    owner, attacker = make_principal(), make_principal()
    created = lib.add(owner, LibraryItemCreateDTO(arXivId="1706.03762", meta=META))
    with pytest.raises(NotFoundError):
        lib.remove(attacker, created.id)
    lib.remove(owner, created.id)  # owner can remove


def test_legacy_arxiv_id_accepted(make_services, make_principal):
    _s, lib, _h, _repo, _a = make_services()
    p = make_principal()
    dto = lib.add(
        p,
        LibraryItemCreateDTO(
            arXivId="math.GT/0309136",
            meta={**META, "arxivId": "math.GT/0309136"},
        ),
    )
    assert dto.arXivId == "math.GT/0309136"


def test_paper_retracted_event_marks_matching_library_items(make_services, make_principal):
    _s, lib, _h, _repo, _a = make_services()
    owner, other_owner = make_principal(), make_principal()
    lib.add(
        owner,
        LibraryItemCreateDTO(
            arXivId="2401.00001v1",
            meta={**META, "arxivId": "2401.00001v1"},
        ),
    )
    lib.add(
        other_owner,
        LibraryItemCreateDTO(
            arXivId="2401.00001",
            meta={**META, "arxivId": "2401.00001"},
        ),
    )
    consumer = PaperRetractedEventConsumer(lib)

    changed = consumer.consume(
        PaperRetractedEvent(paperId="2401.00001v2", timestamp=datetime.now(UTC))
    )
    changed_again = consumer.consume(
        {"paperId": "2401.00001", "timestamp": datetime.now(UTC).isoformat()}
    )

    assert changed == 2
    assert changed_again == 0
    assert lib.list(owner, PageParams(limit=10)).items[0].meta["retracted"] is True
    assert lib.list(other_owner, PageParams(limit=10)).items[0].meta["retracted"] is True
