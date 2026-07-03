"""GlossaryResolver — BR-S4 / Q8: keep-as-is preserved, user simple-noun post-substitution."""

from __future__ import annotations

import pytest

from summarization.domain.glossary import GlossaryResolver, is_glossary_worthy
from summarization.domain.models import Glossary, TermMapping


@pytest.mark.parametrize(
    "term",
    [
        # model / method / dataset / metric names + acronyms — real keywords
        "SAM", "TransUNet", "iTransformer", "TimeMixer++", "CIFAR-100", "MSE", "HD95",
        "Segment Anything", "Softmax", "Hessian", "Danskin", "ETTh1", "SSFormer-L", "T5",
    ],
)
def test_is_glossary_worthy_keeps_keywords(term: str) -> None:
    assert is_glossary_worthy(term) is True


@pytest.mark.parametrize(
    "term",
    [
        # Greek variables / LaTeX commands standing alone
        "theta", "eta", "rho", "nabla", "partial", "rangle", "odot", "varepsilon", "mid",
        # sub/superscripts, expressions, LaTeX fragments, relations, single letters, citations
        "W_q", "nabla_theta", "L_att^sm", "L(w+delta)", "O(rho^2)", "mathbb{E}", "sqrt{2eta T}",
        "1/L", "H=96", "partial theta", "eta Td", "w-eta", "F", "S", "He et al., 2023",
    ],
)
def test_is_glossary_worthy_drops_math_notation(term: str) -> None:
    assert is_glossary_worthy(term) is False


def test_resolve_fail_soft_on_repo_error() -> None:
    # Personal-term overrides are OPTIONAL: a repo fault (DB down, table not yet migrated) must
    # NOT propagate — it would fail-close the whole summary/translate to "근거 없음". Degrade to
    # the shared seed glossary (no personal terms) instead.
    class _BrokenRepo:
        def get_user_glossary(self, user_id):
            raise RuntimeError("relation \"user_glossary\" does not exist")

    g = GlossaryResolver(_BrokenRepo()).resolve("u1")
    assert g.user_overrides == ()  # degraded — no crash


class _TermRepo:
    """A repo whose term set can be swapped per test."""

    def __init__(self, terms: tuple[TermMapping, ...] = ()) -> None:
        self.terms = terms

    def get_user_glossary(self, user_id):
        return self.terms


def test_summary_signature_ignores_post_substitution_edits() -> None:
    # NFR-C1: summary output varies ONLY with prompt-enforced terms. A post-substitution-only term
    # set must yield the baseline signature (0) so it never forks the per-user summary cache.
    res = GlossaryResolver(
        _TermRepo(terms=(TermMapping("attention", "어텐션", prompt_enforced=False),))
    )
    assert res.prompt_glossary_signature("u1") == 0  # post-sub only → shared baseline


def test_summary_signature_changes_when_prompt_enforced_term_demoted() -> None:
    # BR-S1: the signature is content-based (not a filtered MAX), so DEMOTING a prompt-enforced
    # term to post-substitution changes it → the stale summary is invalidated (the regression a
    # non-monotonic MAX(glossary_ver) WHERE prompt_enforced would have).
    enforced = GlossaryResolver(
        _TermRepo(
            terms=(
                TermMapping("attention", "어텐션", prompt_enforced=True),
                TermMapping("embedding", "임베딩", prompt_enforced=True),
            )
        )
    ).prompt_glossary_signature("u1")
    demoted = GlossaryResolver(
        _TermRepo(
            terms=(
                TermMapping("attention", "어텐션", prompt_enforced=False),  # demoted
                TermMapping("embedding", "임베딩", prompt_enforced=True),
            )
        )
    ).prompt_glossary_signature("u1")
    assert enforced != 0 and demoted != 0 and enforced != demoted


def test_summary_signature_degrades_to_baseline_on_fault() -> None:
    class _BrokenRepo:
        def get_user_glossary(self, user_id):
            raise RuntimeError("db down")

    # A signature fault must degrade to the shared baseline (0), not fail the request.
    assert GlossaryResolver(_BrokenRepo()).prompt_glossary_signature("u1") == 0
    assert GlossaryResolver(None).prompt_glossary_signature("u1") == 0


def test_signature_of_matches_prompt_glossary_signature() -> None:
    # signature_of is the pure (no-I/O) core; prompt_glossary_signature is resolve()+signature_of.
    # The orchestrator uses signature_of on an already-resolved glossary — they must agree.
    terms = (
        TermMapping("attention", "어텐션", prompt_enforced=True),
        TermMapping("잠재공간", "latent space", prompt_enforced=False),
    )
    repo = _TermRepo(terms=terms)
    resolver = GlossaryResolver(repo)
    glossary = resolver.resolve("u1")
    assert GlossaryResolver.signature_of(glossary) == resolver.prompt_glossary_signature("u1")
    # Pure over a Glossary with only weak terms → baseline (0), like the wrapper.
    weak_only = Glossary(user_overrides=(TermMapping("주의", "어텐션", prompt_enforced=False),))
    assert GlossaryResolver.signature_of(weak_only) == 0


def test_post_substitute_applies_user_simple_noun() -> None:
    glossary = Glossary(
        user_overrides=(TermMapping("잠재공간", "latent space", prompt_enforced=False),)
    )
    out = GlossaryResolver.post_substitute("이 모델은 잠재공간을 학습한다.", glossary)
    assert "latent space" in out
    assert "잠재공간" not in out


def test_post_substitute_is_idempotent() -> None:
    glossary = Glossary(user_overrides=(TermMapping("주의", "어텐션", prompt_enforced=False),))
    once = GlossaryResolver.post_substitute("주의 메커니즘", glossary)
    twice = GlossaryResolver.post_substitute(once, glossary)
    assert once == twice


def test_prompt_enforced_overrides_are_not_post_substituted() -> None:
    # prompt_enforced terms are injected into the prompt, NOT applied as post-substitution.
    glossary = Glossary(user_overrides=(TermMapping("embedding", "임베딩", prompt_enforced=True),))
    out = GlossaryResolver.post_substitute("embedding space", glossary)
    assert out == "embedding space"


def test_resolve_includes_seed_keep_as_is() -> None:
    glossary = GlossaryResolver(None).resolve("user-1")
    assert "Transformer" in glossary.keep_as_is
    assert glossary.user_overrides == ()


# --- personal strong override may replace a shared seed mapping (lock removed, BR-S4) -----------


class _CapRepo:
    """Owner-scoped repo that records upsert calls (and never returns saved terms)."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def get_user_glossary(self, user_id):
        return ()

    def upsert_term(self, user_id, term_from, term_to, *, prompt_enforced):
        self.calls.append((user_id, term_from, term_to, prompt_enforced))
        return 1


def test_strong_override_of_seed_mapping_is_allowed() -> None:
    # No lock: a personal STRONG override of a shared seed mapping (attention→어텐션) is permitted —
    # it wins over the seed for that user (precedence handled in the prompt, see _glossary_block).
    repo = _CapRepo()
    ver = GlossaryResolver(repo).upsert_term("u1", "attention", "주목", prompt_enforced=True)
    assert ver == 1
    assert repo.calls == [("u1", "attention", "주목", True)]


def test_weak_override_delegates() -> None:
    repo = _CapRepo()
    GlossaryResolver(repo).upsert_term("u1", "encoder", "인코더", prompt_enforced=False)
    assert repo.calls == [("u1", "encoder", "인코더", False)]
