"""view_figure 도구 어댑터(BLM §3, BR-RA11) — 논문 그림·수식 crop을 멀티모달 입력으로.

**2모드 계약**: `asset_id` 없이 호출하면 그 논문의 자산 목록(assetId·type·caption)을
텍스트로 돌려주고, `asset_id`를 주면 그 자산 하나를 이미지로 돌려준다. 온디맨드
원칙(FD 게이트 Q7=A — 캡션 보고 필요 판단한 것만 조회)을 도구 어휘 확장 없이 지킨다.

**서빙 대상은 figure·formula뿐이다(`_SERVED_TYPES`)** — 표 crop은 제외한다.

- **수식**: `latex`와 `assetRef` 중 하나만 렌더 소스이므로(docmodel.schema.json) 수식
  crop 행의 존재가 곧 LaTeX 복원 실패를 뜻한다. 따라서 crop 서빙이 "LaTeX 1차, crop
  폴백"(BLM §3)의 결과다. 로컬 코퍼스 전수 확인(2026-07-27): 수식 crop 24건 중 DocModel에
  `latex`가 함께 있는 것은 **0건**.
- **표**: 제외한다. u1은 표를 구조화(rows/cells)해 DocModel에 싣고 **동시에** 페이지 crop도
  남기는데, DocModel은 그 crop을 참조하지 않는다. 로컬 코퍼스 표본 확인(199편·자산 2,244건):
  표 crop 772건 중 DocModel이 참조하는 것 **0건**, 표본의 82%가 DocModel에 구조화 표를 갖고
  있었다. 즉 표 crop을 서빙하면 에이전트가 이미 텍스트로 읽을 수 있는 것을 이미지로 다시
  받으며 캡 8회를 태운다 — BLM §3의 "표는 텍스트 경로로 읽힌다"와 BR-RA11의 "DocModel에
  실재하는"에 모두 어긋난다.

u7 리더(`rds_assets.py`)는 `type IN ('figure','table')`(표시 갤러리용)이고 여기는
`('figure','formula')`(비전 입력용)다 — 목적이 다르니 대상도 다르다.
"""

from __future__ import annotations

import base64
import logging
import os
import re
from collections.abc import Callable
from typing import Any

from ..ports.assets import AssetStoreUnavailable, FigureAsset, FigureManifest
from ..ports.tools import (
    TOOL_VIEW_FIGURE,
    ImageAttachment,
    ToolContext,
    ToolResult,
    ToolSpec,
)
from .external.base import SourceBreaker, SourceUnavailable

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
# 부재로 취급하는 S3 오류 코드 — ingestion `s3_get_or_none`과 같은 분류.
_MISS_CODES = frozenset({"NoSuchKey", "404", "NotFound"})
_LIST_LIMIT = 60
# 비전 입력 대상 — 표는 제외한다(모듈 docstring의 근거·실측). 포트 계약이므로
# 테스트 대역도 이 상수를 그대로 쓴다.
_SERVED_TYPES = frozenset({"figure", "formula"})

# recordRef는 **모델이 쓴 값**이다 — u7 `_paper_ref`의 rsplit 휴리스틱은 앱이 나르는
# 정규 id용이라 여기에 쓰면 안 된다: 'arXiv:2401.00001'을 rsplit('v')하면 paper_id가
# 'arXi'가 되고 버전이 1로 강제되어, 실재하는 논문에 "자산이 없다"는 확신에 찬
# 오답이 나간다. 접두어를 벗기고 **끝의 vN만** 버전으로 인정하는 검증적 파서를 쓴다.
_RECORD_REF_RE = re.compile(r"^(?:arxiv:)?(?P<paper>.+?)(?:v(?P<version>\d+))?$", re.IGNORECASE)
_RECORD_REF_MAX_CHARS = 100  # ToolSpec.parameters의 maxLength와 같은 값


def _parse_record_ref(record_ref: str) -> tuple[str, int | None] | None:
    # 스펙의 maxLength는 모델에 대한 안내일 뿐 강제가 아니다 — 경계에서 막는다.
    if len(record_ref) > _RECORD_REF_MAX_CHARS:
        return None
    match = _RECORD_REF_RE.match(record_ref)
    if match is None:
        return None
    version = match["version"]
    return match["paper"], int(version) if version else None

