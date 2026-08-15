"""``model_ver`` must rotate the summary cache key whenever the models change.

Cached summaries live at a path containing ``model_ver``; a read that finds the path skips the
LLM entirely. So a stale ``model_ver`` does not fail — it serves the PREVIOUS model's text with
no error and no log line, which is the hardest shape of wrong to notice. It used to be a
hand-maintained constant, so the rotation depended on someone remembering to bump it.
"""

from __future__ import annotations

import pytest

from summarization.adapters.settings import (
    DEFAULT_SUMMARY_MODEL,
    DEFAULT_TRANSLATE_MODEL,
    SummarizationSettings,
    model_ver,
)


def test_changing_either_model_changes_the_key() -> None:
    base = model_ver(DEFAULT_SUMMARY_MODEL, DEFAULT_TRANSLATE_MODEL)

    assert model_ver("global.anthropic.claude-opus-5", DEFAULT_TRANSLATE_MODEL) != base
    assert model_ver(DEFAULT_SUMMARY_MODEL, "global.anthropic.claude-haiku-9") != base
    # ...and the same pair is stable, or every deploy would invalidate the cache.
    assert model_ver(DEFAULT_SUMMARY_MODEL, DEFAULT_TRANSLATE_MODEL) == base


def test_a_version_bump_alone_rotates_the_key() -> None:
    """The subtle case: same family, newer version. Dropping the version from the slug would
    make ``sonnet-4-6`` and ``sonnet-4-7`` share a cache."""
    a = model_ver("global.anthropic.claude-sonnet-4-6", DEFAULT_TRANSLATE_MODEL)
    b = model_ver("global.anthropic.claude-sonnet-4-7", DEFAULT_TRANSLATE_MODEL)

    assert a != b


def test_key_is_path_safe_and_readable() -> None:
    """It goes into an S3 object path, so no ``.``/``:``/``/`` from the profile id — and it
    should still say which model it is, or a stale object can't be diagnosed by eye."""
    key = model_ver(DEFAULT_SUMMARY_MODEL, DEFAULT_TRANSLATE_MODEL)

    assert not set(key) & set("./: _+%")  # 경로에 이미 있던 문자(-)만 쓴다
    assert "sonnet-4-6" in key
    assert "haiku-4-5" in key


def test_settings_derives_it_from_the_ids_it_resolved(monkeypatch) -> None:
    """The wiring, not just the helper: overriding the env must reach the cache key."""
    monkeypatch.setenv("DOCSURI_SUMMARY_MODEL_ID", "global.anthropic.claude-opus-5")
    monkeypatch.delenv("DOCSURI_TRANSLATE_MODEL_ID", raising=False)

    settings = SummarizationSettings.from_env()

    assert settings.summary_model_id == "global.anthropic.claude-opus-5"
    assert settings.model_ver == model_ver(
        "global.anthropic.claude-opus-5", DEFAULT_TRANSLATE_MODEL
    )
    assert settings.model_ver != model_ver(DEFAULT_SUMMARY_MODEL, DEFAULT_TRANSLATE_MODEL)


@pytest.mark.parametrize(
    "model_id",
    ["global.anthropic.claude-sonnet-4-6", "anthropic.claude-sonnet-4-6", "sonnet-4-6"],
)
def test_profile_prefix_is_stripped_but_the_model_survives(model_id: str) -> None:
    """Only the vendor/profile prefix is dropped — the three spellings of the SAME model must
    agree, or switching to an inference profile would silently orphan the cache."""
    assert model_ver(model_id, DEFAULT_TRANSLATE_MODEL) == model_ver(
        "global.anthropic.claude-sonnet-4-6", DEFAULT_TRANSLATE_MODEL
    )
