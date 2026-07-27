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
from collections.abc import Callable
from typing import Any

# u11 evidence가 같은 방식으로 쓰는 공용 arXiv id 규약(`evidence/tools.py`) —
# 백엔드는 summarization을 의존성으로 선언하므로 사본을 만들지 않는다.
from summarization.adapters._paper_ref import bare_paper_id, paper_version

from ..ports.assets import FigureAsset, FigureManifest
from ..ports.tools import (
    TOOL_VIEW_FIGURE,
    ImageAttachment,
    ToolContext,
    ToolResult,
    ToolSpec,
)

__all__ = ["SqlS3FigureReader", "ViewFigureTool"]

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

# 버전 해석을 별도 질의로 두지 않는다 — 코퍼스의 recordRef가 거의 전부 bare라
# 나누면 사실상 모든 호출이 왕복 2회가 된다. `count(*) OVER ()`는 LIMIT 적용
# 전에 계산되므로 상한을 걸어도 실제 총 개수를 얻는다.
_RESOLVED_VERSION = (
    "COALESCE(:version, (SELECT max(version) FROM paper_asset WHERE paper_id = :paper_id))"
)
_LIST_SQL = (
    "SELECT asset_id, type, ordinal, caption, object_ref, version, count(*) OVER () "
    "FROM paper_asset WHERE paper_id = :paper_id AND version = "
    f"{_RESOLVED_VERSION} ORDER BY type, ordinal LIMIT :limit"
)
_GET_SQL = (
    "SELECT asset_id, type, ordinal, caption, object_ref "
    "FROM paper_asset WHERE paper_id = :paper_id AND asset_id = :asset_id "
    f"AND version = {_RESOLVED_VERSION}"
)


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

    def list_assets(
        self, paper_id: str, version: int | None, *, limit: int = _LIST_LIMIT
    ) -> FigureManifest | None:
        from sqlalchemy import text

        with self._session_factory() as session:
            rows = session.execute(
                text(_LIST_SQL),
                {"paper_id": paper_id, "version": version, "limit": limit},
            ).all()
        if not rows:
            return None
        return FigureManifest(
            version=int(rows[0][5]),
            assets=[_asset_from_row(row) for row in rows],
            total=int(rows[0][6]),
        )

    def get_asset(
        self, paper_id: str, version: int | None, asset_id: str
    ) -> FigureAsset | None:
        from sqlalchemy import text

        with self._session_factory() as session:
            row = session.execute(
                text(_GET_SQL),
                {"paper_id": paper_id, "version": version, "asset_id": asset_id},
            ).first()
        return _asset_from_row(row) if row is not None else None

    def fetch_bytes(self, object_ref: str, *, max_bytes: int) -> tuple[str, bytes] | None:
        parsed = _split_s3_ref(object_ref)
        if parsed is None:
            return None
        bucket, key = parsed
        media_type = _media_type_for(key)
        if media_type is None:
            return None
        try:
            response = self._client().get_object(Bucket=bucket, Key=key)
            # 본문을 읽기 전에 크기를 본다 — 어차피 버릴 메가바이트를 받지 않는다.
            length = response.get("ContentLength")
            if length is not None and int(length) > max_bytes:
                return None
            data = response["Body"].read()
            return (media_type, data) if len(data) <= max_bytes else None
        except Exception:  # noqa: BLE001 — 자산 1건의 부재·장애가 루프를 끊지 않는다
            log.warning("novelty view_figure: asset fetch failed", exc_info=True)
            return None


def _asset_from_row(row: Any) -> FigureAsset:
    return FigureAsset(
        asset_id=str(row[0]),
        type=str(row[1]),
        ordinal=int(row[2]),
        caption=str(row[3] or ""),
        object_ref=str(row[4]),
    )


def _split_s3_ref(object_ref: str) -> tuple[str, str] | None:
    if not object_ref.startswith("s3://"):
        return None
    bucket, _, key = object_ref[len("s3://") :].partition("/")
    return (bucket, key) if bucket and key else None


def _media_type_for(key: str) -> str | None:
    _, _, ext = key.rpartition(".")
    return _MEDIA_TYPES.get(f".{ext.lower()}") if ext else None


