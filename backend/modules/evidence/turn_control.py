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
    """트레이스 저장·전송 형태 — sanitized 요약만(INV-EV-5). 실행자와 API가 같은 키를 본다."""
    return {
        "seq": record.seq,
        "tool": record.tool,
        "argsSummary": record.args_summary,
        "outcome": record.outcome.value,
        "resultSummary": record.result_summary,
        "costUsd": record.cost_usd,
        "stance": record.stance,
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
