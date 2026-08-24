"""evidence real_wiring — the second reader must share discovery's embedding space (⑤a(b)-1).

The evidence agent reads discovery's index with its own wiring. These tests pin that it builds
the same embedder AND applies the same-space guard, so a same-dimension/different-model swap
disables the vector leg instead of scoring queries against a foreign embedding space. The live
case is Cohere Embed Multilingual v3 vs Embed v4 — both 1024-dimensional, so no shape check
catches the swap.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from discovery.adapters.bedrock_embedding import BedrockCohereQueryEmbedder
from discovery.adapters.space_guard import MismatchedSpaceEmbedder
from discovery.ports.search_ports import EmbeddingUnavailable
from docsuri_shared.vector_spec import DIMENSIONS

from backend.modules.evidence.real_wiring import _build_guarded_query_embedder

_INDEX = "docsuri-corpus-v1"
_MODEL = "cohere.embed-v4:0"


def _d_settings(model_id: str = _MODEL) -> SimpleNamespace:
    return SimpleNamespace(
        bedrock_model_id=model_id,
        bedrock_region="us-west-2",
        opensearch_index=_INDEX,
    )


def _client(manifest: dict | None) -> SimpleNamespace:
    """OpenSearch client stub whose get_mapping returns (or omits) an _meta.embedding stamp."""

    class _Indices:
        def get_mapping(self, index: str) -> dict:  # noqa: ARG002
            meta = {"_meta": {"embedding": manifest}} if manifest is not None else {}
            return {_INDEX: {"mappings": meta}}

    return SimpleNamespace(indices=_Indices())


def _manifest(model: str) -> dict:
    return {"provider": "bedrock", "model": model, "dimensions": DIMENSIONS}


def test_matching_manifest_keeps_the_embedder() -> None:
    emb = _build_guarded_query_embedder(
        _d_settings(), _client(_manifest(_MODEL)), "ap-northeast-2"
    )
    assert isinstance(emb, BedrockCohereQueryEmbedder)


def test_same_dimension_model_swap_disables_the_vector_leg() -> None:
    # Index stamped with v3, reader compiled against v4 — same vendor, same 1024 dimensions,
    # incompatible spaces. Nothing but the manifest can tell these apart.
    emb = _build_guarded_query_embedder(
        _d_settings(_MODEL),
        _client(_manifest("cohere.embed-multilingual-v3")),
        "ap-northeast-2",
    )
    assert isinstance(emb, MismatchedSpaceEmbedder)
    with pytest.raises(EmbeddingUnavailable):
        emb.embed_query("some query")


def test_absent_manifest_passes_through() -> None:
    # Legacy index without the _meta.embedding stamp → guard can't verify, serves anyway
    # (logged, not failed) so pre-manifest local indices keep working.
    emb = _build_guarded_query_embedder(_d_settings(), _client(None), "ap-northeast-2")
    assert isinstance(emb, BedrockCohereQueryEmbedder)


def test_app_shell_calls_the_runner_builder_with_the_arguments_it_accepts() -> None:
    """마운트가 조용히 실패하던 자리 — 앱은 초록으로 뜨고 evidence만 skipped가 된다.

    `_mount_evidence`는 `build_evidence_runner(...)`를 키워드로 부르는데, 그 호출은 실 경로
    (DocModel 버킷·OpenSearch 구성)에서만 실행돼 단위 테스트가 한 번도 밟지 않는다. 인자
    이름이 갈리면 `TypeError`가 WARNING 한 줄로 삼켜진다 — 서명만 기계적으로 맞춰 둔다.
    """
    import ast
    import inspect
    from pathlib import Path

    from backend.modules.evidence.real_wiring import build_evidence_runner

    accepted = set(inspect.signature(build_evidence_runner).parameters)
    source = Path(__file__).resolve().parents[1] / "wiring.py"
    tree = ast.parse(source.read_text())
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "build_evidence_runner"
    ]
    assert calls, "wiring.py가 build_evidence_runner를 부르지 않는다"
    for call in calls:
        used = {kw.arg for kw in call.keywords if kw.arg}
        assert used <= accepted, f"wiring이 넘기는 {used - accepted}를 러너 빌더가 안 받는다"
