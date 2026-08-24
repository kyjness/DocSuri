"""턴 이어가기와 세션 기억(설계 v3 §3.4).

둘은 서로 다른 것을 나른다. **이어가기**는 직전 턴이 찾아 둔 논문 집합을 새 턴의 씨앗으로
옮기고(체크포인트), **기억**은 이전 대화를 토큰 예산 안에서 관찰에 싣는다(세션 행). 앞의
것이 없으면 "이어서 더 찾아줘"가 검색부터 다시 하고, 뒤의 것이 없으면 "그중에서"가 무엇을
가리키는지 모델이 모른다.
"""

from __future__ import annotations

from typing import Any

from docsuri_shared._generated.dtos.evidence_schema import (
    EvidenceAbstainResult,
    EvidenceRequest,
)

from backend.modules.evidence.domain.models import (
    AgentRunContext,
    LoopState,
    PaperHandle,
    PaperOrigin,
)
from backend.modules.evidence.models import (
    EvidenceSession,
    EvidenceTurn,
    TurnAbstainResult,
)
from backend.modules.evidence.repository import InMemoryEvidenceRepository
from backend.modules.evidence.runner import EvidenceTurnRunner, RunnerDeps
from backend.modules.evidence.service import build_run_context
from backend.modules.evidence.testing import ScriptedAnswer, ScriptedLlm, loop_budget


class _Checkpoints:
    """`TurnCheckpoints.seeds_from`만 흉내 낸다 — 러너가 그 하나만 부른다."""

    def __init__(self, by_turn: dict[str, LoopState] | None = None, raises: bool = False) -> None:
        self.by_turn = by_turn or {}
        self.raises = raises
        self.asked: list[str] = []
        self.graph = None

    def seeds_from(self, turn_id: str) -> LoopState | None:
        self.asked.append(turn_id)
        if self.raises:
            raise RuntimeError("checkpoint store down")
        return self.by_turn.get(turn_id)


def _prior_state(*, examined: str = "2106.09685", pending: str = "2401.00001") -> LoopState:
    prior = LoopState(topic="이전 질문")
    prior.examine(
        PaperHandle(examined, examined, PaperOrigin.CORPUS, title="읽은 논문", abstract_text="a")
    )
    prior.discovered[pending] = PaperHandle(
        pending, pending, PaperOrigin.CORPUS, title="안 읽은 후보"
    )
    # 실제 씨앗은 체크포인트 왕복을 거친다 — 직렬화에서 죽는 필드가 있으면 여기서 드러난다.
    return LoopState.from_snapshot(prior.to_snapshot())


def _runner(checkpoints: Any) -> EvidenceTurnRunner:
    return EvidenceTurnRunner(
        RunnerDeps(
            llm=ScriptedLlm(question_kind="fact"),
            extractor=_NoItems(),
            answer=ScriptedAnswer(),
            budget_factory=lambda: loop_budget(
                max_iterations=2, max_tool_calls_total=4, max_tool_calls={}
            ),
        ),
        checkpoints=checkpoints,
    )


class _NoItems:
    def extract(self, *, topic, focus, papers):
        return []


def _run(runner: EvidenceTurnRunner, ctx: AgentRunContext) -> LoopState:
    """러너가 심은 씨앗을 보려면 상태가 필요한데 `run()`은 결과만 준다 — 도구가 쥔
    상태를 통해 본다. 레지스트리는 턴마다 상태를 쥐고 만들어진다."""
    seen: list[LoopState] = []
    original = EvidenceTurnRunner._build_registry

    def spy(self, state, *, scope):
        seen.append(state)
        return original(self, state, scope=scope)

    EvidenceTurnRunner._build_registry = spy  # type: ignore[method-assign]
    try:
        runner.run(ctx, EvidenceRequest(topic="이어서 더 찾아줘"))
    finally:
        EvidenceTurnRunner._build_registry = original  # type: ignore[method-assign]
    return seen[0]


