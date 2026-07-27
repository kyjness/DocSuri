"""워커 엔트리포인트(NFR-NV2-1~3) — 큐 소비 → 실행 잠금 → 자율 루프 실행.

기동: ``python -m backend.modules.novelty.worker`` (API 프로세스와 동일 설정,
TD-NV2-2 — 배포 워커도 같은 엔트리포인트). 큐·저장소·LLM 미구성은 기동 시점에
fail-fast한다. 실행 잠금은 ``job_id`` 리스(TTL)로 이중 실행을 막고(멱등), 리스가
만료된 채 방치된 잡은 stale 스윕이 failed로 수렴시킨다(NFR-NV2-3). 협조적 취소는
루프의 턴 경계 확인에 위임한다(BR-RA8).

비용: per-job 3중 예산은 루프가 집행한다(FR-45). U6 전역 예산 판정은 잡 접수
시점(API)의 단일 권위 확인으로 수행되며 워커는 재판정하지 않는다(BLM §9).
"""

from __future__ import annotations

import logging
import signal
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

# 계측 방출은 공유 best-effort 헬퍼(포트 시그니처 강제) — 유닛 사본 금지.
from docsuri_shared.observability import emit_metric as _emit

from .domain.agent_step import ON_DEMAND_UNAVAILABLE_NOTICE, append_agent_message
from .domain.loop import LoopDeps, run_loop
from .domain.models import (
    ON_DEMAND_ELIGIBLE_STATES,
    TERMINAL_STATES,
    AgentLoopRun,
    ChatRole,
    JobState,
    NoveltyChatMessage,
    NoveltyJob,
    TerminationReason,
    utc_now,
    validate_transition,
)
from .domain.turn import run_turn
from .ports.queue import KIND_TURN, QueuedJob
from .ports.store import NoveltyStorePort
from .ports.tools import ToolRegistry
from .settings import NoveltySettings

log = logging.getLogger("docsuri.novelty.worker")

_CONSUME_TIMEOUT_S = 5.0
_STALE_SWEEP_EVERY_N_IDLE = 12  # 유휴 consume 12회(~1분)마다 스윕
_CONTENTION_BACKOFF_MAX_S = 30.0  # 잠금 경합 재시도 상한(잠금 TTL보다 짧게 유지)
_CONSUME_ERROR_BACKOFF_MAX_S = 30.0  # 큐 조회 실패 재시도 상한


@dataclass(slots=True)
class WorkerDeps:
    store: NoveltyStorePort
    queue: Any  # JobQueuePort + ExecutionLockPort
    llm: Any
    registry: ToolRegistry
    settings: NoveltySettings
    observability: Any | None = None
    sleep: Callable[[float], None] = time.sleep  # 경합 백오프 주입점(테스트)
    _idle_count: int = field(default=0, init=False)
    # 잡별 연속 경합 횟수 — 전역 카운터면 잡 A의 경합이 무관한 잡 B의 대기를 키운다.
    _contention_counts: dict[str, int] = field(default_factory=dict, init=False)
    _consume_failures: int = field(default=0, init=False)  # 연속 큐 조회 실패(백오프용)


def _backoff_delay(attempt: int, cap_seconds: float) -> float:
    """연속 실패 횟수 → 대기 시간(첫 재시도 1초, 이후 2배씩, 상한까지).

    지수를 먼저 제한한다 — 장애가 길어져 attempt가 1024를 넘으면 `2.0 ** n`이
    OverflowError를 던져, 하필 워커를 살려두려고 만든 처리 경로가 워커를 죽인다.
    """
    return min(2.0 ** min(attempt - 1, 20), cap_seconds)


def run_worker(deps: WorkerDeps, should_stop) -> None:
    recover = getattr(deps.queue, "recover_processing", None)
    if recover is not None:
        requeued = recover()
        if requeued:
            log.info("novelty worker: requeued %d in-flight jobs", requeued)
    while not should_stop():
        # 큐 조회 실패로 워커가 죽으면 안 된다 — redis 재시작·페일오버 같은 일시적
        # 장애에 프로세스가 영구 종료되면, 복구된 뒤에도 아무도 잡을 집지 않는다.
        # 개별 잡의 실패는 process_message가 이미 흡수하지만 consume 자체는 무방비였다.
        try:
            message = deps.queue.consume(_CONSUME_TIMEOUT_S)
        except Exception:  # noqa: BLE001 — 큐 장애는 백오프 후 재시도
            deps._consume_failures += 1
            delay = _backoff_delay(deps._consume_failures, _CONSUME_ERROR_BACKOFF_MAX_S)
            log.warning(
                "novelty worker: queue consume failed (%d in a row); retrying in %.0fs",
                deps._consume_failures, delay, exc_info=True,
            )
            deps.sleep(delay)
            continue
        deps._consume_failures = 0
        if message is None:
            deps._idle_count += 1
            if deps._idle_count >= _STALE_SWEEP_EVERY_N_IDLE:
                deps._idle_count = 0
                sweep_stale_jobs(deps)
            continue
        deps._idle_count = 0
        process_message(deps, message)


