"""NoveltySettings — env 주도 설정(v2, tech-stack-decisions TD-NV2-1~8).

로컬 1차: redis 큐 + postgres 저장 + OpenAI tool-calling. 배포 기준선(SQS·Bedrock)
env 이름은 v1을 보존한다. 예산 시작값은 nfr-requirements §3 — 완화(상향)는 U6
예산 상태 확인 후에만(NFR-NV2-8).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from .domain.models import LoopBudget
from .ports.tools import (
    TOOL_CORPUS_SEARCH,
    TOOL_DATASET_SEARCH,
    TOOL_FORM_EVIDENCE,
    TOOL_GITHUB_SEARCH,
    TOOL_SAVE_ARTIFACT,
    TOOL_VIEW_FIGURE,
)

DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
# v1 승계 — Bedrock inference profile(배포 기준선).
DEFAULT_BEDROCK_MODEL = "global.anthropic.claude-sonnet-4-6"

# 캡 그룹(nfr-requirements §3) — 탐색류는 합산 캡.
CAP_GROUP_SEARCH = "search"
CAP_GROUP_FORM_EVIDENCE = "form_evidence"
CAP_GROUP_VIEW_FIGURE = "view_figure"
CAP_GROUP_SAVE_ARTIFACT = "save_artifact"

TOOL_CAP_GROUPS: dict[str, str] = {
    TOOL_CORPUS_SEARCH: CAP_GROUP_SEARCH,
    TOOL_GITHUB_SEARCH: CAP_GROUP_SEARCH,
    TOOL_DATASET_SEARCH: CAP_GROUP_SEARCH,
    TOOL_FORM_EVIDENCE: CAP_GROUP_FORM_EVIDENCE,
    TOOL_VIEW_FIGURE: CAP_GROUP_VIEW_FIGURE,
    TOOL_SAVE_ARTIFACT: CAP_GROUP_SAVE_ARTIFACT,
}


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw else default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    return float(raw) if raw else default


@dataclass(frozen=True, slots=True)
class NoveltySettings:
    # LLM 프로바이더 스위치(TD-NV2-3) — 어댑터 선택은 composition root에서만.
    llm_provider: str
    openai_api_key: str | None
    openai_model: str
    bedrock_model_id: str
    region_name: str | None
    # 잡 큐(TD-NV2-1): redis URL(로컬 1차) / SQS URL(배포 기준선, v1 env 보존)
    queue_url: str | None
    sqs_queue_url: str | None
    # 외부 탐색
    github_token: str | None
    external_timeout_seconds: float
    # 워커 잠금·stale 감지(NFR-NV2-2·3)
    lock_ttl_seconds: float
    stale_after_seconds: float
    # 3중 예산 시작값(nfr-requirements §3)
    max_iterations: int
    max_tool_calls_total: int
    max_search_calls: int
    max_form_evidence_calls: int
    max_view_figure_calls: int
    max_save_artifact_calls: int
    job_cost_limit_usd: float

    @property
    def queue_configured(self) -> bool:
        return bool(self.queue_url or self.sqs_queue_url)

    @property
    def llm_configured(self) -> bool:
        if self.llm_provider == "openai":
            return bool(self.openai_api_key)
        return self.llm_provider == "bedrock"

    def build_loop_budget(self) -> LoopBudget:
        return LoopBudget(
            max_iterations=self.max_iterations,
            max_tool_calls_total=self.max_tool_calls_total,
            max_tool_calls={
                CAP_GROUP_SEARCH: self.max_search_calls,
                CAP_GROUP_FORM_EVIDENCE: self.max_form_evidence_calls,
                CAP_GROUP_VIEW_FIGURE: self.max_view_figure_calls,
                CAP_GROUP_SAVE_ARTIFACT: self.max_save_artifact_calls,
            },
            tool_cap_groups=dict(TOOL_CAP_GROUPS),
            token_cost_limit_usd=self.job_cost_limit_usd,
        )

    @classmethod
    def from_env(cls) -> NoveltySettings:
        return cls(
            llm_provider=os.environ.get("DOCSURI_NOVELTY_LLM_PROVIDER", "openai").lower(),
            openai_api_key=os.environ.get("OPENAI_API_KEY"),
            openai_model=os.environ.get("DOCSURI_NOVELTY_OPENAI_MODEL", DEFAULT_OPENAI_MODEL),
            bedrock_model_id=os.environ.get(
                "DOCSURI_NOVELTY_LLM_MODEL_ID", DEFAULT_BEDROCK_MODEL
            ),
            region_name=os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION"),
            queue_url=os.environ.get("DOCSURI_NOVELTY_QUEUE_URL"),
            sqs_queue_url=os.environ.get("DOCSURI_NOVELTY_JOB_QUEUE_URL"),
            github_token=os.environ.get("DOCSURI_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN"),
            external_timeout_seconds=_env_float("DOCSURI_NOVELTY_EXTERNAL_TIMEOUT_SECONDS", 10.0),
            lock_ttl_seconds=_env_float("DOCSURI_NOVELTY_LOCK_TTL_SECONDS", 120.0),
            stale_after_seconds=_env_float("DOCSURI_NOVELTY_STALE_AFTER_SECONDS", 900.0),
            max_iterations=_env_int("DOCSURI_NOVELTY_MAX_ITERATIONS", 24),
            max_tool_calls_total=_env_int("DOCSURI_NOVELTY_MAX_TOOL_CALLS", 40),
            max_search_calls=_env_int("DOCSURI_NOVELTY_MAX_SEARCH_CALLS", 12),
            max_form_evidence_calls=_env_int("DOCSURI_NOVELTY_MAX_FORM_EVIDENCE_CALLS", 4),
            max_view_figure_calls=_env_int("DOCSURI_NOVELTY_MAX_VIEW_FIGURE_CALLS", 8),
            max_save_artifact_calls=_env_int("DOCSURI_NOVELTY_MAX_SAVE_ARTIFACT_CALLS", 12),
            job_cost_limit_usd=_env_float("DOCSURI_NOVELTY_JOB_COST_LIMIT_USD", 0.50),
        )
