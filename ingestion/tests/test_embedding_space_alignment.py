"""Writer and reader must resolve to the SAME embedding model.

Vectors only compare inside one embedding space, and a mismatch does not announce itself: it
fails as semantically wrong neighbours, which looks like "search quality is bad" rather than
like a bug. The index carries an embedding manifest for exactly this reason
(`discovery/adapters/space_guard.py`), but that check runs at read time — i.e. after a full
corpus has already been built with the wrong model.

The provider half of this risk is now gone by construction: Bedrock/Cohere is the only embedding
path on both sides, so there is no switch that could point writer and reader at different
vendors. What remains is the MODEL id, which is still env-driven on both sides — so that is what
these tests pin: one env name, read by both packages.
"""

from __future__ import annotations

import pytest

from docsuri_ingestion.runtime import _embedding_port
from docsuri_ingestion.settings import IngestionSettings

_MODEL_ENV = "DOCSURI_BEDROCK_MODEL_ID"


def test_writer_has_no_provider_branch_left() -> None:
    """One embedding vendor, unconditionally. A provider branch here is what previously let a
    single env value split the writer from the reader while both stayed 1024-dimensional."""
    settings = IngestionSettings(
        DOCSURI_BEDROCK_MODEL_ID="cohere.embed-v4:0",
        # The Bedrock port builds its boto3 client in __init__, which needs a region. Supplied
        # here so the test asserts the SELECTION rather than the ambient AWS configuration — CI
        # has no region and would otherwise fail on NoRegionError while the logic is correct.
        DOCSURI_EMBED_REGION="us-east-1",
    )

    assert type(_embedding_port(settings)).__name__ == "BedrockCohereEmbeddingPort"


def test_writer_and_reader_read_the_same_model_env_name() -> None:
    """The two packages must not drift onto different env names — that would reintroduce the
    split silently, since each side would look correctly configured on its own."""
    reader_settings = pytest.importorskip(
        "discovery.adapters.settings", reason="discovery package not installed in this env"
    )

    assert IngestionSettings.model_fields["bedrock_model_id"].alias == _MODEL_ENV
    # The reader reads the same name via os.getenv in its from_env(); assert on the source so a
    # rename on either side fails here rather than at the next corpus build.
    reader_source = inspect_source(reader_settings)
    assert _MODEL_ENV in reader_source


def inspect_source(module) -> str:
    from pathlib import Path

    return Path(module.__file__).read_text(encoding="utf-8")
