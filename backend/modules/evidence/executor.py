"""프로세스 내 실행자 — SQS 워커가 없는 배포(로컬·단일 태스크)에서 턴을 돌린다(v3 §5.1).

API·이벤트 계약은 실행자가 어디 있든 같다. 여기서는 같은 `process_job`을 스레드풀에서 돌릴
뿐이고, 워커 프로세스와 다른 점은 종료 신호가 SIGTERM이 아니라 앱 lifespan이라는 것뿐이다.
종료 시 진행 중 턴은 다음 super-step 경계에서 INTERRUPTED로 마감되고(부분 답), 그 뒤 풀을
닫는다 — 그냥 죽이면 턴이 pending으로 남아 stale 마감까지 침묵한다.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, wait
from datetime import timedelta
from typing import Any

from .models import TurnErrorResult
from .repository import EvidenceRepository
from .turn_control import TurnControl
from .worker import process_sqs_payload

log = logging.getLogger("docsuri.evidence.executor")

__all__ = ["LocalTurnExecutor"]


class LocalTurnExecutor:
    def __init__(
        self,
        *,
        repo_factory: Callable[[], EvidenceRepository],
        runner: Any,
        user_docmodel_factory: Callable[[], Any] | None = None,
        workers: int = 2,
        checkpoints: Any = None,
        checkpoint_retention: timedelta | None = None,
    ) -> None:
        self._repo_factory = repo_factory
        self._runner = runner
        # 첨부 재수화용 — 첫 턴에서 한 번 만든다(앱 부팅을 S3 클라이언트 조립으로 늦추지 않는다).
        # 팩토리는 요청 경로와 **같은 객체**를 돌려줘야 한다 — 따로 만들면 boto3 클라이언트와
        # 자격증명 해석이 프로세스에 두 벌 생긴다.
        self._user_docmodel_factory = user_docmodel_factory
        self._user_docmodel: Any = None
        self._checkpoints = checkpoints
        self._retention = checkpoint_retention
        self._shutdown = threading.Event()
        self._pool = ThreadPoolExecutor(
            max_workers=max(1, workers), thread_name_prefix="evidence-turn"
        )
        self._inflight: set[Future] = set()
        self._lock = threading.Lock()

    def submit(self, payload: dict[str, Any]) -> None:
        """dispatch 계약 — 실패하면 예외(서비스가 턴을 error로 전이시킨다)."""
        if self._shutdown.is_set():
            raise RuntimeError("evidence executor is shutting down")
        future = self._pool.submit(self._run, payload)
        with self._lock:
            self._inflight.add(future)
        future.add_done_callback(self._forget)

    def _forget(self, future: Future) -> None:
        with self._lock:
            self._inflight.discard(future)

    def _docmodel(self) -> Any:
        if self._user_docmodel is None and self._user_docmodel_factory is not None:
            with self._lock:
                if self._user_docmodel is None:
                    self._user_docmodel = self._user_docmodel_factory()
        return self._user_docmodel

    def _run(self, payload: dict[str, Any]) -> None:
        try:
            process_sqs_payload(
                self._repo_factory,
                payload,
                runner=self._runner,
                user_docmodel=self._docmodel(),
                shutdown=self._shutdown,
                checkpoints=self._checkpoints,
                checkpoint_retention=self._retention,
            )
        except Exception:  # noqa: BLE001 — 스레드에서 올라온 예외는 아무도 안 본다
            log.exception("evidence local turn failed")
            # process_job이 관문을 통과했으면 이미 error로 닫았다. 그 앞(페이로드 파싱·코디네이터
            # 조립)에서 죽은 경우를 위해 한 번 더 — 조건부 UPDATE라 이미 닫힌 턴은 건드리지 않는다.
            self._close_as_error(payload)

    def _close_as_error(self, payload: dict[str, Any]) -> None:
        owner_id = payload.get("ownerId") or payload.get("owner_id")
        turn_id = payload.get("turnId") or payload.get("turn_id")
        if not owner_id or not turn_id:
            return
        try:
            TurnControl(self._repo_factory, owner_id=str(owner_id), turn_id=str(turn_id)).finish(
                TurnErrorResult(error_code="internal_error")
            )
        except Exception:  # noqa: BLE001
            log.warning("evidence local turn %s left pending", turn_id, exc_info=True)

    def close(self, timeout: float = 30.0) -> bool:
        """진행 중 턴이 INTERRUPTED로 닫힐 때까지 기다린다. 전부 비웠으면 True."""
        self._shutdown.set()
        with self._lock:
            pending = list(self._inflight)
        drained = True
        if pending:
            _done, not_done = wait(pending, timeout=timeout)
            if not_done:
                drained = False
                log.warning(
                    "evidence executor: %d turn(s) still running at shutdown", len(not_done)
                )
        self._pool.shutdown(wait=False, cancel_futures=True)
        return drained
