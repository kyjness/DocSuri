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
