from __future__ import annotations

import pytest

from docsuri_ingestion.adapters.grobid import GrobidHttpClient, _tei_to_text
from docsuri_ingestion.domain.errors import PermanentIngestionError, RetriableIngestionError
from docsuri_ingestion.settings import IngestionSettings, validate_corpus_build_settings


def test_grobid_tei_to_text_extracts_body_text() -> None:
    text = _tei_to_text("<TEI><text><body><p>First</p><p>Second</p></body></text></TEI>")
    assert text == "First Second"


def test_grobid_tei_to_text_rejects_invalid_xml() -> None:
    with pytest.raises(PermanentIngestionError):
        _tei_to_text("<TEI>")


def test_corpus_settings_parse_grobid_and_alias_env() -> None:
    settings = IngestionSettings.model_validate(
        {
            "DOCSURI_GROBID_URL": "http://127.0.0.1:8070",
            "DOCSURI_OPENSEARCH_ALIAS": "docsuri-corpus",
            "DOCSURI_CORPUS_SOURCES": "ARXIV,OPENALEX",
        }
    )

    assert settings.grobid_url == "http://127.0.0.1:8070"
    assert settings.opensearch_alias == "docsuri-corpus"
    assert settings.corpus_sources == "ARXIV,OPENALEX"


def test_corpus_build_preflight_rejects_expensive_or_incomplete_config() -> None:
    settings = IngestionSettings.model_validate(
        {
            "DOCSURI_ENV": "production",
            "DOCSURI_CORPUS_SOURCES": "ARXIV,SEMANTIC_SCHOLAR,OPENALEX",
            "DOCSURI_BEDROCK_MODEL_ID_V2": "cohere.embed-v4",
        }
    )

    with pytest.raises(RuntimeError) as exc:
        validate_corpus_build_settings(settings)

    assert "DOCSURI_MULTIMODAL_ASSETS_ENABLED" in str(exc.value)
    assert "DOCSURI_BEDROCK_MODEL_ID_V2" in str(exc.value)
    assert "DOCSURI_CORPUS_BUILD_ROLLOUT_CONFIRMED" in str(exc.value)
    assert "DOCSURI_GROBID_URL" in str(exc.value)


def test_corpus_build_preflight_accepts_ready_config() -> None:
    settings = IngestionSettings.model_validate(
        {
            "DOCSURI_ENV": "production",
            "DOCSURI_CORPUS_SOURCES": "ARXIV,SEMANTIC_SCHOLAR,OPENALEX",
            "DOCSURI_GROBID_URL": "http://grobid.internal:8070",
            "DOCSURI_MULTIMODAL_ASSETS_ENABLED": "true",
            "DOCSURI_CORPUS_BUILD_ROLLOUT_CONFIRMED": "true",
        }
    )

    validate_corpus_build_settings(settings)


class _Response:
    def __init__(self, status_code: int, text: str = "<TEI><text>ok</text></TEI>") -> None:
        self.status_code = status_code
        self.text = text


def test_grobid_429_is_retriable(monkeypatch) -> None:
    def post(*args, **kwargs):
        del args, kwargs
        return _Response(429)

    import httpx

    monkeypatch.setattr(httpx, "post", post)
    client = GrobidHttpClient(base_url="http://grobid.test")

    with pytest.raises(RetriableIngestionError):
        client.extract_text(b"%PDF")


def test_grobid_bad_pdf_400_is_permanent(monkeypatch) -> None:
    def post(*args, **kwargs):
        del args, kwargs
        return _Response(400)

    import httpx

    monkeypatch.setattr(httpx, "post", post)
    client = GrobidHttpClient(base_url="http://grobid.test")

    with pytest.raises(PermanentIngestionError):
        client.extract_text(b"%PDF")
