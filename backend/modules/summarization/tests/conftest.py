"""Pytest fixtures. Shared stubs/helpers live in ``tests.stubs`` (real-first: test-only)."""

from __future__ import annotations

import pytest

from summarization.domain.models import SummaryDraft
from tests.stubs import SAMPLE_PAPER, valid_draft


@pytest.fixture(autouse=True)
def _isolate_boto3_default_session():
    """Drop boto3's process-wide default session between tests.

    ``boto3.client(...)`` lazily builds a module-level ``DEFAULT_SESSION`` and that session
    RESOLVES AND CACHES credentials on first use. A test that monkeypatches AWS_* env vars
    therefore leaks into every later test in the process: monkeypatch restores the environment,
    but the already-resolved credentials on the cached session are never re-read.

    That silently disabled the S3 round-trip tests — a fake key set by an earlier unit test was
    still in force when the integration module built its client, so it failed to authenticate and
    self-skipped. A skip reads as a pass, so the tests written to prove the read path works were
    reported green while never running. Reset the slot so each test resolves credentials fresh.
    """
    try:
        import boto3
    except ImportError:  # pragma: no cover - the `real` extra is not installed
        yield
        return
    boto3.DEFAULT_SESSION = None
    yield
    boto3.DEFAULT_SESSION = None


@pytest.fixture
def sample_paper() -> str:
    return SAMPLE_PAPER


@pytest.fixture(name="valid_draft")
def valid_draft_fixture() -> SummaryDraft:
    return valid_draft()
