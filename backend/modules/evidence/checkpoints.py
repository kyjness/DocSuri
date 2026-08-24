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
from .domain.models import LoopState, TerminationReason
from .models import TurnResult, to_turn_result

log = logging.getLogger("docsuri.evidence.checkpoints")

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
        snapshot = load_snapshot(self._graph, turn_id)
        if snapshot is None:
            return None
        state = LoopState.from_snapshot(snapshot)
        return to_turn_result(state, TerminationReason.INTERRUPTED, query_used=topic)

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
