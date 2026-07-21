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


def test_guard_completes_permit_structurally() -> None:
    import pytest

    breaker = CircuitBreaker(failure_threshold=1)
    # 예외 이탈 → 자동 실패 마감(수동 finally 불필요).
    with pytest.raises(RuntimeError):
        with breaker.guard() as permit:
            assert permit is not None
            raise RuntimeError("dependency down")
    assert breaker.acquire() is None  # threshold 1 → OPEN

    # OPEN 중 guard는 None을 내주고, None 경로는 아무것도 마감하지 않는다.
    with breaker.guard() as permit:
        assert permit is None

    # 성공 선언 후 이탈 → 자동 마감은 no-op(멱등) — 회로가 실패로 오염되지 않는다.
    clock = _Clock()
    healthy = _breaker(clock, threshold=1)
    with healthy.guard() as permit:
        assert permit is not None
        permit.success()
    assert healthy.acquire() is not None  # CLOSED 유지


def test_neutral_completion_preserves_the_failure_count() -> None:
    """중립 완주는 카운터를 초기화하지도, 증가시키지도 않는다.

    ``success()``로 마감하면 카운터가 0이 되어, retriable 실패와 중립 결과가 섞여 들어오는
    장애에서는 임계에 영원히 도달하지 못한다 — 브레이커가 있으나 마나가 된다.
    """
    clock = _Clock()
    breaker = _breaker(clock, threshold=3)
    _fail_times(breaker, 2)

    permit = breaker.acquire()
    assert permit is not None
    permit.neutral()
    assert breaker.acquire() is not None, "중립 완주가 회로를 열어서는 안 된다"

    _fail_times(breaker, 1)  # 누적 3회째
    assert breaker.acquire() is None, "중립 완주가 앞선 실패를 지워버렸다"


def test_a_neutral_probe_releases_the_slot_without_deciding_recovery() -> None:
    """판정을 보류한 프로브는 슬롯만 반납하고 HALF-OPEN을 유지한다.

    닫으면 회복을 증명하지 못한 의존성에 전체 트래픽이 복귀하고, 열면 그 의존성 탓이 아닌
    결과로 회복 창 하나를 통째로 태운다.
    """
    clock = _Clock()
    breaker = _breaker(clock, threshold=3, recovery=30.0)
    _fail_times(breaker, 3)
    clock.now = 31.0

    probe = breaker.acquire()
    assert probe is not None
    probe.neutral()

    # 여전히 HALF-OPEN: 다음 호출자가 진짜 프로브가 되고, 그 실패 한 번이 즉시 재개방한다.
    retry = breaker.acquire()
    assert retry is not None, "슬롯이 반납되지 않아 회로가 물렸다"
    retry.failure()
    assert breaker.acquire() is None
