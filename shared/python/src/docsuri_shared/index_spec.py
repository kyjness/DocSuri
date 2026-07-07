"""OpenSearch index mapping for the papers corpus — single source of truth.

The U1 writer side (ingestion provisioning) and the U2 reader side (discovery bootstrap/seed)
both create the index from THIS one body, so the k-NN/on-disk mapping can never drift between
them. Lives in ``docsuri_shared`` (not the discovery scripts package) because the ingestion
image installs only ``shared`` + ``ingestion`` — it has no access to the discovery package.

``on_disk=True`` (production, OpenSearch >= 2.17) keeps full-precision vectors on disk + a
4x-compressed copy in RAM (~4x k-NN RAM cut for full-body multi-chunk papers; implies faiss +
hnsw defaults). The default path stays plain lucene HNSW so local tests run on any version
(on_disk is rejected pre-2.17).
"""

from __future__ import annotations

from typing import Any

from .vector_spec import DIMENSIONS

__all__ = ["papers_index_body"]


def papers_index_body(
    *,
    on_disk: bool = False,
    number_of_shards: int | None = None,
    number_of_replicas: int | None = None,
    refresh_interval: str | None = None,
    dimension: int | None = None,
) -> dict[str, Any]:
    """Corpus index body. The ``number_of_*`` / ``refresh_interval`` knobs default to ``None``
    (omitted → OpenSearch cluster defaults, so the live provisioning path is unchanged). A fast
    bulk-load rebuild passes ``number_of_replicas=0`` + ``refresh_interval="-1"`` to cut write
    amplification, then restores them before cutover (see the re-embed runbook).

    ``dimension`` defaults to the frozen ``DIMENSIONS`` (1024); a re-embed to a different embedding
    space (e.g. Cohere v4's 1536 default) passes it explicitly so the target k-NN mapping matches
    the new vectors — without bumping the frozen vector-spec until reader cutover (see runbook)."""
    dim = dimension or DIMENSIONS
    if on_disk:
        vector: dict[str, Any] = {
            "type": "knn_vector",
            "dimension": dim,
            "space_type": "cosinesimil",
            "mode": "on_disk",
            "compression_level": "4x",
        }
    else:
        vector = {
            "type": "knn_vector",
            "dimension": dim,
            "method": {"name": "hnsw", "space_type": "cosinesimil", "engine": "lucene"},
        }
    index_settings: dict[str, Any] = {"knn": True}
    if number_of_shards is not None:
        index_settings["number_of_shards"] = number_of_shards
    if number_of_replicas is not None:
        index_settings["number_of_replicas"] = number_of_replicas
    if refresh_interval is not None:
        index_settings["refresh_interval"] = refresh_interval
    return {
        "settings": {"index": index_settings},
        "mappings": {
            "properties": {
                "chunkId": {"type": "keyword"},
                "paperId": {"type": "keyword"},
                "version": {"type": "integer"},
                "vector": vector,
                "section": {"type": "keyword"},
                "lexicalTerms": {"type": "text"},
                "blockRefs": {"type": "object", "enabled": False},
                "title": {"type": "text"},
                "authors": {"type": "keyword"},
                "year": {"type": "integer"},
                "arxivId": {"type": "keyword"},
                "abstract": {"type": "text"},
                "abstractSnippet": {"type": "text"},
                "arxivUrl": {"type": "keyword"},
                "categories": {"type": "keyword"},
                "doi": {"type": "keyword"},
                "sourceArxivId": {"type": "keyword"},
                "sourceProvenance": {"type": "object", "enabled": False},
            }
        },
    }
