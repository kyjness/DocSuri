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
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from .domain.loop import LoopDeps, run_loop
from .domain.models import (
    TERMINAL_STATES,
    AgentLoopRun,
    JobState,
    NoveltyJob,
    TerminationReason,
    utc_now,
    validate_transition,
)
from .ports.queue import QueuedJob
from .ports.store import NoveltyStorePort
from .ports.tools import ToolRegistry
from .settings import NoveltySettings

log = logging.getLogger("docsuri.novelty.worker")

_CONSUME_TIMEOUT_S = 5.0
_STALE_SWEEP_EVERY_N_IDLE = 12  # 유휴 consume 12회(~1분)마다 스윕


@dataclass(slots=True)
class WorkerDeps:
    store: NoveltyStorePort
    queue: Any  # JobQueuePort + ExecutionLockPort
    llm: Any
    registry: ToolRegistry
    settings: NoveltySettings
    observability: Any | None = None
    _idle_count: int = field(default=0, init=False)


def run_worker(deps: WorkerDeps, should_stop) -> None:
    recover = getattr(deps.queue, "recover_processing", None)
    if recover is not None:
        requeued = recover()
        if requeued:
            log.info("novelty worker: requeued %d in-flight jobs", requeued)
    while not should_stop():
        message = deps.queue.consume(_CONSUME_TIMEOUT_S)
        if message is None:
            deps._idle_count += 1
            if deps._idle_count >= _STALE_SWEEP_EVERY_N_IDLE:
                deps._idle_count = 0
                sweep_stale_jobs(deps)
            continue
        deps._idle_count = 0
        process_message(deps, message)


def process_message(deps: WorkerDeps, message: QueuedJob) -> None:
    """한 메시지 처리 — 멱등: 종단 잡 재전달은 ack만, 잠금 실패는 재전달에 맡긴다."""
    store = deps.store
    job = store.get_job_for_worker(message.job_id)
    if job is None or job.state in TERMINAL_STATES:
        deps.queue.ack(message)
        return
    if not deps.queue.acquire(message.job_id, deps.settings.lock_ttl_seconds):
        # 다른 워커가 실행 중 — ack하지 않고 재전달(리스 만료 후 회수)에 맡긴다.
        return
    try:
        if job.cancel_requested:
            _finalize_cancelled(store, job)
            deps.queue.ack(message)
            return
        if job.loop_run is None:
            job.loop_run = AgentLoopRun(budget=deps.settings.build_loop_budget())
        outcome = run_loop(job, _loop_deps(deps, message.job_id))
        _emit(deps.observability, f"novelty.loop_{outcome.reason.value}")
        deps.queue.ack(message)
    except Exception:  # noqa: BLE001 — 잡 하나의 실패가 워커를 죽이지 않는다
        log.exception("novelty worker: job %s crashed", message.job_id)
        _mark_failed(store, message.job_id, "worker crashed while running the loop")
        deps.queue.ack(message)
    finally:
        deps.queue.release(message.job_id)


def sweep_stale_jobs(deps: WorkerDeps) -> int:
    """실행 잠금이 만료된 채 방치된 잡을 failed로 수렴(NFR-NV2-3)."""
    cutoff = utc_now() - timedelta(seconds=deps.settings.stale_after_seconds)
    swept = 0
    for job in deps.store.list_stale_active(updated_before=cutoff, limit=20):
        # 유효한 리스가 남아 있으면(acquire 실패) 실행 중 — 건드리지 않는다.
        if not deps.queue.acquire(job.job_id, deps.settings.lock_ttl_seconds):
            continue
        try:
            _mark_failed(deps.store, job.job_id, "stale job — worker lease expired")
            _emit(deps.observability, "novelty.job_stale_failed")
            swept += 1
        finally:
            deps.queue.release(job.job_id)
    return swept


def _loop_deps(deps: WorkerDeps, job_id: str) -> LoopDeps:
    return LoopDeps(
        store=_LeaseKeepingStore(deps.store, deps.queue, job_id, deps.settings.lock_ttl_seconds),
        llm=deps.llm,
        registry=deps.registry,
    )


class _LeaseKeepingStore:
    """스토어 위임 프록시 — 루프가 매 턴 호출하는 취소 확인 시점에 실행 리스를
    갱신한다(장기 실행 잡의 잠금 유지, SQS visibility 갱신과 등가)."""

    def __init__(
        self, store: NoveltyStorePort, queue: Any, job_id: str, ttl_seconds: float
    ) -> None:
        self._store = store
        self._queue = queue
        self._job_id = job_id
        self._ttl = ttl_seconds

    def is_cancel_requested(self, job_id: str) -> bool:
        self._queue.renew(self._job_id, self._ttl)
        return self._store.is_cancel_requested(job_id)

    def __getattr__(self, name: str):
        return getattr(self._store, name)


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


def _emit(observability: Any | None, name: str) -> None:
    if observability is None:
        return
    try:
        observability.emit_metric(name)
    except Exception:  # noqa: BLE001 — 계측은 best-effort side path
        log.debug("novelty worker: metric emit failed", exc_info=True)


def build_worker_deps() -> WorkerDeps:
    """env 조립 — 미구성 의존성은 fail-fast(NFR-NV2-1)."""
    from backend.config import Settings
    from backend.db import make_engine, make_session_factory

    from .adapters.local_wiring import build_llm, build_queue, build_store, build_tool_registry

    settings = NoveltySettings.from_env()
    if not settings.queue_configured:
        raise SystemExit("novelty worker: job queue is not configured")
    if not settings.llm_configured:
        raise SystemExit("novelty worker: LLM provider is not configured")
    app_settings = Settings.from_env()
    database_url = app_settings.database_url
    if not database_url or not database_url.startswith(
        ("postgresql://", "postgresql+psycopg://", "postgres://")
    ):
        raise SystemExit("novelty worker: postgres DATABASE_URL is required")
    session_factory = make_session_factory(make_engine(database_url))
    store = build_store(session_factory)
    queue = build_queue(settings)
    llm = build_llm(settings)
    orchestrator, grounding_hook = _build_corpus_deps()
    evidence_port = _build_evidence_port()
    registry = build_tool_registry(
        settings,
        orchestrator=orchestrator,
        grounding_hook=grounding_hook,
        evidence_port=evidence_port,
    )
    return WorkerDeps(store=store, queue=queue, llm=llm, registry=registry, settings=settings)


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
