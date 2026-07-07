from __future__ import annotations

from typing import Any

from backend.modules.user_docmodel import (
    UserDocModelCoordinator,
    ref_from_attachment,
)

from .models import AttachmentInput


def attachment_inputs_from_dicts(
    *,
    owner_id: str,
    scope_id: str,
    attachments: list[dict[str, Any]],
    user_docmodel: UserDocModelCoordinator | None = None,
) -> tuple[AttachmentInput, ...]:
    inputs: list[AttachmentInput] = []
    for item in attachments:
        name = str(item.get("name") or "첨부 문서")
        kind = str(item.get("kind") or "")
        raw_text = item.get("contentText")
        text = raw_text if isinstance(raw_text, str) and raw_text.strip() else None
        if text is not None or kind != "pdf":
            inputs.append(AttachmentInput(name=name, kind=kind, text=text))
            continue

        object_key = str(item.get("objectKey") or "")
        if not object_key:
            inputs.append(AttachmentInput(name=name, kind=kind))
            continue

        ref = ref_from_attachment(
            owner_id=owner_id,
            scope_id=scope_id,
            attachment_id=str(item.get("id") or name),
            object_key=object_key,
            module="evidence",
            paper_id=item.get("paperId"),
            record_ref=item.get("recordRef"),
        )
        doc_model = user_docmodel.enqueue_and_poll(ref) if user_docmodel is not None else None
        inputs.append(
            AttachmentInput(
                name=name,
                kind=kind,
                paper_id=ref.paper_id,
                record_ref=ref.record_ref,
                object_key=ref.object_key,
                doc_model=doc_model,
            )
        )
    return tuple(inputs)


def attachment_inputs_to_payloads(
    attachment_docs: tuple[AttachmentInput, ...],
) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for doc in attachment_docs:
        payloads.append(
            {
                key: value
                for key, value in {
                    "name": doc.name,
                    "kind": doc.kind,
                    "contentText": doc.text,
                    "paperId": doc.paper_id,
                    "recordRef": doc.record_ref,
                    "objectKey": doc.object_key,
                }.items()
                if value not in (None, "")
            }
        )
    return payloads


def unresolved_pdf_names(attachment_docs: tuple[AttachmentInput, ...]) -> list[str]:
    return [
        doc.name
        for doc in attachment_docs
        if doc.kind == "pdf" and doc.doc_model is None
    ]
