"""Writer and reader must resolve to the SAME embedding model.

Vectors only compare inside one embedding space. Both sides of this system are 1024-dimensional,
so a Cohere index queried with OpenAI vectors passes every dimension check and fails only as
semantically wrong neighbours — which looks like "search quality is bad", not like a bug. The
index carries an embedding manifest for exactly this reason (`discovery/adapters/space_guard.py`),
but that check happens at read time, i.e. after a full corpus has been built with the wrong model.

So the alignment is pinned here instead: one env var, read by both sides, resolving to one model.
Before this test the writer ignored the var entirely and hardcoded Bedrock.
"""

from __future__ import annotations

import pytest

from docsuri_ingestion.runtime import _embedding_port
from docsuri_ingestion.settings import IngestionSettings

_WRITER_PORT_BY_PROVIDER = {
    "bedrock": "BedrockCohereEmbeddingPort",
    "openai": "OpenAIEmbeddingPort",
}


@pytest.mark.parametrize("provider", sorted(_WRITER_PORT_BY_PROVIDER))
def test_writer_follows_the_embedding_provider_setting(provider: str) -> None:
    settings = IngestionSettings(
        DOCSURI_EMBEDDING_PROVIDER=provider,
        DOCSURI_BEDROCK_MODEL_ID="cohere.embed-v4:0",
        # The Bedrock port builds its boto3 client in __init__, which needs a region. Supplied
        # here so the test asserts the SELECTION rather than the ambient AWS configuration — CI
        # has no region and would otherwise fail on NoRegionError while the logic is correct.
        DOCSURI_EMBED_REGION="us-east-1",
    )
    port = _embedding_port(settings)
    assert type(port).__name__ == _WRITER_PORT_BY_PROVIDER[provider]


def test_writer_and_reader_read_the_same_env_name() -> None:
    """The two packages must not drift onto different env names — that would reintroduce the
    split silently, since each side would look correctly configured on its own."""
    reader_settings = pytest.importorskip(
        "discovery.adapters.settings", reason="discovery package not installed in this env"
    )
    writer_alias = IngestionSettings.model_fields["embedding_provider"].alias
    assert writer_alias == "DOCSURI_EMBEDDING_PROVIDER"
    # The reader reads the same name via os.getenv in its from_env(); assert the constant it
    # falls back to matches ours so an unset env cannot split them either.
    assert reader_settings._DEFAULT_EMBEDDING_PROVIDER == IngestionSettings().embedding_provider


def test_default_is_bedrock_so_an_unset_env_cannot_split_the_two_sides() -> None:
    assert IngestionSettings().embedding_provider == "bedrock"
