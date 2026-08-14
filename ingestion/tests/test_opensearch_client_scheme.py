"""The OpenSearch client's TLS follows the endpoint, not the call site.

Three call sites each decided this separately and the pipeline writer — the one that indexes a
whole batch — did not decide at all: it took ``use_ssl=True`` and spoke TLS to an ``http://``
cluster, so every ``_bulk`` died with ``WRONG_VERSION_NUMBER``. That is the worst place for this
failure to live, because it comes after the fetch, the parse and the embedding: a run's papers are
paid for in full and then dropped at the last step.

Pinned here rather than left to the call sites, since a missing keyword argument is invisible in
review — the wrong value looks exactly like no value.
"""

from __future__ import annotations

import pytest

from docsuri_ingestion.adapters.aws import OpenSearchVectorIndex, build_opensearch_client


def _client_kwargs(monkeypatch) -> dict:
    """Capture what the opensearch-py constructor is actually handed."""
    seen: dict = {}

    class _Recorder:
        def __init__(self, **kwargs) -> None:
            seen.update(kwargs)

    monkeypatch.setattr("opensearchpy.OpenSearch", _Recorder)
    return seen


@pytest.mark.parametrize(
    ("endpoint", "tls"),
    [
        ("http://localhost:9200", False),
        ("https://search-docsuri.ap-northeast-2.es.amazonaws.com", True),
    ],
)
def test_tls_is_read_off_the_endpoint_scheme(monkeypatch, endpoint: str, tls: bool) -> None:
    seen = _client_kwargs(monkeypatch)
    build_opensearch_client(endpoint=endpoint)
    assert seen["use_ssl"] is tls
    assert seen["verify_certs"] is tls


def test_the_pipeline_writer_gets_the_same_derivation(monkeypatch) -> None:
    """The writer is the call site that had it wrong, so it is asserted on its own rather than
    trusted to inherit the factory's behaviour."""
    seen = _client_kwargs(monkeypatch)
    OpenSearchVectorIndex(endpoint="http://localhost:9200", index_name="docsuri-deploy-v1")
    assert seen["use_ssl"] is False
    assert seen["verify_certs"] is False


def test_an_explicit_value_still_wins(monkeypatch) -> None:
    """A caller that means to skip verification behind a TLS terminator must still be able to say
    so — the derivation is a default, not a policy."""
    seen = _client_kwargs(monkeypatch)
    build_opensearch_client(endpoint="http://localhost:9200", use_ssl=True, verify_certs=False)
    assert seen["use_ssl"] is True
    assert seen["verify_certs"] is False
