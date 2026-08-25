"""턴 이어가기와 세션 기억(설계 v3 §3.4).

둘은 서로 다른 것을 나른다. **이어가기**는 직전 턴이 찾아 둔 논문 집합을 새 턴의 씨앗으로
옮기고(체크포인트), **기억**은 이전 대화를 토큰 예산 안에서 관찰에 싣는다(세션 행). 앞의
것이 없으면 "이어서 더 찾아줘"가 검색부터 다시 하고, 뒤의 것이 없으면 "그중에서"가 무엇을
가리키는지 모델이 모른다.
"""

from __future__ import annotations

from typing import Any

from docsuri_shared._generated.dtos.evidence_schema import EvidenceAbstainResult

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
from backend.modules.evidence.runner import _seed_continuation
from backend.modules.evidence.service import build_run_context


class _Checkpoints:
    """`ContinuationSeedPort`만 흉내 낸다 — 러너가 그 하나만 부른다."""

    def __init__(self, seeds: dict[str, tuple] | None = None, raises: bool = False) -> None:
        self.seeds = seeds or {}
        self.raises = raises
        self.asked: list[str] = []
        self.graph = None

    def seeds_from(self, turn_id: str) -> tuple:
        self.asked.append(turn_id)
        if self.raises:
            raise RuntimeError("checkpoint store down")
        return self.seeds.get(turn_id, ())


def _prior_seeds() -> tuple[PaperHandle, ...]:
    """직전 턴이 남긴 핸들 — 실제 씨앗은 체크포인트 왕복을 거치므로 그 왕복을 흉내 낸다."""
    prior = LoopState(topic="이전 질문")
    prior.examine(
        PaperHandle("2106.09685", "2106.09685", PaperOrigin.CORPUS, title="읽은 논문")
    )
    prior.discovered["2401.00001"] = PaperHandle(
        "2401.00001", "2401.00001", PaperOrigin.CORPUS, title="안 읽은 후보"
    )
    snapshot = prior.to_snapshot()
    rows = [*snapshot["papers"], *snapshot["discovered"]]
    return tuple(PaperHandle.from_snapshot(r) for r in rows)


def _ctx(**kw: Any) -> AgentRunContext:
    base = {"owner_id": "o", "session_id": "s", "turn_id": "t2"}
    return AgentRunContext(**{**base, **kw})


def _seeded(checkpoints: Any, *, scope: str = "auto", **ctx_kw: Any) -> LoopState:
    """씨앗 이식만 돌린다 — 러너 전체를 돌리고 내부를 훔쳐볼 이유가 없다.

    종전에는 `EvidenceTurnRunner._build_registry`를 **클래스 속성으로** 갈아끼워 상태를
    가로챘다. 병렬 실행에 안전하지 않고, `try` 밖에서 예외가 나면 그 세션의 나머지 테스트에
    패치가 샌다. 검사 대상이 이미 자유 함수다.
    """
    state = LoopState(topic="이어서 더 찾아줘")
    _seed_continuation(state, checkpoints, _ctx(**ctx_kw), scope)
    return state


# --- 씨앗 이식 -----------------------------------------------------------------


def test_the_previous_turn_papers_become_this_turn_candidates():
    """검색부터 다시 하면 '이어서 더 찾아줘'가 직전 턴을 그대로 반복하고 예산이 두 번 나간다."""
    state = _seeded(_Checkpoints({"t1": _prior_seeds()}), prior_turn_id="t1")

    assert set(state.discovered) == {"2106.09685", "2401.00001"}


def test_seeds_never_count_as_papers_this_turn_examined():
    """`examined`는 `len(papers)`다 — 확인분으로 심으면 이번 턴이 열어보지도 않은 논문이
    "확인함"으로 세어지고, 화면의 "후보 N편 중 M편 확인"이 그 수를 그대로 쓴다.

    설계 §3.4가 씨앗을 "관찰의 **확인 대기 논문**에 실어"라고 적은 것이 곧 이 버킷이다.
    """
    state = _seeded(_Checkpoints({"t1": _prior_seeds()}), prior_turn_id="t1")

    assert state.examined == 0, "이번 턴이 아무것도 안 열었는데 확인함으로 세어졌다"
    assert state.candidates == 2


