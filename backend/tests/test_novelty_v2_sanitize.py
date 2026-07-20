"""외부 도구 payload allowlist 차단(BR-RA7, NFR-NV2-15) + 어댑터 경계 테스트.

에이전트가 원고 원문·근거 전문을 인자에 넣어도(프롬프트 인젝션 포함 —
SECURITY-11) 어댑터 경계에서 실행 전에 차단됨을 검증한다.
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from backend.modules.novelty.adapters.external.base import SourceBreaker, SourceUnavailable
from backend.modules.novelty.adapters.external.datasets import DatasetSearchTool
from backend.modules.novelty.adapters.external.github import GithubSearchTool
from backend.modules.novelty.adapters.external.sanitize import (
    PAYLOAD_ALLOWLISTS,
    sanitize_payload,
)
from backend.modules.novelty.ports.tools import (
    TOOL_DATASET_SEARCH,
    TOOL_GITHUB_SEARCH,
    ToolContext,
)

_CTX = ToolContext(owner_id="o1", job_id="j1")


# ── allowlist 규칙 ──


def test_unknown_keys_are_violations() -> None:
    sanitized, violations = sanitize_payload(
        TOOL_GITHUB_SEARCH, {"query": "sparse retrieval", "manuscript_text": "전체 원고…"}
    )
    assert sanitized == {"query": "sparse retrieval"}
    assert any(v.key == "manuscript_text" and v.reason == "unknown_key" for v in violations)


def test_overlong_text_is_blocked_not_truncated() -> None:
    # 원고 전문을 잘라 보내는 것도 유출 — 절단이 아니라 차단한다.
    _, violations = sanitize_payload(TOOL_GITHUB_SEARCH, {"query": "x" * 5000})
    assert any(v.reason == "too_long" for v in violations)


def test_non_text_values_blocked_and_required_enforced() -> None:
    _, violations = sanitize_payload(TOOL_DATASET_SEARCH, {"query": {"nested": "obj"}})
    reasons = {v.reason for v in violations}
    assert "not_text" in reasons
    assert "missing_required" in reasons


def test_unknown_tool_has_no_allowlist() -> None:
    _, violations = sanitize_payload("mystery_tool", {"query": "q"})
    assert violations and violations[0].reason == "unknown_tool"


@given(
    tool=st.sampled_from(sorted(PAYLOAD_ALLOWLISTS)),
    args=st.dictionaries(
        st.text(min_size=1, max_size=20),
        st.one_of(st.text(max_size=300), st.integers(), st.lists(st.text(max_size=10))),
        max_size=6,
    ),
)
def test_pbt_sanitized_payload_always_within_allowlist(tool: str, args: dict) -> None:
    sanitized, violations = sanitize_payload(tool, args)
    rules = PAYLOAD_ALLOWLISTS[tool]
    # 불변식: 정제 결과는 항상 allowlist 키·길이 안이며, 위반 없이 통과한 키만 남는다.
    for key, value in sanitized.items():
        assert key in rules
        assert isinstance(value, str)
        assert len(value) <= rules[key].max_length
    # 위반으로 지목된 키는 정제 결과에 절대 실리지 않는다(유출 차단의 핵심 불변식).
    violated_keys = {v.key for v in violations}
    assert violated_keys.isdisjoint(sanitized.keys())
    if not violations:
        assert all(key in rules for key in args)


# ── 어댑터 경계: 위반 시 실행 없이 오류 반환(BLM §3.1) ──


class _RecordingClient:
    def __init__(self, payload=None, status_code: int = 200) -> None:
        self.calls: list[str] = []
        self._payload = payload if payload is not None else {"items": []}
        self._status = status_code

    def get(self, url: str, params=None, headers=None):
        self.calls.append(url)
        client = self

        class _Response:
            status_code = client._status

            def json(self):
                return client._payload

        return _Response()


def test_github_tool_blocks_payload_before_any_network_call() -> None:
    client = _RecordingClient()
    tool = GithubSearchTool(client)
    result = tool.invoke({"query": "ok", "readme_dump": "근거 전문…"}, _CTX)
    assert result.ok is False
    assert result.error and result.error.startswith("payload_blocked")
    assert client.calls == []  # 실행 자체가 없다


def test_github_tool_normalizes_and_drops_unsafe_urls() -> None:
    client = _RecordingClient(
        payload={
            "items": [
                {
                    "full_name": "acme/dp-retrieval",
                    "html_url": "https://github.com/acme/dp-retrieval",
                    "license": {"spdx_id": "MIT"},
                    "description": "DP retrieval baselines",
                },
                {"full_name": "evil/repo", "html_url": "http://evil.test/repo"},
            ]
        }
    )
    tool = GithubSearchTool(client)
    result = tool.invoke({"query": "dp retrieval"}, _CTX)
    assert result.ok is True
    findings = result.content["findings"]
    assert len(findings) == 1
    assert findings[0]["source_type"] == "github"
    assert findings[0]["license"] == "MIT"


def test_dataset_tool_partial_source_failure_degrades_not_fails() -> None:
    class _SplitClient(_RecordingClient):
        def get(self, url: str, params=None, headers=None):
            if "zenodo" in url:
                raise RuntimeError("zenodo down")
            self.calls.append(url)

            class _Response:
                status_code = 200

                def json(self):
                    return [{"id": "acme/beir-dp", "tags": ["task_categories:retrieval"]}]

            return _Response()

    tool = DatasetSearchTool(_SplitClient())
    result = tool.invoke({"query": "beir"}, _CTX)
    assert result.ok is True
    assert result.content["degraded_sources"] == ["zenodo"]
    assert result.content["findings"][0]["task"] == "retrieval"


def test_dataset_tool_all_sources_down_returns_error() -> None:
    class _DownClient:
        def get(self, url: str, params=None, headers=None):
            raise RuntimeError("down")

    tool = DatasetSearchTool(_DownClient())
    result = tool.invoke({"query": "beir"}, _CTX)
    assert result.ok is False
    assert "unavailable" in (result.error or "")


def test_source_breaker_opens_after_threshold_and_recovers() -> None:
    clock = {"now": 0.0}
    breaker = SourceBreaker(failure_threshold=2, cooldown_seconds=30, clock=lambda: clock["now"])

    def boom():
        raise RuntimeError("down")

    for _ in range(2):
        try:
            breaker.call(boom)
        except SourceUnavailable:
            pass
    # 차단 개방 — 호출 없이 즉시 거부.
    calls = {"n": 0}

    def counting():
        calls["n"] += 1
        return "ok"

    try:
        breaker.call(counting)
    except SourceUnavailable:
        pass
    assert calls["n"] == 0
    clock["now"] = 31.0
    assert breaker.call(counting) == "ok"
