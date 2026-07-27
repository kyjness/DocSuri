"""Novelty v2 포트 페이크 — 루프 코어를 결정론적으로 검증하기 위한 테스트 대역.

InMemory 스토어·큐의 기준 구현은 모듈 어댑터(adapters/memory.py)로 이동했고
여기서는 재수출한다 — 계약 테스트·루프 테스트의 임포트 경로는 불변.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterable
from typing import Any

from backend.modules.novelty.adapters.memory import (
    InMemoryJobQueue,
    InMemoryNoveltyStore,
)
from backend.modules.novelty.ports.assets import FigureAsset
from backend.modules.novelty.ports.llm import (
    LlmDecision,
    LoopObservation,
)
from backend.modules.novelty.ports.tools import ToolContext, ToolResult, ToolSpec

__all__ = [
    "FakeFigureAssetPort",
    "FakeTool",
    "InMemoryJobQueue",
    "InMemoryNoveltyStore",
    "ScriptedToolCallingLlm",
]


class ScriptedToolCallingLlm:
    """결정 시퀀스를 재생하는 LLM 페이크 — 루프 코어의 결정론 검증용."""

    def __init__(
        self,
        script: Iterable[LlmDecision | Callable[[LoopObservation], LlmDecision]],
    ) -> None:
        self._script = deque(script)
        self.observations: list[LoopObservation] = []

    def decide(self, observation: LoopObservation, tools: tuple[ToolSpec, ...]) -> LlmDecision:
        self.observations.append(observation)
        if not self._script:
            raise AssertionError("scripted LLM exhausted — loop asked for more decisions")
        step = self._script.popleft()
        return step(observation) if callable(step) else step


class FakeTool:
    """설정 가능한 도구 페이크."""

    def __init__(
        self,
        name: str,
        results: Iterable[ToolResult] | None = None,
        default: ToolResult | None = None,
    ) -> None:
        self.spec = ToolSpec(name=name, description=f"fake {name}", parameters={"type": "object"})
        self._results = deque(results or ())
        self._default = default or ToolResult(ok=True, result_summary=f"{name} ok")
        self.calls: list[tuple[dict[str, Any], ToolContext]] = []

    def invoke(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        self.calls.append((args, ctx))
        return self._results.popleft() if self._results else self._default


class FakeFigureAssetPort:
    """FigureAssetPort 대역 — `paper_asset` 행과 S3 바이트를 메모리로 흉내 낸다."""

    def __init__(
        self,
        assets: dict[tuple[str, int], list[FigureAsset]] | None = None,
        blobs: dict[str, tuple[str, bytes]] | None = None,
    ) -> None:
        self.assets = assets or {}
        self.blobs = blobs or {}
        self.fetched: list[str] = []

    def latest_version(self, paper_id: str) -> int | None:
        versions = [version for (pid, version) in self.assets if pid == paper_id]
        return max(versions) if versions else None

    def list_assets(self, paper_id: str, version: int) -> list[FigureAsset]:
        return list(self.assets.get((paper_id, version), ()))

    def fetch_bytes(self, object_ref: str) -> tuple[str, bytes] | None:
        self.fetched.append(object_ref)
        return self.blobs.get(object_ref)
