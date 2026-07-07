from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from docsuri_shared._generated.dtos.docmodel_schema import DocModel
from docsuri_shared._generated.dtos.evidence_schema import EvidenceItem, SourceRef

from .prompts import build_evidence_extraction_prompt

logger = logging.getLogger(__name__)

_MAX_RETRIES = 1
_MAX_TOKENS = 8192
_CB_FAILURE_THRESHOLD = 5
_CB_RECOVERY_TIMEOUT = 30.0


class LlmUnavailable(Exception):
    """Bedrock 호출 불가 — Orchestrator가 fail-closed로 처리(BR-EV-12)."""


DocModelSource = tuple[str, DocModel] | tuple[str, DocModel, str]


class _LocalCircuitBreaker:
    def __init__(self) -> None:
        self._failures = 0
        self._open_until: float = 0.0

    def allow_request(self) -> bool:
        if self._open_until and time.monotonic() < self._open_until:
            return False
        return True

    def record_success(self) -> None:
        self._failures = 0
        self._open_until = 0.0

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= _CB_FAILURE_THRESHOLD:
            self._open_until = time.monotonic() + _CB_RECOVERY_TIMEOUT


class EvidenceExtractor:
    """LLM 호출 + INV-EV-3 날조 금지 강제 — DocModel 원문에 없는 statement 제거."""

    def __init__(
        self,
        *,
        model_id: str,
        region_name: str | None = None,
        client: Any | None = None,
        max_retries: int = _MAX_RETRIES,
        cost_guard: Any | None = None,
    ) -> None:
        if client is None:
            import boto3
            from botocore.config import Config

            config = Config(
                connect_timeout=5.0,
                read_timeout=60.0,
                retries={'max_attempts': 1},
            )
            client = boto3.client('bedrock-runtime', region_name=region_name, config=config)
        self._client = client
        self._model_id = model_id
        self._max_retries = max_retries
        self._cb = _LocalCircuitBreaker()
        # NFR-C1: Bedrock 사용량(USD 추정)을 기록할 cost guard — None이면 계측 생략.
        self._cost_guard = cost_guard

    def extract(
        self,
        topic: str,
        doc_models: list[DocModelSource],
    ) -> list[EvidenceItem]:
        """DocModel 블록 → EvidenceItem 목록.

        빈 배열이면 Orchestrator가 abstain 처리 (INV-EV-2).
        """
        if not doc_models:
            return []

        system, user = build_evidence_extraction_prompt(topic, doc_models)
        payload = self._invoke_json(system, user)
        raw_items: list[dict] = payload.get('items', [])

        paper_texts = _build_paper_texts(doc_models)
        paper_anchor_ids = _build_paper_anchor_ids(doc_models)
        return _filter_hallucinated(raw_items, paper_texts, paper_anchor_ids)

    def _invoke_json(self, system: str, user: str) -> dict:
        if not self._cb.allow_request():
            raise LlmUnavailable('EvidenceExtractor circuit breaker OPEN')

        body = {
            'anthropic_version': 'bedrock-2023-05-31',
            'max_tokens': _MAX_TOKENS,
            'system': system,
            'messages': [{'role': 'user', 'content': [{'type': 'text', 'text': user}]}],
        }
        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            if attempt > 0:
                time.sleep(2 ** attempt * 0.5)
            try:
                text = self._stream_text(body)
                payload = _parse_json(text)
                self._cb.record_success()
                return payload
            except Exception as exc:
                last_exc = exc
        self._cb.record_failure()
        raise LlmUnavailable('EvidenceExtractor Bedrock call failed') from last_exc

    def _stream_text(self, body: dict) -> str:
        response = self._client.invoke_model_with_response_stream(
            modelId=self._model_id,
            body=json.dumps(body).encode('utf-8'),
            accept='application/json',
            contentType='application/json',
        )
        chunks: list[str] = []
        invocation_metrics: dict = {}
        for event in response['body']:
            chunk = event.get('chunk', {})
            raw = chunk.get('bytes', b'')
            if raw:
                data = json.loads(raw)
                if data.get('type') == 'content_block_delta':
                    delta = data.get('delta', {})
                    if delta.get('type') == 'text_delta':
                        chunks.append(delta.get('text', ''))
                # 마지막 청크에 실리는 Bedrock 사용량 — NFR-C1 지출 기록용.
                metrics = data.get('amazon-bedrock-invocationMetrics')
                if metrics:
                    invocation_metrics = metrics
        self._record_spend(invocation_metrics)
        return ''.join(chunks)

    def _record_spend(self, metrics: dict) -> None:
        """NFR-C1 — invocationMetrics를 cost guard 지출로 기록. 계측 실패가 추출을 막지 않는다."""
        if self._cost_guard is None or not metrics:
            return
        try:
            from uuid import uuid4

            from docsuri_ops.cost_guard import estimate_bedrock_usd
            from docsuri_ops.domain.models import UsageEvent

            amount = estimate_bedrock_usd(
                input_tokens=int(metrics.get('inputTokenCount') or 0),
                output_tokens=int(metrics.get('outputTokenCount') or 0),
            )
            if amount > 0:
                self._cost_guard.record_spend(
                    UsageEvent(
                        event_id=f'evidence-extract-{uuid4()}',
                        amount_usd=amount,
                        source='evidence.extractor',
                    )
                )
        except Exception:  # noqa: BLE001 — 지출 계측은 best-effort
            logger.warning('failed to record evidence Bedrock spend', exc_info=True)


