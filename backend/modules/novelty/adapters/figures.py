"""view_figure 도구(BLM §3, BR-RA11) — 논문 그림·수식 crop을 멀티모달 입력으로.

**2모드 계약**: `asset_id` 없이 호출하면 그 논문의 자산 목록(assetId·type·caption)을
텍스트로 돌려주고, `asset_id`를 주면 그 자산 하나를 이미지로 돌려준다. 온디맨드
원칙(FD 게이트 Q7=A — 캡션 보고 필요 판단한 것만 조회)을 도구 어휘 확장 없이 지킨다.

자산 리더 자체는 u11 evidence와 공유하므로 `backend.modules.paper_assets`에 있다
(로드맵 ⑥ 항목 4). 여기 남은 것은 novelty 도구 계약(ToolResult·ToolSpec)에 묶인
껍데기뿐이다 — 두 유닛의 ToolResult 타입이 다르므로 도구는 유닛별로 둔다.
"""

from __future__ import annotations

import base64
import logging
from typing import Any

from backend.modules.paper_assets import AssetStoreUnavailable, parse_record_ref

from ..ports.tools import (
    TOOL_VIEW_FIGURE,
    ImageAttachment,
    ToolContext,
    ToolResult,
    ToolSpec,
)

__all__ = ["ViewFigureTool"]

log = logging.getLogger("docsuri.novelty.figures")

_LIST_LIMIT = 60


# 거부 사유는 판정이자 **수리 지시**다(⑤2 실스택 검증 교훈) — 무엇이 틀렸는지와
# 다음에 무엇을 하면 되는지를 함께 담지 않으면 자율 루프는 같은 실수를 반복한다.
_RETRY_HINT = "같은 논문의 다른 자산을 고르거나 텍스트 근거로 진행하라"


def _refuse(summary: str, message: str) -> ToolResult:
    return ToolResult(ok=False, error=message, result_summary=f"view_figure: {summary}")


class ViewFigureTool:
    spec = ToolSpec(
        name=TOOL_VIEW_FIGURE,
        description=(
            "확보한 논문의 그림·수식을 조회한다. asset_id 없이 호출하면 그 논문의 "
            "자산 목록(assetId·종류·캡션)을 돌려주고, asset_id를 주면 그 자산을 "
            "**이미지로 첨부해 실제로 보여준다**. "
            "캡션은 그림이 무엇을 그렸는지 알려주지 않는다 — 축·수치·패널 구성·경향처럼 "
            "그림 자체를 봐야 아는 것이 필요하면 목록에서 고른 뒤 asset_id로 반드시 연다. "
            "캡션만 다시 옮겨 적는 것은 이 도구를 쓴 것이 아니다."
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
        parsed = parse_record_ref(record_ref) if record_ref else None
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
