"""view_figure 도구 어댑터(BLM §3, BR-RA11) — 논문 그림·수식 crop을 멀티모달 입력으로.

**2모드 계약**: `asset_id` 없이 호출하면 그 논문의 자산 목록(assetId·type·caption)을
텍스트로 돌려주고, `asset_id`를 주면 그 자산 하나를 이미지로 돌려준다. 온디맨드
원칙(FD 게이트 Q7=A — 캡션 보고 필요 판단한 것만 조회)을 도구 어휘 확장 없이 지킨다.

**타입별 처리를 분기하지 않는 이유**: `paper_asset`에 행이 존재한다는 사실 자체가
이미 판정이다. 구조화에 성공한 표는 DocModel에 rows/cells로 실리고 crop을 만들지
않으므로 표 crop 행은 비-HTML 폴백 티어에서만 생기고, 수식은 `latex`와 `assetRef` 중
하나만 렌더 소스이므로(docmodel.schema.json) 수식 crop 행의 존재는 LaTeX 복원 실패를
뜻한다. 즉 "표는 텍스트로, 수식은 LaTeX 1차·crop 폴백"(BLM §3)은 DocModel을 따로 읽지
않아도 자산 매니페스트만으로 성립한다.

u7 리더(`rds_assets.py`)는 `type IN ('figure','table')`로 수식을 걸러내지만 여기서는
걸러내지 않는다 — 수식 crop은 ⑤3의 1급 대상이다.
"""

from __future__ import annotations

import base64
import logging
import os
from collections.abc import Callable, Sequence
from typing import Any

from ..ports.assets import FigureAsset
from ..ports.tools import (
    TOOL_VIEW_FIGURE,
    ImageAttachment,
    ToolContext,
    ToolResult,
    ToolSpec,
)

__all__ = ["SqlS3FigureReader", "ViewFigureTool", "bare_paper_id", "paper_version"]

log = logging.getLogger("docsuri.novelty.figures")

# LLM 프로바이더가 받는 이미지 포맷만 허용한다(OpenAI·Anthropic 공통 교집합).
# 다른 확장자가 오면 조회를 거부한다 — 프로바이더가 400을 돌려주면 루프는 원인을
# 알 수 없는 LlmUnavailable로 수렴해 예산만 태운다.
_MEDIA_TYPES = {
    ".webp": "image/webp",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
}
_LIST_LIMIT = 60


def bare_paper_id(paper_id: str) -> str:
    """arXiv 버전 suffix(``v<N>``)를 떼어낸다 — `paper_asset.paper_id`는 bare다.

    u7 `_paper_ref.bare_paper_id`와 같은 규약(u1의 ``rsplit('v', 1)`` 파생). u7 모듈을
    import하지 않는 이유는 novelty가 summarization 서브프로젝트에 의존하지 않기
    때문이다(헥사고날 — 모듈 간 직접 의존 금지).
    """
    return paper_id.rsplit("v", 1)[0] if "v" in paper_id else paper_id


def paper_version(paper_id: str) -> int | None:
    """버전 suffix가 있으면 그 번호, 없으면 None(호출자가 최신 버전을 찾는다)."""
    bare, sep, tail = paper_id.rpartition("v")
    return int(tail) if sep and bare and tail.isdigit() else None


