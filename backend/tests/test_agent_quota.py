"""NFR-C1 — 에이전트 경로(evidence turn / novelty job) 사용자별 일일 쿼터."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.app import create_app
from backend.config import Settings
from backend.middleware import agent_quota
from backend.middleware.rate_limit import InProcessWindowLimiter


def _request(user_id: str | None = "u1") -> SimpleNamespace:
    principal = SimpleNamespace(user_id=user_id) if user_id else None
    return SimpleNamespace(state=SimpleNamespace(principal=principal))


@pytest.fixture()
def limiter(monkeypatch: pytest.MonkeyPatch) -> InProcessWindowLimiter:
    shared = InProcessWindowLimiter()
    monkeypatch.setattr(agent_quota, "get_shared_limiter", lambda: shared)
    return shared


def test_evidence_turn_quota_blocks_after_daily_limit(limiter, monkeypatch) -> None:
    monkeypatch.setattr(agent_quota, "_EVIDENCE_DAILY_LIMIT", 2)

    asyncio.run(agent_quota.enforce_evidence_turn_quota(_request()))
    asyncio.run(agent_quota.enforce_evidence_turn_quota(_request()))
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(agent_quota.enforce_evidence_turn_quota(_request()))

    assert excinfo.value.status_code == 429


def test_quota_is_isolated_per_user_and_per_scope(limiter, monkeypatch) -> None:
    monkeypatch.setattr(agent_quota, "_EVIDENCE_DAILY_LIMIT", 1)
    monkeypatch.setattr(agent_quota, "_NOVELTY_DAILY_LIMIT", 1)

    asyncio.run(agent_quota.enforce_evidence_turn_quota(_request("a")))
    # 다른 사용자·다른 scope는 서로의 한도를 소비하지 않는다.
    asyncio.run(agent_quota.enforce_evidence_turn_quota(_request("b")))
    asyncio.run(agent_quota.enforce_novelty_job_quota(_request("a")))

    with pytest.raises(HTTPException):
        asyncio.run(agent_quota.enforce_evidence_turn_quota(_request("a")))


def test_quota_skips_unauthenticated_requests(limiter) -> None:
    # principal은 인증 미들웨어가 세팅한다 — 없으면 라우트의 401이 담당하고 쿼터는 통과.
    asyncio.run(agent_quota.enforce_evidence_turn_quota(_request(None)))


def _route_dependency_names(app) -> dict[tuple[str, str], list[str]]:
    """(method, path) -> 라우트에 걸린 의존성 함수명 목록. FastAPI 서브라우터 wrapper를
    한 겹 벗겨야 실제 APIRoute.dependencies에 닿는다(app-shell의 지연 마운트 방식)."""
    result: dict[tuple[str, str], list[str]] = {}
    for included in app.routes:
        router = getattr(included, "original_router", None)
        if router is None:
            continue
        for route in router.routes:
            path = getattr(route, "path", None)
            methods = getattr(route, "methods", None)
            if not path or not methods:
                continue
            names = [
                getattr(dep.dependency, "__name__", str(dep.dependency))
                for dep in getattr(route, "dependencies", [])
            ]
            for method in methods:
                result[(method, path)] = names
    return result


def test_bedrock_incurring_routes_are_all_quota_gated(monkeypatch) -> None:
    """NFR-C1 회귀 방지 — PR #364 병합 시 POST /api/research/jobs(첫 메시지도
    orchestrator.run()을 실행해 Bedrock을 호출)가 쿼터 없이 병합돼, 매번 새 세션을
    만들기만 하면 일일 한도를 완전히 우회할 수 있었다. 라우트 배선 자체를 검증해
    같은 종류의 누락(단위 테스트로는 못 잡는 배선 문제)을 앞으로 잡는다."""
    monkeypatch.setenv("RESEARCH_AGENT_ENABLED", "true")
    app = create_app(Settings(env="test", database_url="sqlite://"))
    dependencies = _route_dependency_names(app)

    must_be_evidence_gated = {
        ("POST", "/api/research/jobs"),  # create_job → add_message → orchestrator.run()
        ("POST", "/api/research/jobs/{job_id}/messages"),
        ("POST", "/api/evidence/turns"),
    }
    for route in must_be_evidence_gated:
        assert "enforce_evidence_turn_quota" in dependencies.get(route, []), (
            f"{route}가 evidence 일일 쿼터로 게이트되지 않음"
        )

    must_be_novelty_gated = {("POST", "/api/novelty/jobs")}
    for route in must_be_novelty_gated:
        assert "enforce_novelty_job_quota" in dependencies.get(route, []), (
            f"{route}가 novelty 일일 쿼터로 게이트되지 않음"
        )
