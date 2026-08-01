"""온디맨드 승격 — enqueue + bounded polling(TD-EV2-5).

핵심은 "실패해도 예외가 아니다"이다. 예외를 올리면 루프가 깨지고, 그러면 초록
범위로라도 답할 수 있었던 근거까지 잃는다.
"""

from __future__ import annotations

from backend.modules.evidence.adapters.promotion import QueuedPaperPromotion
from backend.modules.evidence.domain.models import PromotionOutcome


class FakeQueue:
    def __init__(self, raises: Exception | None = None) -> None:
        self.calls: list[str] = []
        self.raises = raises

    def enqueue_build(self, paper_id: str) -> None:
        self.calls.append(paper_id)
        if self.raises:
            raise self.raises


class FakeReader:
    """`ready_after`번째 읽기부터 DocModel이 나타난다 — 워커가 늦게 끝나는 상황."""

    def __init__(self, ready_after: int | None = None, raises: Exception | None = None) -> None:
        self.ready_after = ready_after
        self.raises = raises
        self.reads = 0

    def get_doc_model(self, paper_id: str):
        self.reads += 1
        if self.raises:
            raise self.raises
        if self.ready_after is not None and self.reads >= self.ready_after:
            return {"paperId": paper_id}
        return None


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def _promotion(queue, reader, timeout=3.0):
    clock = FakeClock()
    return QueuedPaperPromotion(
        build_queue=queue,
        doc_models=reader,
        poll_timeout_seconds=timeout,
        poll_interval_seconds=0.5,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
    )


def test_already_built_paper_skips_the_queue():
    """백필·다른 소비자가 만들어 뒀으면 큐를 거치지 않는다."""
    queue = FakeQueue()
    result = _promotion(queue, FakeReader(ready_after=1)).promote("2401.00001")

    assert result.outcome == PromotionOutcome.PROMOTED
    assert queue.calls == []


def test_enqueues_then_polls_until_the_worker_finishes():
    queue = FakeQueue()
    reader = FakeReader(ready_after=3)

    result = _promotion(queue, reader).promote("2401.00001")

    assert result.outcome == PromotionOutcome.PROMOTED
    assert queue.calls == ["2401.00001"]
    assert result.doc_model == {"paperId": "2401.00001"}


def test_timeout_is_a_normal_result_not_an_exception():
    """워커 미가동·라이선스 차단·파싱 실패가 모두 여기로 수렴한다 — 후속 행동이 같다."""
    result = _promotion(FakeQueue(), FakeReader(ready_after=None)).promote("2401.00001")

    assert result.outcome == PromotionOutcome.TIMED_OUT
    assert result.doc_model is None


def test_queue_failure_falls_back_instead_of_raising():
    queue = FakeQueue(raises=RuntimeError("redis down"))

    result = _promotion(queue, FakeReader()).promote("2401.00001")

    assert result.outcome == PromotionOutcome.TIMED_OUT
    assert "queue" in result.detail


def test_reader_failure_is_treated_as_not_ready_yet():
    reader = FakeReader(raises=RuntimeError("s3 down"))

    result = _promotion(FakeQueue(), reader).promote("2401.00001")

    assert result.outcome == PromotionOutcome.TIMED_OUT


def test_zero_timeout_does_not_poll_forever():
    reader = FakeReader(ready_after=None)

    result = _promotion(FakeQueue(), reader, timeout=0.0).promote("2401.00001")

    assert result.outcome == PromotionOutcome.TIMED_OUT
    # 사전 확인 1회만 — 폴링 루프에 들어가지 않는다.
    assert reader.reads == 1