def _parse_json(text: str) -> dict:
    text = text.strip()
    start = text.find('{')
    end = text.rfind('}')
    if start == -1 or end == -1:
        return {}
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {}


def _build_paper_texts(doc_models: list[DocModelSource]) -> dict[str, str]:
    """paper_id → 전체 텍스트 맵 (INV-EV-3 quote 검증용)."""
    result: dict[str, str] = {}
    for source in doc_models:
        paper_id, doc_model = source[0], source[1]
        result[paper_id] = doc_model.fullText
    return result


def _build_paper_anchor_ids(doc_models: list[DocModelSource]) -> dict[str, set[str]]:
    """paper_id → 실제 Section/Block id 집합 (anchor 검증용, PR #338 리뷰 Medium #15).

    anchor는 DocModel Section/Block id를 가리켜 UI의 "원문 이동" 링크가 참조한다.
    LLM이 존재하지 않는 id(예: 's99.p1')를 지어내도 여태 그대로 통과시켜서 그 링크가
    깨질 수 있었다."""
    result: dict[str, set[str]] = {}
    for source in doc_models:
        paper_id, doc_model = source[0], source[1]
        ids: set[str] = set()
        for section in getattr(doc_model, 'sections', None) or []:
            _collect_anchor_ids(section, ids)
        result[paper_id] = ids
    return result


def _collect_anchor_ids(section: object, ids: set[str]) -> None:
    section_id = getattr(section, 'id', None)
    if section_id:
        ids.add(section_id)
    for block in getattr(section, 'blocks', None) or []:
        block_id = getattr(getattr(block, 'root', block), 'id', None)
        if block_id:
            ids.add(block_id)
    for nested in getattr(section, 'sections', None) or []:
        _collect_anchor_ids(nested, ids)


# INV-EV-3 substring 검사만으로는 'the', '0.9' 같은 1~2토큰 quote가 trivially 통과해
# fullText에 우연히 존재하는 숫자로 날조된 statement를 그라운딩할 수 있다(PR #338 리뷰
# Medium #14). 완전한 문장 단위는 아니지만, 짧은 조각 인용을 걸러내는 최소 방어선.
_MIN_QUOTE_LENGTH = 20

_NUMBER_PATTERN = re.compile(r'\d+(?:\.\d+)?%?')


def _numbers_in(text: str) -> set[str]:
    return set(_NUMBER_PATTERN.findall(text))


