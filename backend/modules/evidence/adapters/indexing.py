"""백그라운드 색인 요청 — 실시간 조회로 찾아 **실제로 쓴** 논문을 코퍼스에 올린다(§2.6 4단계).

**색인은 U1이 한다.** 여기서 하는 것은 U1의 본 큐에 `EVENT` 잡 하나를 넣는 것뿐이고
결과를 기다리지 않는다(INV-EV-7과 같은 경계). U7이 `BUILD_DOC_MODEL`을 넣는 방식과 같은
모양이며, 다른 것은 **잡 종류와 큐**다:

- `BUILD_DOC_MODEL`(우선순위 큐) — 본문만 만든다. U1 쪽 docstring이 "이 잡은 **이미 색인된**
  논문을 위한 것"이라고 명시한다. 그래서 승격만으로는 코퍼스가 자라지 않는다.
- `EVENT`(본 큐) — `ingest_one`을 태워 수집·파싱·**색인**까지 간다. 색인은 다음 질문을 위한
  것이라 지연에 민감하지 않으므로 우선순위 큐를 쓰지 않는다 — 그쪽은 사용자가 기다리는
  본문 확보용이고, 색인 잡을 섞으면 기다리는 쪽이 밀린다.

**arXiv 논문만 올린다.** `live_lookup`이 arXiv 밖 논문을 `doi:` 네임스페이스로 실어 오는데
U1의 수집 사다리는 arXiv id로 도는 것이라, 그런 잡은 만들어봐야 DLQ로 간다.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any
from uuid import uuid4

from backend.modules.paper_assets import parse_record_ref

__all__ = ["SqsPaperIndexQueue"]

log = logging.getLogger("docsuri.evidence.indexing")

# 같은 논문을 다시 올리기까지 기다리는 시간. 수집·파싱·색인이 도는 창보다 넉넉해야 한다 —
# 짧으면 색인이 끝나기 전에 다음 턴이 같은 잡을 또 넣는다. 프로세스별 best-effort이고,
# 교차 인스턴스 중복은 U1의 정규 중복 제거(canonical dedup)가 흡수한다.
_DEDUP_TTL_SECONDS = 900


class SqsPaperIndexQueue:
    """`PaperIndexQueuePort` 실구현 — U1 본 큐에 `EVENT` 잡을 넣는다."""

    def __init__(
        self,
        *,
        queue_url: str,
        region_name: str | None = None,
        client: Any | None = None,
        dedup_ttl_seconds: int = _DEDUP_TTL_SECONDS,
    ) -> None:
        if client is None:
            import boto3

            client = boto3.client("sqs", region_name=region_name)
        self._sqs = client
        self._queue_url = queue_url
        self._ttl = dedup_ttl_seconds
        self._inflight: dict[str, float] = {}

    def enqueue_index(self, paper_id: str) -> None:
        ref = _arxiv_ref(paper_id)
        if ref is None:
            # arXiv 밖 논문 — 올려봐야 U1이 못 받는다. 조용히 건너뛰는 것이 맞다(오류가 아니다).
            return

        now = time.monotonic()
        self._prune(now)
        # 중복 제거는 **잡이 나르는 신원**(버전 붙은 ref)으로 한다 — 철자가 갈라지면 같은
        # 논문이 두 버킷을 쓰고 dedup이 없는 것과 같아진다(U7 어댑터와 같은 근거).
        expiry = self._inflight.get(ref)
        if expiry is not None and expiry > now:
            return

        body = json.dumps(
            {
                "jobId": f"evidence-index-{ref}-{uuid4().hex[:8]}",
                "kind": "EVENT",
                "arxivRef": ref,
                "eventId": None,
                "correlationId": None,
            }
        )
        try:
            self._sqs.send_message(QueueUrl=self._queue_url, MessageBody=body)
        except Exception:  # noqa: BLE001 — 색인은 다음 질문을 위한 것이라 이 턴을 깨지 않는다
            log.warning("evidence index enqueue failed for %s", ref, exc_info=True)
            return
        self._inflight[ref] = now + self._ttl
        log.info("evidence: queued %s for background indexing", ref)

    def _prune(self, now: float) -> None:
        for key, expiry in list(self._inflight.items()):
            if expiry <= now:
                del self._inflight[key]


def _arxiv_ref(paper_id: str) -> str | None:
    """`arxiv:2304.10557v3` → `2304.10557v3`. arXiv id가 아니면 None.

    버전이 없으면 v1로 요청한다 — U1의 `arxivRef`는 버전이 필수이고, 실시간 조회는 버전을
    박아 보내므로 대개 명시돼 있다.
    """
    from .tools import promotable

    if not promotable(paper_id):
        return None
    parsed = parse_record_ref(paper_id)
    if parsed is None:
        return None
    bare, version = parsed
    return f"{bare}v{version or 1}"
