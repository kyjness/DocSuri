"""백그라운드 색인(설계 v3 §2.6 4단계) — "쓸수록 코퍼스가 그쪽으로 자란다".

없으면 같은 논문을 매 턴 실시간으로 다시 조회하고 코퍼스는 영원히 자라지 않는다. 승격만으로는
안 된다 — U1의 `BUILD_DOC_MODEL`은 본문만 만들고, 그 docstring이 "이 잡은 **이미 색인된**
논문을 위한 것"이라고 명시한다.
"""

from __future__ import annotations

import json
from typing import Any

from backend.modules.evidence.adapters.indexing import SqsPaperIndexQueue
from backend.modules.evidence.domain.models import LoopState, PaperHandle, PaperOrigin
from backend.modules.evidence.runner import _queue_for_indexing


class _Sqs:
    def __init__(self, fails: bool = False) -> None:
        self.sent: list[dict[str, Any]] = []
        self.fails = fails

    def send_message_batch(self, *, QueueUrl: str, Entries: list) -> dict:  # noqa: N803 — boto3
        if self.fails:
            raise RuntimeError("sqs down")
        self.sent += [json.loads(e["MessageBody"]) for e in Entries]
        return {"Failed": []}


def _queue(sqs: _Sqs, **kw: Any) -> SqsPaperIndexQueue:
    return SqsPaperIndexQueue(queue_url="https://q", client=sqs, **kw)


# --- 잡 모양 -------------------------------------------------------------------


def test_the_job_is_an_EVENT_not_a_doc_model_build():
    """`BUILD_DOC_MODEL`은 본문만 만든다 — 그것만 넣으면 코퍼스가 자라지 않는다.
    `EVENT`가 `ingest_one`을 태워 수집·파싱·색인까지 간다."""
    sqs = _Sqs()

    _queue(sqs).enqueue_index(["arxiv:2304.10557v3"])

    assert len(sqs.sent) == 1
    assert sqs.sent[0]["kind"] == "EVENT"
    assert sqs.sent[0]["arxivRef"] == "2304.10557v3"
    assert sqs.sent[0]["jobId"]


def test_a_bare_id_is_versioned_because_u1_requires_it():
    sqs = _Sqs()

    _queue(sqs).enqueue_index(["2106.09685"])

    assert sqs.sent[0]["arxivRef"] == "2106.09685v1"


def test_a_non_arxiv_paper_is_never_queued():
    """`live_lookup`이 `doi:`로 실어 오는 논문은 U1의 수집 사다리가 arXiv id로 도는 탓에
    잡을 만들어봐야 DLQ로 간다."""
    sqs = _Sqs()

    _queue(sqs).enqueue_index(["doi:10.1145/abc", "userdoc:abc"])

    assert sqs.sent == []


# --- 중복·실패 -----------------------------------------------------------------


def test_the_same_paper_is_not_queued_twice_in_a_window():
    sqs = _Sqs()
    queue = _queue(sqs)

    queue.enqueue_index(["arxiv:2304.10557v3"])
    queue.enqueue_index(["arxiv:2304.10557v3"])

    assert len(sqs.sent) == 1


def test_different_versions_are_different_papers():
    """v1과 v3은 다른 산출물이다 — 하나로 접으면 개정본이 영영 색인되지 않는다."""
    sqs = _Sqs()
    queue = _queue(sqs)

    queue.enqueue_index(["arxiv:2304.10557v1", "arxiv:2304.10557v3"])

    assert [m["arxivRef"] for m in sqs.sent] == ["2304.10557v1", "2304.10557v3"]


def test_the_window_expires():
    sqs = _Sqs()
    queue = _queue(sqs, dedup_ttl_seconds=0)

    queue.enqueue_index(["arxiv:2304.10557v3"])
    queue.enqueue_index(["arxiv:2304.10557v3"])

    assert len(sqs.sent) == 2


def test_a_queue_outage_is_swallowed():
    """색인은 **다음** 질문을 위한 것이라 이 턴의 답에 아무 영향이 없다."""
    _queue(_Sqs(fails=True)).enqueue_index(["arxiv:2304.10557v3"])


def test_a_failed_send_is_not_remembered_as_sent():
    """실패를 dedup 창에 넣으면 그 논문은 창이 만료될 때까지 영영 재시도되지 않는다."""
    sqs = _Sqs(fails=True)
    queue = _queue(sqs)
    queue.enqueue_index(["arxiv:2304.10557v3"])

    sqs.fails = False
    queue.enqueue_index(["arxiv:2304.10557v3"])

    assert len(sqs.sent) == 1


# --- 러너가 무엇을 올리나 --------------------------------------------------------


class _Recording:
    def __init__(self) -> None:
        self.ids: list[str] = []

    def enqueue_index(self, paper_ids: list[str]) -> None:
        self.ids += paper_ids


class _Boom:
    def enqueue_index(self, paper_ids: list[str]) -> None:
        raise RuntimeError("nope")


def _seeded_state() -> LoopState:
    """확인·후보·출처가 섞인 상태 — `_queue_for_indexing`이 무엇을 고르는지 보는 재료."""
    state = LoopState(topic="q")
    state.examine(
        PaperHandle("arxiv:2401.00001v1", "r", PaperOrigin.EXTERNAL, title="확인한 외부 논문")
    )
    state.examine(PaperHandle("2106.09685", "r", PaperOrigin.CORPUS, title="코퍼스 논문"))
    state.examine(PaperHandle("attachment:x", "r", PaperOrigin.ATTACHMENT, title="첨부"))
    state.discovered["arxiv:2402.00002v1"] = PaperHandle(
        "arxiv:2402.00002v1", "r", PaperOrigin.EXTERNAL, title="안 열어본 후보"
    )
    return state


def test_only_examined_external_papers_are_queued():
    """검색 히트를 전부 올리면 질의 한 번에 열 편이 큐로 가고 대부분은 열어보지도 않은
    논문이다. 코퍼스 논문은 이미 색인돼 있고, 첨부는 사적 문서라 코퍼스에 안 넣는다."""
    queue = _Recording()

    _queue_for_indexing(_seeded_state(), queue)

    assert queue.ids == ["arxiv:2401.00001v1"]


def test_nothing_to_queue_never_touches_the_queue():
    """올릴 것이 없는 턴(코퍼스 안에서만 답한 턴)이 대다수다 — 빈 호출도 왕복이다."""
    queue = _Recording()
    state = LoopState(topic="q")
    state.examine(PaperHandle("2106.09685", "r", PaperOrigin.CORPUS))

    _queue_for_indexing(state, queue)

    assert queue.ids == []


def test_no_queue_configured_is_not_an_error():
    _queue_for_indexing(_seeded_state(), None)


def test_a_broken_queue_never_breaks_the_answer():
    _queue_for_indexing(_seeded_state(), _Boom())
