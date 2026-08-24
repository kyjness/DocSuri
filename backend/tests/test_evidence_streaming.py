"""v3 §5.3 — 턴 이벤트 SSE(GET /turns/{id}/events)는 Postgres 트레이스 행을 tail한다.

검증 대상:
- 접속 즉시 `accepted` 프레임(수락 직후 침묵 금지) → 트레이스 행이 `tool` 프레임으로 →
  턴이 종단이면 `result` 프레임(TurnOut wire shape) 후 종료.
- eventId가 결정적(`{turn}:{seq}`)이라 `after=` 재접속에서 같은 줄이 두 번 나오지 않는다.
- C-2/INV-EV-3 — 터미널 이전 어떤 프레임에도 claim/quote 텍스트가 실리지 않는다.
- 조용한 구간은 `: ping` 주석으로 연결을 유지하고, 상한을 넘으면 닫는다(재접속 좌표는 after).
- NFR-O1 — first-token·completed·abort·error 메트릭(evidence.stream.*).
"""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from uuid import uuid4

from docsuri_shared.authz import Principal, UserRole
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.config import Settings
from backend.modules.evidence import controller
from backend.modules.evidence import streaming as streaming_mod
from backend.modules.evidence.domain.models import ToolCallOutcome, ToolCallRecord
from backend.modules.evidence.models import TurnSuccessResult
from backend.modules.evidence.repository import InMemoryEvidenceRepository
from backend.modules.evidence.settings import TurnExecutionSettings
from backend.modules.evidence.streaming import turn_events_stream
from backend.modules.evidence.worker import process_sqs_payload

CLAIM_STATEMENT = '벤치마크 재사용은 데이터 누수 위험을 높인다.'
CLAIM_QUOTE = 'benchmark reuse inflates scores through leakage'


def _principal(user_id: str | None = None) -> Principal:
    return Principal(user_id=user_id or str(uuid4()), role=UserRole.USER)


def _success_result() -> TurnSuccessResult:
    from docsuri_shared._generated.dtos.evidence_schema import (
        EvidenceCoverage,
        EvidenceItem,
        EvidenceResult,
        SourceRef,
    )

    return TurnSuccessResult(
        outcome=EvidenceResult(
            state='ok',
            claims=[
                EvidenceItem(
                    statement=CLAIM_STATEMENT,
                    supporting=[
                        SourceRef(
                            paperId='2401.01234',
                            recordRef='rec-1',
                            anchor='s4.p2',
                            quote=CLAIM_QUOTE,
                        )
                    ],
                    conflicting=[],
                )
            ],
            coverage=EvidenceCoverage(paperCount=1, queryUsed='benchmark reuse'),
        )
    )


class _TracingStubRunner:
    """도구 트레이스를 흘린 뒤 검증 완료 결과를 반환하는 러너 스텁 — 활동 피드는
    결정 트레이스에서 파생된다(FD 게이트 Q7=A)."""

    def run(self, ctx, request, *, attachments=(), on_trace=None, should_stop=None):
        if on_trace is not None:
            for seq, (tool, summary) in enumerate(
                [('corpus_search', 'query=protein'), ('extract_evidence', 'paper_ids=p1')], 1
            ):
                on_trace(
                    ToolCallRecord(
                        seq=seq,
                        tool=tool,
                        args_summary=summary,
                        outcome=ToolCallOutcome.OK,
                        result_summary=f'{tool}: ok',
                    )
                )
        return _success_result()


def _client(monkeypatch, principal: Principal, repo, runner, *, run_inline=True) -> TestClient:
    monkeypatch.setenv('EVIDENCE_AGENT_ENABLED', 'true')
    app = create_app(Settings(env='test', database_url='sqlite://'))
    app.dependency_overrides[controller.get_principal] = lambda: principal
    app.dependency_overrides[controller.get_repo] = lambda: repo
    app.dependency_overrides[controller.get_repo_factory] = lambda: (lambda: repo)
    app.dependency_overrides[controller.get_checkpoints] = lambda: None
    app.state.evidence_execution = TurnExecutionSettings(
        stale_after=timedelta(seconds=600), poll_seconds=0.01
    )

    def dispatch(payload: dict) -> None:
        if run_inline:
            process_sqs_payload(lambda: repo, payload, runner=runner)

    app.dependency_overrides[controller.get_dispatch] = lambda: dispatch
    return TestClient(app)


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    frames: list[tuple[str, dict]] = []
    for block in text.strip().split('\n\n'):
        event, data = 'message', []
        for line in block.split('\n'):
            if line.startswith('event:'):
                event = line[len('event:'):].strip()
            if line.startswith('data:'):
                data.append(line[len('data:'):].strip())
        if data:
            frames.append((event, json.loads('\n'.join(data))))
    return frames


# ---------------------------------------------------------------------------
# API: GET /api/evidence/turns/{id}/events
# ---------------------------------------------------------------------------

