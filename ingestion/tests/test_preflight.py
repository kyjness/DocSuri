"""A corpus batch refuses to start when a dependency it needs is down.

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

from docsuri_ingestion.runtime import RuntimeServices, preflight_dependencies, probe_grobid
from docsuri_ingestion.settings import IngestionSettings

_ARXIV_ONLY = ("ARXIV",)
_WITH_EXTERNAL = ("ARXIV", "SEMANTIC_SCHOLAR")


class _Embedding:
    def __init__(self, error: Exception | None = None) -> None:
        self._error = error
        self.calls = 0

    def embed_documents(self, texts, *, correlation_id=None):  # noqa: ARG002
        self.calls += 1
        if self._error is not None:
            raise self._error
        return [[0.0] * DIMENSIONS for _ in texts]


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


def _dead_grobid(monkeypatch) -> None:
    def boom(url, timeout=None):  # noqa: ARG001
        raise ConnectionError("connection refused")

    monkeypatch.setattr("httpx.get", boom)


def test_a_reachable_stack_passes(monkeypatch) -> None:
    monkeypatch.setattr(
        "httpx.get", lambda url, timeout=None: type("R", (), {"status_code": 200})()
    )
    embedding = _Embedding()

    preflight_dependencies(
        _runtime(embedding),
        _settings(DOCSURI_GROBID_URL="http://grobid:8070"),
        sources=_WITH_EXTERNAL,
    )

    assert embedding.calls == 1, "the embedding path must be exercised, not just configured"


def test_a_dead_grobid_stops_a_run_that_parses_non_arxiv_sources(monkeypatch) -> None:
    """S2/OpenAlex have no ar5iv rung — GROBID is their only structure parser, so a run that
    touches them cannot proceed without it."""
    _dead_grobid(monkeypatch)

    with pytest.raises(RuntimeError, match="GROBID"):
        preflight_dependencies(
            _runtime(_Embedding()),
            _settings(DOCSURI_GROBID_URL="http://grobid:8070"),
            sources=_WITH_EXTERNAL,
        )


def test_a_dead_grobid_only_warns_an_arxiv_only_run(monkeypatch, caplog) -> None:
    """An arXiv-id list is served by the ar5iv rung for all but a small minority, and on a small
    box GROBID is better left DOWN: it holds 1.7GB resident while Docling needs 1.6GB to re-read a
    table, and the two together killed both the container and the worker mid-paper.

    So the run proceeds — but it must SAY so. Losing that slice silently is the failure this whole
    module exists to prevent, and the fix cannot reintroduce it in the name of convenience.
    """
    _dead_grobid(monkeypatch)

    with caplog.at_level("WARNING"):
        preflight_dependencies(
            _runtime(_Embedding()),
            _settings(DOCSURI_GROBID_URL="http://grobid:8070"),
            sources=_ARXIV_ONLY,
        )

    assert any("GROBID" in record.getMessage() for record in caplog.records), (
        "a down GROBID passed without a word"
    )


def test_the_source_set_decides_not_a_hand_passed_flag(monkeypatch) -> None:
    """The rule lives in one place — the same ``GROBID_ONLY_SOURCES`` test the settings check
    uses — applied to whatever this run will actually parse. A hand-passed boolean drifted from it
    immediately: it hard-blocked an arXiv-only rebuild that the settings layer says needs no
    GROBID at all."""
    _dead_grobid(monkeypatch)

    # Same settings, same dead GROBID; only the run's declared sources differ.
    settings = _settings(DOCSURI_GROBID_URL="http://grobid:8070")
    preflight_dependencies(_runtime(_Embedding()), settings, sources=_ARXIV_ONLY)
    with pytest.raises(RuntimeError):
        preflight_dependencies(_runtime(_Embedding()), settings, sources=_WITH_EXTERNAL)


def test_an_exhausted_embedding_quota_stops_the_batch() -> None:
    """The throttle answers immediately and looks like any other dependency error — which is why
    it has to be probed rather than assumed."""
    embedding = _Embedding(error=RuntimeError("Too many tokens per day"))

    with pytest.raises(RuntimeError, match="embedding call failed"):
        preflight_dependencies(_runtime(embedding), _settings(), sources=_ARXIV_ONLY)


def test_a_runtime_without_an_embedding_port_is_a_failure_not_a_skip() -> None:
    """The guard must not be able to pass by checking nothing. A builder that forgets the field
    would otherwise make the probe a silent no-op — and the five-hour quota outage comes back with
    a green pre-flight in the log."""
    with pytest.raises(RuntimeError, match="embedding port"):
        preflight_dependencies(_runtime(None), _settings(), sources=_ARXIV_ONLY)


def test_every_failure_is_reported_not_just_the_first(monkeypatch) -> None:
    """Fixing one and rediscovering the next an hour later is the failure mode this whole check
    exists to remove."""
    _dead_grobid(monkeypatch)
    embedding = _Embedding(error=RuntimeError("Too many tokens per day"))

    with pytest.raises(RuntimeError) as caught:
        preflight_dependencies(
            _runtime(embedding),
            _settings(DOCSURI_GROBID_URL="http://grobid:8070"),
            sources=_WITH_EXTERNAL,
        )

    assert "GROBID" in str(caught.value)
    assert "embedding" in str(caught.value)


def test_no_grobid_configured_is_not_a_failure(monkeypatch) -> None:
    """A run without it configured is a valid (arXiv-HTML-only) shape and must not be blocked."""
    monkeypatch.setattr("httpx.get", lambda url, timeout=None: pytest.fail("must not be called"))

    preflight_dependencies(_runtime(_Embedding()), _settings(), sources=_WITH_EXTERNAL)


def test_grobid_can_be_probed_before_the_runtime_exists(monkeypatch) -> None:
    """``probe_grobid`` takes settings alone so the CLI can call it BEFORE
    ``build_production_runtime`` imports Docling and pix2tex and loads their models. Probing after
    that build made an operator whose GROBID was down wait out the whole torch import."""
    _dead_grobid(monkeypatch)

    problem = probe_grobid(_settings(DOCSURI_GROBID_URL="http://grobid:8070"), required=True)

    assert problem is not None and "GROBID" in problem