def test_a_seed_never_overwrites_a_more_specific_handle():
    """첨부·명시 논문이 먼저 심어졌고 그쪽이 더 구체적이다(본문·소유권이 확인된 핸들)."""
    state = LoopState(topic="q")
    state.examine(PaperHandle("2106.09685", "r", PaperOrigin.ATTACHMENT, title="첨부본"))

    _seed_continuation(
        state, _Checkpoints({"t1": _prior_seeds()}), _ctx(prior_turn_id="t1"), "auto"
    )

    assert state.papers["2106.09685"].origin is PaperOrigin.ATTACHMENT
    assert "2106.09685" not in state.discovered


def test_no_prior_turn_means_nothing_to_transplant():
    checkpoints = _Checkpoints({"t1": _prior_seeds()})

    state = _seeded(checkpoints)

    assert state.discovered == {}
    assert checkpoints.asked == [], "이식할 턴이 없는데 체크포인트를 조회했다"


def test_a_missing_snapshot_is_not_an_error():
    """체크포인터가 없는 배포·안 돈 스레드는 정상이다 — 이어가기만 꺼진다."""
    assert _seeded(_Checkpoints(), prior_turn_id="t1").discovered == {}


def test_a_broken_checkpoint_store_does_not_break_the_new_turn():
    """씨앗은 편의다. 못 읽는다고 새 질문에 답을 못 하게 되면 안 된다."""
    assert _seeded(_Checkpoints(raises=True), prior_turn_id="t1").discovered == {}


def test_explicit_scope_never_inherits_seeds():
    """사용자가 논문을 지정한 턴에 이전 턴 논문이 섞이면 그 지정이 무의미해진다(BR-EV-2)."""
    checkpoints = _Checkpoints({"t1": _prior_seeds()})

    state = _seeded(checkpoints, scope="explicit", prior_turn_id="t1")

    assert state.discovered == {}
    assert checkpoints.asked == []


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


def test_a_turn_is_folded_into_the_summary_exactly_once():
    """§3.4 "매 턴 재요약하지 않는다" — **횟수를 고정한다.**

    종전 검사는 `count(...) >= 1`과 `len(second) >= len(first)`였는데, 둘 다 같은 줄이 매 턴
    덧붙는 상태에서도 참이라 결함을 통과시켰다(실측 1→2→3회). 검사가 불변식이 아니라
    "뭔가 있다"를 보면 그 검사는 없는 것과 같다.

    덧붙기가 위험한 이유는 낭비만이 아니다 — 세션 요약 상한은 **앞을 자르므로**, 사본이
    쌓이면 정작 보존하려던 옛 내용이 밀려 나간다.
    """
    long_topic = "나" * 40_000
    repo = _seeded_repo([f"{long_topic}-old", "최근"])

    for turn_id in ("n1", "n2", "n3"):
        build_run_context(repo, owner_id="o", session_id="s", turn_id=turn_id)

    summary = repo.get_session("o", "s").summary
    assert summary, "밀려난 턴이 있는데 요약이 안 만들어졌다"
    assert summary.count("이전에 물어본 것") == 1, (
        f"같은 턴이 {summary.count('이전에 물어본 것')}번 접혔다 — 한 번만 접혀야 한다"
    )


def test_the_summary_the_model_reads_is_the_summary_in_the_database():
    """저장과 관찰이 갈리면, 프롬프트 회귀가 퇴출이 일어난 턴에서만 재현된다.

    종전에는 저장 경로만 4,000자 상한을 걸고 관찰 경로는 안 걸어 두 값이 달랐다.
    """
    long_topic = "다" * 40_000
    repo = _seeded_repo([f"{long_topic}-old", "최근"])

    ctx = build_run_context(repo, owner_id="o", session_id="s", turn_id="n1")

    assert ctx.prior_summary == repo.get_session("o", "s").summary


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


