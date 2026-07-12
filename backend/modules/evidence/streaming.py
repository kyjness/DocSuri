"""U11 sync-turn SSE streaming — US-EV2/NFR-P6 (§2 스트리밍 first-token).

novelty/streaming.py의 프레이밍(`event: progress\\ndata: {...}`)과 wire shape
(eventId/state/message/payload/createdAt)을 그대로 계승해 FE 파서를 공유한다.

스트리밍 타이밍(INV-EV-3/C-2, nfr-design-patterns §2.1): 진행(progress) 이벤트는
단계명·건수만 싣는다 — claim/quote 텍스트는 날조 금지 검증이 끝난 뒤 터미널
`result` 이벤트로만 나간다.

NFR-O1 스트리밍 건강도: first-token 지연(evidence.stream.first_token_ms)·클라이언트
중단(evidence.stream.abort)을 citation.graph.*와 동일한 fail-soft 계약으로 계측한다.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)

# orchestrator 단계 → FE timeline 라벨(novelty progress처럼 message가 곧 라벨).
STAGE_LABELS = {
    'started': '근거형성 시작',
    'scope_resolved': '질문 범위 결정',
    'papers_fetched': '관련 논문 검색',
    'extracting': '근거 추출',
    'validating': '근거 검증',
}

# (stage, payload) — payload는 단계명·건수 등 비텍스트 신호만(C-2).
ProgressFn = Callable[[str, dict[str, Any]], None]

_DONE = object()

# asyncio는 태스크를 약참조로만 유지한다 — 중단(abort) 후에도 백엔드가 턴을 끝까지
# 완결하도록(영속·과금 정합, PR #338 교훈) 강참조를 붙잡는다.
_background_runs: set[asyncio.Task] = set()


def progress_event(stage: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """novelty ProgressEvent와 동일한 wire shape — FE mapProgressEvent 재사용."""
    return {
        'eventId': f'ev-{uuid4()}',
        'state': 'running',
        'stage': stage,
        'message': STAGE_LABELS.get(stage, stage),
        'payload': payload or {},
        'createdAt': datetime.now(timezone.utc).isoformat(),
    }


def encode_sse(event: str, data: dict[str, Any]) -> str:
    return f'event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n'


async def turn_sse_stream(
    run_turn: Callable[[ProgressFn], Awaitable[Any]],
    serialize_terminal: Callable[[Any], dict[str, Any]],
    *,
    initial_events: list[dict[str, Any]] | None = None,
    observability: Any = None,
    surface: str = 'evidence_turns',
) -> AsyncIterator[str]:
    """동기 턴 실행을 SSE로 중계 — progress 이벤트 스트림 + 검증 후 터미널 result 1건.

    run_turn(emit)은 async이며 내부에서 orchestrator를 실행한다. emit은 워커 스레드에서
    호출돼도 안전하다(call_soon_threadsafe). 클라이언트가 중단해도 run_turn은 끝까지
    실행돼 턴이 영속된다(FE는 스냅샷으로 복구).
    """
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[Any] = asyncio.Queue()

    def emit(stage: str, payload: dict[str, Any]) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, progress_event(stage, payload))

    async def _run() -> Any:
        try:
            return await run_turn(emit)
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, _DONE)

    runner = asyncio.create_task(_run())
    _background_runs.add(runner)
    runner.add_done_callback(_discard_run)

    started = time.perf_counter()
    tags = {'surface': surface}
    first_token_sent = False

    def _mark_first_token() -> None:
        nonlocal first_token_sent
        if not first_token_sent:
            first_token_sent = True
            _metric(
                observability,
                'evidence.stream.first_token_ms',
                (time.perf_counter() - started) * 1000.0,
                tags,
            )

    try:
        for event in initial_events or []:
            _mark_first_token()
            yield encode_sse('progress', event)
        while True:
            item = await queue.get()
            if item is _DONE:
                break
            _mark_first_token()
            yield encode_sse('progress', item)
        result = await runner
        _mark_first_token()
        yield encode_sse('result', serialize_terminal(result))
        _metric(observability, 'evidence.stream.completed', 1.0, tags)
    except (asyncio.CancelledError, GeneratorExit):
        # 클라이언트 중단/연결 끊김 — NFR-O1 중단율. runner는 취소하지 않는다(위 주석).
        _metric(observability, 'evidence.stream.abort', 1.0, tags)
        raise
    except Exception:  # noqa: BLE001 — fail-closed: 내부 상세 비노출(SEC-9/INV-EV-5)
        logger.exception('evidence turn stream failed (surface=%s)', surface)
        _metric(observability, 'evidence.stream.error', 1.0, tags)
        yield encode_sse('error', {'message': '일시적인 오류로 답변을 생성하지 못했습니다.'})


def wants_event_stream(accept_header: str | None) -> bool:
    return 'text/event-stream' in (accept_header or '')


def _discard_run(task: asyncio.Task) -> None:
    _background_runs.discard(task)
    if not task.cancelled() and task.exception() is not None:
        logger.warning('evidence turn background run failed', exc_info=task.exception())


def _metric(hub: Any, name: str, value: float, tags: dict[str, str]) -> None:
    """citation.graph.*와 동일한 fail-soft 계약 — 관측 실패가 스트림을 깨지 않는다."""
    emit_metric = getattr(hub, 'emit_metric', None)
    if not emit_metric:
        return
    try:
        emit_metric(name, value, tags)
    except Exception:  # noqa: BLE001 - observability is advisory
        pass
