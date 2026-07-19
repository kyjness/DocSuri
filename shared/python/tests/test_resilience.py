"""CircuitBreaker 상태기계 — 유닛 사본 4종(U2/U7/U11/U12)을 대체하는 단일 계약.

각 유닛의 사본이 개별적으로 보증하던 성질을 전부 승계해 검증한다:
단일 프로브(U7), stale success 무시(U7), 프로브 슬롯 만료 자가 치유(U2),
연속 실패 임계·성공 리셋(공통).
"""

from __future__ import annotations

from docsuri_shared.resilience import CircuitBreaker


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _breaker(clock: _Clock, threshold: int = 3, recovery: float = 30.0) -> CircuitBreaker:
    return CircuitBreaker(
        "test", failure_threshold=threshold, recovery_seconds=recovery, clock=clock
    )


def _fail_times(breaker: CircuitBreaker, times: int) -> None:
    for _ in range(times):
        permit = breaker.acquire()
        assert permit is not None
        permit.failure()


def test_opens_after_consecutive_failures_and_recovers_via_probe() -> None:
    clock = _Clock()
    breaker = _breaker(clock)
    _fail_times(breaker, 3)
    assert breaker.acquire() is None  # OPEN — fail fast

    clock.now = 31.0
    probe = breaker.acquire()  # HALF-OPEN — 단일 프로브 슬롯
    assert probe is not None
    assert breaker.acquire() is None  # 프로브 진행 중 동시 호출 거부
    probe.success()
    assert breaker.acquire() is not None  # CLOSED 복귀


def test_failed_probe_reopens_a_fresh_window() -> None:
    clock = _Clock()
    breaker = _breaker(clock)
    _fail_times(breaker, 3)
    clock.now = 31.0
    probe = breaker.acquire()
    assert probe is not None
    probe.failure()  # 프로브 실패 → 새 창으로 재개방
    clock.now = 60.0  # 새 창(31.0 개방) 내부
    assert breaker.acquire() is None
    clock.now = 62.0
    assert breaker.acquire() is not None  # 다음 프로브


def test_success_resets_consecutive_count() -> None:
    breaker = _breaker(_Clock())
    _fail_times(breaker, 2)
    ok = breaker.acquire()
    assert ok is not None
    ok.success()
    _fail_times(breaker, 2)
    assert breaker.acquire() is not None  # 연속 3회 미도달 — CLOSED 유지


def test_stale_success_does_not_close_half_open() -> None:
    # 트립 전 승인된 늦은 성공이 프로브 밑에서 회로를 닫지 못한다(U7 보증).
    clock = _Clock()
    breaker = _breaker(clock, threshold=1)
    stale = breaker.acquire()  # CLOSED에서 승인된 느린 호출
    tripper = breaker.acquire()
    assert stale is not None and tripper is not None
    tripper.failure()  # → OPEN
    clock.now = 31.0
    probe = breaker.acquire()  # 단일 프로브
    assert probe is not None
    stale.success()  # 트립 전 호출의 늦은 성공
    assert breaker.acquire() is None  # 회로는 닫히지 않는다
    probe.success()
    assert breaker.acquire() is not None  # 프로브 판정만 회복을 결정


def test_leaked_probe_slot_self_heals_and_late_completion_is_ignored() -> None:
    # 프로브 permit을 완료하지 못하고 죽어도 회로가 영구 OPEN으로 고정되지 않는다(U2 보증).
    clock = _Clock()
    breaker = _breaker(clock)
    _fail_times(breaker, 3)
    clock.now = 31.0
    dead_probe = breaker.acquire()
    assert dead_probe is not None  # 프로브 획득… 보유자가 조용히 죽는다
    clock.now = 40.0
    assert breaker.acquire() is None  # 창 내에선 슬롯 유효
    clock.now = 62.0
    live_probe = breaker.acquire()
    assert live_probe is not None  # 만료 슬롯 회수
    dead_probe.failure()  # 죽은 프로브의 늦은 완료 — 현 프로브 판정을 방해하지 않는다
    live_probe.success()
    assert breaker.acquire() is not None  # CLOSED


def test_permit_completion_is_one_shot() -> None:
    # ``finally: permit.failure()``가 catch-all — success() 후엔 no-op이어야 한다.
    breaker = CircuitBreaker(failure_threshold=1)
    permit = breaker.acquire()
    assert permit is not None
    permit.success()
    permit.failure()
    assert breaker.acquire() is not None  # 여전히 CLOSED
