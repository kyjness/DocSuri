"""EvidenceSettings — env-driven config (U11 infrastructure-design).

``evidence_enabled`` gates real adapter assembly: the app-shell mounts U11 only when
the required deps (Bedrock model + S3 DocModel bucket) are configured.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from docsuri_shared.env import env_choice as _env_choice
from docsuri_shared.env import env_flag as _env_flag
from docsuri_shared.env import env_float as _env_float
from docsuri_shared.env import env_int as _env_int

# 프로바이더에 묶인 사실 셋 — (기본 모델, 입력 단가, 출력 단가). 한 테이블에 두는 이유는
# 셋이 함께 움직이기 때문이다: 모델 id는 프로바이더 어휘라 하나로 둘 수 없고(한쪽 어휘만
# 기본값으로 뒀다가 실경로가 마운트되고도 매 호출이 모델 미존재로 실패한 적이 있다), 단가는
# 모델을 따라간다(gpt-4o-mini 단가를 Sonnet에 쓰면 예산 대장이 20배 과소계상된다).
# 흩어놓으면 프로바이더를 추가할 때 편집 지점이 셋이 되고, 과거에 드리프트한 필드가 정확히
# 이 셋이다.
_PROVIDERS: dict[str, tuple[str, float, float]] = {
    'bedrock': ('global.anthropic.claude-sonnet-4-6', 3.0, 15.0),
    'openai': ('gpt-4o-mini', 0.15, 0.60),
}
_DEFAULT_PROVIDER = 'bedrock'


@dataclass(frozen=True, slots=True)
class EvidenceSettings:
    model_id: str
    # 'openai' | 'bedrock' — 어댑터 선택은 composition root에서만 일어난다(TD-EV2-2).
    llm_provider: str
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
    cap_external_search: int
    cap_fetch_paper: int
    cap_read_paper: int
    cap_view_figure: int
    cap_extract_evidence: int
    token_cost_limit_usd: float

    @property
    def evidence_enabled(self) -> bool:
        # 실 경로 = DocModel S3 버킷 필요 (Bedrock는 항상 사용 가능 가정)
        return bool(self.docmodel_bucket)

    @classmethod
    def from_env(cls) -> EvidenceSettings:
        # 기본은 bedrock. OPENAI_API_KEY가 저장소에서 제거된 뒤(2026-08-15) openai를
        # 기본값으로 두면 실경로가 마운트되고도 매 호출이 401로 끝난다. 테이블 자체가
        # 허용 어휘라 오타는 여기서 이름이 불린 채 죽는다 — 조용한 기본값 폴백이 아니다.
        provider = _env_choice('DOCSURI_EVIDENCE_LLM_PROVIDER', _PROVIDERS, _DEFAULT_PROVIDER)
        default_model, in_rate, out_rate = _PROVIDERS[provider]
        return cls(
            llm_provider=provider,
            model_id=os.environ.get('DOCSURI_EVIDENCE_MODEL_ID', default_model),
            docmodel_bucket=os.environ.get('DOCSURI_DOCMODEL_BUCKET'),
            region_name=os.environ.get('AWS_REGION') or os.environ.get('AWS_DEFAULT_REGION'),
            async_enabled=_env_flag('DOCSURI_EVIDENCE_ASYNC_ENABLED'),
            job_queue_url=os.environ.get('DOCSURI_EVIDENCE_JOB_QUEUE_URL'),
            input_usd_per_mtok=_env_float('DOCSURI_EVIDENCE_INPUT_USD_PER_MTOK', in_rate),
            output_usd_per_mtok=_env_float('DOCSURI_EVIDENCE_OUTPUT_USD_PER_MTOK', out_rate),
            max_iterations=_env_int('DOCSURI_EVIDENCE_MAX_ITERATIONS', 12),
            max_tool_calls_total=_env_int('DOCSURI_EVIDENCE_MAX_TOOL_CALLS', 30),
            cap_corpus_search=_env_int('DOCSURI_EVIDENCE_CAP_CORPUS_SEARCH', 5),
            cap_external_search=_env_int('DOCSURI_EVIDENCE_CAP_EXTERNAL_SEARCH', 3),
            cap_fetch_paper=_env_int('DOCSURI_EVIDENCE_CAP_FETCH_PAPER', 3),
            cap_read_paper=_env_int('DOCSURI_EVIDENCE_CAP_READ_PAPER', 8),
            cap_view_figure=_env_int('DOCSURI_EVIDENCE_CAP_VIEW_FIGURE', 6),
            cap_extract_evidence=_env_int('DOCSURI_EVIDENCE_CAP_EXTRACT_EVIDENCE', 8),
            token_cost_limit_usd=_env_float('DOCSURI_EVIDENCE_TURN_COST_LIMIT_USD', 0.50),
        )

    def build_loop_budget(self):
        """턴 1회의 3중 한도(FR-45) — runner가 factory로 쓴다."""
        from .domain.models import BudgetConsumed, LoopBudget
        from .ports.tools import (
            TOOL_CORPUS_SEARCH,
            TOOL_EXTERNAL_SEARCH,
            TOOL_EXTRACT_EVIDENCE,
            TOOL_FETCH_PAPER,
            TOOL_READ_PAPER,
            TOOL_VIEW_FIGURE,
        )

        return LoopBudget(
            max_iterations=self.max_iterations,
            max_tool_calls_total=self.max_tool_calls_total,
            max_tool_calls={
                TOOL_CORPUS_SEARCH: self.cap_corpus_search,
                TOOL_EXTERNAL_SEARCH: self.cap_external_search,
                TOOL_FETCH_PAPER: self.cap_fetch_paper,
                TOOL_READ_PAPER: self.cap_read_paper,
                TOOL_VIEW_FIGURE: self.cap_view_figure,
                TOOL_EXTRACT_EVIDENCE: self.cap_extract_evidence,
            },
            token_cost_limit_usd=self.token_cost_limit_usd,
            consumed=BudgetConsumed(),
        )
