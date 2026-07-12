from __future__ import annotations

import json
from types import SimpleNamespace

from backend.modules.evidence.extractor import EvidenceExtractor, _filter_hallucinated

_PAPER_TEXT = (
    'We propose OPAC, a pessimistic actor-critic algorithm that learns a latent reward '
    'model. OPAC achieves a 12.5% improvement over the baseline on the held-out set.'
)
_VERBATIM_QUOTE = 'OPAC, a pessimistic actor-critic algorithm that learns a latent reward model'


def _raw_item(
    *,
    statement: str,
    supporting: list[dict],
    conflicting: list[dict] | None = None,
) -> dict:
    return {
        'statement': statement,
        'supporting': supporting,
        'conflicting': conflicting or [],
    }


def test_quote_less_ref_is_not_counted_as_grounding() -> None:
    """PR #338 Blocking #1 — quote를 생략한 ref는 verbatim 검증을 우회해선 안 된다."""
    raw_items = [
        _raw_item(
            statement='OPAC learns a latent reward model.',
            supporting=[{'paperId': 'p1', 'recordRef': 'p1#abs'}],  # quote 없음
        )
    ]
    items = _filter_hallucinated(raw_items, {'p1': _PAPER_TEXT})
    assert items == []


def test_ref_with_fabricated_quote_is_dropped() -> None:
    raw_items = [
        _raw_item(
            statement='OPAC learns a latent reward model.',
            supporting=[{'paperId': 'p1', 'recordRef': 'p1#abs', 'quote': 'not in the paper text'}],
        )
    ]
    items = _filter_hallucinated(raw_items, {'p1': _PAPER_TEXT})
    assert items == []


def test_ref_with_verbatim_quote_is_accepted() -> None:
    raw_items = [
        _raw_item(
            statement='OPAC learns a latent reward model.',
            supporting=[{'paperId': 'p1', 'recordRef': 'p1#abs', 'quote': _VERBATIM_QUOTE}],
        )
    ]
    items = _filter_hallucinated(raw_items, {'p1': _PAPER_TEXT})
    assert len(items) == 1
    assert items[0].supporting[0].quote is not None


def test_ref_with_short_quote_is_dropped() -> None:
    """PR #338 Medium #14 — 1~2토큰짜리 짧은 quote는 trivially 통과하면 안 된다."""
    raw_items = [
        _raw_item(
            statement='OPAC learns a latent reward model.',
            supporting=[{'paperId': 'p1', 'recordRef': 'p1#abs', 'quote': 'OPAC'}],
        )
    ]
    items = _filter_hallucinated(raw_items, {'p1': _PAPER_TEXT})
    assert items == []


def test_statement_with_fabricated_number_is_dropped() -> None:
    """PR #338 Blocking #2 — statement이 검증된 quote에 없는 수치를 지어내면 제거."""
    raw_items = [
        _raw_item(
            statement='OPAC achieves a 99.9% improvement over the baseline.',
            supporting=[{'paperId': 'p1', 'recordRef': 'p1#abs', 'quote': _VERBATIM_QUOTE}],
        )
    ]
    items = _filter_hallucinated(raw_items, {'p1': _PAPER_TEXT})
    assert items == []


def test_statement_with_verified_number_is_accepted() -> None:
    quote = 'OPAC achieves a 12.5% improvement over the baseline on the held-out set.'
    raw_items = [
        _raw_item(
            statement='OPAC achieves a 12.5% improvement over the baseline.',
            supporting=[{'paperId': 'p1', 'recordRef': 'p1#abs', 'quote': quote}],
        )
    ]
    items = _filter_hallucinated(raw_items, {'p1': _PAPER_TEXT})
    assert len(items) == 1


def test_statement_without_numbers_skips_number_check() -> None:
    raw_items = [
        _raw_item(
            statement='이 논문의 핵심 기여는 잠재 보상 모델 학습이다.',  # 한국어 의역, 숫자 없음
            supporting=[{'paperId': 'p1', 'recordRef': 'p1#abs', 'quote': _VERBATIM_QUOTE}],
        )
    ]
    items = _filter_hallucinated(raw_items, {'p1': _PAPER_TEXT})
    assert len(items) == 1


def test_conflicting_refs_also_require_verbatim_quotes() -> None:
    raw_items = [
        _raw_item(
            statement='OPAC learns a latent reward model.',
            supporting=[{'paperId': 'p1', 'recordRef': 'p1#abs', 'quote': _VERBATIM_QUOTE}],
            conflicting=[{'paperId': 'p2', 'recordRef': 'p2#abs'}],  # quote 없음
        )
    ]
    items = _filter_hallucinated(raw_items, {'p1': _PAPER_TEXT, 'p2': 'unrelated text'})
    assert len(items) == 1
    assert items[0].conflicting == []


# ---------------------------------------------------------------------------
# PR #338 리뷰 Medium #15 — anchor는 실제 DocModel Section/Block id와 대조돼야 한다
# ---------------------------------------------------------------------------

def test_anchor_matching_real_block_id_is_kept() -> None:
    raw_items = [
        _raw_item(
            statement='OPAC learns a latent reward model.',
            supporting=[
                {
                    'paperId': 'p1',
                    'recordRef': 'p1#abs',
                    'quote': _VERBATIM_QUOTE,
                    'anchor': 's3.p2',
                }
            ],
        )
    ]
    items = _filter_hallucinated(
        raw_items, {'p1': _PAPER_TEXT}, {'p1': {'s3.p2', 's3'}}
    )
    assert len(items) == 1
    assert items[0].supporting[0].anchor == 's3.p2'


