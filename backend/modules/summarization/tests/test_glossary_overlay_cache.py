"""Personal-glossary — shared base translation (masked standard-term tokens) + serve-time render +
seed cache-invalidation (BR-S1/BR-S4/NFR-C1).

Translate caches ONE shared base per paper: standard terms are masked into ``⟦N⟧`` tokens and the
user's weak (post-substitution) terms are NOT baked in. On read, ``render_translation`` restores the
tokens to their effective rendering (seed default or the user's strong override) with josa
normalization, applies weak terms, and builds ``standardGlossary`` from the tokens that occur. So a
term edit — weak OR strong-of-a-seed — reflects by re-rendering the SAME base (no fork/regenerate),
and a seed edit self-invalidates the path.
"""

from __future__ import annotations

import json

from summarization.domain import glossary as glossary_mod
from summarization.domain.assembler import ResultAssembler
from summarization.domain.cache_key import build_cache_key
from summarization.domain.glossary import GlossaryResolver
from summarization.domain.masking import build_mask_table
from summarization.domain.models import (
    AuthSession,
    Glossary,
    RequestContext,
    SourceKind,
    SourceText,
    SummaryRequest,
    Task,
    TermMapping,
    TranslationDraft,
)
from tests.stubs import StubStore, make_orchestrator, tiny_doc


class _FakeGlossaryRepo:
    """Owner-scoped term store whose per-user term set can be swapped mid-test (edit simulation)."""

    def __init__(self, terms_by_user: dict[str, tuple[TermMapping, ...]]) -> None:
        self.terms_by_user = terms_by_user

    def get_user_glossary(self, user_id: str):
        return self.terms_by_user.get(user_id, ())

    def upsert_term(self, user_id, term_from, term_to, *, prompt_enforced) -> int:  # unused here
        return 1


def _ctx(user: str = "u1") -> RequestContext:
    return RequestContext(auth_session=AuthSession(user_id=user), request_id="r")


def _translate_req() -> SummaryRequest:
    return SummaryRequest(paper_id="2401.1", version=1, task=Task.TRANSLATE,
                          abstract="An abstract about BERT.")


def _text(result) -> str:
    return json.dumps(result.to_dict(), ensure_ascii=False)


def _weak(term_from: str, term_to: str) -> TermMapping:
    return TermMapping(term_from, term_to, prompt_enforced=False)


def _orch(store: StubStore, terms_by_user: dict[str, tuple[TermMapping, ...]]):
    resolver = GlossaryResolver(_FakeGlossaryRepo(terms_by_user))
    return make_orchestrator(store=store, glossary_resolver=resolver)


# Seed-derived mask table, to embed the right token for a term in synthetic bases.
_TABLE = build_mask_table()


def _tok(term: str) -> str:
    for e in _TABLE.entries:
        if e.term_from.lower() == term.lower():
            return e.token
    raise KeyError(term)


# --- orchestrator: shared base, weak overlay on read ------------------------------------


def test_weak_terms_share_one_base_across_users() -> None:
    # Two users with DIFFERENT weak terms → identical prompt-enforced signature (0) → same shared
    # base key (no owner segment). The second user is a cache HIT (no re-translation), yet each
    # user sees their OWN weak overlay applied on read (NFR-C1: one base, per-user views).
    store = StubStore()
    orch = _orch(store, {
        "u1": (_weak("BERT", "버트"),),
        "u2": (_weak("BERT", "베르트"),),
    })
    r1 = orch.run(_translate_req(), _ctx("u1"))
    r2 = orch.run(_translate_req(), _ctx("u2"))

    assert store.puts == 1  # ONE shared base — u2 hit u1's base, no second generation
    assert r2.to_dict()["cached"] is True
    assert "버트" in _text(r1) and "베르트" not in _text(r1)  # u1's overlay
    assert "베르트" in _text(r2) and "버트" not in _text(r2)  # u2's overlay


def test_weak_edit_reflected_on_read_without_retranslation() -> None:
    # Editing a weak term does not change the cache key → HIT → the new term is applied by the
    # read-time render (no re-translation, no per-user fork). This is the core cost win.
    store = StubStore()
    terms: dict[str, tuple[TermMapping, ...]] = {"u1": (_weak("BERT", "버트"),)}
    orch = _orch(store, terms)

    r1 = orch.run(_translate_req(), _ctx())
    assert store.puts == 1 and "버트" in _text(r1)

    terms["u1"] = (_weak("BERT", "베르트"),)  # user edits the preferred term
    r2 = orch.run(_translate_req(), _ctx())
    assert store.puts == 1  # NO re-translation — same key, cache HIT
    assert r2.to_dict()["cached"] is True
    assert "베르트" in _text(r2) and "버트" not in _text(r2)  # edit reflected on read


