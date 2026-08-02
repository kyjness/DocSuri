"""논문 자산 리더 — `paper_asset` 매니페스트 + S3 바이트(FR-17 산출물).

**비전 입력용 공용 부품**이다. u12 novelty와 u11 evidence가 같은 요구(바이트 반환,
figure·formula)를 갖게 되어 novelty 안에서 꺼냈다(로드맵 ⑥ 항목 4).

u7 `summarization/adapters/rds_assets.py`(서명 URL, `figure|table`, 표시 갤러리용)와는
**합치지 않는다** — 반환 형태도 대상 타입도 목적이 다르고, 억지로 묶으면 두 소비자의
요구가 충돌하는 추상이 굳는다.

위치가 `shared/python`이 아니라 여기인 이유: `docsuri-shared`는 pydantic만 의존하는
계약 패키지다. sqlalchemy·boto3를 쓰는 런타임 부품을 거기 넣으면 계약 소비자 전부가
그 의존을 진다. 저장소의 기존 선례(`backend/modules/user_docmodel.py`)와 같은 자리에 둔다.

서빙 대상은 **figure·formula뿐이다**(`_SERVED_TYPES`). 표는 u1이 구조화(rows)해
DocModel에 싣고 crop은 참조하지 않으므로, 표 crop을 서빙하면 이미 텍스트로 읽을 수
있는 것을 이미지로 다시 받으며 캡을 태운다(로컬 코퍼스 실측: 표 crop 772건 중 DocModel
참조 0건). 수식은 `latex`와 `assetRef` 중 하나만 렌더 소스라 crop 행의 존재가 곧 LaTeX
복원 실패를 뜻한다(수식 crop 24건 중 latex 동반 0건).
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from backend.modules.novelty.adapters.external.base import SourceBreaker, SourceUnavailable

__all__ = [
    "AssetStoreUnavailable",
    "FigureAsset",
    "FigureAssetPort",
    "FigureManifest",
    "SqlS3FigureReader",
    "parse_record_ref",
]

log = logging.getLogger("docsuri.paper_assets")


class AssetStoreUnavailable(RuntimeError):
    """자산 스토어 자체의 장애(자격증명·엔드포인트·연속 실패) — 자산 1건의 부재와
    구분한다. 부재는 다른 자산을 고르면 되지만, 스토어 장애에서 같은 안내를 하면
    에이전트가 로드될 수 없는 자산들로 캡 8회를 전부 태운다."""


@dataclass(frozen=True, slots=True)
class FigureAsset:
    """`paper_asset` 한 행. `object_ref`는 내부 값이며 모델에 노출하지 않는다(SEC-9)."""

    asset_id: str
    type: str
    ordinal: int
    caption: str
    object_ref: str


@dataclass(frozen=True, slots=True)
class FigureManifest:
    """해석된 버전 + (상한까지의) 자산 목록.

    `total`은 상한 적용 **전** 개수다 — 모델에게 목록이 전부가 아님을 알린다.
    """

    version: int
    assets: Sequence[FigureAsset]
    total: int


class FigureAssetPort(Protocol):
    """`paper_id`는 **bare**(버전 suffix 없음)다 — `paper_asset`가 그렇게 키를 잡는다.
    정규화는 호출자(도구)가 한 번 수행한다.

    구현은 **비전 입력 대상 타입만**(figure·formula) 돌려준다. 표 crop은 DocModel이
    참조하지 않는 중복물이라 제외된다 — 근거는 `adapters/figures.py` 모듈 docstring."""

    def list_assets(
        self, paper_id: str, version: int | None, *, limit: int
    ) -> FigureManifest | None:
        """자산이 하나도 없으면 None. `version=None`이면 최신 버전을 해석한다."""
        ...

    def get_asset(
        self, paper_id: str, version: int | None, asset_id: str
    ) -> FigureAsset | None:
        """단건 조회 — 존재 확인용으로 매니페스트 전체를 읽지 않는다."""
        ...

    def fetch_bytes(self, object_ref: str, *, max_bytes: int) -> tuple[str, bytes] | None:
        """(media_type, data) — 없거나 `max_bytes` 초과면 None(본문 전송 전 차단).

        스토어 자체가 죽었으면 `AssetStoreUnavailable`을 던진다 — 부재와 장애를
        한 값으로 뭉개면 호출자가 수리 지시를 잘못 준다.
        """
        ...


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


def parse_record_ref(record_ref: str) -> tuple[str, int | None] | None:
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
