"""NoveltySettings — env 주도 설정(v2, tech-stack-decisions TD-NV2-1~8).

로컬 1차: redis 큐 + postgres 저장 + OpenAI tool-calling. 배포 기준선(SQS·Bedrock)
env 이름은 v1을 보존한다. 예산 시작값은 nfr-requirements §3 — 완화(상향)는 U6
예산 상태 확인 후에만(NFR-NV2-8).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from docsuri_shared.env import env_flag as _env_flag
from docsuri_shared.env import env_float as _env_float
from docsuri_shared.env import env_int as _env_int

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


@dataclass(frozen=True, slots=True)
class NoveltySettings:
    # LLM 프로바이더 스위치(TD-NV2-3) — 어댑터 선택은 composition root에서만.
    llm_provider: str
    openai_api_key: str | None
    openai_model: str
    # 비용 추정 단가(USD/1M tokens) — 예산 집계 입력(FR-45). 모델 교체 시 env로 조정.
    openai_input_usd_per_mtok: float
    openai_output_usd_per_mtok: float
    bedrock_model_id: str
    region_name: str | None
    # 잡 큐(TD-NV2-1): redis URL(로컬 1차) / SQS URL(배포 기준선, v1 env 보존)
    queue_url: str | None
    sqs_queue_url: str | None
    # 외부 탐색
    github_token: str | None
    external_timeout_seconds: float
    # 자산 스토어(FR-17) — view_figure 등록 조건(logical-components §4).
    # u1/u7과 같은 토글을 공유한다: 자산을 쓰지 않는 배포에서 도구만 살아나면
    # 에이전트가 매번 빈 목록을 받고 캡만 태운다.
    assets_enabled: bool
    asset_bucket: str | None
    # 이미지 1건 바이트 상한 — 백엔드에 이미지 처리 의존성이 없어 다운스케일 불가,
    # 초과는 거부한다. Anthropic 이미지 한도(5MB)보다 낮게 잡는다.
    figure_max_image_bytes: int
    # OpenAI image_url detail 힌트(low|high|auto). 미지정이면 프로바이더 기본값.
    figure_image_detail: str | None
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
    # 온디맨드 대화 턴 한 번의 decide 상한(NFR-NV2-7 — 잡 재실행이 아니다).
    # 예산 원장은 잡의 LoopBudget 하나이고, 이 값은 한 턴이 잔여 예산을 통째로
    # 태우지 못하게 막는 별도 상한이다.
    max_turn_steps: int

    @property
    def queue_configured(self) -> bool:
        return bool(self.queue_url or self.sqs_queue_url)

    @property
    def llm_configured(self) -> bool:
        if self.llm_provider == "openai":
            return bool(self.openai_api_key)
        return self.llm_provider == "bedrock"

    @property
    def figure_assets_configured(self) -> bool:
        """자산 스토어 설정 존재 — view_figure 등록 조건(logical-components §4)."""
        return self.assets_enabled and bool(self.asset_bucket)

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
            openai_input_usd_per_mtok=_env_float(
                "DOCSURI_NOVELTY_OPENAI_INPUT_USD_PER_MTOK", 0.15
            ),
            openai_output_usd_per_mtok=_env_float(
                "DOCSURI_NOVELTY_OPENAI_OUTPUT_USD_PER_MTOK", 0.60
            ),
            bedrock_model_id=os.environ.get(
                "DOCSURI_NOVELTY_LLM_MODEL_ID", DEFAULT_BEDROCK_MODEL
            ),
            region_name=os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION"),
            queue_url=os.environ.get("DOCSURI_NOVELTY_QUEUE_URL"),
            sqs_queue_url=os.environ.get("DOCSURI_NOVELTY_JOB_QUEUE_URL"),
            github_token=os.environ.get("DOCSURI_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN"),
            external_timeout_seconds=_env_float("DOCSURI_NOVELTY_EXTERNAL_TIMEOUT_SECONDS", 10.0),
            assets_enabled=_env_flag("DOCSURI_MULTIMODAL_ASSETS_ENABLED"),
            asset_bucket=os.environ.get("DOCSURI_S3_BUCKET"),
            figure_max_image_bytes=_env_int(
                "DOCSURI_NOVELTY_FIGURE_MAX_BYTES", 4 * 1024 * 1024
            ),
            figure_image_detail=os.environ.get("DOCSURI_NOVELTY_FIGURE_IMAGE_DETAIL") or None,
            lock_ttl_seconds=_env_float("DOCSURI_NOVELTY_LOCK_TTL_SECONDS", 120.0),
            stale_after_seconds=_env_float("DOCSURI_NOVELTY_STALE_AFTER_SECONDS", 900.0),
            max_iterations=_env_int("DOCSURI_NOVELTY_MAX_ITERATIONS", 24),
            max_tool_calls_total=_env_int("DOCSURI_NOVELTY_MAX_TOOL_CALLS", 40),
            max_search_calls=_env_int("DOCSURI_NOVELTY_MAX_SEARCH_CALLS", 12),
            max_form_evidence_calls=_env_int("DOCSURI_NOVELTY_MAX_FORM_EVIDENCE_CALLS", 4),
            max_view_figure_calls=_env_int("DOCSURI_NOVELTY_MAX_VIEW_FIGURE_CALLS", 8),
            max_save_artifact_calls=_env_int("DOCSURI_NOVELTY_MAX_SAVE_ARTIFACT_CALLS", 12),
            job_cost_limit_usd=_env_float("DOCSURI_NOVELTY_JOB_COST_LIMIT_USD", 0.50),
            max_turn_steps=_env_int("DOCSURI_NOVELTY_MAX_TURN_STEPS", 4),
        )