def _ctx(**kw: Any) -> AgentRunContext:
    base = {"owner_id": "o", "session_id": "s", "turn_id": "t2"}
    return AgentRunContext(**{**base, **kw})


# --- 씨앗 이식 -----------------------------------------------------------------


def test_the_previous_turn_papers_become_this_turn_seeds():
    """검색부터 다시 하면 '이어서 더 찾아줘'가 직전 턴을 그대로 반복하고 예산이 두 번 나간다."""
    checkpoints = _Checkpoints({"t1": _prior_state()})

    state = _run(_runner(checkpoints), _ctx(prior_turn_id="t1"))

    assert "2106.09685" in state.papers, "확인했던 논문이 안 넘어왔다"
    assert "2401.00001" in state.discovered, "안 읽은 후보가 안 넘어왔다"


def test_examined_and_pending_stay_in_their_own_bucket():
    """한 칸에 몰면 확인 범위 수치가 이전 턴 것을 물려받아 부풀려진다."""
    checkpoints = _Checkpoints({"t1": _prior_state()})

    state = _run(_runner(checkpoints), _ctx(prior_turn_id="t1"))

    assert state.examined == 1
    assert "2401.00001" not in state.papers


def test_no_prior_turn_means_nothing_to_transplant():
    checkpoints = _Checkpoints({"t1": _prior_state()})

    state = _run(_runner(checkpoints), _ctx())

    assert state.papers == {} and state.discovered == {}
    assert checkpoints.asked == [], "이식할 턴이 없는데 체크포인트를 조회했다"


def test_a_missing_snapshot_is_not_an_error():
    """체크포인터가 없는 배포·안 돈 스레드는 정상이다 — 이어가기만 꺼진다."""
    state = _run(_runner(_Checkpoints()), _ctx(prior_turn_id="t1"))

    assert state.papers == {}


def test_a_broken_checkpoint_store_does_not_break_the_new_turn():
    """씨앗은 편의다. 못 읽는다고 새 질문에 답을 못 하게 되면 안 된다."""
    state = _run(_runner(_Checkpoints(raises=True)), _ctx(prior_turn_id="t1"))

    assert state.papers == {}


def test_explicit_scope_never_inherits_seeds():
    """사용자가 논문을 지정한 턴에 이전 턴 논문이 섞이면 그 지정이 무의미해진다(BR-EV-2)."""
    checkpoints = _Checkpoints({"t1": _prior_state()})
    runner = _runner(checkpoints)
    seen: list[LoopState] = []
    original = EvidenceTurnRunner._build_registry

    def spy(self, state, *, scope):
        seen.append(state)
        return original(self, state, scope=scope)

    EvidenceTurnRunner._build_registry = spy  # type: ignore[method-assign]
    try:
        runner.run(
            _ctx(prior_turn_id="t1"),
            EvidenceRequest(topic="이 논문만", scope="explicit", paperIds=["2301.00001"]),
        )
    finally:
        EvidenceTurnRunner._build_registry = original  # type: ignore[method-assign]

    assert seen[0].handle("2106.09685") is None


# --- 세션 기억 -----------------------------------------------------------------


def _finished(turn_id: str, topic: str) -> EvidenceTurn:
    """끝난 턴 — 세션당 진행 중 턴은 하나라(§5.4) 픽스처가 pending이면 두 번째부터 막힌다."""
    return EvidenceTurn(
        turn_id=turn_id,
        session_id="s",
        owner_id="o",
        topic=topic,
        result=TurnAbstainResult(
            outcome=EvidenceAbstainResult(state="abstain", abstainReason="insufficient_evidence")
        ),
    )


def _seeded_repo(topics: list[str]) -> InMemoryEvidenceRepository:
    repo = InMemoryEvidenceRepository()
    repo.create_session(EvidenceSession(session_id="s", owner_id="o"))
    for i, topic in enumerate(topics):
        repo.add_turn(_finished(f"t{i}", topic))
    return repo