def test_events_stream_replays_trace_then_validated_terminal(monkeypatch) -> None:
    principal = _principal()
    repo = InMemoryEvidenceRepository()
    client = _client(monkeypatch, principal, repo, _TracingStubRunner())

    accepted = client.post('/api/evidence/turns', json={'topic': 'benchmark reuse risks'})
    assert accepted.status_code == 202
    turn_id = accepted.json()['turnId']

    resp = client.get(f'/api/evidence/turns/{turn_id}/events')

    assert resp.status_code == 200
    assert resp.headers['content-type'].startswith('text/event-stream')
    frames = _parse_sse(resp.text)

    assert [event for event, _ in frames[:-1]] == ['progress'] * (len(frames) - 1)
    stages = [data.get('stage') for event, data in frames if event == 'progress']
    assert stages == ['accepted', 'tool', 'tool']
    first = frames[0][1]
    assert first['eventId'] == f'{turn_id}:accepted'
    assert first['payload']['sessionId'] == accepted.json()['sessionId']
    assert first['payload']['turnId'] == turn_id

    feed = [data for event, data in frames if event == 'progress' and data.get('stage') == 'tool']
    assert [item['payload']['tool'] for item in feed] == ['corpus_search', 'extract_evidence']
    assert [item['eventId'] for item in feed] == [f'{turn_id}:1', f'{turn_id}:2']
    assert [item['payload']['seq'] for item in feed] == [1, 2]
    # 호출 인자가 함께 실린다 — 결과만 보이면 모델이 같은 질의를 반복한다.
    assert feed[0]['payload']['argsSummary'] == 'query=protein'

    terminal_event, terminal = frames[-1]
    assert terminal_event == 'result'
    # 터미널 페이로드 = 폴링 경로와 동일한 TurnOut wire shape (계약 불변).
    assert terminal['result']['state'] == 'ok'
    assert terminal['result']['claims'][0]['statement'] == CLAIM_STATEMENT
    assert terminal['result']['claims'][0]['supporting'][0]['quote'] == CLAIM_QUOTE
    assert terminal['turnId'] == turn_id


def test_events_stream_after_cursor_skips_what_the_client_already_has(monkeypatch) -> None:
    """재접속은 `after=seq`로 — accepted도 다시 오지 않고, seq ≤ after는 빠진다."""
    principal = _principal()
    repo = InMemoryEvidenceRepository()
    client = _client(monkeypatch, principal, repo, _TracingStubRunner())
    turn_id = client.post('/api/evidence/turns', json={'topic': 'q'}).json()['turnId']

    frames = _parse_sse(client.get(f'/api/evidence/turns/{turn_id}/events?after=1').text)

    assert [(e, d.get('stage')) for e, d in frames] == [('progress', 'tool'), ('result', None)]
    assert frames[0][1]['eventId'] == f'{turn_id}:2'


def test_events_stream_exposes_no_claim_text_before_terminal(monkeypatch) -> None:
    """C-2/INV-EV-3 — 검증 전 claim/quote 텍스트는 어떤 pre-terminal 프레임에도 없다."""
    principal = _principal()
    client = _client(monkeypatch, principal, InMemoryEvidenceRepository(), _TracingStubRunner())
    turn_id = client.post('/api/evidence/turns', json={'topic': 'q'}).json()['turnId']

    body = client.get(f'/api/evidence/turns/{turn_id}/events').text
    terminal_at = body.index('event: result')
    pre_terminal = body[:terminal_at]
    assert CLAIM_STATEMENT not in pre_terminal
    assert CLAIM_QUOTE not in pre_terminal
    assert CLAIM_STATEMENT in body[terminal_at:]


def test_events_stream_is_owner_scoped(monkeypatch) -> None:
    """INV-EV-1 — 남의 턴·없는 턴은 스트림이 아니라 404다."""
    owner = _principal()
    repo = InMemoryEvidenceRepository()
    client = _client(monkeypatch, owner, repo, _TracingStubRunner())
    turn_id = client.post('/api/evidence/turns', json={'topic': 'q'}).json()['turnId']

    client.app.dependency_overrides[controller.get_principal] = lambda: _principal()
    assert client.get(f'/api/evidence/turns/{turn_id}/events').status_code == 404
    assert client.get('/api/evidence/turns/nope/events').status_code == 404


def test_events_stream_does_not_lose_a_trace_row_committed_just_before_the_result(monkeypatch):
    """폴링은 상태를 먼저 읽는다 — 행을 먼저 읽으면 그 사이 커밋된 마지막 행이 영영 안 흐른다."""
    principal = _principal()
    repo = InMemoryEvidenceRepository()
    runner = _TracingStubRunner()
    client = _client(monkeypatch, principal, repo, runner, run_inline=False)
    turn_id = client.post('/api/evidence/turns', json={'topic': 'q'}).json()['turnId']
    session_id = repo.get_turn(principal.user_id, turn_id).session_id

    # 첫 트레이스 조회 **직후**에 실행자가 트레이스 2건과 결과를 전부 커밋한다. 상태를 먼저
    # 읽는 구현은 이번 폴에서 pending·빈 행을 보고, 다음 폴에서 종단·행 2건을 함께 본다.
    original = repo.list_trace_after
    fired = {'done': False}

    def racing_list(owner_id, tid, after_seq):
        rows = original(owner_id, tid, after_seq)
        if tid == turn_id and not fired['done']:
            fired['done'] = True
            process_sqs_payload(
                lambda: repo,
                {'ownerId': owner_id, 'sessionId': session_id, 'turnId': tid, 'topic': 'q'},
                runner=runner,
            )
        return rows

    monkeypatch.setattr(repo, 'list_trace_after', racing_list)

    frames = _parse_sse(client.get(f'/api/evidence/turns/{turn_id}/events').text)
    tool_seqs = [
        d['payload']['seq'] for e, d in frames if e == 'progress' and d.get('stage') == 'tool'
    ]
    assert tool_seqs == [1, 2]
    assert frames[-1][0] == 'result'