def process_message(deps: WorkerDeps, message: QueuedJob) -> None:
    """한 메시지 처리 — 멱등: 종단 잡의 loop 재전달은 ack만, 잠금 실패는 nack."""
    store = deps.store
    job = store.get_job_for_worker(message.job_id)
    if job is None:
        deps.queue.ack(message)
        return
    if message.kind == KIND_TURN:
        _process_turn(deps, message, job)
        return
    if job.state in TERMINAL_STATES:
        deps.queue.ack(message)
        return
    if not _acquire_or_backoff(deps, message):
        return
    try:
        if job.cancel_requested:
            _finalize_cancelled(store, job)
            deps.queue.ack(message)
            return
        if job.loop_run is None:
            job.loop_run = AgentLoopRun(budget=deps.settings.build_loop_budget())
        # 리스 하트비트 — 한 턴이 TTL(기본 120s)보다 길어도(LLM 재시도·근거형성)
        # 잠금이 중간에 만료되지 않도록 백그라운드에서 주기 갱신한다(코드 리뷰 반영).
        with _LeaseHeartbeat(deps.queue, message.job_id, deps.settings.lock_ttl_seconds):
            outcome = run_loop(
                job, LoopDeps(store=store, llm=deps.llm, registry=deps.registry)
            )
        _emit(deps.observability, f"novelty.loop_{outcome.reason.value}")
        deps.queue.ack(message)
    except Exception:  # noqa: BLE001 — 잡 하나의 실패가 워커를 죽이지 않는다
        log.exception("novelty worker: job %s crashed", message.job_id)
        _mark_failed(store, message.job_id, "worker crashed while running the loop")
        deps.queue.ack(message)
    finally:
        deps.queue.release(message.job_id)


def _process_turn(deps: WorkerDeps, message: QueuedJob, job: NoveltyJob) -> None:
    """온디맨드 대화 턴(BLM §5) — 잡 상태를 바꾸지 않고 답장만 남긴다."""
    store = deps.store
    # BLM §5.1은 "완료/부분 완료"의 잡만 대상으로 한다. 실패·취소 잡은 산출물이
    # 없거나 loop_run조차 없을 수 있어 근거 있는 생성이 성립하지 않는다.
    if job.state not in ON_DEMAND_ELIGIBLE_STATES or job.loop_run is None:
        append_agent_message(store, job, ON_DEMAND_UNAVAILABLE_NOTICE)
        deps.queue.ack(message)
        return
    request = _turn_request(store, job, message)
    if request is None:
        # 대상 메시지가 없거나 이미 답장이 있다 — 재전달분이므로 조용히 흡수한다.
        deps.queue.ack(message)
        return
    if not _acquire_or_backoff(deps, message):
        return
    try:
        with _LeaseHeartbeat(deps.queue, message.job_id, deps.settings.lock_ttl_seconds):
            outcome = run_turn(
                job,
                request,
                LoopDeps(store=store, llm=deps.llm, registry=deps.registry),
                max_steps=deps.settings.max_turn_steps,
            )
        _emit(
            deps.observability,
            "novelty.turn_saved" if outcome.saved_kind else "novelty.turn_replied",
        )
        deps.queue.ack(message)
    except Exception:  # noqa: BLE001 — 턴 하나의 실패가 워커를 죽이지 않는다
        log.exception("novelty worker: turn for job %s crashed", message.job_id)
        # in_reply_to를 걸어 이 턴을 종결로 기록한다 — 재전달이 crash 안내 뒤에
        # 같은 턴을 또 돌려 안내+답장이 겹치는 것을 막는다.
        append_agent_message(
            store, job, "요청을 처리하는 중 문제가 생겼어요. 다시 시도해 주세요.",
            in_reply_to=request.message_id,
        )
        deps.queue.ack(message)
    finally:
        deps.queue.release(message.job_id)


def _acquire_or_backoff(deps: WorkerDeps, message: QueuedJob) -> bool:
    """실행 잠금을 시도하고, 경합이면 nack 후 백오프한다 — loop·turn 공용 정책.

    ack 생략만으로는 부족하다: redis 구현은 소비 시점에 processing 리스트로 옮기므로
    되돌리지 않으면 워커 재시작(recover_processing)까지 방치된다. nack은 큐 끝으로
    넣으므로 다른 메시지가 있으면 그쪽이 먼저 처리되고, 같은 메시지만 남아 반복
    경합할 때는 지수 백오프가 핫루프를 막는다(상한은 잠금 TTL보다 짧게).

    sleep이 소비 스레드를 세우는 것은 의도된 절충이다 — 경합은 같은 잡을 다른
    워커가 쥐고 있을 때(더블탭·재전달)뿐이라 드물고, 카운터가 잡별이므로 무관한
    잡의 경합이 이 잡의 대기를 키우지 않는다.
    """
    if deps.queue.acquire(message.job_id, deps.settings.lock_ttl_seconds):
        deps._contention_counts.pop(message.job_id, None)
        return True
    deps.queue.nack(message)
    count = deps._contention_counts.get(message.job_id, 0) + 1
    deps._contention_counts[message.job_id] = count
    deps.sleep(_backoff_delay(count, _CONTENTION_BACKOFF_MAX_S))
    return False


