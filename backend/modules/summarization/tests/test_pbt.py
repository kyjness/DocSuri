"""Property-based tests (Hypothesis) — PBT-S1~S5 (business-rules.md §2)."""

from __future__ import annotations

from hypothesis import assume, given
from hypothesis import strategies as st

from summarization.domain.cache_key import build_cache_key
from summarization.domain.glossary import GlossaryResolver
from summarization.domain.models import (
    Glossary,
    Persona,
    SummaryRequest,
    SummaryResultDTO,
    Task,
    TermMapping,
    TranslationDraft,
)
from summarization.domain.refiner import InputRefiner

_text = st.text(
    alphabet=st.characters(min_codepoint=32, max_codepoint=126), min_size=0, max_size=400
)


# PBT-S1 — cache key determinism / immutable identity.
@given(
    paper=st.text(min_size=1, max_size=20),
    version=st.integers(min_value=1, max_value=99),
    task=st.sampled_from(list(Task)),
    persona=st.sampled_from(list(Persona)),
    gver=st.integers(min_value=0, max_value=50),
)
def test_pbt_cache_key_deterministic(paper, version, task, persona, gver) -> None:
    req = SummaryRequest(paper_id=paper, version=version, task=task, persona=persona)
    a = build_cache_key(req, glossary_ver=gver, model_ver="m", user_id="u1")
    b = build_cache_key(req, glossary_ver=gver, model_ver="m", user_id="u1")
    assert a == b
    assert a.object_path() == b.object_path()
    # BR-S1: a glossaryVer bump must change the key (path) so the term change invalidates
    # the cached artifact (new object), rather than serving the stale translation.
    bumped = build_cache_key(req, glossary_ver=gver + 1, model_ver="m", user_id="u1")
    assert bumped.object_path() != a.object_path()
    assert bumped.redis_key() != a.redis_key()
    # BR-S1 cross-user isolation: two different users sharing the SAME glossary_ver integer
    # must not share a personalized key (the counter is per-user, not a content identity).
    # The baseline (ver 0, no personal terms) is owner-agnostic and intentionally shared.
    other = build_cache_key(req, glossary_ver=gver, model_ver="m", user_id="u2")
    if gver > 0:
        assert other.object_path() != a.object_path()
        assert other.redis_key() != a.redis_key()
    else:
        assert other.object_path() == a.object_path()


# PBT-S2 — refine is a fixed point on already-refined body.
@given(raw=_text.map(lambda s: s + "\n"))
def test_pbt_refine_idempotent(raw: str) -> None:
    once = InputRefiner().refine(raw).body
    twice = InputRefiner().refine(once).body
    assert once == twice


# PBT-S3 — post-substitution idempotent; keep-as-is words never altered.
@given(text=_text)
def test_pbt_post_substitution_idempotent(text: str) -> None:
    glossary = Glossary(user_overrides=(TermMapping("주의", "어텐션", prompt_enforced=False),))
    once = GlossaryResolver.post_substitute(text, glossary)
    twice = GlossaryResolver.post_substitute(once, glossary)
    assert once == twice


@given(text=_text)
def test_pbt_keep_as_is_invariant(text: str) -> None:
    # An empty user glossary must never change the text (keep-as-is is prompt-side, not post-sub).
    assert GlossaryResolver.post_substitute(text, Glossary()) == text


# PBT-S4 — response to_dict round-trip exposes no internal fields (SEC-9) for all terminal states.
# Internal identifiers that must never appear in the serialized DTO.
_SEC9_FORBIDDEN = ("model_ver", "prompt_ver", "token", "redis", "cache_key", "user_id")


@given(
    status=st.sampled_from(["ok_summary", "ok_translate", "abstain", "cost_degraded", "source_unavailable"]),
    tldr=_text,
    korean=_text,
    # ``reason`` is a PUBLIC field echoed into the DTO; a free-text value that happens to
    # contain an internal field name is not a SEC-9 leak, so exclude those tokens to avoid a
    # false positive (real reasons are short codes like "insufficient_grounding").
    reason=st.text(min_size=1, max_size=100).filter(
        lambda r: not any(f in r for f in _SEC9_FORBIDDEN)
    ),
)
def test_pbt_response_to_dict_sec9_all_states(status: str, tldr: str, korean: str, reason: str) -> None:
    from summarization.domain.models import SummaryDraft, Anchor, AnchorTarget, AbstainDTO, CostDegradedDTO, SourceUnavailableDTO
    if status == "ok_summary":
        draft = SummaryDraft(
            tldr=tldr,
            contributions=("A",),
            method="M",
            results="R",
            limitations="L",
            reproducibility={"code": "", "data": ""},
            anchors=(Anchor("results", AnchorTarget.SECTION, span="S", label="L"),),
            truncated=False,
        )
        dto = SummaryResultDTO(task=Task.SUMMARY, summary=draft, meta={"source": "full_text"})
    elif status == "ok_translate":
        from tests.stubs import tiny_doc

        dto = SummaryResultDTO(
            task=Task.TRANSLATE,
            translation=TranslationDraft(
                doc_model=tiny_doc(paragraph=korean or "x"), kept_terms=("BERT",)
            ),
            meta={"source": "abstract"},
        )
    elif status == "abstain":
        dto = AbstainDTO(reason=reason)
    elif status == "cost_degraded":
        dto = CostDegradedDTO()
    else:
        dto = SourceUnavailableDTO(reason=reason)

    out = dto.to_dict()
    flat = str(out)
    for forbidden in _SEC9_FORBIDDEN:
        assert forbidden not in flat
    # ponytail: "cost" is a legitimate PUBLIC abstain reason ({"status":"abstain","reason":"cost"}),
    # not a SEC-9 internal field — the whitelisted forbidden set above is the real non-exposure check.


# PBT-S5 — 앵커 검증 건전성 (Step 34).
@given(
    span=st.text(min_size=1, max_size=50),
    ref_body=st.text(min_size=10, max_size=500),
    is_present=st.booleans()
)
def test_pbt_anchor_validation_soundness(span: str, ref_body: str, is_present: bool) -> None:
    from summarization.domain.grounding import GroundingValidator
    from summarization.domain.models import GroundingInput, SummaryDraft, Anchor, AnchorTarget, RefinedSource

    # whitespace-only spans strip to "" → the validator treats them as no-span (auto-pass);
    # the present/absent soundness property only holds once the span is non-empty after strip.
    assume(span.strip())
    
    # If is_present is True, ensure the span exists in the ref_body
    if is_present:
        ref_body = ref_body + span
    else:
        # Ensure span is NOT in ref_body
        ref_body = ref_body.replace(span, "")
        if span in ref_body:
            return
            
    draft = SummaryDraft(
        tldr="tldr text",
        contributions=("C",),
        method="method text",
        results="results text",  # No numbers to avoid numeric mismatch
        limitations="limitations text",
        reproducibility={"code": "", "data": ""},
        anchors=(Anchor("results", AnchorTarget.SECTION, span=span, label=""),),
        truncated=False,
    )
    refined = RefinedSource(body=ref_body, captions=())
    gi = GroundingInput(draft=draft, refined=refined)
    
    verdict = GroundingValidator().validate(gi)
    if is_present:
        assert not any(v.kind == "anchor_missing" for v in verdict.violations)
    else:
        assert not verdict.ok
        assert any(v.kind == "anchor_missing" for v in verdict.violations)
