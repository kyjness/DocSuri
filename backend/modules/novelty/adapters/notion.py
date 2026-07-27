"""Notion export 어댑터(US-NV8 승계) — 루프 밖 승인 게이트 경로 전용(BR-RA12).

api.notion.com만 호출한다(allowlist). v2 산출물 payload(유사 연구 표·여백 분석·
실험 계획)를 페이지 블록으로 렌더링한다. 레거시 클라이언트 이식.
"""

from __future__ import annotations

from typing import Any

from ..domain.models import ARTIFACT_LABELS
from .external.base import SourceBreaker

__all__ = ["NotionApiExportClient", "build_notion_client"]


class NotionApiExportClient:
    _API_URL = "https://api.notion.com/v1/pages"
    _VERSION = "2022-06-28"
    _MAX_BLOCKS = 90  # Notion 페이지 생성 children 한도(100) 밑

    def __init__(self, client: Any, *, breaker: SourceBreaker | None = None) -> None:
        self._client = client
        # 외부 연동 규칙: 일시 실패 재시도 1회 + 반복 실패 차단 — 일시적 502로
        # 승인된 export가 FAILED로 수렴하지 않게 한다(코드 리뷰 반영).
        self._breaker = breaker or SourceBreaker()

    def export(self, connection: dict[str, str], content: dict[str, Any]) -> str:
        return self._breaker.call(lambda: self._export_once(connection, content))

    def _export_once(self, connection: dict[str, str], content: dict[str, Any]) -> str:
        response = self._client.post(
            self._API_URL,
            headers={
                "Authorization": f"Bearer {connection['token']}",
                "Notion-Version": self._VERSION,
                "Content-Type": "application/json",
            },
            json={
                "parent": {"page_id": connection["parentPageId"]},
                "properties": {
                    "title": {
                        "title": [
                            {
                                "text": {
                                    "content": str(
                                        content.get("title") or "Novelty analysis"
                                    )[:200]
                                }
                            }
                        ]
                    }
                },
                "children": _notion_blocks(content)[: self._MAX_BLOCKS],
            },
        )
        if getattr(response, "status_code", 500) >= 400:
            raise RuntimeError(
                f"notion api returned {getattr(response, 'status_code', 'error')}"
            )
        page_id = str((response.json() or {}).get("id") or "")
        if not page_id:
            raise RuntimeError("notion api returned no page id")
        return page_id


def build_notion_client() -> NotionApiExportClient:
    import httpx

    return NotionApiExportClient(
        httpx.Client(timeout=10.0, headers={"User-Agent": "DocSuri-Novelty/1.0"})
    )



def _notion_blocks(content: dict[str, Any]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    prompt = str(content.get("inputPrompt") or "").strip()
    if prompt:
        blocks.append(_bullet(f"입력 프롬프트: {prompt}"))
    for artifact in content.get("artifacts") or []:
        kind = str(artifact.get("kind") or "")
        blocks.append(_heading(ARTIFACT_LABELS.get(kind, kind or "산출물")))
        payload = artifact.get("payload") or {}
        for item in (payload.get("items") or [])[:5]:
            if not isinstance(item, dict):
                continue
            text = _item_text(kind, item)
            if text:
                blocks.append(_bullet(text))
        hypothesis = str(payload.get("hypothesis") or "").strip()
        if hypothesis:
            blocks.append(_bullet(f"가설: {hypothesis}"))
    return blocks


def _item_text(kind: str, item: dict[str, Any]) -> str:
    if kind == "gap_analysis":
        area = str(item.get("area") or "").strip()
        status = str(item.get("status") or "").strip()
        rationale = str(item.get("rationale") or "").strip()
        return " — ".join(part for part in (f"[{status}] {area}".strip(), rationale) if part)
    title = str(item.get("title") or item.get("angle") or item.get("statement") or "").strip()
    detail = str(
        item.get("overlap_with_user_idea") or item.get("rationale") or item.get("url") or ""
    ).strip()
    return f"{title} — {detail}" if title and detail else title or detail


def _heading(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "heading_2",
        "heading_2": {"rich_text": [{"type": "text", "text": {"content": text[:200]}}]},
    }


def _bullet(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {
            "rich_text": [{"type": "text", "text": {"content": text[:500]}}]
        },
    }
