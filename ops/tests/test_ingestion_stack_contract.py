from pathlib import Path

STACK_SOURCE = (
    Path(__file__).resolve().parents[1] / "cdk" / "stacks" / "ingestion_stack.py"
).read_text()


def test_ingestion_stack_provisions_userdoc_grobid_worker() -> None:
    # GROBID Option B: a dedicated user-PDF build queue + worker with its own GROBID sidecar,
    # kept separate from the lean docsuri-docmodel-builder so arXiv reader-triggered builds never
    # inherit the ~20GB GROBID cold-pull.
    assert 'queue_name="docsuri-userdoc-queue"' in STACK_SOURCE
    assert 'queue_name="docsuri-userdoc-dlq"' in STACK_SOURCE
    assert 'service_name="docsuri-userdoc-builder"' in STACK_SOURCE

    # The user-PDF worker carries a GROBID sidecar (a second one, alongside the bulk worker's) and
    # points the runtime at it.
    assert STACK_SOURCE.count('ecs.ContainerImage.from_registry("grobid/grobid:0.8.0")') >= 2
    assert '"DOCSURI_GROBID_URL": "http://127.0.0.1:8070"' in STACK_SOURCE
    assert "/api/isalive" in STACK_SOURCE
    assert "userdoc_worker.add_container_dependencies" in STACK_SOURCE
    assert "ecs.ContainerDependencyCondition.HEALTHY" in STACK_SOURCE

    # It drains the userdoc queue via the docmodel worker mode (the worker's single priority-queue
    # slot points at the userdoc queue).
    assert '"DOCSURI_DOCMODEL_QUEUE_URL": self.userdoc_queue.queue_url' in STACK_SOURCE
    assert '"DOCSURI_WORKER_QUEUE_MODE": "docmodel"' in STACK_SOURCE

    # Least privilege: consume its own queue + read/write the papers bucket. No Bedrock/OpenSearch/
    # RDS grants — the build path is S3-only.
    assert "self.userdoc_queue.grant_consume_messages(userdoc_task_def.task_role)" in STACK_SOURCE
    assert "self.bucket.grant_read_write(userdoc_task_def.task_role)" in STACK_SOURCE


def test_ingestion_writes_through_corpus_alias() -> None:
    # Re-embed cutover moves docsuri-corpus to a fresh backing index; writers must follow it.
    assert STACK_SOURCE.count('"DOCSURI_OPENSEARCH_INDEX": "docsuri-corpus"') == 3
    assert '"DOCSURI_OPENSEARCH_INDEX": "docsuri-corpus-v2"' not in STACK_SOURCE
    assert '"DOCSURI_OPENSEARCH_INDEX_V2": "docsuri-corpus-v2"' in STACK_SOURCE


def test_docmodel_builder_stays_single_arxiv_caller() -> None:
    # The arXiv limiter is process-local. A backlog drain with two docmodel-builder tasks doubles
    # the caller rate and can 429 retryable metadata fetches into docsuri-docmodel-dlq.
    block = STACK_SOURCE.split("docmodel_scaling = ")[1].split(
        "# --- ECS Fargate: user-PDF doc-model worker", maxsplit=1
    )[0]
    assert "self.docmodel_service.auto_scale_task_count(\n" in block
    assert "min_capacity=0, max_capacity=1" in block
    assert "DocModelDepth" in block
    assert "appscaling.ScalingInterval(lower=10, change=2)" not in block
