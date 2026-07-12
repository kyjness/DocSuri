"""US-EV2/NFR-P6 — 동기 evidence 턴 SSE 스트리밍.

검증 대상(nfr-requirements §2 · nfr-design-patterns §2.1/§2.2):
- SSE 협상 시 진행(progress) 이벤트가 점진 스트리밍되고 터미널 `result` 이벤트가
  JSON 경로와 동일한(검증 완료) 턴 페이로드를 싣는다.
- C-2/INV-EV-3 — 터미널 이전 어떤 프레임에도 claim/quote 텍스트가 실리지 않는다.
- 비동기 적격(sqs_enqueue) 턴은 SSE 표면에서도 pending/jobId JSON을 그대로 반환한다.
- NFR-O1 — first-token 지연·클라이언트 중단(abort) 메트릭(evidence.stream.*).
"""

from __future__ import annotations

import asyncio
import json
from uuid import uuid4

from docsuri_shared.authz import Principal, UserRole
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.config import Settings
from backend.modules.evidence import controller
from backend.modules.evidence.models import TurnSuccessResult
from backend.modules.evidence.repository import InMemoryEvidenceRepository
from backend.modules.evidence.streaming import progress_event, turn_sse_stream
from backend.modules.research import controller as research_controller
from backend.modules.research.repository import InMemoryResearchRepository

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


class _StreamingStubOrchestrator:
    """단계 진행을 emit한 뒤 검증 완료 결과를 반환하는 동기 orchestrator 스텁."""

    def run(self, ctx, request, on_progress=None):
        if on_progress is not None:
            on_progress('scope_resolved', {'scope': 'auto', 'paperCount': 0})
            on_progress('papers_fetched', {'count': 1})
            on_progress('extracting', {'paperCount': 1})
            on_progress('validating', {'claimCount': 1})
        return _success_result()


def _client(monkeypatch, principal: Principal, repo, orchestrator) -> TestClient:
    monkeypatch.setenv('EVIDENCE_AGENT_ENABLED', 'true')
    app = create_app(Settings(env='test', database_url='sqlite://'))
    app.dependency_overrides[controller.get_principal] = lambda: principal
    app.dependency_overrides[controller.get_repo] = lambda: repo
    app.dependency_overrides[controller.get_orchestrator] = lambda: orchestrator
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
# API: POST /api/evidence/turns (Accept: text/event-stream)
# ---------------------------------------------------------------------------

def test_sse_turn_streams_stages_then_validated_terminal(monkeypatch) -> None:
    principal = _principal()
    repo = InMemoryEvidenceRepository()
    client = _client(monkeypatch, principal, repo, _StreamingStubOrchestrator())

    resp = client.post(
        '/api/evidence/turns',
        json={'topic': 'benchmark reuse risks', 'scope': 'auto'},
        headers={'accept': 'text/event-stream'},
    )

    assert resp.status_code == 200
    assert resp.headers['content-type'].startswith('text/event-stream')
    frames = _parse_sse(resp.text)

    # 진행 이벤트가 먼저, 터미널 result가 마지막 1건.
    assert [event for event, _ in frames[:-1]] == ['progress'] * (len(frames) - 1)
    stages = [data.get('stage') for event, data in frames if event == 'progress']
    assert stages == [
        'started', 'scope_resolved', 'papers_fetched', 'extracting', 'validating',
    ]

    terminal_event, terminal = frames[-1]
    assert terminal_event == 'result'
    # 터미널 페이로드 = JSON 경로와 동일한 TurnOut wire shape (계약 불변).
    assert terminal['result']['state'] == 'ok'
    assert terminal['result']['claims'][0]['statement'] == CLAIM_STATEMENT
    assert terminal['result']['claims'][0]['supporting'][0]['quote'] == CLAIM_QUOTE
    assert terminal['sessionId'] and terminal['turnId']

    # 턴이 영속됐다(FR-38) — 스트리밍이 저장 경로를 우회하지 않는다.
    assert len(repo.list_turns(principal.user_id, terminal['sessionId'])) == 1


