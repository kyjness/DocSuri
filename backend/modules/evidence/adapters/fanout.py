"""동시 호출 팬아웃 — **순서 보존이 이 모듈의 계약이다.**

evidence에는 팬아웃이 둘 있다(실시간 조회 세 소스, 추출 논문별). 둘 다 같은 것을 요구한다:
동시에 던지되 **제출 순서로** 모으고, 일부가 죽어도 나머지를 살리고, 전멸일 때만 실패다.

각자 적어 두면 그 불변식이 두 곳에서 따로 재천명된다 — 한쪽을 `as_completed`로 바꾸는
최적화가 들어오면 다른 쪽은 그대로고, 깨지는 것은 화면의 근거 번호 `[n]`이다(예외 없이
조용히). summarization의 `map_bounded`는 fail-fast라 부분 실패를 못 담아 그대로는 못 쓴다.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import TypeVar

__all__ = ["fan_out"]

T = TypeVar("T")


def fan_out(
    calls: Sequence[Callable[[], T]], *, max_workers: int
) -> tuple[list[T], list[Exception]]:
    """`calls`를 동시에 돌려 `(성공분, 실패분)`을 돌려준다.

    성공분은 **제출 순서**다 — 완료 순서로 모으면 실행마다 결과 순서가 달라진다.
    실패는 던지지 않고 모아서 돌려준다: "전부 죽었는가"와 "일부가 죽었는가"는 호출자마다
    다른 판정이라(실시간 조회는 부분 저하를 결과로 나르고, 추출은 모델에게 알린다) 여기서
    정하지 않는다.

    `max_workers`는 **상한이지 목표가 아니다.** 호출 수가 그보다 적으면 그만큼만 쓴다.
    상한을 두는 이유는 같은 모델 엔드포인트에 동시 요청이 몰리면 스로틀을 부르기 때문이다 —
    이 저장소는 직렬 호출로도 거기 물린 이력이 있다.
    """
    if not calls:
        return [], []
    if len(calls) == 1:
        # 나눌 것이 없으면 스레드풀을 만들지 않는다. `max_workers=0`이 ValueError를
        # 내는 것도 여기서 함께 막힌다.
        try:
            return [calls[0]()], []
        except Exception as exc:  # noqa: BLE001 — 호출자가 판정한다
            return [], [exc]

    results: list[T] = []
    failures: list[Exception] = []
    with ThreadPoolExecutor(max_workers=min(len(calls), max(1, max_workers))) as pool:
        for future in [pool.submit(call) for call in calls]:
            try:
                results.append(future.result())
            except Exception as exc:  # noqa: BLE001 — 호출자가 판정한다
                failures.append(exc)
    return results, failures