def test_strong_seed_edit_reflected_without_fork_or_retranslation() -> None:
    # A STRONG override of a SEED term (attention→주목) is now a read-time re-render of the masked
    # token — same shared base, NO cache fork and NO re-translation (the Q2 win). The base carries
    # the ⟦attention⟧ token; editing only changes the rendering the render step inserts.
    para = f"모델은 {_tok('attention')}를 쓴다."
    # Build a token-carrying base directly (bypasses the stub's abstract text).
    base = ResultAssembler().assemble_translation(
        TranslationDraft(doc_model=tiny_doc(paragraph=para), kept_terms=()),
        SourceText(kind=SourceKind.ABSTRACT),
    ).to_dict()
    g1 = Glossary(user_overrides=(TermMapping("attention", "주목", prompt_enforced=True),))
    v1 = ResultAssembler.render_translation(base, g1)
    assert "주목" in json.dumps(v1, ensure_ascii=False)
    # A different override renders differently from the SAME base object (no regeneration).
    g2 = Glossary(user_overrides=(TermMapping("attention", "어텐선", prompt_enforced=True),))
    v2 = ResultAssembler.render_translation(base, g2)
    blob2 = json.dumps(v2, ensure_ascii=False)
    assert "어텐선" in blob2 and "주목" not in blob2


def test_hit_and_miss_views_match_for_same_user() -> None:
    # The fresh (write-through) view and the cache-hit view are identical except for ``cached``.
    store = StubStore()
    orch = _orch(store, {"u1": (_weak("BERT", "버트"),)})
    miss = orch.run(_translate_req(), _ctx()).to_dict()
    hit = orch.run(_translate_req(), _ctx()).to_dict()
    assert miss["cached"] is False and hit["cached"] is True
    assert {k: v for k, v in miss.items() if k != "cached"} == {
        k: v for k, v in hit.items() if k != "cached"
    }


def test_stored_base_carries_tokens_and_is_render_free() -> None:
    # What lands in the store is the BASE: standard-term tokens un-rendered, no weak substitution
    # and no standardGlossary (all serve-time). So it is reusable across users.
    store = StubStore()
    orch = _orch(store, {"u1": (_weak("BERT", "버트"),)})
    orch.run(_translate_req(), _ctx())
    (stored,) = store.data.values()
    blob = json.dumps(stored, ensure_ascii=False)
    assert _tok("BERT") in blob  # standard term masked in the base text
    assert "버트" not in blob  # weak overlay not baked in
    assert "standardGlossary" not in stored["translation"]  # built on read


# --- assembler: base carries tokens, render restores on read ----------------------------


def _src() -> SourceText:
    return SourceText(kind=SourceKind.ABSTRACT)


def _rendered(paragraph: str, glossary: Glossary, *, kept=()) -> dict:
    draft = TranslationDraft(doc_model=tiny_doc(title="", paragraph=paragraph), kept_terms=kept)
    base = ResultAssembler().assemble_translation(draft, _src()).to_dict()
    return ResultAssembler.render_translation(base, glossary)["translation"]


def test_assemble_translation_keeps_tokens_and_defers_glossary() -> None:
    # The assembled base carries masked tokens + raw keptTerms; rendering + standardGlossary are
    # serve-time (kept out of the shared base so it stays user-agnostic).
    para = f"모델은 {_tok('attention')} 을 쓴다."
    base = ResultAssembler().assemble_translation(
        TranslationDraft(doc_model=tiny_doc(paragraph=para), kept_terms=("SAM",)), _src()
    ).to_dict()["translation"]
    assert _tok("attention") in base["docModel"]["sections"][0]["blocks"][0]["text"]
    assert "standardGlossary" not in base  # built on read
    assert base["keptTerms"] == ["SAM"]


def test_render_restores_tokens_and_builds_standard_glossary() -> None:
    para = f"{_tok('attention')}를 쓰는 {_tok('Transformer')}, {_tok('BLEU')} 평가."
    tr = _rendered(para, Glossary(), kept=("SAM",))
    text = tr["docModel"]["sections"][0]["blocks"][0]["text"]
    # mapping token → Korean (josa fixed: 를→을 after ㄴ받침); keep-as-is tokens → English.
    assert "어텐션을" in text and "Transformer" in text and "BLEU" in text
    assert "⟦" not in text and "⟧" not in text
    std = tr["standardGlossary"]
    assert {"term": "attention", "translated": "어텐션"} in std
    assert {"term": "Transformer"} in std and {"term": "BLEU"} in std
    assert tr["docModel"]["fullText"].count("어텐션") == 1  # reprojected, aligned