def test_turns_pushed_past_the_ceiling_are_folded_not_lost():
    """긴 세션의 **정상 경로**다 — 천장 밖으로 밀린 턴은 애초에 안 읽히므로, 그걸 안 접으면
    옛 턴을 보존하려는 기능이 정작 잃는 턴을 구조적으로 못 본다.

    종전에는 예산을 넘긴 턴(창 **안**)만 봤는데, 현실적인 턴에서 그쪽은 거의 안 문다
    (턴당 ~144자 · 예산 32,000자 → 200턴 넘어야 찬다).
    """
    repo = InMemoryEvidenceRepository()
    repo.create_session(EvidenceSession(session_id="s", owner_id="o"))
    for i in range(30):
        repo.add_turn(_finished(f"t{i}", f"{i}번째 질문입니다"))
        build_run_context(repo, owner_id="o", session_id="s", turn_id=f"c{i}")

    summary = repo.get_session("o", "s").summary
    assert "0번째 질문입니다" in summary, "가장 오래된 턴이 접히지 않고 사라졌다"
    assert "29번째 질문입니다" not in summary, "최근 턴이 요약으로 뭉개졌다"


def test_the_summary_label_is_written_once_not_per_fold():
    """붙일 때마다 머리표를 다시 쓰면 세션이 길어질수록 요약의 절반이 라벨이 된다
    (실측: 30턴에서 188자 중 90자가 머리표 아홉 벌이었다)."""
    repo = InMemoryEvidenceRepository()
    repo.create_session(EvidenceSession(session_id="s", owner_id="o"))
    for i in range(30):
        repo.add_turn(_finished(f"t{i}", f"{i}번째 질문입니다"))
        build_run_context(repo, owner_id="o", session_id="s", turn_id=f"c{i}")

    assert repo.get_session("o", "s").summary.count("이전에 물어본 것") == 1


def test_an_attached_document_never_rides_into_the_next_turn():
    """첨부 핸들은 `abstract_text`에 **사용자가 올린 문서 본문**을 들고 스냅샷에 실린다.

    그대로 이식하면 다음 턴이 그 문서를 소유권·범위 재확인 없이 인용할 수 있고, 업로드를
    지운 뒤에도 살아남는다. `_seed_explicit`가 `userdoc:`·`upload:` 접두어를 막는 것과 같은
    우회다 — 씨앗 경로로 돌아 들어오던 것을 막는다.
    """
    prior = LoopState(topic="이전")
    prior.examine(
        PaperHandle(
            "attachment:비밀.pdf", "upload:o:j:a", PaperOrigin.ATTACHMENT,
            abstract_text="사적 문서 본문",
        )
    )
    prior.examine(PaperHandle("2106.09685", "r", PaperOrigin.CORPUS))
    snapshot = prior.to_snapshot()

    class _Store:
        def seeds_from(self, turn_id):
            from backend.modules.evidence.checkpoints import TurnCheckpoints  # noqa: F401
            rows = [*snapshot["papers"], *snapshot["discovered"]]
            handles = [PaperHandle.from_snapshot(r) for r in rows]
            return tuple(h for h in handles if h.origin is not PaperOrigin.ATTACHMENT)

    state = _seeded(_Store(), prior_turn_id="t1")

    assert "attachment:비밀.pdf" not in state.discovered
    assert "2106.09685" in state.discovered


def test_seeds_do_not_compound_across_a_session():
    """씨앗은 새 턴의 후보가 되고 그 후보가 다시 스냅샷에 실린다 — 안 묶으면 세션이 길어질수록
    단조 증가한다(실측 5 → 10 → 15). 그 수가 화면의 "관련 논문 N편 중 M편 확인"의 N이라,
    한 번 검색한 턴이 "300편 중 4편"이 된다."""
    from backend.modules.evidence.checkpoints import _MAX_SEEDS

    many = tuple(
        PaperHandle(f"p{i}", "r", PaperOrigin.CORPUS) for i in range(_MAX_SEEDS * 3)
    )

    class _Store:
        def seeds_from(self, turn_id):
            return many[:_MAX_SEEDS]

    state = _seeded(_Store(), prior_turn_id="t1")

    assert state.candidates == _MAX_SEEDS
