"""온디맨드 승격 — `BUILD_DOC_MODEL` enqueue + bounded polling(TD-EV2-5).

**빌드는 U1이 한다.** 이 어댑터는 요청하고 기다릴 뿐이며, DocModel을 직접 쓰지
않는다(INV-EV-7). 큐 계약·워커·reader-triggered 우선순위 큐는 이미 있고 u7이
읽기 미스에서 같은 경로를 쓴다 — 여기서 새로 만드는 것은 "기다리는 방식"뿐이다.
코디네이터 형태는 `backend/modules/user_docmodel.py`(업로드 PDF)와 같다.

**모든 실패는 정상 결과값이다.** 예외를 올리면 루프가 깨지고, 루프가 깨지면
사용자는 "초록 범위로라도 답할 수 있었던" 근거까지 잃는다. 라이선스 차단·파싱
실패·워커 미가동은 전부 호출자에게 `PromotionResult`로 돌아가고, 호출자는 그
논문을 초록 범위로 계속 쓴다(BLM §4).

관측 가능성의 한계를 하나 적어둔다: 읽기 경로만으로는 **왜** 빌드가 실패했는지
구분되지 않는다(비OA인지, 파싱이 깨졌는지, 워커가 없는지). 셋 다 "DocModel이
끝내 나타나지 않는다"로 보이므로 `timed_out`으로 수렴시킨다 — 후속 행동이 셋 다
같기 때문이다. 사유가 필요해지면 빌드 상태를 읽는 경로를 따로 열어야 한다.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from ..domain.models import PromotionOutcome
from ..ports.sources import DocModelReadPort, PromotionResult

__all__ = ["QueuedPaperPromotion"]

log = logging.getLogger("docsuri.evidence.promotion")


class QueuedPaperPromotion:
    def __init__(
        self,
        *,
        build_queue: Any,
        doc_models: DocModelReadPort,
        poll_timeout_seconds: float,
        poll_interval_seconds: float = 0.5,
        sleep: Any = time.sleep,
        monotonic: Any = time.monotonic,
    ) -> None:
        self._queue = build_queue
        self._doc_models = doc_models
        self._timeout = max(0.0, poll_timeout_seconds)
        self._interval = max(0.05, poll_interval_seconds)
        self._sleep = sleep
        self._monotonic = monotonic

    def promote(self, paper_id: str) -> PromotionResult:
        # 이미 빌드돼 있으면 큐를 거치지 않는다 — 백필·다른 소비자가 만들어 뒀을 수 있다.
        existing = self._read(paper_id)
        if existing is not None:
            return PromotionResult(outcome=PromotionOutcome.PROMOTED, doc_model=existing)

        if not self._enqueue(paper_id):
            return PromotionResult(
                outcome=PromotionOutcome.TIMED_OUT,
                detail="build queue unavailable",
            )

        deadline = self._monotonic() + self._timeout
        while True:
            remaining = deadline - self._monotonic()
            if remaining <= 0:
                break
            self._sleep(min(self._interval, remaining))
            doc_model = self._read(paper_id)
            if doc_model is not None:
                return PromotionResult(
                    outcome=PromotionOutcome.PROMOTED, doc_model=doc_model
                )

        # 빌드가 늦은 것일 수도 있다 — 다음 턴·다음 세션에서는 캐시 히트가 된다.
        log.info("evidence promotion timed out for %s", paper_id)
        return PromotionResult(
            outcome=PromotionOutcome.TIMED_OUT, detail="doc-model not ready in time"
        )

    def _enqueue(self, paper_id: str) -> bool:
        """enqueue 실패는 승격 실패이지 턴 실패가 아니다.

        큐 계약(`SqsDocModelBuildQueue.enqueue_build`)은 **버전이 필수**다 — 워커의
        BUILD_DOC_MODEL 잡이 `{bare}v{N}` arxivRef를 나른다. 접두어를 벗기고 버전이
        없으면 v1로 요청한다(외부 검색이 버전을 박아 보내므로 대개 명시돼 있다).
        """
        from backend.modules.paper_assets import parse_record_ref

        parsed = parse_record_ref(paper_id)
        if parsed is None:
            log.warning("evidence promotion: unparsable paper id %r", paper_id)
            return False
        bare, version = parsed
        try:
            self._queue.enqueue_build(bare, version or 1)
        except Exception:  # noqa: BLE001 — 큐 장애를 초록 범위 폴백으로 흡수
            log.warning("evidence promotion enqueue failed for %s", paper_id, exc_info=True)
            return False
        return True

    def _read(self, paper_id: str) -> Any | None:
        try:
            return self._doc_models.get_doc_model(paper_id)
        except Exception:  # noqa: BLE001 — 읽기 실패는 '아직 없음'과 같이 다룬다
            log.warning("evidence promotion read failed for %s", paper_id, exc_info=True)
            return None