_REPLY_SCAN_LIMIT = 50


def _turn_request(
    store: NoveltyStorePort, job: NoveltyJob, message: QueuedJob
) -> NoveltyChatMessage | None:
    """처리 대상 사용자 메시지를 찾고, 이미 답한 턴이면 None.

    멱등성: 큐 재전달(워커 crash 후 recover_processing)로 같은 턴이 두 번 올 수
    있다. 대상 메시지 뒤에 **이 메시지를 in_reply_to로 가리키는** 에이전트 행이
    있으면 이미 실행된 턴이므로 다시 돌리지 않는다 — 중복 답장과 중복 과금을 막는다.
    "아무 에이전트 행"으로 판정하면 연속 요청 A·B에서 A의 답장이 B의 답장으로
    오인돼 B가 무응답으로 사라진다(코드 리뷰 반영).
    """
    if message.message_id is None:
        return None
    target = store.get_message(job.owner_id, job.job_id, message.message_id)
    if target is None:
        return None  # 대상 메시지가 사라졌다(잡 삭제 경합)
    try:
        after = store.list_messages(
            job.owner_id, job.job_id, after=message.message_id, limit=_REPLY_SCAN_LIMIT
        )
    except KeyError:
        return None
    if any(
        item.role is ChatRole.AGENT and item.in_reply_to == message.message_id
        for item in after
    ):
        return None
    return target


def sweep_stale_jobs(deps: WorkerDeps) -> int:
    """방치된 잡을 failed로 수렴(NFR-NV2-3) — 실행 잠금이 만료된 실행 중 잡과,
    큐 메시지가 유실된 채 남은 RECEIVED 잡(적재 실패·독약 메시지 폐기 잔재) 모두."""
    cutoff = utc_now() - timedelta(seconds=deps.settings.stale_after_seconds)
    swept = 0
    for job in deps.store.list_stale_active(updated_before=cutoff, limit=20):
        # 유효한 리스가 남아 있으면(acquire 실패) 실행 중 — 건드리지 않는다.
        if not deps.queue.acquire(job.job_id, deps.settings.lock_ttl_seconds):
            continue
        try:
            reason = (
                "stale job — never picked up (queue message lost)"
                if job.state is JobState.RECEIVED
                else "stale job — worker lease expired"
            )
            _mark_failed(deps.store, job.job_id, reason)
            _emit(deps.observability, "novelty.job_stale_failed")
            swept += 1
        finally:
            deps.queue.release(job.job_id)
    return swept


class _LeaseHeartbeat:
    """실행 리스 백그라운드 갱신 — TTL의 1/3 주기로 renew(SQS visibility 하트비트
    등가). 스토어 프록시에 갱신을 숨기던 방식을 대체한다(턴 길이와 무관하게 유지)."""

    def __init__(self, queue: Any, job_id: str, ttl_seconds: float) -> None:
        self._queue = queue
        self._job_id = job_id
        self._ttl = ttl_seconds
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._beat, daemon=True)

    def _beat(self) -> None:
        interval = max(self._ttl / 3.0, 1.0)
        while not self._stop.wait(interval):
            try:
                self._queue.renew(self._job_id, self._ttl)
            except Exception:  # noqa: BLE001 — 갱신 실패는 다음 주기 재시도
                log.warning("novelty worker: lease renew failed for %s", self._job_id)

    def __enter__(self) -> _LeaseHeartbeat:
        self._thread.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self._stop.set()
        self._thread.join(timeout=5.0)


def _finalize_cancelled(store: NoveltyStorePort, job: NoveltyJob) -> None:
    """워커 픽업 전 취소된 잡 — 루프 진입 없이 종단 처리(협조적 취소의 즉시 경로)."""
    validate_transition(job.state, JobState.CANCELLED)
    job.state = JobState.CANCELLED
    if job.loop_run is not None:
        job.loop_run.termination_reason = TerminationReason.CANCELLED
        job.loop_run.ended_at = utc_now()
    job.updated_at = utc_now()
    job.completed_at = utc_now()
    store.update_job(job)