# 거부 사유는 판정이자 **수리 지시**다(⑤2 실스택 검증 교훈) — 무엇이 틀렸는지와
# 다음에 무엇을 하면 되는지를 함께 담지 않으면 자율 루프는 같은 실수를 반복한다.
_RETRY_HINT = "같은 논문의 다른 자산을 고르거나 텍스트 근거로 진행하라"


def _refuse(summary: str, message: str) -> ToolResult:
    return ToolResult(ok=False, error=message, result_summary=f"view_figure: {summary}")


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

    def __init__(self, assets: Any, *, max_image_bytes: int) -> None:
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
            return _refuse(
                "missing record_ref",
                "record_ref는 필수다 — 검색·근거 결과의 recordRef 값을 그대로 넣어라",
            )

        # 포트는 bare paper_id를 받는다 — 정규화는 여기서 한 번만 한다. 어댑터의
        # 방어적 정규화에 기대면 다른 구현이 들어올 때 조용한 영구 미스가 된다.
        paper_id = bare_paper_id(record_ref)
        # suffix가 있을 때만 명시 버전 — bare면 None으로 넘겨 어댑터가 최신을 해석한다.
        version = paper_version(record_ref) if paper_id != record_ref else None

        asset_id = str(args.get("asset_id") or "").strip()
        if asset_id:
            return self._image_result(record_ref, paper_id, version, asset_id)
        return self._list_result(record_ref, paper_id, version)

    def _list_result(
        self, record_ref: str, paper_id: str, version: int | None
    ) -> ToolResult:
        manifest = self._assets.list_assets(paper_id, version, limit=_LIST_LIMIT)
        if manifest is None:
            return _refuse(
                "no assets",
                f"{record_ref} 논문에는 저장된 그림·수식 자산이 없다 — "
                "다른 논문을 고르거나 텍스트 근거로 진행하라",
            )
        # object_ref는 내부 값 — 목록에 싣지 않는다(SEC-9).
        content: dict[str, Any] = {
            "recordRef": record_ref,
            "assets": [
                {
                    "assetId": asset.asset_id,
                    "type": asset.type,
                    "ordinal": asset.ordinal,
                    "caption": asset.caption,
                }
                for asset in manifest.assets
            ],
        }
        # `omitted`를 직접 쓰지 않는다 — 그 키는 렌더 단계의 `fit_result_content`가
        # 소유하고, 둘이 같이 쓰면 나중 값이 앞의 개수를 덮어써 모델이 실제보다
        # 적게 숨겨졌다고 믿는다. 총량은 이름이 겹치지 않는 필드로 알린다.
        if manifest.total > len(manifest.assets):
            content["totalAssets"] = manifest.total
        return ToolResult(
            ok=True,
            content=content,
            result_summary=f"figure list: {len(manifest.assets)} assets",
        )

    def _image_result(
        self, record_ref: str, paper_id: str, version: int | None, asset_id: str
    ) -> ToolResult:
        # BR-RA11 — 실재하는 자산만. 단건 조회로 존재를 확인한다(매니페스트 전체를
        # 다시 읽지 않는다 — 자산이 많은 논문에서 통째로 낭비된다).
        match = self._assets.get_asset(paper_id, version, asset_id)
        if match is None:
            return _refuse(
                "unknown asset",
                f"asset_id '{asset_id}'는 {record_ref} 논문에 없다 — "
                "asset_id 없이 view_figure를 호출해 목록을 먼저 받아라",
            )

        fetched = self._assets.fetch_bytes(
            match.object_ref, max_bytes=self._max_image_bytes
        )
        if fetched is None:
            # 부재·장애·상한 초과가 한 사유로 모인다 — 에이전트가 할 수 있는 다음
            # 행동이 셋 다 같기 때문이다(다른 자산을 고르거나 텍스트로 진행).
            return _refuse(
                "asset unavailable",
                f"asset_id '{asset_id}' 이미지를 쓸 수 없다(부재·장애 또는 크기 초과) — "
                f"{_RETRY_HINT}",
            )
        media_type, data = fetched
        if not data:
            return _refuse(
                "empty asset", f"asset_id '{asset_id}' 이미지가 비어 있다 — {_RETRY_HINT}"
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
                ),
            ),
            result_summary=f"figure: {match.type} {match.asset_id}",
        )
