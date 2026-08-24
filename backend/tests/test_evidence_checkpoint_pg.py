"""실 Postgres 게이트 — 체크포인터·트레이스 가시성·세션 잠금(v3 §5).

인메모리 repo는 객체를 공유해서 세 가지를 증명할 수 없다: (1) 실행자가 flush만 한 행은
다른 세션에서 안 보인다 — 이벤트 스트림의 원천이 빈다, (2) 부분 유니크 인덱스가 pending
턴 둘을 막는다, (3) saver가 thread_id=turn_id로 스냅샷을 쓰고 읽고 지운다.

`DOCSURI_TEST_PG_DSN`이 없으면 skip — CI backend 레인은 서비스 컨테이너로 연다.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from docsuri_shared._generated.dtos.evidence_schema import (
    AnchorType,
    EvidenceAbstainResult,
    EvidenceItem,
)

from backend.db import make_engine, make_session_factory
from backend.modules.evidence.checkpoints import TurnCheckpoints, build_postgres_checkpointer
from backend.modules.evidence.domain.loop import LoopDeps, load_snapshot, run_loop
from backend.modules.evidence.domain.models import (
    AgentRunContext,
    LoopBudget,
    LoopState,
    TerminationReason,
    ToolCallOutcome,
    ToolCallRecord,
)
from backend.modules.evidence.models import (
    EvidenceSession,
    EvidenceTurn,
    TurnAbstainResult,
    TurnPendingResult,
    TurnSuccessResult,
)
from backend.modules.evidence.ports.llm import ToolCallProposal
from backend.modules.evidence.ports.tools import (
    TOOL_CORPUS_SEARCH,
    ToolRegistry,
    ToolResult,
    ToolSpec,
)
from backend.modules.evidence.repository import (
    Base,
    SessionBusy,
    SqlEvidenceRepository,
)
from backend.modules.evidence.testing import ScriptedLlm, evidence_item, loop_budget
from backend.modules.evidence.worker import process_job

DSN = os.environ.get("DOCSURI_TEST_PG_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="set DOCSURI_TEST_PG_DSN to a test Postgres")


@pytest.fixture(scope="module")
def pg():
    engine = make_engine(DSN)
    Base.metadata.create_all(engine)
    saver, close = build_postgres_checkpointer(DSN, setup=True)
    # setup은 멱등이어야 한다 — API·워커가 각자 부팅하며 부른다.
    saver.setup()
    yield engine, make_session_factory(engine), saver
    close()
    engine.dispose()


@pytest.fixture
def owner(pg):
    engine, _, saver = pg
    owner_id = str(uuid4())
    yield owner_id
    from sqlalchemy import text

    with engine.begin() as conn:
        turn_ids = [
            str(r[0]) for r in conn.execute(
                text("SELECT turn_id FROM evidence_turns WHERE owner_id = :o"), {"o": owner_id}
            )
        ]
        # ORM create_all에는 FK CASCADE가 없다(마이그레이션에만 있다) — 자식부터 지운다.
        conn.execute(text("DELETE FROM evidence_trace WHERE owner_id = :o"), {"o": owner_id})
        conn.execute(text("DELETE FROM evidence_turns WHERE owner_id = :o"), {"o": owner_id})
        conn.execute(text("DELETE FROM evidence_sessions WHERE owner_id = :o"), {"o": owner_id})
    for turn_id in turn_ids:
        saver.delete_thread(turn_id)


class _Tool:
    name = TOOL_CORPUS_SEARCH
    spec = ToolSpec(name=TOOL_CORPUS_SEARCH, description="s", parameters={"type": "object"})

    def __init__(self, on_invoke=None) -> None:
        self.on_invoke = on_invoke

    def invoke(self, args, ctx):
        if self.on_invoke:
            self.on_invoke()
        return ToolResult(ok=True, content={"hits": 1})


def _llm(calls: int) -> ScriptedLlm:
    """검색을 `calls`번 제안한 뒤 종료한다."""
    return ScriptedLlm(
        script=[ToolCallProposal(tool_name=TOOL_CORPUS_SEARCH, args={"q": "a"})] * calls
    )


def _item() -> EvidenceItem:
    return evidence_item("s", record_ref="r1", anchor="a", quote="q",
                         anchor_type=AnchorType.paragraph)


def _budget() -> LoopBudget:
    return loop_budget(max_iterations=5, max_tool_calls_total=10,
                       max_tool_calls={TOOL_CORPUS_SEARCH: 5})


def _seed(session_factory, owner_id: str) -> tuple[str, str]:
    repo = SqlEvidenceRepository(session_factory())
    session = repo.create_session(EvidenceSession(owner_id=owner_id))
    turn = EvidenceTurn(session_id=session.session_id, owner_id=owner_id, topic="q",
                        result=TurnPendingResult())
    repo.add_turn(turn)
    repo.commit()
    repo.close()
    return session.session_id, turn.turn_id


def test_checkpointer_writes_reads_and_deletes_the_turn_thread(pg, owner):
    _, _, saver = pg
    turn_id = str(uuid4())
    registry = ToolRegistry()
    registry.register(_Tool())
    state = LoopState(topic="q")
    state.accumulator.items.append(_item())
    deps = LoopDeps(llm=_llm(2), registry=registry, budget=_budget(),
                    ctx=AgentRunContext(owner_id=owner, session_id="s", turn_id=turn_id))
    checkpoints = TurnCheckpoints(saver)

    outcome = run_loop(state, deps, graph=checkpoints.graph)

    assert outcome.reason is TerminationReason.SUFFICIENT
    assert checkpoints.enabled
    snapshot = load_snapshot(checkpoints.graph, turn_id)
    assert snapshot is not None
    assert len(snapshot["trace"]) == 2
    assert snapshot["termination_reason"] == "sufficient"

    finalized = checkpoints.finalize(turn_id, "q")
    assert isinstance(finalized, TurnSuccessResult)
    assert finalized.outcome.coverage.stoppedReason.value == "partial_failure"

    assert checkpoints.delete([turn_id]) == 1
    assert load_snapshot(checkpoints.graph, turn_id) is None
    assert checkpoints.finalize(turn_id, "q") is None


def test_trace_rows_are_visible_to_another_session_mid_turn(pg, owner):
    """이벤트 스트림의 전제 — 실행자가 커밋한 행을 API 세션이 턴이 끝나기 전에 본다."""
    _, session_factory, _ = pg
    session_id, turn_id = _seed(session_factory, owner)
    seen_mid_turn: list[int] = []
    heartbeat_mid_turn: list = []

    class _Runner:
        has_checkpointer = False

        def run(self, ctx, request, *, attachments=(), on_trace=None, should_stop=None):
            on_trace(ToolCallRecord(seq=1, tool="corpus_search", args_summary="q=a",
                                    outcome=ToolCallOutcome.OK))
            should_stop()  # 하트비트 1회
            other = SqlEvidenceRepository(session_factory())  # API 프로세스 역할
            try:
                seen_mid_turn.extend(r["seq"] for r in other.list_trace_after(owner, turn_id, 0))
                heartbeat_mid_turn.append(other.get_turn(owner, turn_id).heartbeat_at)
            finally:
                other.close()
            return TurnAbstainResult(
                outcome=EvidenceAbstainResult(state="abstain", abstainReason="out_of_corpus")
            )

    process_job(lambda: SqlEvidenceRepository(session_factory()), runner=_Runner(),
                owner_id=owner, session_id=session_id, turn_id=turn_id, topic="q")

    assert seen_mid_turn == [1]
    assert heartbeat_mid_turn[0] is not None
    repo = SqlEvidenceRepository(session_factory())
    try:
        assert isinstance(repo.get_turn(owner, turn_id).result, TurnAbstainResult)
        assert repo.active_turn(owner, session_id) is None
    finally:
        repo.close()


def test_second_pending_turn_in_a_session_is_rejected_by_the_index(pg, owner):
    _, session_factory, _ = pg
    session_id, _ = _seed(session_factory, owner)
    repo = SqlEvidenceRepository(session_factory())
    try:
        with pytest.raises(SessionBusy):
            repo.add_turn(EvidenceTurn(session_id=session_id, owner_id=owner, topic="q2",
                                       result=TurnPendingResult()))
    finally:
        repo.close()


def test_cancel_flag_round_trips_through_the_row(pg, owner):
    _, session_factory, _ = pg
    session_id, turn_id = _seed(session_factory, owner)
    api = SqlEvidenceRepository(session_factory())
    executor = SqlEvidenceRepository(session_factory())
    try:
        assert executor.heartbeat(owner, turn_id) is False
        executor.commit()
        assert api.request_cancel(owner, turn_id) is True
        api.commit()
        assert executor.heartbeat(owner, turn_id) is True  # READ COMMITTED: 커밋된 플래그
        executor.commit()
        far_future = datetime.now(UTC) + timedelta(days=1)
        assert turn_id not in api.expired_turn_ids(far_future)  # pending은 정리 대상이 아니다
        # 남의 턴은 하트비트도 못 찍는다(INV-EV-1) — super-step마다 부르는 유일한 메서드다.
        with pytest.raises(KeyError):
            executor.heartbeat(str(uuid4()), turn_id)
    finally:
        api.close()
        executor.close()


def test_prune_marker_advances_so_the_same_turns_are_not_deleted_forever(pg, owner):
    """도장이 없으면 앞쪽 N건만 영원히 재삭제되고 그 뒤 턴은 영영 안 지워진다."""
    _, session_factory, _ = pg
    session_id, _ = _seed(session_factory, owner)
    repo = SqlEvidenceRepository(session_factory())
    finished: list[str] = []
    try:
        for i in range(3):
            turn = EvidenceTurn(
                session_id=session_id, owner_id=owner, topic=f"q{i}",
                result=TurnAbstainResult(
                    outcome=EvidenceAbstainResult(state="abstain", abstainReason="out_of_corpus")
                ),
            )
            turn.created_at = turn.created_at - timedelta(days=30)
            repo.add_turn(turn)
            finished.append(turn.turn_id)
        repo.commit()

        first = repo.expired_turn_ids(datetime.now(UTC) - timedelta(days=7), limit=2)
        assert len(first) == 2
        repo.mark_checkpoints_pruned(first)
        repo.commit()

        second = repo.expired_turn_ids(datetime.now(UTC) - timedelta(days=7), limit=2)
        assert second and not set(second) & set(first)   # 다음 묶음으로 넘어간다
        repo.mark_checkpoints_pruned(second)
        repo.commit()
        assert repo.expired_turn_ids(datetime.now(UTC) - timedelta(days=7)) == []
    finally:
        repo.close()
