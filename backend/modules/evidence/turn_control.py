"""실행 중 턴의 제어 채널 — 하트비트·취소·트레이스·결과를 **각각 짧은 트랜잭션**으로.

실행자가 잡 하나를 긴 트랜잭션 안에서 돌리면 두 가지가 깨진다. 트레이스 행이 flush만 되고
커밋되지 않아 API의 이벤트 스트림(다른 프로세스·다른 세션)이 완료 때까지 아무것도 못 보고,
API가 커밋한 취소 플래그를 실행자가 못 읽는다(READ COMMITTED는 커밋된 것만 보인다). 그래서
제어 채널은 호출마다 세션을 열고 커밋하고 닫는다 — super-step당 쿼리 한두 개라 비용은 없다.

트레이스·하트비트는 advisory다(NFR-O1) — 실패해도 근거형성은 계속된다. 결과 기록(`finish`)만
예외를 올린다 — 그게 실패하면 턴은 영원히 pending이다.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

from .domain.models import TerminationReason, ToolCallRecord
from .models import TurnResult
from .repository import EvidenceRepository, in_transaction

log = logging.getLogger("docsuri.evidence.turn_control")

__all__ = ["TurnControl", "trace_row"]


def trace_row(record: ToolCallRecord) -> dict[str, Any]:
    """트레이스 **저장** 형태 — sanitized 요약만(INV-EV-5).

    화면으로 나가는 키는 이보다 좁다(`repository.trace_wire_row`) — `stance`는 §7 트레이스로
    남기지만 진행 표시에 실을 것이 아니다(§5.3: 단계명·논문 제목·건수만).

    `at`은 **루프가 그 호출을 기록한 시각**이고 여기서 한 번만 정해진다. 종전에는 SQL 스토어가
    삽입 시각을 따로 찍고 인메모리는 아무것도 안 찍어서, 같은 트레이스가 스토어에 따라 시각을
    갖기도 하고 안 갖기도 했다 — 화면이 단계별 소요 시간을 그 값으로 재므로, 갈리면 로컬에서는
    시간이 안 보이고 배포에서만 보인다(그리고 그 차이는 아무 데도 안 나타난다).

    **datetime 그대로 싣는다.** 이 dict는 저장소로 바로 넘어가는 내부 값이지 wire가 아니다
    (사이에 JSON 경계가 없다). 여기서 문자열로 만들면 SQL 스토어가 컬럼에 넣으려고 되파싱하고
    읽을 때 다시 문자열로 만든다 — 도구 호출마다 왕복이 한 번씩 돈다. 문자열화는 화면으로
    나가는 단일 투영 지점(`repository.trace_wire_row`)이 한 번만 한다.
    """
    return {
        "seq": record.seq,
        "tool": record.tool,
        "argsSummary": record.args_summary,
        "outcome": record.outcome.value,
        "resultSummary": record.result_summary,
        "costUsd": record.cost_usd,
        "stance": record.stance,
        "at": record.at,
    }


class TurnControl:
    def __init__(
        self,
        repo_factory: Callable[[], EvidenceRepository],
        *,
        owner_id: str,
        turn_id: str,
        shutdown: threading.Event | None = None,
    ) -> None:
        self._factory = repo_factory
        self._owner_id = owner_id
        self._turn_id = turn_id
        self._shutdown = shutdown

    def _in_transaction(self, fn: Callable[[EvidenceRepository], Any]) -> Any:
        return in_transaction(self._factory, fn)

    # -- super-step 경계 ------------------------------------------------------
    def heartbeat(self) -> bool:
        """하트비트를 찍고 취소 플래그를 돌려준다. 조회 실패는 '취소 아님'으로 읽는다."""
        try:
            return bool(self._in_transaction(lambda r: r.heartbeat(self._owner_id, self._turn_id)))
        except Exception:  # noqa: BLE001 — advisory
            log.warning("evidence heartbeat failed (turn=%s)", self._turn_id, exc_info=True)
            return False

    def should_stop(self) -> TerminationReason | None:
        """루프의 `deps.should_stop` — 취소가 종료 신호보다 먼저다(사용자 의사가 우선)."""
        if self.heartbeat():
            return TerminationReason.CANCELLED
        if self._shutdown is not None and self._shutdown.is_set():
            return TerminationReason.INTERRUPTED
        return None

    # -- 트레이스 -------------------------------------------------------------
    def append_trace(self, record: ToolCallRecord) -> None:
        row = trace_row(record)
        try:
            self._in_transaction(lambda r: r.append_trace(self._owner_id, self._turn_id, row))
        except Exception:  # noqa: BLE001 — advisory(NFR-O1)
            log.warning("evidence trace append failed (turn=%s)", self._turn_id, exc_info=True)

    # -- 결과 -----------------------------------------------------------------
    def finish(self, result: TurnResult) -> None:
        self._in_transaction(
            lambda r: r.update_turn_result(self._owner_id, self._turn_id, result)
        )
