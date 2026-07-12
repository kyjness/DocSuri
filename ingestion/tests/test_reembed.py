"""AWS-free unit tests for the pure helpers of the re-embed rebuild runner. The step functions
themselves hit OpenSearch/Bedrock and are exercised in the live rebuild, not here."""

from docsuri_shared.index_spec import papers_index_body
from docsuri_shared.vector_spec import DIMENSIONS

from docsuri_ingestion.reembed import _embed_text_for_source, _scroll_body
from docsuri_ingestion.settings import IngestionSettings


def test_embed_text_for_abstract_chunk_uses_abstract_field():
    src = {"section": "abstract", "abstract": "the abstract text", "lexicalTerms": ""}
    assert _embed_text_for_source(src) == "the abstract text"


def test_embed_text_for_body_chunk_uses_lexical_terms():
    src = {"section": "1", "lexicalTerms": "normalized body text", "abstract": "abs"}
    assert _embed_text_for_source(src) == "normalized body text"


def test_embed_text_body_chunk_falls_back_to_abstract_then_title():
    assert _embed_text_for_source({"section": "1", "lexicalTerms": "", "abstract": "abs"}) == "abs"
    assert _embed_text_for_source({"section": "1", "title": "the title"}) == "the title"


def test_embed_text_all_empty_returns_empty_string():
    assert _embed_text_for_source({"section": "1"}) == ""
    assert _embed_text_for_source({"section": "abstract"}) == ""


def test_scroll_body_has_no_slice_when_single_shard():
    settings = IngestionSettings()
    body = _scroll_body(settings, page_size=96)
    assert "slice" not in body
    assert body == {"query": {"match_all": {}}, "size": 96}


def test_scroll_body_includes_slice_when_sharded():
    settings = IngestionSettings(DOCSURI_REEMBED_SHARD_COUNT="3", DOCSURI_REEMBED_SHARD="1")
    body = _scroll_body(settings, page_size=50)
    assert body["slice"] == {"id": 1, "max": 3}
    assert body["size"] == 50


def _vector_dim(body: dict) -> int:
    return body["mappings"]["properties"]["vector"]["dimension"]


def test_index_body_dimension_defaults_to_frozen_spec():
    assert _vector_dim(papers_index_body()) == DIMENSIONS
    assert _vector_dim(papers_index_body(on_disk=True)) == DIMENSIONS


def test_index_body_dimension_override_for_reembed():
    # Cohere v4 default (1536) target index without touching the frozen vector-spec.
    assert _vector_dim(papers_index_body(dimension=1536)) == 1536
    assert _vector_dim(papers_index_body(on_disk=True, dimension=1536)) == 1536


def test_estimate_tokens_conservative_and_min_one():
    from docsuri_ingestion.reembed import _estimate_tokens

    assert _estimate_tokens("") == 1  # min 1 so short text still consumes budget
    assert _estimate_tokens("a" * 70) == 20  # ~len/3.5, over-counts vs the real tokenizer
    assert _estimate_tokens("a" * 7000) > _estimate_tokens("a" * 700)


def test_existing_ids_returns_found_subset():
    from docsuri_ingestion.reembed import _existing_ids

    class _FakeClient:
        def mget(self, index, body, _source):
            found = {"a", "c"}
            return {"docs": [{"_id": i, "found": i in found} for i in body["ids"]]}

    assert _existing_ids(_FakeClient(), "idx", ["a", "b", "c"]) == {"a", "c"}
    assert _existing_ids(_FakeClient(), "idx", []) == set()


def test_token_bucket_acquire_amount_and_oversized_batch(monkeypatch):
    import docsuri_ingestion.resilience as resilience
    from docsuri_ingestion.resilience import TokenBucket

    now = 0.0
    sleeps = []

    def fake_monotonic():
        return now

    def fake_sleep(seconds):
        nonlocal now
        sleeps.append(seconds)
        now += seconds

    monkeypatch.setattr(resilience.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(resilience.time, "sleep", fake_sleep)

    tb = TokenBucket(rate_per_second=10.0, capacity=10)
    tb.acquire(4)  # partial draw from a full bucket → immediate
    tb.acquire(0)  # no-op
    tb.acquire(25)  # > capacity → spends multiple refill windows, never deadlocks

    assert [round(s, 1) for s in sleeps if s > 1e-9] == [0.4, 1.0, 0.5]


def _embed_port_with_fake_client(model_id, output_dimension):
    import json as _json

    from docsuri_ingestion.adapters.aws import BedrockCohereEmbeddingPort

    port = BedrockCohereEmbeddingPort(
        model_id=model_id, region_name="us-east-1", output_dimension=output_dimension
    )
    captured = {}

    class _Body:
        def __init__(self, n, dim):
            self._payload = _json.dumps(
                {"embeddings": {"float": [[0.0] * dim for _ in range(n)]}}
            ).encode()

        def read(self):
            return self._payload

    class _Client:
        def invoke_model(self, **kw):
            body = _json.loads(kw["body"])
            captured["body"] = body
            dim = body.get("output_dimension", 1024)
            return {"body": _Body(len(body["texts"]), dim)}

    port._client = _Client()
    return port, captured


def test_embed_body_v3_omits_output_dimension_and_truncates():
    port, captured = _embed_port_with_fake_client("cohere.embed-multilingual-v3", 1024)
    port.embed_documents(["a" * 5000, "short"])
    assert "output_dimension" not in captured["body"]  # v3 rejects it (400)
    assert captured["body"]["truncate"] == "END"  # v3 512-token cap → truncate
    assert all(len(t) <= 2048 for t in captured["body"]["texts"])  # v3 2048-CHAR hard limit


def test_embed_body_v4_pins_output_dimension_no_truncate():
    port, captured = _embed_port_with_fake_client("global.cohere.embed-v4:0", 1536)
    port.embed_documents(["a"])
    assert captured["body"]["output_dimension"] == 1536  # v4 path unchanged
    assert "truncate" not in captured["body"]
