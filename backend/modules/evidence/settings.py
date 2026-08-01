"""EvidenceSettings — env-driven config (U11 infrastructure-design).

``evidence_enabled`` gates real adapter assembly: the app-shell mounts U11 only when
the required deps (Bedrock model + S3 DocModel bucket) are configured.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from docsuri_shared.env import env_flag as _env_flag

# v2 어댑터는 OpenAI 호환 HTTP를 친다(TD-EV2-2) — 기본값도 그 어휘여야 한다.
# v1의 Bedrock 추론 프로파일명을 그대로 두면 실경로가 마운트되고도 매 호출이
# 모델 미존재로 실패해 llm_unavailable로만 수렴한다(로컬 실측에서 드러났다).
DEFAULT_EVIDENCE_MODEL = 'gpt-4o-mini'


@dataclass(frozen=True, slots=True)
class EvidenceSettings:
    model_id: str
    docmodel_bucket: str | None   # S3 bucket (U1 소유 DocModel 버킷)
    region_name: str | None
    # 비동기 잡 경로 게이트 (BR-EV-6, NFR-P6)
    async_enabled: bool
    job_queue_url: str | None     # SQS evidence-agent-job-queue

    @property
    def evidence_enabled(self) -> bool:
        # 실 경로 = DocModel S3 버킷 필요 (Bedrock는 항상 사용 가능 가정)
        return bool(self.docmodel_bucket)

    @classmethod
    def from_env(cls) -> EvidenceSettings:
        return cls(
            model_id=os.environ.get('DOCSURI_EVIDENCE_MODEL_ID', DEFAULT_EVIDENCE_MODEL),
            docmodel_bucket=os.environ.get('DOCSURI_DOCMODEL_BUCKET'),
            region_name=os.environ.get('AWS_REGION') or os.environ.get('AWS_DEFAULT_REGION'),
            async_enabled=_env_flag('DOCSURI_EVIDENCE_ASYNC_ENABLED'),
            job_queue_url=os.environ.get('DOCSURI_EVIDENCE_JOB_QUEUE_URL'),
        )