def test_render_recovers_keepasis_present_without_token() -> None:
    # A keep-as-is term present in text but NOT as a token (verbatim field like a table cell, or a
    # mask-missed variant) is still recovered into standardGlossary by exact text presence (BR-S4),
    # not dropped or mis-grouped under 원어 유지.
    tr = _rendered("이 논문은 BERT 를 쓴다.", Glossary())  # literal BERT, no token
    assert {"term": "BERT"} in tr["standardGlossary"]


def test_render_standard_glossary_only_lists_present_tokens() -> None:
    # A seed term whose token is absent from THIS paper never becomes a chip (exact by token, no
    # string-match heuristic). Free-form (non-seed) kept terms are preserved.
    para = f"모델은 {_tok('VAE')} 와 {_tok('GNN')} 을 쓴다."
    tr = _rendered(para, Glossary(), kept=("VAE", "GNN", "CrysBFN"))
    assert {g["term"] for g in tr["standardGlossary"]} == {"VAE", "GNN"}
    # VAE/GNN are standard keep-as-is → 표준 only, so stripped from keptTerms; only the genuinely
    # non-standard term survives in 원어 유지.
    assert tr["keptTerms"] == ["CrysBFN"]


def test_render_applies_weak_terms_and_reprojects_fulltext() -> None:
    # Weak (post-substitution) simple-noun terms are applied on the rendered Korean; fullText is
    # re-projected so it stays aligned. (A non-seed term, so it isn't masked.)
    tr = _rendered("이것은 모델 이다.", Glossary(user_overrides=(_weak("모델", "신경망"),)))
    assert tr["docModel"]["sections"][0]["blocks"][0]["text"] == "이것은 신경망 이다."
    assert "신경망" in tr["docModel"]["fullText"]


def test_render_strong_override_changes_text_and_chip() -> None:
    # A strong override of a seed term re-renders its token at serve — the chip stays (editable,
    # pre-filled) and the TEXT shows the override, no stale seed-rendering chip.
    para = f"모델은 {_tok('attention')}를 쓰는 {_tok('Transformer')} 이다."
    glossary = Glossary(user_overrides=(
        TermMapping("attention", "주목", prompt_enforced=True),
        TermMapping("Transformer", "트랜스포머", prompt_enforced=True),
    ))
    tr = _rendered(para, glossary)
    text = tr["docModel"]["sections"][0]["blocks"][0]["text"]
    assert "주목" in text and "트랜스포머" in text and "어텐션" not in text
    std = tr["standardGlossary"]
    assert {"term": "attention", "translated": "주목"} in std
    assert {"term": "Transformer", "translated": "트랜스포머"} in std
    assert {"term": "attention", "translated": "어텐션"} not in std


def test_render_filters_math_notation_from_kept_terms() -> None:
    # keptTerms exposes only keyword-like terms; Greek vars / expressions / LaTeX fragments drop.
    para = f"모델은 {_tok('attention')}를 쓴다."
    kept = ("SAM", "MSE", "CIFAR-100", "theta", "W_q", "L(w+delta)", "mathbb{E}", "F")
    tr = _rendered(para, Glossary(), kept=kept)
    assert tr["keptTerms"] == ["SAM", "MSE", "CIFAR-100"]


def test_render_strips_echoed_tokens_from_kept_terms() -> None:
    # Real models sometimes echo the masked tokens back in keptTerms ("I kept ⟦G0⟧ verbatim").
    # Those internal artifacts must never surface as 원어 유지 chips (observed in a real smoke).
    para = f"모델은 {_tok('attention')}를 쓴다."
    tr = _rendered(para, Glossary(), kept=(_tok("attention"), _tok("Transformer"), "SAM"))
    assert tr["keptTerms"] == ["SAM"]  # tokens dropped, real term kept
    assert not any("⟦" in t for t in tr["keptTerms"])


def test_render_strips_standard_renderings_from_kept_terms() -> None:
    # The seed glossary rides into the translate prompt as variant guidance, so the model echoes
    # seed renderings into keptTerms — mapping Korean (어텐션·임베딩·잠재 공간), keep-as-is English
    # (Transformer), or a user override (주목). None of these may surface as 원어 유지 chips; only
    # genuinely non-standard kept terms survive (BR-S4). attention + Transformer are both present.
    para = f"모델은 {_tok('attention')}와 {_tok('Transformer')}를 쓴다."
    glossary = Glossary(user_overrides=(TermMapping("attention", "주목", prompt_enforced=True),))
    kept = ("어텐션", "임베딩", "잠재 공간", "Transformer", "주목", "SAM")
    tr = _rendered(para, glossary, kept=kept)
    assert tr["keptTerms"] == ["SAM"]  # every standard rendering dropped, real term kept