# ---------------------------------------------------------------------------
# 단위: turn_events_stream — 폴링·핑·상한·메트릭(fail-soft)
# ---------------------------------------------------------------------------

class _Hub:
    def __init__(self) -> None:
        self.metrics: list[tuple[str, float, dict]] = []

    def emit_metric(self, name: str, value: float, tags: dict) -> None:
        self.metrics.append((name, value, tags))

    def names(self) -> list[str]:
        return [name for name, _, _ in self.metrics]


def _collect(stream) -> list[str]:
    async def run() -> list[str]:
        return [chunk async for chunk in stream]

    return asyncio.run(run())


def test_stream_emits_accepted_before_the_first_poll_and_tails_rows() -> None:
    hub = _Hub()
    polls: list[int] = []
    script = iter([([{'seq': 1, 'tool': 'corpus_search'}], None),
                   ([], None),
                   ([{'seq': 2, 'tool': 'extract_evidence'}], {'turnId': 't1', 'done': True})])

    def poll(after_seq: int):
        polls.append(after_seq)
        return next(script)

    chunks = _collect(turn_events_stream(
        poll, turn_id='t1', session_id='s1', poll_seconds=0.001, observability=hub
    ))

    assert chunks[0].startswith('event: progress') and '"accepted"' in chunks[0]
    assert chunks[-1].startswith('event: result')
    assert polls == [0, 1, 1]  # 커서는 마지막으로 흘린 seq
    assert hub.names() == ['evidence.stream.first_token_ms', 'evidence.stream.completed']
    assert hub.metrics[0][2] == {'surface': 'evidence_turn_events'}
    # 첫 tool 프레임까지의 지연이다 — accepted로 재면 구조적으로 0이라 아무것도 못 잡는다.
    assert hub.metrics[0][1] > 0


def test_stream_pings_when_quiet_and_closes_at_the_cap(monkeypatch) -> None:
    """조용해도 연결은 살아 있어야 하고(CloudFront 유휴 30s), 상한을 넘으면 닫는다."""
    monkeypatch.setattr(streaming_mod, 'PING_INTERVAL_SECONDS', 0.0)
    monkeypatch.setattr(streaming_mod, 'MAX_STREAM_SECONDS', 0.05)
    hub = _Hub()

    chunks = _collect(turn_events_stream(
        lambda after: ([], None), turn_id='t1', session_id='s1', poll_seconds=0.01,
        observability=hub,
    ))

    assert chunks[0].startswith('event: progress')
    assert ': ping' in ''.join(chunks[1:])
    assert not any(c.startswith('event: result') for c in chunks)
    assert 'evidence.stream.completed' not in hub.names()
    # 진행 프레임이 하나도 없었으므로 first_token도 없다(0을 찍지 않는다).
    assert 'evidence.stream.first_token_ms' not in hub.names()


def test_stream_client_abort_emits_abort_metric() -> None:
    """NFR-O1 — 클라이언트 중단(연결 끊김) 카운트: evidence.stream.abort."""
    hub = _Hub()

    async def scenario() -> None:
        stream = turn_events_stream(
            lambda after: ([], None), turn_id='t1', session_id='s1', poll_seconds=0.01,
            observability=hub,
        )
        first = await anext(stream)
        assert first.startswith('event: progress')
        await stream.aclose()  # StreamingResponse가 제너레이터를 닫는 경로

    asyncio.run(scenario())

    assert 'evidence.stream.abort' in hub.names()
    assert 'evidence.stream.completed' not in hub.names()


def test_stream_failure_yields_error_frame_without_internals() -> None:
    """fail-closed(SEC-9/INV-EV-5) — 내부 예외는 비기술 error 프레임으로만 노출."""
    hub = _Hub()

    def poll(after_seq: int):
        raise RuntimeError('postgres exploded: secret-dsn-123')

    chunks = _collect(turn_events_stream(
        poll, turn_id='t1', session_id='s1', poll_seconds=0.01, observability=hub
    ))

    assert chunks[-1].startswith('event: error')
    assert 'secret-dsn-123' not in chunks[-1]
    assert 'RuntimeError' not in chunks[-1]
    assert 'evidence.stream.error' in hub.names()
