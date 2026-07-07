"""PR #338 리뷰 Blocking #1, #2 — evidence와 research가 물리적으로 분리된 테이블을
쓰는지, 비동기 job_id 폴링이 완료 후에도 동작하는지 실제 SQL 엔진으로 검증한다.

기존 테스트 대부분이 InMemory 저장소(서로 별개의 Python dict)를 쓰기 때문에 이
버그(물리 테이블 공유로 인한 오염)를 원천적으로 재현할 수 없었다 — 그래서 리뷰
전까지 발견되지 못했다.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from docsuri_shared._generated.dtos.evidence_schema import EvidenceCoverage, EvidenceResult

from backend.db import make_engine, make_session_factory
from backend.modules.evidence.models import (
    EvidenceSession,
    EvidenceTurn,
    TurnPendingResult,
    TurnSuccessResult,
)
from backend.modules.evidence.repository import Base as EvidenceBase
from backend.modules.evidence.repository import SqlEvidenceRepository
from backend.modules.research.models import ResearchJob
from backend.modules.research.repository import Base as ResearchBase
from backend.modules.research.repository import SqlResearchRepository


@pytest.fixture
def session():
    engine = make_engine('sqlite://')
    EvidenceBase.metadata.create_all(engine)
    ResearchBase.metadata.create_all(engine)
    factory = make_session_factory(engine)
    s = factory()
    yield s
    s.close()


def test_evidence_session_does_not_leak_into_research_jobs(session) -> None:
    owner_id = str(uuid4())
    research_repo = SqlResearchRepository(session)
    evidence_repo = SqlEvidenceRepository(session)

    evidence_repo.create_session(EvidenceSession(owner_id=owner_id))
    session.commit()

    assert research_repo.list_jobs(owner_id) == []


def test_evidence_soft_delete_does_not_break_research_job_state_parsing(session) -> None:
    """PR #338 Blocking #1 — evidence의 status='deleted'가 ResearchJobState(DELETED
    없음)를 깨뜨리던 문제. 물리적으로 분리된 테이블이면 애초에 이 값이 research 쪽
    파싱 경로에 들어갈 일이 없다."""
    owner_id = str(uuid4())
    research_repo = SqlResearchRepository(session)
    evidence_repo = SqlEvidenceRepository(session)

    ev_session = evidence_repo.create_session(EvidenceSession(owner_id=owner_id))
    session.commit()
    evidence_repo.soft_delete_session(owner_id, ev_session.session_id)
    session.commit()

    # 예전엔 여기서 ResearchJobState('deleted') ValueError가 났다.
    assert research_repo.list_jobs(owner_id) == []


def test_research_job_still_works_independently(session) -> None:
    owner_id = str(uuid4())
    research_repo = SqlResearchRepository(session)
    evidence_repo = SqlEvidenceRepository(session)

    evidence_repo.create_session(EvidenceSession(owner_id=owner_id))
    job = research_repo.create_job(ResearchJob(ownerId=owner_id, title='test job'))
    session.commit()

    jobs = research_repo.list_jobs(owner_id)
    assert len(jobs) == 1
    assert jobs[0].jobId == job.jobId


def test_job_id_polling_works_after_turn_completes(session) -> None:
    """PR #338 Blocking #2 — job_id가 TurnPendingResult 안에만 있으면 완료 후
    get_turn_by_job_id가 영원히 404가 되던 문제."""
    owner_id = str(uuid4())
    job_id = str(uuid4())
    evidence_repo = SqlEvidenceRepository(session)

    ev_session = evidence_repo.create_session(EvidenceSession(owner_id=owner_id))
    turn = EvidenceTurn(
        session_id=ev_session.session_id,
        job_id=job_id,
        result=TurnPendingResult(job_id=job_id),
    )
    evidence_repo.add_turn(turn)
    session.commit()

    # 완료 전: pending 상태에서 조회 가능
    assert evidence_repo.get_turn_by_job_id(owner_id, job_id).turn_id == turn.turn_id

    evidence_repo.update_turn_result(
        owner_id, turn.turn_id,
        TurnSuccessResult(
            outcome=EvidenceResult(state='ok', claims=[], coverage=EvidenceCoverage(paperCount=0))
        ),
    )
    session.commit()

    # 완료 후: 예전엔 여기서 KeyError(404)가 났다.
    resolved = evidence_repo.get_turn_by_job_id(owner_id, job_id)
    assert resolved.turn_id == turn.turn_id
    assert isinstance(resolved.result, TurnSuccessResult)
