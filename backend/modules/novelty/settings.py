"""NoveltySettings — env 주도 설정(v2, tech-stack-decisions TD-NV2-1~8).

로컬 1차: redis 큐 + postgres 저장. 배포 기준선(SQS·RDS)
env 이름은 v1을 보존한다. 예산 시작값은 nfr-requirements §3 — 완화(상향)는 U6
예산 상태 확인 후에만(NFR-NV2-8).
"""

from __future__ import annotations

import logging
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

log = logging.getLogger("docsuri.novelty.settings")

# 비용 추정 단가(USD/1M tokens) — 기본값은 아래 Bedrock 모델 기준. 모델을 env로 바꾸면
# 단가도 함께 바꾼다: 코드에 박으면 비싼 모델로 갈아탄 뒤 예산 대장이 조용히 과소계상된다.
DEFAULT_INPUT_USD_PER_MTOK = 3.0
DEFAULT_OUTPUT_USD_PER_MTOK = 15.0
# v1 승계 — Bedrock inference profile(배포 기준선).
DEFAULT_BEDROCK_MODEL = "global.anthropic.claude-sonnet-4-6"

# 3.5MB — 프로바이더 이미지 한도(첫 프로바이더 5MB, 배포 기준선 Bedrock은 그보다
# 낮다) 아래로 여유를 둔 값. 실측 코퍼스 최대 자산 1.5MB 미만이라 손실 없음.
DEFAULT_FIGURE_MAX_IMAGE_BYTES = 3_500_000

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


def _rate(direction: str, default: float) -> float:
    """단가 env 하나 — 이름이 바뀌었으므로 옛 이름도 읽고, 읽었으면 시끄럽게 알린다.

    프로바이더 스위치를 걷어내면서 `DOCSURI_NOVELTY_OPENAI_*` → `DOCSURI_NOVELTY_*`로 이름이
    바뀌었다. 옛 이름만 설정해 둔 환경은 조용히 기본값으로 떨어지는데, 지금 기본값이 마침
    Sonnet 단가와 같아 **아무 증상 없이** 지나가고 나중에 모델을 바꾼 뒤 예산 대장(FR-45)이
    틀어진 채로만 드러난다. 한 릴리스 동안 별칭을 읽어 주고 경고로 이전을 요구한다.
    """
    new_name = f"DOCSURI_NOVELTY_{direction}_USD_PER_MTOK"
    if os.environ.get(new_name):
        return _env_float(new_name, default)
    legacy = f"DOCSURI_NOVELTY_OPENAI_{direction}_USD_PER_MTOK"
    if os.environ.get(legacy):
        log.warning(
            "novelty: %s is deprecated and will stop being read — rename it to %s",
            legacy, new_name,
        )
        return _env_float(legacy, default)
    return default


