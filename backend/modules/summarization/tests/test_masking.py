"""Masking — deterministic standard-term enforcement (BR-S4).

Covers: token round-trip, longest-first, alnum boundaries, effective rendering (seed default vs
strong override), josa normalization (받침 exact for Hangul), the josa-vs-next-word disambiguation
lock case (``⟦G⟧은닉층``), planted/seen index accounting, and the residual-token fail-soft sweep.

The mask table is built from the SHARED SEED constants (``build_mask_table()`` takes no args), so
tokens for a term are looked up from the real table rather than hardcoded indices.
"""

from __future__ import annotations

import pytest

from summarization.domain.masking import (
    MaskEntry,
    build_mask_table,
    found_token_indices,
    mask_text,
    normalize_particle,
    render_tokens,
)

TABLE = build_mask_table()


def _tok(term: str) -> str:
    for e in TABLE.entries:
        if e.term_from.lower() == term.lower():
            return e.token
    raise KeyError(term)


def _seed_effective(entry: MaskEntry) -> str:
    return entry.seed_render


def _effective_with(overrides: dict[str, str]):
    def eff(entry: MaskEntry) -> str:
        return overrides.get(entry.term_from.lower(), entry.seed_render)

    return eff


# --- table ------------------------------------------------------------------
def test_build_mask_table_is_deterministic_and_ordered() -> None:
    t1 = build_mask_table()
    t2 = build_mask_table()
    assert [e.token for e in t1.entries] == [e.token for e in t2.entries]
    # keep-as-is take the first indices (all "keepasis"), then the seed mappings ("mapping").
    kinds = [e.kind for e in t1.entries]
    assert set(kinds[:1]) == {"keepasis"}
    assert kinds[-3:] == ["mapping", "mapping", "mapping"]
    # attention/embedding/latent space are the seed mappings (rendered to Korean).
    mapping_terms = {e.term_from for e in t1.entries if e.kind == "mapping"}
    assert mapping_terms == {"attention", "embedding", "latent space"}


# --- masking ----------------------------------------------------------------
def test_mask_replaces_terms_with_tokens_and_reports_planted() -> None:
    masked, planted = mask_text("The Transformer uses attention over embedding.", TABLE)
    assert "Transformer" not in masked and "attention" not in masked
    assert len(planted) == 3  # three distinct terms planted
    rendered, seen = render_tokens(masked, TABLE, _seed_effective)
    assert "Transformer" in rendered
    assert "어텐션" in rendered and "임베딩" in rendered
    assert seen == planted


def test_mask_is_longest_first_and_boundary_safe() -> None:
    # "fine-tuning" masks as one unit; "F1" must not match inside "F12".
    masked, _ = mask_text("fine-tuning F1 F12", TABLE)
    rendered, _ = render_tokens(masked, TABLE, _seed_effective)
    assert "fine-tuning" in rendered
    assert "F12" in rendered  # untouched


def test_underscore_adjacent_term_is_not_masked() -> None:
    # A term embedded in an identifier ("attention_weights") must NOT be partially masked; only the
    # standalone occurrence is. The identifier form falls back to the prompt's variant guidance.
    masked, planted = mask_text("attention_weights and pure attention", TABLE)
    assert "attention_weights" in masked  # identifier left intact
    assert len(planted) == 1  # only the standalone "attention" masked
    rendered, _ = render_tokens(masked, TABLE, _seed_effective)
    assert "attention_weights" in rendered and "어텐션" in rendered


def test_multiword_mapping_masks_as_unit() -> None:
    masked, planted = mask_text("the latent space of the model", TABLE)
    assert "latent" not in masked and "space" not in masked
    rendered, _ = render_tokens(masked, TABLE, _seed_effective)
    assert "잠재 공간" in rendered


def test_lowercase_occurrence_restores_to_canonical_casing() -> None:
    masked, _ = mask_text("a transformer block", TABLE)
    rendered, _ = render_tokens(masked, TABLE, _seed_effective)
    assert "Transformer" in rendered


# --- effective rendering (override) -----------------------------------------
def test_strong_override_changes_rendering_not_token() -> None:
    masked, _ = mask_text("attention and Transformer", TABLE)
    rendered, _ = render_tokens(
        masked, TABLE, _effective_with({"attention": "주목", "transformer": "트랜스포머"})
    )
    assert "주목" in rendered and "트랜스포머" in rendered
    assert "어텐션" not in rendered


# --- josa normalization -----------------------------------------------------
@pytest.mark.parametrize(
    ("term", "given", "expected"),
    [
        ("어텐션", "는", "은"),  # ㄴ받침 → 은
        ("임베딩", "를", "을"),  # ㅇ받침 → 을
        ("잠재 공간", "은", "은"),  # 간 ㄴ받침 → 은
        ("어텐션", "가", "이"),  # ㄴ받침 → 이
        ("트랜스포머", "은", "는"),  # 머 무받침 → 는
        ("모델", "으로", "로"),  # ㄹ받침 → 로
        ("어텐션", "으로", "으로"),  # ㄴ받침 → 으로
        ("모델", "로", "로"),
    ],
)
def test_normalize_particle_hangul(term: str, given: str, expected: str) -> None:
    assert normalize_particle(term, given) == expected


def test_render_fixes_particle_for_mapping() -> None:
    # The model wrote the wrong allomorph after the token; restore must fix it to 어텐션+은.
    text = _tok("attention") + "는 핵심이다"
    rendered, _ = render_tokens(text, TABLE, _seed_effective)
    assert "어텐션은" in rendered
    assert "어텐션는" not in rendered


def test_particle_disambiguation_next_word_not_josa() -> None:
    # "⟦attention⟧은닉층" — the 은 is the first syllable of 은닉층, NOT a josa. It must stay intact.
    text = _tok("attention") + "은닉층"
    rendered, _ = render_tokens(text, TABLE, _seed_effective)
    assert rendered == "어텐션은닉층"


def test_english_particle_normalized_for_curated_reading() -> None:
    # Transformer (curated reading 트랜스포머, 무받침) → 은 becomes 는.
    text = _tok("Transformer") + "은 강력하다"
    rendered, _ = render_tokens(text, TABLE, _seed_effective)
    assert rendered.startswith("Transformer는")


# --- fail-soft / recovery ---------------------------------------------------
def test_tolerant_matching_absorbs_padded_token() -> None:
    idx = next(e.index for e in TABLE.entries if e.term_from == "attention")
    rendered, seen = render_tokens(f"⟦ G {idx} ⟧ 결과", TABLE, _seed_effective)
    assert "어텐션" in rendered
    assert idx in seen


def test_found_token_indices_detects_dropped_token() -> None:
    masked, planted = mask_text("Transformer with attention", TABLE)
    # Simulate the model dropping one token from the returned text.
    one = next(iter(planted))
    dropped_text = masked.replace(_tok_by_index(one), "", 1)
    assert planted - found_token_indices(dropped_text) == {one}


def test_residual_unknown_token_is_swept() -> None:
    rendered, _ = render_tokens("⟦G9999⟧ 결과", TABLE, _seed_effective)
    assert "⟦" not in rendered and "⟧" not in rendered


def _tok_by_index(index: int) -> str:
    entry = TABLE.by_index(index)
    assert entry is not None
    return entry.token
