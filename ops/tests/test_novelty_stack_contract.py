from pathlib import Path

STACK_SOURCE = (
    Path(__file__).resolve().parents[1] / "cdk" / "stacks" / "novelty_stack.py"
).read_text()


def test_novelty_worker_can_retry_and_consume_user_docmodel() -> None:
    assert '"DOCSURI_DOCMODEL_BUCKET"' in STACK_SOURCE
    assert '"DOCSURI_DOCMODEL_BUILD_QUEUE_URL"' in STACK_SOURCE
    assert "docsuri-docmodel-queue" in STACK_SOURCE

    assert "queue.grant_send_messages(task_def.task_role)" in STACK_SOURCE
    assert 'actions=["sqs:SendMessage"]' in STACK_SOURCE
    assert "docsuri-docmodel-queue" in STACK_SOURCE

    assert 'actions=["s3:GetObject"]' in STACK_SOURCE
    assert '/doc-model/*"' in STACK_SOURCE


def test_novelty_worker_routes_user_pdf_builds_to_grobid_queue() -> None:
    # GROBID Option B: novelty manuscripts enqueue to the dedicated user-PDF queue whose worker
    # carries the GROBID sidecar; the coordinator factory prefers this over the shared doc-model
    # queue. SendMessage on the userdoc queue is granted alongside the docmodel one.
    assert '"DOCSURI_USERDOC_BUILD_QUEUE_URL"' in STACK_SOURCE
    assert "docsuri-userdoc-queue" in STACK_SOURCE
