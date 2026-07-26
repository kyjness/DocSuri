"""잡 큐 포트 — 적재·소비·실행 잠금(NFR-NV2-1~3).

잠금은 리스 기반(TTL) 계약이다: redis SET NX EX와 SQS visibility timeout이
같은 계약을 만족한다 — 만료된 리스는 다른 워커가 회수할 수 있어야 하고(stale
잡 감지), 갱신(renew)으로 장기 실행을 유지한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

__all__ = ["KIND_LOOP", "KIND_TURN", "ExecutionLockPort", "JobQueuePort", "QueuedJob"]

KIND_LOOP = "loop"
KIND_TURN = "turn"


@dataclass(frozen=True, slots=True)
class QueuedJob:
    job_id: str
    owner_id: str
    receipt: str | None = None  # 큐 구현별 ack 핸들(SQS receipt 등)
    # "loop"(자율 조사 실행) 또는 "turn"(종단 잡의 온디맨드 대화 한 턴).
    # 기본값이 loop이므로 이 필드가 없는 기존 페이로드도 그대로 해석된다.
    kind: str = KIND_LOOP
    message_id: str | None = None  # turn일 때 처리 대상 사용자 메시지

    # 직렬 페이로드는 어댑터 간 호환 계약이다(redis↔SQS 전환·인플라이트 생존) —
    # 인코딩·디코딩을 여기 한 곳에만 두고 어댑터는 전송만 담당한다.
    def to_payload(self) -> dict[str, Any]:
        body: dict[str, Any] = {"job_id": self.job_id, "owner_id": self.owner_id}
        # loop은 생략한다 — 배포 시점에 큐에 남아 있던 기존 페이로드와 모양이 같아
        # 인플라이트 메시지가 그대로 소비된다(from_payload가 부재 시 loop으로 읽는다).
        if self.kind != KIND_LOOP:
            body["kind"] = self.kind
        if self.message_id is not None:
            body["message_id"] = self.message_id
        return body

    @classmethod
    def from_payload(cls, data: dict[str, Any], *, receipt: str | None) -> QueuedJob:
        """손상 페이로드는 KeyError/ValueError로 표면화 — 폐기 정책은 어댑터 몫."""
        message_id = data.get("message_id")
        return cls(
            job_id=str(data["job_id"]),
            owner_id=str(data["owner_id"]),
            receipt=receipt,
            kind=str(data.get("kind") or KIND_LOOP),
            message_id=str(message_id) if message_id is not None else None,
        )


class JobQueuePort(Protocol):
    def enqueue(
        self,
        job_id: str,
        owner_id: str,
        *,
        kind: str = KIND_LOOP,
        message_id: str | None = None,
    ) -> None: ...

    def consume(self, timeout_seconds: float) -> QueuedJob | None: ...

    def ack(self, job: QueuedJob) -> None: ...

    def nack(self, job: QueuedJob) -> None:
        """처리하지 않은 메시지를 즉시 재전달 가능 상태로 되돌린다.

        ack 생략만으로는 부족하다 — SQS는 visibility 만료로 스스로 재전달하지만
        redis 구현은 소비 시점에 processing 리스트로 옮겨두므로, 되돌리지 않으면
        워커 재시작(recover_processing) 전까지 메시지가 방치된다. 재적재 위치는
        큐의 끝이어야 한다(FIFO 유지 — 같은 메시지를 즉시 다시 집지 않도록).
        """
        ...


class ExecutionLockPort(Protocol):
    """job_id 단위 실행 잠금 — 이중 실행 방지(멱등)."""

    def acquire(self, job_id: str, ttl_seconds: float) -> bool: ...

    def renew(self, job_id: str, ttl_seconds: float) -> bool: ...

    def release(self, job_id: str) -> None: ...
