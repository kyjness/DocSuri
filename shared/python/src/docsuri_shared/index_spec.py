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


def papers_index_body(*, on_disk: bool = False) -> dict[str, Any]:
    if on_disk:
        vector: dict[str, Any] = {
            "type": "knn_vector",
            "dimension": DIMENSIONS,
            "space_type": "cosinesimil",
            "mode": "on_disk",
            "compression_level": "4x",
        }
    else:
        vector = {
            "type": "knn_vector",
            "dimension": DIMENSIONS,
            "method": {"name": "hnsw", "space_type": "cosinesimil", "engine": "lucene"},
        }
    return {
        "settings": {"index": {"knn": True}},
        "mappings": {
            "properties": {
                "chunkId": {"type": "keyword"},
                "paperId": {"type": "keyword"},
                "version": {"type": "integer"},
                "vector": vector,
                "section": {"type": "keyword"},
                "lexicalTerms": {"type": "text"},
                "title": {"type": "text"},
                "authors": {"type": "keyword"},
                "year": {"type": "integer"},
                "arxivId": {"type": "keyword"},
                "abstract": {"type": "text"},
                "abstractSnippet": {"type": "text"},
                "arxivUrl": {"type": "keyword"},
                "categories": {"type": "keyword"},
            }
        },
    }
