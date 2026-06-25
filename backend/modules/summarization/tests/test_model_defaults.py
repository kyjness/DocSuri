"""The default summary/translate model ids must be Bedrock inference profiles.

Bare foundation-model ids (``anthropic.claude-*``) are NOT on-demand invokable in-region —
Bedrock returns a ValidationException ("retry with an inference profile"), which the gateway
turns into ``LlmUnavailable`` → every summary/translate abstains ("근거 없음"). Guard the
defaults so a regression to a bare id is caught before deploy.
"""

from __future__ import annotations

from summarization.adapters.settings import DEFAULT_SUMMARY_MODEL, DEFAULT_TRANSLATE_MODEL

# Bedrock inference-profile id scopes (region/global). A bare foundation-model id has none.
_PROFILE_SCOPES = {"global", "apac", "us", "eu"}


def test_default_models_are_inference_profiles_not_bare_foundation_models() -> None:
    for mid in (DEFAULT_SUMMARY_MODEL, DEFAULT_TRANSLATE_MODEL):
        assert not mid.startswith("anthropic."), f"bare foundation-model id (not invokable): {mid}"
        assert mid.split(".", 1)[0] in _PROFILE_SCOPES, f"not an inference-profile id: {mid}"