class SqlS3FigureReader:
    """`paper_asset`(u1이 쓰고 우리는 읽기만) + S3 객체 바이트.

    novelty 저장소와 같은 SQLAlchemy session factory를 공유한다 — `paper_asset`은
    novelty의 ORM 모델이 아니므로 raw SQL로 읽는다.
    """

    def __init__(
        self,
        session_factory: Callable[[], Any],
        *,
        s3_client: Any | None = None,
        region_name: str | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._s3 = s3_client
        self._region = region_name

    def _client(self) -> Any:
        if self._s3 is None:
            import boto3  # lazy — 자산 스토어가 설정된 경우에만 필요

            region = (
                self._region
                or os.getenv("AWS_REGION")
                or os.getenv("DOCSURI_AWS_REGION")
                or "ap-northeast-2"
            )
            # 엔드포인트를 명시적으로 넘긴다 — 넘기지 않으면 boto3가 실제 AWS로 나가
            # 솔로-로컬 s3proxy의 객체를 전부 404로 본다(u7 리더와 같은 함정).
            endpoint = os.getenv("AWS_ENDPOINT_URL_S3") or f"https://s3.{region}.amazonaws.com"
            self._s3 = boto3.client("s3", region_name=region, endpoint_url=endpoint)
        return self._s3

    def latest_version(self, paper_id: str) -> int | None:
        from sqlalchemy import text

        sql = text("SELECT max(version) FROM paper_asset WHERE paper_id = :paper_id")
        with self._session_factory() as session:
            row = session.execute(sql, {"paper_id": bare_paper_id(paper_id)}).first()
        return int(row[0]) if row and row[0] is not None else None

    def list_assets(self, paper_id: str, version: int) -> Sequence[FigureAsset]:
        from sqlalchemy import text

        # figure·table·formula 전부 — u7과 달리 type 필터를 걸지 않는다(모듈 docstring).
        sql = text(
            "SELECT asset_id, type, ordinal, caption, source_mode, object_ref "
            "FROM paper_asset WHERE paper_id = :paper_id AND version = :version "
            "ORDER BY type, ordinal"
        )
        with self._session_factory() as session:
            rows = session.execute(
                sql, {"paper_id": bare_paper_id(paper_id), "version": version}
            ).all()
        return [
            FigureAsset(
                asset_id=str(row[0]),
                type=str(row[1]),
                ordinal=int(row[2]),
                caption=str(row[3] or ""),
                source_mode=str(row[4] or ""),
                object_ref=str(row[5]),
            )
            for row in rows
        ]

    def fetch_bytes(self, object_ref: str) -> tuple[str, bytes] | None:
        parsed = _split_s3_ref(object_ref)
        if parsed is None:
            return None
        bucket, key = parsed
        media_type = _media_type_for(key)
        if media_type is None:
            return None
        try:
            response = self._client().get_object(Bucket=bucket, Key=key)
            return media_type, response["Body"].read()
        except Exception:  # noqa: BLE001 — 자산 1건의 부재·장애가 루프를 끊지 않는다
            log.warning("novelty view_figure: asset fetch failed", exc_info=True)
            return None


def _split_s3_ref(object_ref: str) -> tuple[str, str] | None:
    if not object_ref.startswith("s3://"):
        return None
    bucket, _, key = object_ref[len("s3://") :].partition("/")
    return (bucket, key) if bucket and key else None


def _media_type_for(key: str) -> str | None:
    _, _, ext = key.rpartition(".")
    return _MEDIA_TYPES.get(f".{ext.lower()}") if ext else None


class ViewFigureTool:
    spec = ToolSpec(
        name=TOOL_VIEW_FIGURE,
        description=(
            "확보한 논문의 그림·수식·표 자산을 조회한다. "
            "asset_id 없이 호출하면 그 논문의 자산 목록(assetId·종류·캡션)을 돌려주고, "
            "asset_id를 주면 그 자산 하나를 이미지로 보여준다. "
            "먼저 목록을 받아 캡션을 보고 꼭 필요한 것만 이미지로 조회한다."
        ),
        parameters={
            "type": "object",
            "properties": {
                "record_ref": {"type": "string", "maxLength": 100},
                "asset_id": {"type": "string", "maxLength": 200},
            },
            "required": ["record_ref"],
        },
    )

    def __init__(self, assets: Any, *, max_image_bytes: int = 4 * 1024 * 1024) -> None:
        self._assets = assets
        self._max_image_bytes = max_image_bytes

    def invoke(self, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        """`ctx`는 쓰지 않는다 — 코퍼스 자산은 소유자별 리소스가 아니다.

        코퍼스에는 OA 허용 논문만 적재되므로(BR-1) 어떤 소유자에게도 표시 가능한
        자산이고, 접근 경계는 소유자가 아니라 **매니페스트 실재성**이다(BR-RA11):
        `paper_asset`에 없는 자산은 조회되지 않는다. 업로드 원고(userdoc)는 이
        경로의 대상이 아니다.
        """
        record_ref = str(args.get("record_ref") or "").strip()
        if not record_ref:
            return ToolResult(
                ok=False,
                error="record_ref는 필수다 — 검색·근거 결과의 recordRef 값을 그대로 넣어라",
                result_summary="view_figure: missing record_ref",
            )
        asset_id = str(args.get("asset_id") or "").strip()

        # 포트는 bare paper_id를 받는다 — 정규화는 여기서 한 번만 한다. 어댑터의
        # 방어적 정규화에 기대면 다른 구현이 들어올 때 조용한 영구 미스가 된다.
        paper_id = bare_paper_id(record_ref)
        version = paper_version(record_ref)
        if version is None:
            version = self._assets.latest_version(paper_id)
        if version is None:
            return ToolResult(
                ok=False,
                error=(
                    f"{record_ref} 논문에는 저장된 그림·수식 자산이 없다 — "
                    "다른 논문을 고르거나 텍스트 근거로 진행하라"
                ),
                result_summary="view_figure: no assets",
            )

        assets = list(self._assets.list_assets(paper_id, version))
        if not assets:
            return ToolResult(
                ok=False,
                error=(
                    f"{record_ref} 논문에는 저장된 그림·수식 자산이 없다 — "
                    "다른 논문을 고르거나 텍스트 근거로 진행하라"
                ),
                result_summary="view_figure: no assets",
            )

        if not asset_id:
            return self._list_result(record_ref, assets)
        return self._image_result(record_ref, assets, asset_id)

    def _list_result(self, record_ref: str, assets: list[FigureAsset]) -> ToolResult:
        # object_ref는 내부 값 — 목록에 싣지 않는다(SEC-9).
        items = [
            {
                "assetId": asset.asset_id,
                "type": asset.type,
                "ordinal": asset.ordinal,
                "caption": asset.caption,
            }
            for asset in assets[:_LIST_LIMIT]
        ]
        content: dict[str, Any] = {"recordRef": record_ref, "assets": items}
        if len(assets) > _LIST_LIMIT:
            content["omitted"] = {"field": "assets", "count": len(assets) - _LIST_LIMIT}
        return ToolResult(
            ok=True,
            content=content,
            result_summary=f"figure list: {len(items)} assets",
        )

    def _image_result(
        self, record_ref: str, assets: list[FigureAsset], asset_id: str
    ) -> ToolResult:
        # BR-RA11 — 실재하는 자산만. 매니페스트에 없는 id는 조회하지 않는다.
        match = next((asset for asset in assets if asset.asset_id == asset_id), None)
        if match is None:
            return ToolResult(
                ok=False,
                error=(
                    f"asset_id '{asset_id}'는 {record_ref} 논문에 없다 — "
                    "asset_id 없이 view_figure를 호출해 목록을 먼저 받아라"
                ),
                result_summary="view_figure: unknown asset",
            )

        fetched = self._assets.fetch_bytes(match.object_ref)
        if fetched is None:
            return ToolResult(
                ok=False,
                error=(
                    f"asset_id '{asset_id}' 이미지를 가져오지 못했다 — "
                    "같은 논문의 다른 자산을 고르거나 텍스트 근거로 진행하라"
                ),
                result_summary="view_figure: asset unavailable",
            )
        media_type, data = fetched
        if not data:
            return ToolResult(
                ok=False,
                error=(
                    f"asset_id '{asset_id}' 이미지가 비어 있다 — "
                    "같은 논문의 다른 자산을 고르거나 텍스트 근거로 진행하라"
                ),
                result_summary="view_figure: empty asset",
            )
        if len(data) > self._max_image_bytes:
            # 백엔드에 이미지 처리 의존성이 없어 다운스케일이 불가하다 — 거부하되
            # 사유에 다음 행동을 담는다.
            return ToolResult(
                ok=False,
                error=(
                    f"asset_id '{asset_id}' 이미지가 너무 크다"
                    f"({len(data)} bytes > {self._max_image_bytes}) — "
                    "같은 논문의 다른 자산을 고르거나 텍스트 근거로 진행하라"
                ),
                result_summary="view_figure: asset too large",
            )

        return ToolResult(
            ok=True,
            # record_refs는 비운다 — view_figure는 새 출처를 확보하는 도구가 아니라
            # 이미 확보한 논문을 들여다보는 도구다(게이트 실재성 집합 오염 금지).
            content={
                "recordRef": record_ref,
                "assetId": match.asset_id,
                "type": match.type,
                "caption": match.caption,
            },
            images=(
                ImageAttachment(
                    media_type=media_type,
                    data_b64=base64.b64encode(data).decode("ascii"),
                    asset_id=match.asset_id,
                    caption=match.caption,
                ),
            ),
            result_summary=f"figure: {match.type} {match.asset_id}",
        )
