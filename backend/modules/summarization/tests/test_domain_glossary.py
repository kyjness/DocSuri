"""GlossaryResolver — BR-S4 / Q8: keep-as-is preserved, user simple-noun post-substitution."""

from __future__ import annotations

from summarization.domain.glossary import GlossaryResolver
from summarization.domain.models import Glossary, TermMapping


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
    """A repo whose term set can be swapped per test, returning the version/terms shape."""

    def __init__(self, terms: tuple[TermMapping, ...] = (), version: int = 0) -> None:
        self.terms = terms
        self.version = version

    def get_user_glossary(self, user_id):
        return self.terms

    def get_glossary_version(self, user_id):
        return self.version


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


def test_full_version_unaffected() -> None:
    assert GlossaryResolver(_TermRepo(version=5)).glossary_version("u1") == 5


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