def test_fabricated_anchor_is_dropped_but_ref_is_kept() -> None:
    """존재하지 않는 anchor("원문 이동" 링크가 깨지는 원인)는 제거하되, quote로 이미
    검증된 ref 자체는 grounding 가치가 있으니 버리지 않는다."""
    raw_items = [
        _raw_item(
            statement='OPAC learns a latent reward model.',
            supporting=[
                {
                    'paperId': 'p1',
                    'recordRef': 'p1#abs',
                    'quote': _VERBATIM_QUOTE,
                    'anchor': 's99.p1',  # 존재하지 않는 block id
                }
            ],
        )
    ]
    items = _filter_hallucinated(
        raw_items, {'p1': _PAPER_TEXT}, {'p1': {'s3.p2', 's3'}}
    )
    assert len(items) == 1
    assert items[0].supporting[0].anchor is None


def test_anchor_is_nulled_when_no_anchor_index_given() -> None:
    """paper_anchor_ids를 안 넘기면(기존 호출부 하위호환) 검증 불가능한 anchor로 취급해
    fail-closed로 무효화한다 — 검증 안 된 anchor를 신뢰해 링크를 노출하지 않는다."""
    raw_items = [
        _raw_item(
            statement='OPAC learns a latent reward model.',
            supporting=[
                {
                    'paperId': 'p1',
                    'recordRef': 'p1#abs',
                    'quote': _VERBATIM_QUOTE,
                    'anchor': 's99.p1',
                }
            ],
        )
    ]
    items = _filter_hallucinated(raw_items, {'p1': _PAPER_TEXT})
    assert len(items) == 1
    assert items[0].supporting[0].anchor is None


# ---------------------------------------------------------------------------
# US-EV2(#266) AC2 — 추출 전용 출력: extract() 파이프라인 자체가 C-2/FR-5 게이트를 지난다
# (기존 테스트는 내부 헬퍼 _filter_hallucinated만 직접 호출 — LLM 원시 출력이 컴포넌트
# 경계(extract)를 지나며 걸러지는지는 미고정이었다. QA 2026-07 IMPL-partial-tests 해소.)
# ---------------------------------------------------------------------------


class _FakeBedrockStream:
    """invoke_model_with_response_stream 스탠드인 — 준비된 items 페이로드를 스트림으로 반환."""

    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def invoke_model_with_response_stream(self, **kwargs):
        delta = {
            'type': 'content_block_delta',
            'delta': {'type': 'text_delta', 'text': json.dumps(self._payload)},
        }
        return {'body': [{'chunk': {'bytes': json.dumps(delta).encode('utf-8')}}]}


def test_extract_pipeline_keeps_only_paper_grounded_items() -> None:
    """LLM이 생성 산문·날조 수치를 섞어 반환해도 extract()가 논문 원문 추출 항목만
    내보낸다 — 근거 명제는 논문 원문 기반이며 새로운 주장을 포함하지 않는다(C-2, FR-5)."""
    payload = {
        'items': [
            _raw_item(
                statement='OPAC learns a latent reward model.',
                supporting=[{'paperId': 'p1', 'recordRef': 'p1#abs', 'quote': _VERBATIM_QUOTE}],
            ),
            _raw_item(  # 생성 산문 — quote가 원문에 없다
                statement='The approach generalizes to robotics.',
                supporting=[
                    {
                        'paperId': 'p1',
                        'recordRef': 'p1#abs',
                        'quote': 'the approach generalizes to robotics domains',
                    }
                ],
            ),
            _raw_item(  # 날조 수치 — 검증된 quote에 없는 99.9%
                statement='OPAC achieves a 99.9% improvement.',
                supporting=[{'paperId': 'p1', 'recordRef': 'p1#abs', 'quote': _VERBATIM_QUOTE}],
            ),
        ]
    }
    doc_model = SimpleNamespace(
        fullText=_PAPER_TEXT, sections=[], meta=SimpleNamespace(title='OPAC')
    )
    extractor = EvidenceExtractor(model_id='m', client=_FakeBedrockStream(payload))

    items = extractor.extract(topic='pessimistic actor-critic', doc_models=[('p1', doc_model)])

    assert [item.statement for item in items] == ['OPAC learns a latent reward model.']
    for ref in items[0].supporting:
        assert ref.quote and ref.quote in _PAPER_TEXT  # 살아남은 인용 전부 원문 verbatim


# ---------------------------------------------------------------------------
# US-EV2(#266) AC3 — 쟁점 오버레이: 상충 출처도 verbatim이면 지지 출처와 함께 실린다
# (기존 테스트는 quote 없는 conflicting ref의 '탈락'만 고정 — '유지' 쪽 절반이 비어 있었다.)
# ---------------------------------------------------------------------------

_CONFLICTING_PAPER_TEXT = (
    'A replication study finds the pessimistic actor-critic gains vanish under '
    'distribution shift.'
)


def test_conflicting_ref_with_verbatim_quote_is_kept_alongside_supporting() -> None:
    conflict_quote = 'the pessimistic actor-critic gains vanish under distribution shift'
    raw_items = [
        _raw_item(
            statement='OPAC learns a latent reward model.',
            supporting=[{'paperId': 'p1', 'recordRef': 'p1#abs', 'quote': _VERBATIM_QUOTE}],
            conflicting=[{'paperId': 'p2', 'recordRef': 'p2#abs', 'quote': conflict_quote}],
        )
    ]

    items = _filter_hallucinated(
        raw_items, {'p1': _PAPER_TEXT, 'p2': _CONFLICTING_PAPER_TEXT}
    )

    assert len(items) == 1
    assert [ref.paperId for ref in items[0].supporting] == ['p1']
    assert [ref.paperId for ref in items[0].conflicting] == ['p2']  # 지지/상충이 한 항목에 공존
    assert items[0].conflicting[0].quote == conflict_quote