# 버전 해석을 별도 질의로 두지 않는다 — 코퍼스의 recordRef가 거의 전부 bare라
# 나누면 사실상 모든 호출이 왕복 2회가 된다. `count(*) OVER ()`는 LIMIT 적용
# 전에 계산되므로 상한을 걸어도 실제 총 개수를 얻는다.
_RESOLVED_VERSION = (
    "COALESCE(:version, (SELECT max(version) FROM paper_asset WHERE paper_id = :paper_id))"
)
_TYPE_FILTER = "type IN ('figure', 'formula')"
_LIST_SQL = (
    "SELECT asset_id, type, ordinal, caption, object_ref, version, count(*) OVER () "
    f"FROM paper_asset WHERE paper_id = :paper_id AND {_TYPE_FILTER} AND version = "
    f"{_RESOLVED_VERSION} ORDER BY type, ordinal LIMIT :limit"
)
_GET_SQL = (
    "SELECT asset_id, type, ordinal, caption, object_ref "
    "FROM paper_asset WHERE paper_id = :paper_id AND asset_id = :asset_id "
    f"AND {_TYPE_FILTER} AND version = {_RESOLVED_VERSION}"
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
        breaker: SourceBreaker | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._s3 = s3_client
        self._region = region_name
        # 외부 연동 규칙(재시도 1회 + 반복 실패 시 자동 차단) — 다른 외부 도구와
        # 동일 정책. 부재(NoSuchKey)는 실패로 집계하지 않는다.
        self._breaker = breaker or SourceBreaker()

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
            data = self._breaker.call(lambda: self._get_bounded(bucket, key, max_bytes))
        except SourceUnavailable as exc:
            # 자격증명·엔드포인트·연속 실패 — 부재와 구분해 올린다. 뭉개면 도구가
            # "다른 자산을 고르라"고 잘못 안내해 로드될 수 없는 자산들로 캡을 태운다.
            log.warning("novelty view_figure: asset store unavailable", exc_info=True)
            raise AssetStoreUnavailable(str(exc)) from exc
        return (media_type, data) if data is not None else None

    def _get_bounded(self, bucket: str, key: str, max_bytes: int) -> bytes | None:
        """부재·크기 초과는 None(실패 집계 없음), 그 외 오류는 예외로 승격."""
        from botocore.exceptions import ClientError

        try:
            response = self._client().get_object(Bucket=bucket, Key=key)
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code in _MISS_CODES:
                return None  # 자산 부재는 스토어 장애가 아니다
            raise
        body = response["Body"]
        try:
            # 헤더에 크기가 있으면 본문 전송 전에 끊고, 없으면(로컬 프록시의 chunked
            # 응답) 상한+1까지만 읽는다 — 어느 쪽이든 무제한 버퍼링은 없다.
            length = response.get("ContentLength")
            if length is not None and int(length) > max_bytes:
                return None
            data = body.read(max_bytes + 1)
        finally:
            close = getattr(body, "close", None)
            if close is not None:
                close()
        return data if len(data) <= max_bytes else None


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
        parsed = _parse_record_ref(record_ref) if record_ref else None
        if parsed is None:
            return _refuse(
                "missing record_ref",
                "record_ref는 필수다 — 검색·근거 결과의 recordRef 값을 그대로 넣어라",
            )
        # 포트는 bare paper_id를 받는다 — 정규화는 여기서 한 번만 한다. 어댑터의
        # 방어적 정규화에 기대면 다른 구현이 들어올 때 조용한 영구 미스가 된다.
        # suffix가 없으면 version=None으로 넘겨 어댑터가 최신을 해석한다.
        paper_id, version = parsed

        asset_id = str(args.get("asset_id") or "").strip()
        if asset_id:
            return self._image_result(record_ref, paper_id, version, asset_id)
        return self._list_result(record_ref, paper_id, version)

    def _list_result(
        self, record_ref: str, paper_id: str, version: int | None
    ) -> ToolResult:
        manifest = self._assets.list_assets(paper_id, version, limit=_LIST_LIMIT)
        version_note: str | None = None
        if manifest is None and version is not None:
            # 명시 버전 미스 ≠ 논문에 자산 없음 — 백필 코퍼스는 버전 하나만 갖고
            # 있어 recordRef의 vN과 어긋날 수 있다. 저장된 버전으로 폴백하되
            # 어긋남을 밝힌다("자산이 없다"는 오답이 실재 자산에서 모델을 떼어놓는다).
            manifest = self._assets.list_assets(paper_id, None, limit=_LIST_LIMIT)
            if manifest is not None:
                version_note = (
                    f"요청한 v{version}의 자산은 없어 저장된 v{manifest.version}의 자산이다"
                )
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
        if version_note:
            content["note"] = version_note
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
        if match is None and version is not None:
            # 목록 경로와 같은 버전 폴백 — 목록이 폴백으로 보여준 자산을 이미지로
            # 조회하면 같은 명시 버전으로 다시 미스가 나 무한 목록↔조회 루프가 된다.
            match = self._assets.get_asset(paper_id, None, asset_id)
        if match is None:
            return _refuse(
                "unknown asset",
                f"asset_id '{asset_id}'는 {record_ref} 논문에 없다 — "
                "asset_id 없이 view_figure를 호출해 목록을 먼저 받아라",
            )

        try:
            fetched = self._assets.fetch_bytes(
                match.object_ref, max_bytes=self._max_image_bytes
            )
        except AssetStoreUnavailable:
            # 스토어 장애는 자산 부재와 다른 수리 지시를 받는다 — "다른 자산을
            # 고르라"는 안내는 로드될 수 없는 자산들로 캡 8회를 태우게 만든다.
            return _refuse(
                "asset store unavailable",
                "자산 스토어에 접근할 수 없다(스토리지 장애) — 이미지 조회를 반복하지 "
                "말고 캡션·텍스트 근거로 진행하라",
            )
        if fetched is None:
            # 부재와 상한 초과가 한 사유로 모인다 — 다음 행동이 같기 때문이다
            # (다른 자산을 고르거나 텍스트로 진행). 스토어 장애는 위에서 분리됐다.
            return _refuse(
                "asset unavailable",
                f"asset_id '{asset_id}' 이미지를 쓸 수 없다(부재 또는 크기 초과) — "
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
