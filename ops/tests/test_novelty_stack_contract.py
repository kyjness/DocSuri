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


def test_novelty_worker_can_read_figure_assets_for_view_figure() -> None:
    # ⑤3 view_figure: 워커가 도구 레지스트리를 만드는 유일한 프로세스라, 토글이
    # 여기 없으면 그림 조회 도구가 아무 신호 없이 사라진다(API 태스크에만 켜도 소용없다).
    assert '"DOCSURI_MULTIMODAL_ASSETS_ENABLED": "true"' in STACK_SOURCE
    # crop은 assets/{paper}/v{n}/*.webp에 있다(002_paper_asset.sql object_ref 규약).
    # 이 권한이 없으면 매 조회가 AccessDenied로 떨어지고 에이전트는 원인을 모른 채
    # 캡 8회를 태운다.
    assert '/assets/*"' in STACK_SOURCE
