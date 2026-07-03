"""Personal glossary upsert (개인 용어집 Phase 1) — resolver delegation, post-substitution
literal-insert safety, and the POST /api/glossary endpoint (owner-scoped, validated,
fail-closed).

The endpoint is exercised by invoking its route function directly with a fake Request
(carrying ``state.principal``, the gateway stand-in) — no HTTP client dependency needed.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from summarization.api.router import build_router
from summarization.domain.glossary import GlossaryResolver
from summarization.domain.models import Glossary, TermMapping

from .stubs import make_orchestrator


class _FakeRepo:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def get_user_glossary(self, user_id: str):
        return ()

    def upsert_term(self, user_id, term_from, term_to, *, prompt_enforced) -> int:
        self.calls.append((user_id, term_from, term_to, prompt_enforced))
        return 7


def test_resolver_upsert_delegates_and_defaults_to_post_substitution() -> None:
    repo = _FakeRepo()
    ver = GlossaryResolver(repo).upsert_term("u1", "attention", "주의집중")
    assert ver == 7
    # Phase 1 stores it as a simple noun (prompt_enforced=False → translation post-substitution).
    assert repo.calls == [("u1", "attention", "주의집중", False)]


def test_resolver_upsert_without_repo_raises() -> None:
    with pytest.raises(RuntimeError):
        GlossaryResolver(None).upsert_term("u1", "a", "b")


def test_post_substitute_inserts_term_to_literally() -> None:
    # A user-supplied term_to with a regex-replacement sequence must be inserted literally,
    # never interpreted as a backreference (no raise, no mangling).
    glossary = Glossary(user_overrides=(TermMapping("주의", r"\g<0>x", prompt_enforced=False),))
    out = GlossaryResolver.post_substitute("주의 메커니즘", glossary)
    assert out == r"\g<0>x 메커니즘"


# --- endpoint -------------------------------------------------------------


class _FakeState:
    def __init__(self, principal: Any) -> None:
        self.principal = principal


class _FakeRequest:
    """Minimal stand-in for starlette Request: only ``state``/``headers`` are read."""

    def __init__(self, principal: Any) -> None:
        self.state = _FakeState(principal)
        self.headers: dict[str, str] = {}


class _FakeOrchestrator:
    def __init__(self, *, fail: bool = False, terms: list[dict] | None = None) -> None:
        self.fail = fail
        self.terms = terms or []
        self.calls: list[tuple] = []

    def upsert_glossary_term(self, user_id, term_from, term_to, *, prompt_enforced=False) -> int:
        if self.fail:
            raise RuntimeError("db down")
        self.calls.append((user_id, term_from, term_to, prompt_enforced))
        return 3

    def list_glossary_terms(self, user_id) -> list[dict]:
        if self.fail:
            raise RuntimeError("db down")
        self.calls.append(("list", user_id))
        return self.terms


def _endpoint(orch, method: str):
    router = build_router(orch)
    for route in router.routes:
        if getattr(route, "path", None) == "/api/glossary" and method in getattr(
            route, "methods", set()
        ):
            return route.endpoint
    raise AssertionError(f"{method} /api/glossary route not found")


def _invoke(orch, *, principal, payload):
    response = _endpoint(orch, "POST")(_FakeRequest(principal), payload)
    return response.status_code, json.loads(response.body)


def _invoke_list(orch, *, principal):
    response = _endpoint(orch, "GET")(_FakeRequest(principal))
    return response.status_code, json.loads(response.body)


def test_glossary_endpoint_upserts_and_returns_version() -> None:
    orch = _FakeOrchestrator()
    status, body = _invoke(orch, principal={"user_id": "u1"}, payload={
        "termFrom": "attention",
        "termTo": "주의집중",
    })
    assert status == 201
    assert body == {"status": "ok", "glossaryVer": 3}
    # No promptEnforced in the payload → weak (post-substitution) by default.
    assert orch.calls == [("u1", "attention", "주의집중", False)]


def test_glossary_endpoint_requires_principal() -> None:
    status, body = _invoke(_FakeOrchestrator(), principal=None, payload={
        "termFrom": "a",
        "termTo": "b",
    })
    assert status == 401


def test_glossary_endpoint_rejects_blank_missing_or_oversized() -> None:
    orch = _FakeOrchestrator()
    p = {"user_id": "u1"}
    assert _invoke(orch, principal=p, payload={"termFrom": "  ", "termTo": "x"})[0] == 400
    assert _invoke(orch, principal=p, payload={"termFrom": "a"})[0] == 400
    assert _invoke(orch, principal=p, payload={"termFrom": "a", "termTo": "가" * 41})[0] == 400
    assert orch.calls == []  # nothing persisted on a rejected request


def test_glossary_list_returns_owner_terms() -> None:
    orch = _FakeOrchestrator(terms=[{"termFrom": "attention", "termTo": "주의집중"}])
    status, body = _invoke_list(orch, principal={"user_id": "u1"})
    assert status == 200
    assert body == {"status": "ok", "terms": [{"termFrom": "attention", "termTo": "주의집중"}]}
    assert orch.calls == [("list", "u1")]


def test_glossary_list_requires_principal() -> None:
    status, _ = _invoke_list(_FakeOrchestrator(), principal=None)
    assert status == 401


def test_glossary_endpoint_fails_closed_on_repo_error() -> None:
    status, body = _invoke(
        _FakeOrchestrator(fail=True), principal={"user_id": "u1"}, payload={
            "termFrom": "a",
            "termTo": "b",
        }
    )
    assert status == 503
    assert body == {"status": "unavailable"}


# --- strong-term opening: promptEnforced threading, strict boolean, list flag ---------------------


class _TermsRepo:
    """Owner-scoped repo returning a fixed term set (for the list-shape test)."""

    def __init__(self, terms: tuple[TermMapping, ...]) -> None:
        self._terms = terms

    def get_user_glossary(self, user_id: str):
        return self._terms


def test_glossary_endpoint_threads_strong_flag() -> None:
    orch = _FakeOrchestrator()
    status, _body = _invoke(
        orch,
        principal={"user_id": "u1"},
        payload={"termFrom": "MyModel", "termTo": "내모델", "promptEnforced": True},
    )
    assert status == 201
    assert orch.calls == [("u1", "MyModel", "내모델", True)]


def test_glossary_endpoint_promptEnforced_is_strict_boolean() -> None:
    # Only JSON `true` enables strong; a truthy non-boolean must NOT silently escalate into the
    # prompt (a stray "true" string, 1, … → weak).
    orch = _FakeOrchestrator()
    _invoke(
        orch,
        principal={"user_id": "u1"},
        payload={"termFrom": "a", "termTo": "b", "promptEnforced": "true"},
    )
    assert orch.calls == [("u1", "a", "b", False)]


def test_list_glossary_terms_exposes_prompt_enforced_flag() -> None:
    # The badge editor must tell strong from weak; the listing surfaces the flag (nothing else).
    orch = make_orchestrator(
        glossary_resolver=GlossaryResolver(
            _TermsRepo(
                (
                    TermMapping("MyModel", "내모델", prompt_enforced=True),
                    TermMapping("cat", "고양이", prompt_enforced=False),
                )
            )
        )
    )
    assert orch.list_glossary_terms("u1") == [
        {"termFrom": "MyModel", "termTo": "내모델", "promptEnforced": True},
        {"termFrom": "cat", "termTo": "고양이", "promptEnforced": False},
    ]