def _statement_grounded(statement: str, verified_quotes: list[str]) -> bool:
    """INV-EV-3: statement이 검증된 quote가 뒷받침하지 않는 수치를 날조하지 않았는지 확인.

    statement은 질의 언어로 의역/번역되는 경우가 흔하다(예: 한국어 질문 → 한국어 statement +
    영어 원문 quote). 전체 텍스트 overlap은 언어가 다르면 항상 0에 가까워 신뢰할 수 없으므로,
    언어에 무관한 숫자만 대조한다 — LLM이 실제 quote에 없는 수치(정확도, 복잡도 지수 등)를
    statement에 지어내는 가장 피해가 큰 날조 패턴을 막는 최소 게이트(PR #338 리뷰 Blocking #2).
    """
    statement_numbers = _numbers_in(statement)
    if not statement_numbers:
        return True
    quote_numbers = _numbers_in(' '.join(verified_quotes))
    return statement_numbers.issubset(quote_numbers)


def _filter_hallucinated(
    raw_items: list[dict],
    paper_texts: dict[str, str],
    paper_anchor_ids: dict[str, set[str]] | None = None,
) -> list[EvidenceItem]:
    """INV-EV-3: quote가 원문에 없는 SourceRef 제거 후 유효한 EvidenceItem만 반환."""
    paper_anchor_ids = paper_anchor_ids or {}
    items: list[EvidenceItem] = []
    for raw in raw_items:
        statement = raw.get('statement', '').strip()
        if not statement:
            continue

        supporting = _validate_refs(raw.get('supporting', []), paper_texts, paper_anchor_ids)
        conflicting = _validate_refs(raw.get('conflicting', []), paper_texts, paper_anchor_ids)

        # supporting이 하나도 없으면 해당 item 제거(날조 위험)
        if not supporting:
            logger.warning('dropping EvidenceItem — no valid supporting refs: %.80s', statement)
            continue

        verified_quotes = [ref.quote for ref in supporting if ref.quote]
        if not _statement_grounded(statement, verified_quotes):
            logger.warning(
                'INV-EV-3 violation — statement cites a number absent from verified quotes: %.80s',
                statement,
            )
            continue

        items.append(
            EvidenceItem(
                statement=statement,
                supporting=supporting,
                conflicting=conflicting,
            )
        )
    return items


def _validate_refs(
    raw_refs: list[dict],
    paper_texts: dict[str, str],
    paper_anchor_ids: dict[str, set[str]],
) -> list[SourceRef]:
    valid: list[SourceRef] = []
    for ref in raw_refs:
        paper_id = ref.get('paperId', '')
        record_ref = ref.get('recordRef', '')
        quote = ref.get('quote') or None

        if not paper_id or not record_ref:
            continue

        # INV-EV-3: quote 없는 ref는 grounding으로 인정하지 않는다. SourceRef.quote가
        # optional인 건 DTO 계약(D5) 상 이유이지, LLM이 quote를 생략해 verbatim 검증
        # 자체를 우회해도 된다는 뜻이 아니다(PR #338 리뷰 Blocking #1).
        if not quote:
            logger.warning(
                'INV-EV-3 violation — ref for paper %s has no quote, dropping (ungrounded)',
                paper_id,
            )
            continue

        if len(quote) < _MIN_QUOTE_LENGTH:
            logger.warning(
                'INV-EV-3 violation — quote too short (%d chars) for paper %s, dropping ref',
                len(quote), paper_id,
            )
            continue

        paper_text = paper_texts.get(paper_id, '')
        if quote not in paper_text:
            logger.warning(
                'INV-EV-3 violation — quote not found in paper %s, dropping ref',
                paper_id,
            )
            continue

        anchor = ref.get('anchor') or None
        if anchor and anchor not in paper_anchor_ids.get(paper_id, set()):
            # anchor는 "원문 이동" UI가 참조하는 실제 Section/Block id다. 존재하지
            # 않는 id를 그대로 내보내면 그 링크가 깨진다(PR #338 리뷰 Medium #15) —
            # quote 자체는 verbatim 검증을 통과했으니 ref는 유지하되, 잘못된 anchor만
            # 제거해 UI가 "이동 불가"로 자연히 처리하게 한다.
            logger.warning(
                'anchor %r not found in paper %s block ids, dropping anchor (keeping ref)',
                anchor, paper_id,
            )
            anchor = None

        valid.append(
            SourceRef(
                paperId=paper_id,
                recordRef=record_ref,
                anchor=anchor,
                quote=quote,
            )
        )
    return valid