def test_render_keeps_kept_term_colliding_with_absent_seed() -> None:
    # A non-standard kept term coinciding with an ABSENT seed rendering ("Adam" the person vs the
    # Adam optimizer, which is not in this paper) must NOT be stripped — keep-as-is stripping is
    # scoped to terms present in the paper. Mapping Korean is still stripped globally.
    para = f"모델은 {_tok('attention')}를 쓴다."  # attention present; Adam absent
    tr = _rendered(para, Glossary(), kept=("Adam", "SAM", "어텐션"))
    assert tr["keptTerms"] == ["Adam", "SAM"]  # collision preserved; mapping Korean stripped


def test_render_strips_decomposed_hangul_rendering() -> None:
    # NFC guard: the model may emit decomposed (NFD) Hangul; the standard-rendering strip must still
    # match it (else the seed Korean leaks back into 원어 유지 — the exact fixed bug).
    import unicodedata

    para = f"모델은 {_tok('attention')}를 쓴다."
    nfd = unicodedata.normalize("NFD", "어텐션")
    assert nfd != "어텐션"  # sanity: actually decomposed
    tr = _rendered(para, Glossary(), kept=(nfd, "SAM"))
    assert tr["keptTerms"] == ["SAM"]


def test_render_does_not_mutate_base() -> None:
    # render works on a copy — the cached base keeps its token, and gains no standardGlossary.
    para = f"모델은 {_tok('attention')}를 쓴다."
    base = ResultAssembler().assemble_translation(
        TranslationDraft(doc_model=tiny_doc(paragraph=para), kept_terms=()), _src()
    ).to_dict()
    ResultAssembler.render_translation(base, Glossary())
    assert _tok("attention") in base["translation"]["docModel"]["sections"][0]["blocks"][0]["text"]
    assert "standardGlossary" not in base["translation"]


# --- task-aware glossary signature (translate vs summary fork) --------------------------


def _seed_glossary(*overrides: TermMapping) -> Glossary:
    base = GlossaryResolver(None).resolve(None)
    return Glossary(
        seed_mappings=base.seed_mappings, keep_as_is=base.keep_as_is, user_overrides=overrides
    )


def test_translate_signature_zero_for_seed_strong_override() -> None:
    # A strong override of a SEED term does NOT fork translate (rendered on read from shared base),
    # but summary still forks (no masking there) — the two tasks diverge by design.
    g = _seed_glossary(TermMapping("attention", "주목", prompt_enforced=True))
    assert GlossaryResolver.signature_of_translate(g) == 0
    assert GlossaryResolver.signature_of(g) != 0


def test_translate_signature_forks_for_non_seed_strong_override() -> None:
    # A strong override of a term NOT in the seed is not masked → still forks (owner-scoped), as
    # before (that path stays soft-prompt enforced).
    g = _seed_glossary(TermMapping("GPIO", "지피아이오", prompt_enforced=True))
    assert GlossaryResolver.signature_of_translate(g) != 0


def test_translate_signature_zero_for_weak_only() -> None:
    g = _seed_glossary(TermMapping("모델", "신경망", prompt_enforced=False))
    assert GlossaryResolver.signature_of_translate(g) == 0


def test_translate_key_carries_format_version_summary_does_not() -> None:
    kt = build_cache_key(_translate_req(), glossary_ver=0, model_ver="m", user_id=None, seed_ver="")
    assert "-m1" in kt.object_path()
    ks = build_cache_key(
        SummaryRequest(paper_id="p", version=1, task=Task.SUMMARY),
        glossary_ver=0, model_ver="m", user_id=None, seed_ver="",
    )
    assert "-m1" not in ks.object_path()


# --- seed change → cache self-invalidation ----------------------------------------------


def test_current_seed_diverges_from_baseline_and_activates_segment() -> None:
    # The shipped seed was intentionally edited past the frozen baseline (strong-term finalization:
    # fine-tuning demoted to keep-as-is + keep-as-is enrichment), so the seed segment is ACTIVE
    # (non-empty, == current SEED_VER) → prior seed-based artifacts self-invalidate on deploy.
    assert glossary_mod.SEED_VER != glossary_mod._SEED_BASELINE_VER
    assert glossary_mod.seed_cache_segment() == glossary_mod.SEED_VER
    assert glossary_mod.seed_cache_segment() != ""


def test_seed_edit_flips_segment_and_changes_path(monkeypatch) -> None:
    req = _translate_req()
    k_base = build_cache_key(req, glossary_ver=0, model_ver="m", user_id="u1", seed_ver="")
    assert "_s" not in k_base.object_path()

    monkeypatch.setattr(glossary_mod, "SEED_VER", "deadbeef")
    assert glossary_mod.seed_cache_segment() == "deadbeef"
    k_seed = build_cache_key(
        req, glossary_ver=0, model_ver="m", user_id="u1", seed_ver=glossary_mod.seed_cache_segment()
    )
    assert "_sdeadbeef" in k_seed.object_path()
    assert k_seed.object_path() != k_base.object_path()  # seed edit → new key → miss → regenerate
