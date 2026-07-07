from __future__ import annotations

from backend.modules.evidence.extractor import _filter_hallucinated

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