@dataclass(frozen=True, slots=True)
class NoveltySettings:
    # 비용 추정 단가(USD/1M tokens) — 예산 집계 입력(FR-45). 모델 교체 시 env로 조정.
    llm_input_usd_per_mtok: float
    llm_output_usd_per_mtok: float
    bedrock_model_id: str
    region_name: str | None
    # 잡 큐(TD-NV2-1): redis URL(로컬 1차) / SQS URL(배포 기준선, v1 env 보존)
    queue_url: str | None
    sqs_queue_url: str | None
    # 외부 탐색
    github_token: str | None
    external_timeout_seconds: float
    # 자산 스토어(FR-17) — view_figure 등록 조건(logical-components §4).
    # u1/u7과 같은 토글을 공유한다(u7 read side와 동일): 자산을 쓰지 않는 배포에서
    # 도구만 살아나면 에이전트가 매번 빈 목록을 받고 캡만 태운다. 버킷은 조건에
    # 넣지 않는다 — 객체 주소는 `paper_asset.object_ref`가 들고 있고,
    # `DOCSURI_S3_BUCKET`은 인제스천 스택에만 있어 배포 환경에서 도구가 조용히
    # 사라진다.
    assets_enabled: bool
    # 이미지 1건 바이트 상한 — 백엔드에 이미지 처리 의존성이 없어 다운스케일 불가,
    # 초과는 거부한다. 프로바이더별 이미지 한도 중 **가장 낮은 것보다 아래**로 잡는다:
    # 상한을 통과했는데 프로바이더가 거부하면 자산 1건의 거부로 끝나지 않고
    # LlmUnavailable → 잡 전체 FAILED로 번진다(브레이커가 같은 요청을 재시도한 뒤
    # run_loop의 포괄 except가 fatal로 수렴). 실측 코퍼스 최대 자산이 1.5MB 미만이라
    # 낮게 잡아도 잃는 것이 없다.
    figure_max_image_bytes: int
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
    #
    # ⑤3에서 4 → 6으로 올렸다. `view_figure`가 2모드(목록 → 조회)라 그림을 보는 턴은
    # 바닥이 3스텝이다(목록·조회·답변). 4에서는 그림 두 장을 보면 답변할 스텝이 남지
    # 않아, 실스택 검증에서 조회에 성공하고도 "시도 횟수 안에 마무리하지 못했다"는
    # 안내가 나갔다 — 쓴 비용은 그대로인데 사용자에게 전달된 것이 없다.
    max_turn_steps: int

    @property
    def queue_configured(self) -> bool:
        return bool(self.queue_url or self.sqs_queue_url)

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
            llm_input_usd_per_mtok=_rate("INPUT", DEFAULT_INPUT_USD_PER_MTOK),
            llm_output_usd_per_mtok=_rate("OUTPUT", DEFAULT_OUTPUT_USD_PER_MTOK),
            bedrock_model_id=os.environ.get(
                "DOCSURI_NOVELTY_LLM_MODEL_ID", DEFAULT_BEDROCK_MODEL
            ),
            region_name=os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION"),
            queue_url=os.environ.get("DOCSURI_NOVELTY_QUEUE_URL"),
            sqs_queue_url=os.environ.get("DOCSURI_NOVELTY_JOB_QUEUE_URL"),
            github_token=os.environ.get("DOCSURI_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN"),
            external_timeout_seconds=_env_float("DOCSURI_NOVELTY_EXTERNAL_TIMEOUT_SECONDS", 10.0),
            assets_enabled=_env_flag("DOCSURI_MULTIMODAL_ASSETS_ENABLED"),
            figure_max_image_bytes=_env_int(
                "DOCSURI_NOVELTY_FIGURE_MAX_BYTES", DEFAULT_FIGURE_MAX_IMAGE_BYTES
            ),
            lock_ttl_seconds=_env_float("DOCSURI_NOVELTY_LOCK_TTL_SECONDS", 120.0),
            stale_after_seconds=_env_float("DOCSURI_NOVELTY_STALE_AFTER_SECONDS", 900.0),
            max_iterations=_env_int("DOCSURI_NOVELTY_MAX_ITERATIONS", 24),
            max_tool_calls_total=_env_int("DOCSURI_NOVELTY_MAX_TOOL_CALLS", 40),
            max_search_calls=_env_int("DOCSURI_NOVELTY_MAX_SEARCH_CALLS", 12),
            max_form_evidence_calls=_env_int("DOCSURI_NOVELTY_MAX_FORM_EVIDENCE_CALLS", 4),
            max_view_figure_calls=_env_int("DOCSURI_NOVELTY_MAX_VIEW_FIGURE_CALLS", 8),
            max_save_artifact_calls=_env_int("DOCSURI_NOVELTY_MAX_SAVE_ARTIFACT_CALLS", 12),
            job_cost_limit_usd=_env_float("DOCSURI_NOVELTY_JOB_COST_LIMIT_USD", 0.50),
            max_turn_steps=_env_int("DOCSURI_NOVELTY_MAX_TURN_STEPS", 6),
        )
