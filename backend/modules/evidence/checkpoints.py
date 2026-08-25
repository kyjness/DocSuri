"""턴 체크포인트 — Postgres saver 조립과 그 위의 조작(v3 §3.1·§5).

`thread_id = turn_id`. 테이블(checkpoints·checkpoint_blobs·checkpoint_writes·
checkpoint_migrations)은 saver가 자기 원장으로 만든다 — 우리 `_migrations` 원장 밖이지만 같은
부팅 게이트(RUN_MIGRATIONS_ON_STARTUP) 아래서 `setup()`을 부르므로 적용 시점은 같다.
풀은 autocommit이어야 한다(saver가 트랜잭션을 직접 다루지 않는다) — 라이브러리 요구.

체크포인트 **조작은 러너가 아니라 여기 산다.** 세션 삭제·취소·이벤트·폴링이 스레드 하나를
지우거나 읽으려고 LLM 러너 전체를 의존하면, 러너가 구성되지 않은 배포(DocModel 버킷 없음)에서
그 라우트들이 통째로 죽는다.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from .domain.loop import compile_loop_graph, load_snapshot
from .domain.models import LoopState, PaperHandle, PaperOrigin, TerminationReason
from .models import TurnResult, to_turn_result

log = logging.getLogger("docsuri.evidence.checkpoints")

# 이어가기가 옮기는 논문 수 상한. 도구 상한(fetch 8 · read 8)보다 넉넉하되, 세션이
# 길어져도 확인 범위 수치가 부풀지 않을 만큼 작게.
_MAX_SEEDS = 40

__all__ = ["TurnCheckpoints", "build_postgres_checkpointer"]


class TurnCheckpoints:
    """컴파일된 그래프 하나를 쥐고, 그 위의 읽기·정리를 제공한다.

    그래프는 프로세스당 한 번만 컴파일한다(deps는 context로 들어가므로 턴마다 만들 이유가 없다).
    러너는 `graph`를 받아 돌리기만 하고, 스냅샷 조회·삭제는 이쪽 책임이다.
    """

    def __init__(self, checkpointer: Any | None = None) -> None:
        self._graph = compile_loop_graph(checkpointer)

    @property
    def graph(self) -> Any:
        return self._graph

    @property
    def enabled(self) -> bool:
        return self._graph.checkpointer is not None

    def finalize(self, turn_id: str, topic: str) -> TurnResult | None:
        """실행자가 죽은 턴을 마지막 스냅샷으로 마감한다(§5.5). 스냅샷이 없으면 None."""
        state = self._restore(turn_id)
        if state is None:
            return None
        return to_turn_result(state, TerminationReason.INTERRUPTED, query_used=topic)

    def _restore(self, turn_id: str) -> LoopState | None:
        snapshot = load_snapshot(self._graph, turn_id)
        return LoopState.from_snapshot(snapshot) if snapshot is not None else None

    def seeds_from(self, turn_id: str) -> tuple[PaperHandle, ...]:
        """`ContinuationSeedPort` — 직전 턴이 찾아 둔 논문 핸들만(설계 §3.4).

        **상태 전체를 복원하지 않는다.** 이식이 옮기는 것은 "무엇을 찾았고 무엇을 봤는가"인데,
        `LoopState.from_snapshot`은 근거마다 `model_validate`를 돌리고 트레이스 행마다 객체를
        만든 뒤 전부 버린다 — 첫 턴 이후 **모든 턴**이 그 값을 낸다(씨앗은 이어가기 턴에만
        쓰이지만 조회는 매 턴 돈다).

        복원된 핸들에는 `doc_model`이 없다(직렬화되지 않는다) — 본문이 다시 필요하면
        `fetch_paper`를 부르면 된다.
        """
        snapshot = load_snapshot(self._graph, turn_id)
        if snapshot is None:
            return ()
        rows = [*snapshot.get("papers", []), *snapshot.get("discovered", [])]
        handles = [PaperHandle.from_snapshot(row) for row in rows]
        # **첨부는 옮기지 않는다.** 첨부 핸들은 `abstract_text`에 사용자가 올린 문서 본문을
        # 들고 스냅샷에 실린다 — 그대로 이식하면 다음 턴이 그 문서를 소유권·범위 재확인
        # (`_attachment_inputs(owner_id, scope_id=turn_id, …)`) 없이 인용할 수 있고, 업로드를
        # 지운 뒤에도 살아남는다. `_seed_explicit`가 `userdoc:`·`upload:` 접두어를 막는 것과
        # 같은 우회다.
        seeds = [h for h in handles if h.origin is not PaperOrigin.ATTACHMENT]
        # **수를 묶는다.** 씨앗은 새 턴의 후보가 되고 그 후보가 다시 스냅샷에 실리므로,
        # 안 묶으면 세션이 길어질수록 단조 증가한다(실측 5 → 10 → 15). 그 수가 화면의
        # "관련 논문 N편 중 M편 확인"의 N이라, 한 번 검색한 턴이 "300편 중 4편"이 된다.
        return tuple(seeds[:_MAX_SEEDS])

    def delete(self, turn_ids: Iterable[str]) -> int:
        saver = self._graph.checkpointer
        if saver is None:
            return 0
        count = 0
        for turn_id in turn_ids:
            try:
                saver.delete_thread(turn_id)
                count += 1
            except Exception:  # noqa: BLE001 — 정리 실패가 턴을 깨지 않는다
                log.warning("evidence checkpoint delete failed (turn=%s)", turn_id, exc_info=True)
        return count


def build_postgres_checkpointer(database_url: str, *, setup: bool, max_size: int = 4) -> Any:
    """PostgresSaver + 전용 풀. 반환값은 `(saver, close)` — close는 풀을 닫는다."""
    from langgraph.checkpoint.postgres import PostgresSaver
    from psycopg_pool import ConnectionPool

    from backend.db import libpq_dsn

    # open=False + 지연 오픈 — 부팅 스레드가 DB 연결을 기다리지 않는다(psycopg_pool도 생성자
    # open=True를 폐기 예정으로 본다).
    pool = ConnectionPool(
        libpq_dsn(database_url),
        min_size=1,
        max_size=max_size,
        open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0},
    )
    pool.open()
    saver = PostgresSaver(pool)
    if setup:
        saver.setup()
        log.info("evidence checkpointer: tables ready")
    return saver, pool.close
