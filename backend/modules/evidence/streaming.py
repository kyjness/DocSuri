"""U11 턴 이벤트 스트림 — 수락된 턴의 진행을 SSE로(v3 §5.3).

원천은 Postgres다. API가 여러 태스크로 뜨고 실행자는 또 다른 프로세스일 수 있으므로,
이벤트는 실행자가 커밋한 `evidence_trace` 행과 턴 행의 상태를 **tail**해서 만든다 —
프로세스 안의 큐로는 재접속이 살지 않는다. 폴링 간격(기본 1초)이 곧 지연이다.

novelty/streaming.py의 프레이밍(`event: progress\\ndata: {...}`)과 wire shape
(eventId/state/message/payload/createdAt)을 그대로 계승해 FE 파서를 공유한다. eventId는
결정적이다(`{turn_id}:{seq}`) — 재접속(`after=seq`)에서 같은 줄이 두 번 그려지지 않는다.

스트리밍 타이밍(INV-EV-3/C-2): 진행 이벤트는 단계명·건수만 싣는다 — claim/quote 텍스트는
검증이 끝난 뒤 터미널 `result` 이벤트로만 나간다.

NFR-O1: 첫 **진행** 프레임까지의 지연(evidence.stream.first_token_ms)·클라이언트 중단
(evidence.stream.abort)을 citation.graph.*와 동일한 fail-soft 계약으로 계측한다. `accepted`는
접속 즉시 동기로 나가므로 재는 의미가 없다 — 그것으로 재면 이 지표는 구조적으로 0이 되어
절대 회귀하지 않는다(즉 아무것도 못 잡는다).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from typing import Any

from docsuri_shared.observability import emit_metric
from fastapi.concurrency import run_in_threadpool

from .ports.tools import (
    TOOL_CORPUS_SEARCH,
    TOOL_EXTRACT_EVIDENCE,
    TOOL_FETCH_PAPER,
    TOOL_LIVE_LOOKUP,
    TOOL_READ_PAPER,
    TOOL_VIEW_FIGURE,
)

logger = logging.getLogger(__name__)

# 이 스트림의 계측 표면 — 태그 값이 대시보드 키다.
_SURFACE = 'evidence_turn_events'

# 단계 → FE timeline 라벨(novelty progress처럼 message가 곧 라벨).
#
# **단계는 도구 이름이다.** 종전에는 트레이스 행 전부가 stage='tool'로 나가 화면에
# "도구 실행"만 여덟 줄 쌓였다 — 진행 표시가 진행을 안 알려주고 "뭔가 돌고 있다"만
# 알려줬다. 어휘의 정본은 `ports.tools`이고, 여기 없는 이름은 stage 문자열이 그대로
# 라벨이 된다(도구가 늘어도 화면이 빈칸을 내지 않는다).
STAGE_LABELS = {
    'accepted': '질문 접수',
    TOOL_CORPUS_SEARCH: '논문 검색',
    TOOL_LIVE_LOOKUP: '코퍼스 밖 조회',
    TOOL_FETCH_PAPER: '본문 가져오기',
    TOOL_READ_PAPER: '본문 읽기',
    TOOL_VIEW_FIGURE: '그림 확인',
    TOOL_EXTRACT_EVIDENCE: '근거 추출',
}

# CloudFront 원본 유휴 타임아웃(30s) 아래로 — 조용한 구간에도 연결이 살아 있어야 한다.
PING_INTERVAL_SECONDS = 15.0
# 한 연결의 상한. 넘으면 닫고 클라이언트가 `after`로 다시 붙는다.
MAX_STREAM_SECONDS = 600.0


def progress_event(
    stage: str, payload: dict[str, Any] | None = None, *, event_id: str
) -> dict[str, Any]:
    """novelty ProgressEvent와 동일한 wire shape — FE mapProgressEvent 재사용."""
    return {
        'eventId': event_id,
        'state': 'running',
        'stage': stage,
        'message': STAGE_LABELS.get(stage, stage),
        'payload': payload or {},
        'createdAt': datetime.now(UTC).isoformat(),
    }


def encode_sse(event: str, data: dict[str, Any]) -> str:
    return f'event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n'


# 한 번의 폴링 결과 — (새 트레이스 행들, 종단 결과 또는 None).
PollFn = Callable[[int], tuple[list[dict[str, Any]], dict[str, Any] | None]]


async def turn_events_stream(
    poll: PollFn,
    *,
    turn_id: str,
    session_id: str,
    after_seq: int = 0,
    poll_seconds: float = 1.0,
    observability: Any = None,
) -> AsyncIterator[str]:
    """턴 하나의 진행을 끝까지(또는 상한까지) SSE로 흘린다.

    `poll(after_seq)`는 동기 함수다 — 스레드풀에서 돌며 **자기 세션을 열고 닫는다**(요청
    스코프 세션을 스트림 내내 쥐면 풀 연결이 스트림 수만큼 묶인다). 첫 프레임(accepted)은
    폴링 전에 나간다 — 수락 직후 침묵 금지.
    """
    started = time.monotonic()
    tags = {'surface': _SURFACE}
    cursor = after_seq
    last_frame = started
    first_progress = False
    try:
        if cursor == 0:
            yield encode_sse('progress', progress_event(
                'accepted', {'sessionId': session_id, 'turnId': turn_id, 'seq': 0},
                event_id=f'{turn_id}:accepted',
            ))
        while True:
            rows, terminal = await run_in_threadpool(poll, cursor)
            for row in rows:
                seq = int(row.get('seq', 0))
                cursor = max(cursor, seq)
                if not first_progress:
                    first_progress = True
                    emit_metric(observability, 'evidence.stream.first_token_ms',
                                (time.monotonic() - started) * 1000.0, tags)
                yield encode_sse('progress', progress_event(
                    str(row.get('tool') or 'tool'), {**row, 'turnId': turn_id},
                    event_id=f'{turn_id}:{seq}',
                ))
                last_frame = time.monotonic()
            if terminal is not None:
                yield encode_sse('result', terminal)
                emit_metric(observability, 'evidence.stream.completed', 1.0, tags)
                return
            now = time.monotonic()
            if now - started > MAX_STREAM_SECONDS:
                # 상한 — 클라이언트가 after=cursor로 다시 붙는다(FE 복구 사다리).
                return
            if now - last_frame >= PING_INTERVAL_SECONDS:
                yield ': ping\n\n'
                last_frame = now
            await asyncio.sleep(poll_seconds)
    except (asyncio.CancelledError, GeneratorExit):
        # 클라이언트 중단/연결 끊김 — NFR-O1 중단율. 실행자는 영향 없다(턴은 계속 돈다).
        emit_metric(observability, 'evidence.stream.abort', 1.0, tags)
        raise
    except Exception:  # noqa: BLE001 — fail-closed: 내부 상세 비노출(SEC-9/INV-EV-5)
        logger.exception('evidence turn events stream failed (turn=%s)', turn_id)
        emit_metric(observability, 'evidence.stream.error', 1.0, tags)
        yield encode_sse('error', {'message': '일시적인 오류로 진행 상황을 받지 못했습니다.'})
