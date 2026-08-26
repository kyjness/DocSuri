"""EvidenceSettings — env-driven config (U11 infrastructure-design).

``evidence_enabled`` gates real adapter assembly: the app-shell mounts U11 only when
the required deps (Bedrock model + S3 DocModel bucket) are configured.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import timedelta

from docsuri_shared.env import env_flag as _env_flag
from docsuri_shared.env import env_float as _env_float
from docsuri_shared.env import env_int as _env_int

# 모델과 단가는 함께 움직인다 — 셋을 나란히 둔다. 모델만 바꾸고 단가를 두면 예산 대장이
# 조용히 어긋난다 — 싼 모델의 단가를 20배 비싼 모델에 그대로 쓴 적이 있다.
DEFAULT_MODEL = 'global.anthropic.claude-sonnet-4-6'
DEFAULT_INPUT_USD_PER_MTOK = 3.0
DEFAULT_OUTPUT_USD_PER_MTOK = 15.0


@dataclass(frozen=True, slots=True)
class TurnExecutionSettings:
    """턴 실행 표면이 쓰는 값만 — 컨트롤러가 env 이름이나 dict 키를 알 이유가 없다.

    문자열 dict로 넘기던 동안 기본값이 여기와 컨트롤러 두 곳에 있었고, 키 오타는 조용히
    폴백으로 떨어졌다.
    """

    stale_after: timedelta
    poll_seconds: float

    @classmethod
    def defaults(cls) -> TurnExecutionSettings:
        return cls(stale_after=timedelta(seconds=600), poll_seconds=1.0)


@dataclass(frozen=True, slots=True)
class EvidenceSettings:
    model_id: str
    docmodel_bucket: str | None   # S3 bucket (U1 소유 DocModel 버킷)
    region_name: str | None
    # 비동기 잡 경로 게이트 (BR-EV-6, NFR-P6)
    async_enabled: bool
    job_queue_url: str | None     # SQS evidence-agent-job-queue
    # 토큰 단가(USD/Mtok) — 모델을 env로 바꾸면 단가도 함께 바꾼다. 코드에 박으면
    # 비싼 모델로 갈아탄 뒤 예산 대장이 조용히 과소계상된다(novelty와 같은 패턴).
    input_usd_per_mtok: float
    output_usd_per_mtok: float
    # 루프 예산 시작값(FR-45, nfr-requirements §3) — "실측 후 조정"이 배포 없이
    # 가능해야 하므로 env로 연다. 수치 변경은 문서 갱신을 동반한다.
    max_iterations: int
    max_tool_calls_total: int
    cap_corpus_search: int
    cap_live_lookup: int
    cap_fetch_paper: int
    cap_read_paper: int
    cap_view_figure: int
    cap_extract_evidence: int
    token_cost_limit_usd: float
    # 실행 경로(v3 §5) — SQS가 없을 때 프로세스 안에서 턴을 돌리는 스레드 수, 하트비트가
    # 이만큼 끊기면 고아로 보고 마지막 체크포인트로 마감하는 초(가장 긴 단일 단계인
    # 본문 승격 폴링 20s보다 충분히 크게), 체크포인트 보존 일수, 이벤트 스트림 폴링 간격.
    local_turn_workers: int = 2
    turn_stale_seconds: int = 600
    checkpoint_retention_days: int = 7
    events_poll_seconds: float = 1.0

    @property
    def turn_execution(self) -> TurnExecutionSettings:
        return TurnExecutionSettings(
            stale_after=timedelta(seconds=self.turn_stale_seconds),
            poll_seconds=self.events_poll_seconds,
        )

    @property
    def evidence_enabled(self) -> bool:
        # 실 경로 = DocModel S3 버킷 필요 (Bedrock는 항상 사용 가능 가정)
        return bool(self.docmodel_bucket)

    @classmethod
    def from_env(cls) -> EvidenceSettings:
        return cls(
            model_id=os.environ.get('DOCSURI_EVIDENCE_MODEL_ID', DEFAULT_MODEL),
            docmodel_bucket=os.environ.get('DOCSURI_DOCMODEL_BUCKET'),
            region_name=os.environ.get('AWS_REGION') or os.environ.get('AWS_DEFAULT_REGION'),
            async_enabled=_env_flag('DOCSURI_EVIDENCE_ASYNC_ENABLED'),
            job_queue_url=os.environ.get('DOCSURI_EVIDENCE_JOB_QUEUE_URL'),
            input_usd_per_mtok=_env_float(
                'DOCSURI_EVIDENCE_INPUT_USD_PER_MTOK', DEFAULT_INPUT_USD_PER_MTOK
            ),
            output_usd_per_mtok=_env_float(
                'DOCSURI_EVIDENCE_OUTPUT_USD_PER_MTOK', DEFAULT_OUTPUT_USD_PER_MTOK
            ),
            max_iterations=_env_int('DOCSURI_EVIDENCE_MAX_ITERATIONS', 12),
            max_tool_calls_total=_env_int('DOCSURI_EVIDENCE_MAX_TOOL_CALLS', 30),
            cap_corpus_search=_env_int('DOCSURI_EVIDENCE_CAP_CORPUS_SEARCH', 5),
            cap_live_lookup=_env_int('DOCSURI_EVIDENCE_CAP_LIVE_LOOKUP', 3),
            # 3 → 8 (2026-08-24 실측). 답할 수 있는 질문에서 모델이 실제로 부른 횟수는
            # **6회**였고, 3에 막힌 턴은 논문 3편을 확보한 채 근거 0건으로 기권했다.
            cap_fetch_paper=_env_int('DOCSURI_EVIDENCE_CAP_FETCH_PAPER', 8),
            cap_read_paper=_env_int('DOCSURI_EVIDENCE_CAP_READ_PAPER', 8),
            cap_view_figure=_env_int('DOCSURI_EVIDENCE_CAP_VIEW_FIGURE', 6),
            cap_extract_evidence=_env_int('DOCSURI_EVIDENCE_CAP_EXTRACT_EVIDENCE', 8),
            # 0.50 → 1.50 (2026-08-26). 종전 값은 **추출 비용이 장부 밖에 있을 때** 정해진
            # 것이라 사실상 안 걸렸다. 계상을 고치고 재보니 평범한 턴 하나가 $0.269 — 옛
            # 상한의 54%다. 그대로 두면 지금까지 완주하던 턴이 중간에 끊겨 "이어서 확인할까요?"가
            # 뜬다. 상한의 목적은 정상 턴을 자르는 것이 아니라 폭주를 막는 것이므로 실측
            # 최대치의 약 5배로 둔다.
            token_cost_limit_usd=_env_float('DOCSURI_EVIDENCE_TURN_COST_LIMIT_USD', 1.50),
            local_turn_workers=_env_int('DOCSURI_EVIDENCE_LOCAL_TURN_WORKERS', 2),
            turn_stale_seconds=_env_int('DOCSURI_EVIDENCE_TURN_STALE_SECONDS', 600),
            checkpoint_retention_days=_env_int('DOCSURI_EVIDENCE_CHECKPOINT_RETENTION_DAYS', 7),
            events_poll_seconds=_env_float('DOCSURI_EVIDENCE_EVENTS_POLL_SECONDS', 1.0),
        )

    def build_loop_budget(self):
        """턴 1회의 3중 한도(FR-45) — runner가 factory로 쓴다."""
        from .domain.models import BudgetConsumed, LoopBudget
        from .ports.tools import (
            TOOL_CORPUS_SEARCH,
            TOOL_EXTRACT_EVIDENCE,
            TOOL_FETCH_PAPER,
            TOOL_LIVE_LOOKUP,
            TOOL_READ_PAPER,
            TOOL_VIEW_FIGURE,
        )

        return LoopBudget(
            max_iterations=self.max_iterations,
            max_tool_calls_total=self.max_tool_calls_total,
            max_tool_calls={
                TOOL_CORPUS_SEARCH: self.cap_corpus_search,
                # 세 소스 **합산** 3회다(§3.2) — 소스마다 3이 아니다. 캡 키는 곧 도구
                # 이름이라(`budget.max_tool_calls.get(tool_name)`) 어긋나면 캡이 조용히
                # 무한대가 된다 — 예외도 로그도 없다.
                TOOL_LIVE_LOOKUP: self.cap_live_lookup,
                TOOL_FETCH_PAPER: self.cap_fetch_paper,
                TOOL_READ_PAPER: self.cap_read_paper,
                TOOL_VIEW_FIGURE: self.cap_view_figure,
                TOOL_EXTRACT_EVIDENCE: self.cap_extract_evidence,
            },
            token_cost_limit_usd=self.token_cost_limit_usd,
            consumed=BudgetConsumed(),
        )
