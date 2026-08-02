"""세션 표면(FR-38) + 활동 피드 복원 — /api/evidence 한 벌로 합친 뒤의 계약.

v1에서 이 엔드포인트들은 `/api/research/jobs`에 있었다. 껍데기 표면이 사라지면서
같은 기능이 여기로 왔고, 프론트가 이 경로를 쓴다.
"""

from __future__ import annotations

from uuid import uuid4

from docsuri_shared._generated.dtos.evidence_schema import EvidenceAbstainResult
from docsuri_shared.authz import Principal, UserRole
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.config import Settings
from backend.modules.evidence import controller
from backend.modules.evidence.models import TurnAbstainResult
from backend.modules.evidence.repository import InMemoryEvidenceRepository


class _StubRunner:
    def run(self, ctx, request, *, budget_signal=None, attachments=(), on_trace=None):
        if on_trace is not None:
            from backend.modules.evidence.domain.models import ToolCallOutcome, ToolCallRecord

            on_trace(
                ToolCallRecord(
                    seq=1,
                    tool="corpus_search",
                    args_summary="query=protein",
                    outcome=ToolCallOutcome.OK,
                    result_summary="corpus_search: 3 hits",
                )
            )
        return TurnAbstainResult(
            outcome=EvidenceAbstainResult(state="abstain", abstainReason="out_of_corpus")
        )


def _client(monkeypatch, principal: Principal, repo) -> TestClient:
    monkeypatch.setenv("EVIDENCE_AGENT_ENABLED", "true")
    app = create_app(Settings(env="test", database_url="sqlite://"))
    app.dependency_overrides[controller.get_principal] = lambda: principal
    app.dependency_overrides[controller.get_repo] = lambda: repo
    app.dependency_overrides[controller.get_runner] = lambda: _StubRunner()
    return TestClient(app)


def _principal() -> Principal:
    return Principal(user_id=str(uuid4()), role=UserRole.USER)


def _seed_turn(client: TestClient, topic: str = "질문") -> dict:
    resp = client.post("/api/evidence/turns", json={"topic": topic})
    assert resp.status_code == 200
    return resp.json()


def test_sessions_list_returns_only_the_owner_sessions(monkeypatch) -> None:
    repo = InMemoryEvidenceRepository()
    mine = _principal()
    client = _client(monkeypatch, mine, repo)
    _seed_turn(client)

    listed = client.get("/api/evidence/sessions").json()

    assert len(listed) == 1
    assert listed[0]["title"]


def test_session_detail_returns_turns(monkeypatch) -> None:
    repo = InMemoryEvidenceRepository()
    client = _client(monkeypatch, _principal(), repo)
    turn = _seed_turn(client)

    detail = client.get(f"/api/evidence/sessions/{turn['sessionId']}").json()

    assert detail["id"] == turn["sessionId"]
    assert [t["turnId"] for t in detail["turns"]] == [turn["turnId"]]


def test_other_owners_session_is_404_not_403(monkeypatch) -> None:
    """INV-EV-1/SEC-9 — 존재 여부 자체를 노출하지 않는다."""
    repo = InMemoryEvidenceRepository()
    owner_client = _client(monkeypatch, _principal(), repo)
    turn = _seed_turn(owner_client)

    intruder = _client(monkeypatch, _principal(), repo)
    resp = intruder.get(f"/api/evidence/sessions/{turn['sessionId']}")

    assert resp.status_code == 404


def test_delete_session_hides_it_from_the_list(monkeypatch) -> None:
    repo = InMemoryEvidenceRepository()
    client = _client(monkeypatch, _principal(), repo)
    turn = _seed_turn(client)

    assert client.delete(f"/api/evidence/sessions/{turn['sessionId']}").status_code == 204
    assert client.get("/api/evidence/sessions").json() == []


def test_reset_clears_every_owned_session(monkeypatch) -> None:
    repo = InMemoryEvidenceRepository()
    client = _client(monkeypatch, _principal(), repo)
    _seed_turn(client, "첫 질문")
    _seed_turn(client, "둘째 질문")

    assert client.delete("/api/evidence/sessions").status_code == 204
    assert client.get("/api/evidence/sessions").json() == []


def test_reset_is_idempotent(monkeypatch) -> None:
    client = _client(monkeypatch, _principal(), InMemoryEvidenceRepository())

    assert client.delete("/api/evidence/sessions").status_code == 204
    assert client.delete("/api/evidence/sessions").status_code == 204


def test_turn_trace_is_restorable_after_the_response(monkeypatch) -> None:
    """활동 피드는 스트림이 끝난 뒤에도 저장된 트레이스로 복원된다(FD 게이트 Q7=A)."""
    repo = InMemoryEvidenceRepository()
    client = _client(monkeypatch, _principal(), repo)
    turn = _seed_turn(client)

    trace = client.get(f"/api/evidence/turns/{turn['turnId']}/trace").json()

    assert [item["tool"] for item in trace] == ["corpus_search"]
    assert trace[0]["argsSummary"] == "query=protein"


def test_trace_of_another_owner_is_empty(monkeypatch) -> None:
    repo = InMemoryEvidenceRepository()
    owner = _client(monkeypatch, _principal(), repo)
    turn = _seed_turn(owner)

    intruder = _client(monkeypatch, _principal(), repo)

    assert intruder.get(f"/api/evidence/turns/{turn['turnId']}/trace").json() == []
