"""자산 포트 — `view_figure`가 읽는 논문 그림·수식·표 crop(FR-17 산출물).

u1 인제스천이 WebP로 잘라 S3에 넣고 `paper_asset` 매니페스트에 등재한 자산만
대상이다(BR-RA11 — DocModel에 실재하는 자산만). u7 `AssetReadPort`와 달리 **서명
URL이 아니라 바이트**를 반환한다: 서명 URL은 로컬 s3proxy 주소라 LLM 프로바이더가
가져갈 수 없고, 어차피 data URI로 인라인해야 하기 때문이다.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

__all__ = ["FigureAsset", "FigureAssetPort"]


@dataclass(frozen=True, slots=True)
class FigureAsset:
    """`paper_asset` 한 행. `object_ref`는 내부 값이며 모델에 노출하지 않는다(SEC-9)."""

    asset_id: str
    type: str
    ordinal: int
    caption: str
    source_mode: str
    object_ref: str


class FigureAssetPort(Protocol):
    """`paper_id`는 **bare**(버전 suffix 없음)다 — `paper_asset`가 그렇게 키를 잡는다.
    정규화는 호출자(도구)가 한 번 수행한다."""

    def latest_version(self, paper_id: str) -> int | None: ...

    def list_assets(self, paper_id: str, version: int) -> Sequence[FigureAsset]: ...

    def fetch_bytes(self, object_ref: str) -> tuple[str, bytes] | None:
        """(media_type, data) — 없으면 None. 호출자가 바이트 상한을 강제한다."""
        ...
