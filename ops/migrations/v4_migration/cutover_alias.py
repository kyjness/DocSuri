import sys

from docsuri_ingestion.settings import IngestionSettings
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
    alias_name = "docsuri-corpus"
    v1_index = settings.opensearch_index
    v2_index = settings.opensearch_index_v2

    # Build actions: only remove alias from v1 if it currently exists there
    actions = []
    existing = client.indices.get_alias(name=alias_name, ignore=[404])
    if isinstance(existing, dict) and v1_index in existing:
        actions.append({"remove": {"index": v1_index, "alias": alias_name}})
    actions.append({"add": {"index": v2_index, "alias": alias_name}})

    try:
        client.indices.update_aliases(body={"actions": actions})
        print(f"Successfully pointed {alias_name} → {v2_index}")
    except Exception as e:
        print(f"Failed to cutover: {e}")
        return 1
    return 0

if __name__ == "__main__":
    sys.exit(main())