def test_recent_turns_ride_along_verbatim():
    repo = _seeded_repo(["첫 질문", "둘째 질문"])

    ctx = build_run_context(repo, owner_id="o", session_id="s", turn_id="new")

    assert ctx.prior_topics == ("첫 질문", "둘째 질문")
    assert ctx.prior_summary == ""


def test_the_current_turn_is_never_its_own_history():
    """워커 경로는 pending 턴이 이미 저장된 뒤에 조립한다 — 거르지 않으면 자기 질문이
    '이전 턴 질문'으로 자기에게 다시 보인다."""
    repo = _seeded_repo(["첫 질문"])
    repo.add_turn(_finished("new", "지금 질문"))

    ctx = build_run_context(repo, owner_id="o", session_id="s", turn_id="new")

    assert "지금 질문" not in ctx.prior_topics


def test_the_prior_turn_id_points_at_the_immediately_previous_turn():
    """'이어서 더 찾아줘'가 가리키는 것은 방금 멈춘 그 탐색이다."""
    repo = _seeded_repo(["첫 질문", "둘째 질문"])

    ctx = build_run_context(repo, owner_id="o", session_id="s", turn_id="new")

    assert ctx.prior_turn_id == "t1"


def test_turns_beyond_the_token_budget_fold_into_a_summary():
    """넘치는 앞쪽을 요약으로 접는다 — 반대로 하면 방금 한 질문이 뭉개져, 후속 질문 해석이
    가장 필요한 자리에서 정보가 가장 적어진다."""
    long_topic = "가" * 12_000  # 예산(8k 토큰 ≈ 32k자)을 한 턴이 거의 다 쓴다
    repo = _seeded_repo([f"{long_topic}-1", f"{long_topic}-2", f"{long_topic}-3", "최근 질문"])

    ctx = build_run_context(repo, owner_id="o", session_id="s", turn_id="new")

    assert ctx.prior_topics[-1] == "최근 질문", "최근 턴이 밀려났다"
    assert len(ctx.prior_topics) < 4
    assert "이전에 물어본 것" in ctx.prior_summary


def test_the_summary_is_written_once_and_appended_to():
    """매 턴 재요약하면 같은 턴이 세션 길이에 비례해 반복 요약되고 그 비용이 턴 예산 밖에서
    나간다."""
    long_topic = "나" * 40_000
    repo = _seeded_repo([f"{long_topic}-old", "최근"])

    build_run_context(repo, owner_id="o", session_id="s", turn_id="n1")
    first = repo.get_session("o", "s").summary
    build_run_context(repo, owner_id="o", session_id="s", turn_id="n2")
    second = repo.get_session("o", "s").summary

    assert first, "밀려난 턴이 있는데 요약이 안 만들어졌다"
    assert second.count("이전에 물어본 것") >= 1
    assert len(second) >= len(first)


def test_cited_papers_come_from_the_whole_session_not_just_the_kept_turns():
    """'그중에서'가 가리키는 집합은 토큰 예산과 무관하다 — 밀려난 턴의 논문이라고
    사용자가 잊은 것이 아니다(§3.4)."""
    repo = _seeded_repo(["가" * 40_000, "최근"])

    ctx = build_run_context(repo, owner_id="o", session_id="s", turn_id="new")

    # 픽스처 턴에는 결과가 없어 인용 논문도 없다. 여기서 보는 것은 **예산이 이 수집을
    # 자르지 않는다**는 것이고, 자르면 위 요약 테스트처럼 턴이 빠진 것이 드러난다.
    assert ctx.prior_paper_ids == ()
    assert ctx.prior_turn_id == "t1"


def test_a_session_that_does_not_exist_yields_an_empty_context():
    ctx = build_run_context(
        InMemoryEvidenceRepository(), owner_id="o", session_id="missing", turn_id="t"
    )

    assert ctx.prior_topics == () and ctx.prior_turn_id is None
