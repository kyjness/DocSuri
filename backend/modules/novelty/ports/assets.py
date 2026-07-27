"""자산 포트 — `view_figure`가 읽는 논문 그림·수식·표 crop(FR-17 산출물).

u1 인제스천이 WebP로 잘라 S3에 넣고 `paper_asset` 매니페스트에 등재한 자산만
대상이다(BR-RA11 — DocModel에 실재하는 자산만). u7 `AssetReadPort`와 달리 **서명
URL이 아니라 바이트**를 반환한다: 서명 URL은 로컬 s3proxy 주소라 LLM 프로바이더가
가져갈 수 없고, 어차피 data URI로 인라인해야 하기 때문이다.

`version=None`은 "최신 버전"을 뜻하고 어댑터가 한 번의 질의로 해석한다 — 버전
조회와 자산 조회를 나누면 코퍼스의 recordRef가 거의 전부 bare라서 매 호출이
왕복 2회가 된다.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

__all__ = ["AssetStoreUnavailable", "FigureAsset", "FigureAssetPort", "FigureManifest"]


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
