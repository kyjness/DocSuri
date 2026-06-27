import sys

from docsuri_ingestion.settings import IngestionSettings
from docsuri_shared.index_spec import papers_index_body
from opensearchpy import OpenSearch


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
        client.indices.create(index=v2_index, body=papers_index_body())
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
