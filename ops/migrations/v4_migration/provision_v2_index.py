import sys

from docsuri_ingestion.settings import IngestionSettings
from docsuri_shared.vector_spec import DIMENSIONS
from opensearchpy import OpenSearch

INDEX_BODY = {
    "settings": {"index": {"knn": True}},
    "mappings": {
        "properties": {
            "chunkId": {"type": "keyword"},
            "paperId": {"type": "keyword"},
            "version": {"type": "integer"},
            "vector": {
                "type": "knn_vector",
                "dimension": DIMENSIONS,
                "method": {
                    "name": "hnsw",
                    "space_type": "cosinesimil",
                    "engine": "lucene",
                },
            },
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

def main():
    settings = IngestionSettings.from_env()
    if not settings.opensearch_endpoint:
        print("Missing DOCSURI_OPENSEARCH_ENDPOINT")
        return 1

    local = settings.env == "local"
    client = OpenSearch(
        hosts=[settings.opensearch_endpoint],
        use_ssl=not local,
        verify_certs=not local,
    )
    v1_index = settings.opensearch_index
    v2_index = settings.opensearch_index_v2
    alias_name = "docsuri-corpus"

    if not client.indices.exists(index=v2_index):
        client.indices.create(index=v2_index, body=INDEX_BODY)
        print(f"Created {v2_index}")
    else:
        print(f"{v2_index} already exists")

    # Ensure alias exists (pointing to v1) so Discovery deploy is safe regardless of order
    existing = client.indices.get_alias(name=alias_name, ignore=[404])
    if not isinstance(existing, dict) or not existing:
        client.indices.put_alias(index=v1_index, name=alias_name)
        print(f"Created alias {alias_name} → {v1_index}")
    else:
        print(f"Alias {alias_name} already exists")

    return 0

if __name__ == "__main__":
    sys.exit(main())