def test_sse_turn_exposes_no_claim_text_before_terminal(monkeypatch) -> None:
    """C-2/INV-EV-3 — 검증 전 claim/quote 텍스트는 어떤 pre-terminal 프레임에도 없다."""
    principal = _principal()
    client = _client(
        monkeypatch, principal, InMemoryEvidenceRepository(), _StreamingStubOrchestrator()
    )

    resp = client.post(
        '/api/evidence/turns',
        json={'topic': 'benchmark reuse risks', 'scope': 'auto'},
        headers={'accept': 'text/event-stream'},
    )

    body = resp.text
    terminal_at = body.index('event: result')
    pre_terminal = body[:terminal_at]
    assert CLAIM_STATEMENT not in pre_terminal
    assert CLAIM_QUOTE not in pre_terminal
    # 터미널에는 검증된 결과가 있다(위 가드가 공허하게 통과하지 않도록).
    assert CLAIM_STATEMENT in body[terminal_at:]


def test_sse_surface_keeps_pending_json_for_async_eligible_turn(monkeypatch) -> None:
    """BR-EV-6 — 비동기 적격 턴은 SSE 표면에서도 pending/jobId JSON 동작 그대로."""
    principal = _principal()
    repo = InMemoryEvidenceRepository()
    client = _client(monkeypatch, principal, repo, _StreamingStubOrchestrator())
    enqueued: list[dict] = []
    client.app.state.evidence_sqs_enqueue = enqueued.append

    resp = client.post(
        '/api/evidence/turns',
        json={'topic': 'long analysis', 'scope': 'auto'},
        headers={'accept': 'text/event-stream'},
    )

    assert resp.status_code == 200
    assert resp.headers['content-type'].startswith('application/json')
    body = resp.json()
    assert body['result']['state'] == 'pending'
    assert body['result']['jobId']
    assert len(enqueued) == 1


def test_sse_turn_unknown_session_is_plain_404(monkeypatch) -> None:
    """INV-EV-1 — 스트림 시작 전에 소유권 검증(404는 HTTP 에러로 남는다)."""
    principal = _principal()
    client = _client(
        monkeypatch, principal, InMemoryEvidenceRepository(), _StreamingStubOrchestrator()
    )

    resp = client.post(
        '/api/evidence/turns',
        json={'topic': 'x', 'sessionId': 'not-mine'},
        headers={'accept': 'text/event-stream'},
    )

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# API: research 표면(POST /api/research/jobs[/…/messages]) — FE agent chat 홉
# ---------------------------------------------------------------------------

def _research_client(monkeypatch, principal: Principal, repo, orchestrator) -> TestClient:
    monkeypatch.setenv('RESEARCH_AGENT_ENABLED', 'true')
    app = create_app(Settings(env='test', database_url='sqlite://'))
    app.dependency_overrides[research_controller.get_principal] = lambda: principal
    app.dependency_overrides[research_controller.get_repo] = lambda: repo
    app.dependency_overrides[research_controller.get_evidence_orchestrator] = (
        lambda: orchestrator
    )
    return TestClient(app)


def test_research_create_job_streams_and_persists_turn(monkeypatch) -> None:
    principal = _principal()
    repo = InMemoryResearchRepository()
    client = _research_client(monkeypatch, principal, repo, _StreamingStubOrchestrator())

    resp = client.post(
        '/api/research/jobs',
        json={'content': 'benchmark reuse risks'},
        headers={'accept': 'text/event-stream'},
    )

    assert resp.status_code == 200
    assert resp.headers['content-type'].startswith('text/event-stream')
    frames = _parse_sse(resp.text)

    started = frames[0][1]
    assert started['stage'] == 'started'
    # 중간 중단 시 FE 스냅샷 복구 앵커(jobId) — started payload에 동봉된다.
    job_id = started['payload']['jobId']
    assert job_id

    # C-2 — 터미널 이전 프레임에 claim 텍스트 없음.
    terminal_at = resp.text.index('event: result')
    assert CLAIM_STATEMENT not in resp.text[:terminal_at]

    terminal_event, terminal = frames[-1]
    assert terminal_event == 'result'
    assert terminal == {'jobId': job_id, 'state': 'completed'}

    # JSON 경로와 동일하게 assistant 메시지가 영속되고 잡이 완료된다.
    messages = repo.list_messages(principal.user_id, job_id)
    assert any(CLAIM_STATEMENT in m.content for m in messages)
    assert repo.get_job(principal.user_id, job_id).state.value == 'completed'


