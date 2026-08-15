"""A corpus batch refuses to start when a dependency is down.

Both failures this guards against actually happened on the ⑧-2 foundational run (2026-08-14/15),
and both were CORRECTLY CONFIGURED — the settings validation passed and the thing they named
simply was not answering:

- GROBID's container exited five seconds after starting and nothing noticed. About 42% of arXiv
  papers fall to the PDF/GROBID rung, so that whole slice failed for the entire run.
- Bedrock's daily token quota ran out mid-batch. The run then spent five and a half hours
  fetching, parsing and rendering page crops for 490 papers that all died at the embed step —
  nothing indexed, and every one of them written to the ledger as `failed`, so recovering them
  costs the parse a second time.

Neither is visible in the output, because a paper that fails is simply absent. They surface only
as a failure counter, which is exactly the thing nobody watches during an unattended run.
"""

from __future__ import annotations

import pytest
from docsuri_shared.vector_spec import DIMENSIONS

from docsuri_ingestion.runtime import RuntimeServices, preflight_dependencies
from docsuri_ingestion.settings import IngestionSettings


class _Embedding:
    def __init__(self, dims: int = DIMENSIONS, error: Exception | None = None) -> None:
        self._dims = dims
        self._error = error
        self.calls = 0

    def embed_documents(self, texts, *, correlation_id=None):  # noqa: ARG002
        self.calls += 1
        if self._error is not None:
            raise self._error
        return [[0.0] * self._dims for _ in texts]


def _runtime(embedding=None) -> RuntimeServices:
    return RuntimeServices(
        pipeline=object(),
        refresh=object(),
        queue=object(),
        observability=object(),
        embedding=embedding,
    )


def _settings(**kwargs) -> IngestionSettings:
    return IngestionSettings(DOCSURI_ENV="production", **kwargs)


def test_a_reachable_stack_passes(monkeypatch) -> None:
    monkeypatch.setattr(
        "httpx.get", lambda url, timeout=None: type("R", (), {"status_code": 200})()
    )
    embedding = _Embedding()

    preflight_dependencies(_runtime(embedding), _settings(DOCSURI_GROBID_URL="http://grobid:8070"))

    assert embedding.calls == 1, "the embedding path must be exercised, not just configured"


def test_a_dead_grobid_stops_the_batch(monkeypatch) -> None:
    """The container had exited; the URL was still correct. 42% of papers would have failed."""

    def boom(url, timeout=None):  # noqa: ARG001
        raise ConnectionError("connection refused")

    monkeypatch.setattr("httpx.get", boom)

    with pytest.raises(RuntimeError, match="GROBID"):
        preflight_dependencies(
            _runtime(_Embedding()), _settings(DOCSURI_GROBID_URL="http://grobid:8070")
        )


def test_an_exhausted_embedding_quota_stops_the_batch() -> None:
    """The throttle answers immediately and looks like any other dependency error — which is why
    it has to be probed rather than assumed."""
    embedding = _Embedding(error=RuntimeError("Too many tokens per day"))

    with pytest.raises(RuntimeError, match="embedding call failed"):
        preflight_dependencies(_runtime(embedding), _settings())


def test_a_wrong_dimension_stops_the_batch() -> None:
    """A model swap that still answers is worse than one that fails: both sides of this system are
    1024-dimensional, so a mismatch shows up only as bad search results much later."""
    with pytest.raises(RuntimeError, match="dims"):
        preflight_dependencies(_runtime(_Embedding(dims=768)), _settings())


def test_every_failure_is_reported_not_just_the_first(monkeypatch) -> None:
    """Fixing one and rediscovering the next an hour later is the failure mode this whole check
    exists to remove."""

    def boom(url, timeout=None):  # noqa: ARG001
        raise ConnectionError("connection refused")

    monkeypatch.setattr("httpx.get", boom)
    embedding = _Embedding(error=RuntimeError("Too many tokens per day"))

    with pytest.raises(RuntimeError) as caught:
        preflight_dependencies(
            _runtime(embedding), _settings(DOCSURI_GROBID_URL="http://grobid:8070")
        )

    assert "GROBID" in str(caught.value)
    assert "embedding" in str(caught.value)


def test_no_grobid_configured_is_not_a_failure(monkeypatch) -> None:
    """Only the non-arXiv sources hard-require GROBID; a run without it configured is a valid
    (arXiv-HTML-only) shape and must not be blocked here."""
    monkeypatch.setattr("httpx.get", lambda url, timeout=None: pytest.fail("must not be called"))

    preflight_dependencies(_runtime(_Embedding()), _settings())


def test_a_down_grobid_is_a_warning_when_the_run_can_proceed_without_it(
    monkeypatch, caplog
) -> None:
    """An arXiv-id list is served by the ar5iv rung for all but a small minority, and on a small
    box GROBID is better left DOWN: it holds 1.7GB resident while Docling needs 1.6GB to re-read a
    table, and the two together killed both the container and the worker mid-paper.

    So the run proceeds — but it must SAY so. Losing that slice silently is the failure this whole
    module exists to prevent, and the fix cannot reintroduce it in the name of convenience.
    """

    def boom(url, timeout=None):  # noqa: ARG001
        raise ConnectionError("connection refused")

    monkeypatch.setattr("httpx.get", boom)

    with caplog.at_level("WARNING"):
        preflight_dependencies(
            _runtime(_Embedding()),
            _settings(DOCSURI_GROBID_URL="http://grobid:8070"),
            require_grobid=False,
        )

    assert any("GROBID" in record.getMessage() for record in caplog.records), (
        "a down GROBID passed without a word"
    )


def test_the_embedding_probe_is_never_optional() -> None:
    """Unlike GROBID, there is no partial mode: with the embedder down nothing reaches the index
    at all, so every paper the run touches is wasted work."""
    embedding = _Embedding(error=RuntimeError("Too many tokens per day"))

    with pytest.raises(RuntimeError, match="embedding"):
        preflight_dependencies(_runtime(embedding), _settings(), require_grobid=False)
