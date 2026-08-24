"""NFR-C1 — 에이전트 경로 사용자별 일일 쿼터 (evidence turn / novelty job).

Bedrock 호출을 유발하는 진입점(research 메시지 추가·evidence 직접 턴, novelty job 생성)에
사용자별 하루 한도를 건다. 글로벌 cost guard(총액 캡)와 별개로, 단일 사용자의 폭주가
전체 예산을 소진하는 걸 막는 per-user 레이어다.

한도 초과는 429 — FE는 이미 429를 'rateLimited' UserFacingError로 매핑한다(errors.ts).
Redis 장애 시 limiter는 fail-open(가용성 우선) — 글로벌 cost guard가 백스톱.
"""

from __future__ import annotations

import os

from fastapi import HTTPException, Request

from backend.middleware.rate_limit import get_shared_limiter

_EVIDENCE_DAILY_LIMIT = int(os.getenv("DOCSURI_AGENT_EVIDENCE_DAILY_LIMIT") or "30")
_NOVELTY_DAILY_LIMIT = int(os.getenv("DOCSURI_AGENT_NOVELTY_DAILY_LIMIT") or "5")
# 온디맨드 대화 턴은 잡 생성과 별도 한도다 — 같은 키를 쓰면 잡 5개를 만든 날에는
# 이미 끝난 조사에 후속 질문 하나 못 하게 된다(턴은 잡 한 번보다 훨씬 싸다).
_NOVELTY_TURN_DAILY_LIMIT = int(os.getenv("DOCSURI_AGENT_NOVELTY_TURN_DAILY_LIMIT") or "20")
# ponytail: 첫 사용 기준 고정 24h 창(달력일 아님) — 달력일 리셋이 필요해지면 교체.
_WINDOW_SECONDS = 86_400
_QUOTA_MESSAGE = "오늘의 에이전트 사용 한도에 도달했습니다. 나중에 다시 시도해 주세요."


async def enforce_evidence_turn_quota(request: Request) -> None:
    await _enforce(request, scope="evidence", limit=_EVIDENCE_DAILY_LIMIT)


async def enforce_novelty_job_quota(request: Request) -> None:
    await _enforce(request, scope="novelty", limit=_NOVELTY_DAILY_LIMIT)


async def enforce_novelty_turn_quota(request: Request) -> None:
    await _enforce(request, scope="novelty_turn", limit=_NOVELTY_TURN_DAILY_LIMIT)


async def refund_evidence_turn_quota(request: Request) -> None:
    """수락되지 못한 evidence 턴(세션 잠금 409·dispatch 실패 503)의 한도를 되돌린다."""
    await _refund(request, scope="evidence")


async def refund_novelty_turn_quota(request: Request) -> None:
    """승인된 턴이 실행에 들어가지 못했을 때 한도를 되돌린다.

    쿼터는 "LLM을 쓸 권리"를 세는 것이므로, 큐 적재 실패처럼 서버 사정으로 한 번도
    실행되지 않은 요청까지 세면 인프라 장애가 사용자의 하루치를 태운다. 되돌리기는
    best-effort다 — 실패해도 호출자의 오류 응답을 가리지 않는다."""
    await _refund(request, scope="novelty_turn")


async def _enforce(request: Request, *, scope: str, limit: int) -> None:
    principal = getattr(request.state, "principal", None)
    if principal is None:
        return  # 인증 없음 → 라우트의 401이 담당, 쿼터는 관여하지 않는다
    key = f"agent:{scope}:{principal.user_id}"
    if not await get_shared_limiter().allow(key, limit=limit, window_seconds=_WINDOW_SECONDS):
        raise HTTPException(status_code=429, detail=_QUOTA_MESSAGE)


async def _refund(request: Request, *, scope: str) -> None:
    principal = getattr(request.state, "principal", None)
    if principal is None:
        return
    await get_shared_limiter().refund(f"agent:{scope}:{principal.user_id}")