def test_research_add_message_streams_with_job_scope_404(monkeypatch) -> None:
    principal = _principal()
    repo = InMemoryResearchRepository()
    client = _research_client(monkeypatch, principal, repo, _StreamingStubOrchestrator())

    missing = client.post(
        '/api/research/jobs/unknown-job/messages',
        json={'content': 'follow-up'},
        headers={'accept': 'text/event-stream'},
    )
    assert missing.status_code == 404

    created = client.post('/api/research/jobs', json={'content': 'seed question'})
    job_id = created.json()['jobId']

    resp = client.post(
        f'/api/research/jobs/{job_id}/messages',
        json={'content': 'follow-up question'},
        headers={'accept': 'text/event-stream'},
    )

    assert resp.status_code == 200
    frames = _parse_sse(resp.text)
    assert frames[0][1]['payload'] == {'jobId': job_id}
    terminal_event, terminal = frames[-1]
    assert terminal_event == 'result'
    # 터미널 = JSON 경로의 ResearchChatMessage 본문 그대로.
    assert terminal['role'] == 'assistant'
    assert CLAIM_STATEMENT in terminal['content']


def test_research_json_path_unchanged_without_accept_header(monkeypatch) -> None:
    principal = _principal()
    repo = InMemoryResearchRepository()
    client = _research_client(monkeypatch, principal, repo, _StreamingStubOrchestrator())

    resp = client.post('/api/research/jobs', json={'content': 'plain json turn'})

    assert resp.status_code == 200
    assert resp.headers['content-type'].startswith('application/json')
    assert resp.json()['state'] == 'completed'


# ---------------------------------------------------------------------------
# 단위: turn_sse_stream — NFR-O1 스트리밍 건강도 메트릭 (fail-soft)
# ---------------------------------------------------------------------------

class _Hub:
    def __init__(self) -> None:
        self.metrics: list[tuple[str, float, dict]] = []

    def emit_metric(self, name: str, value: float, tags: dict) -> None:
        self.metrics.append((name, value, tags))

    def names(self) -> list[str]:
        return [name for name, _, _ in self.metrics]


def test_stream_emits_first_token_and_completed_metrics() -> None:
    hub = _Hub()

    async def scenario() -> list[str]:
        async def run(emit):
            emit('papers_fetched', {'count': 2})
            return {'ok': True}

        return [
            chunk
            async for chunk in turn_sse_stream(
                run,
                lambda result: result,
                initial_events=[progress_event('started', {})],
                observability=hub,
                surface='evidence_turns',
            )
        ]

    chunks = asyncio.run(scenario())

    assert chunks[0].startswith('event: progress')
    assert chunks[-1].startswith('event: result')
    assert hub.names() == ['evidence.stream.first_token_ms', 'evidence.stream.completed']
    assert hub.metrics[0][2] == {'surface': 'evidence_turns'}


def test_stream_client_abort_emits_abort_metric() -> None:
    """NFR-O1 — 클라이언트 중단(연결 끊김) 카운트: evidence.stream.abort."""
    hub = _Hub()

    async def scenario() -> None:
        release = asyncio.Event()

        async def run(emit):
            emit('scope_resolved', {'scope': 'auto'})
            await release.wait()
            return {'ok': True}

        stream = turn_sse_stream(run, lambda r: r, observability=hub, surface='research')
        first = await anext(stream)
        assert first.startswith('event: progress')
        # 클라이언트 중단 — StreamingResponse가 제너레이터를 닫는 경로.
        await stream.aclose()
        release.set()
        await asyncio.sleep(0)  # 백그라운드 runner가 끝까지 완결되도록 양보

    asyncio.run(scenario())

    assert 'evidence.stream.abort' in hub.names()
    assert 'evidence.stream.completed' not in hub.names()


def test_stream_failure_yields_error_frame_without_internals() -> None:
    """fail-closed(SEC-9/INV-EV-5) — 내부 예외는 비기술 error 프레임으로만 노출."""
    hub = _Hub()

    async def scenario() -> list[str]:
        async def run(emit):
            raise RuntimeError('bedrock exploded: secret-arn-123')

        return [
            chunk
            async for chunk in turn_sse_stream(run, lambda r: r, observability=hub)
        ]

    chunks = asyncio.run(scenario())

    assert chunks[-1].startswith('event: error')
    assert 'secret-arn-123' not in chunks[-1]
    assert 'RuntimeError' not in chunks[-1]
    assert 'evidence.stream.error' in hub.names()