def _mark_failed(store: NoveltyStorePort, job_id: str, reason: str) -> None:
    job = store.get_job_for_worker(job_id)
    if job is None or job.state in TERMINAL_STATES:
        return
    job.state = JobState.FAILED
    job.error_message = reason
    if job.loop_run is not None:
        job.loop_run.termination_reason = TerminationReason.FATAL_ERROR
        job.loop_run.ended_at = utc_now()
    job.updated_at = utc_now()
    job.completed_at = utc_now()
    store.update_job(job)


def build_worker_deps() -> WorkerDeps:
    """env 조립 — 미구성 의존성은 fail-fast(NFR-NV2-1)."""
    from backend.config import Settings
    from backend.db import make_engine, make_session_factory

    from .adapters.local_wiring import (
        build_asset_port,
        build_llm,
        build_queue,
        build_store,
        build_tool_registry,
    )

    settings = NoveltySettings.from_env()
    if not settings.queue_configured:
        raise SystemExit("novelty worker: job queue is not configured")
    if not settings.llm_configured:
        raise SystemExit("novelty worker: LLM provider is not configured")
    from backend.wiring import _is_postgres

    app_settings = Settings.from_env()
    database_url = app_settings.database_url
    # 판별은 앱쉘과 동일 헬퍼 공유 — 드라이버 표기 변형이 생겨도 한 곳만 갱신.
    if not _is_postgres(database_url):
        raise SystemExit("novelty worker: postgres DATABASE_URL is required")
    session_factory = make_session_factory(make_engine(database_url))
    store = build_store(session_factory)
    queue = build_queue(settings, for_consumer=True)
    llm = build_llm(settings)
    orchestrator, grounding_hook = _build_corpus_deps()
    evidence_port = _build_evidence_port()
    # 자산 리더는 형제 wrapper들과 달리 try/except가 없다 — 다른 서브프로젝트를
    # import하지도, I/O를 하지도 않아서 잡을 실패가 없다(boto3·sqlalchemy는 메서드
    # 안에서 lazy import).
    asset_port = build_asset_port(settings, session_factory)
    registry = build_tool_registry(
        settings,
        orchestrator=orchestrator,
        grounding_hook=grounding_hook,
        evidence_port=evidence_port,
        asset_port=asset_port,
    )
    return WorkerDeps(
        store=store,
        queue=queue,
        llm=llm,
        registry=registry,
        settings=settings,
        observability=_build_observability(),
    )


def _build_observability() -> Any | None:
    """앱쉘과 동일한 U6 관측 허브 — 워커 메트릭(novelty.loop_* 등)의 실제 배선."""
    try:
        from backend.app import _build_observability as build

        observability, _telemetry_store = build()
        return observability
    except Exception:  # noqa: BLE001 — 계측 조립 실패가 워커를 막지 않는다
        log.warning("novelty worker: observability unavailable", exc_info=True)
        return None


def _build_corpus_deps() -> tuple[Any | None, Any | None]:
    """U2 full 검색 의존성 — discovery 설정이 있을 때만(없으면 도구 미노출)."""
    try:
        from discovery.adapters.settings import DiscoverySettings
        from discovery.real_wiring import build_real_orchestrator
        from docsuri_ops.grounding import GroundingEnforcementHook

        discovery_settings = DiscoverySettings.from_env()
        if not discovery_settings.search_enabled:
            return None, None
        bundle = build_real_orchestrator(discovery_settings)
        return bundle.orchestrator, GroundingEnforcementHook()
    except Exception:  # noqa: BLE001 — 코퍼스 검색은 선택 의존성, 부재 시 도구 축소
        log.warning("novelty worker: corpus search unavailable", exc_info=True)
        return None, None


def _build_evidence_port() -> Any | None:
    """U11 EvidenceFormationPort — evidence 설정이 있을 때만."""
    try:
        from backend.modules.evidence.real_wiring import build_evidence_orchestrator
        from backend.modules.evidence.service import EvidenceFormationService
        from backend.modules.evidence.settings import EvidenceSettings

        evidence_settings = EvidenceSettings.from_env()
        if not evidence_settings.evidence_enabled:
            return None
        bundle = build_evidence_orchestrator(evidence_settings)
        return EvidenceFormationService(orchestrator=bundle.orchestrator)
    except Exception:  # noqa: BLE001 — 근거형성은 선택 의존성(자연어 잡은 fatal로 표면화)
        log.warning("novelty worker: evidence engine unavailable", exc_info=True)
        return None


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO)
    deps = build_worker_deps()
    stop = {"flag": False}

    def _handle_signal(signum, frame) -> None:  # noqa: ARG001
        log.info("novelty worker: draining (signal %s)", signum)
        stop["flag"] = True

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    log.info("novelty worker: started (tools=%s)", sorted(deps.registry.names()))
    run_worker(deps, should_stop=lambda: stop["flag"])
    log.info("novelty worker: stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
