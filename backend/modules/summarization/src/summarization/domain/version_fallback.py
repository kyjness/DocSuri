"""요청한 개정판이 없을 때 실제로 저장된 판으로 떨어지는 폴백.

전문·요약·번역·그림은 전부 ``(paperId, version)``으로 키잉된 산출물을 읽는다 —
``doc-model/{id}/v{n}.json`` · ``full-text/{id}/v{n}.txt`` · ``assets/{id}/v{n}`` ·
``paper_asset(paper_id, version)``. 여기서 version은 **arXiv 개정판**이고, 화면은 그것을
검색 카드의 ``arxivId`` 접미사에서 읽는다(``frontend/lib/arxivVersion.ts``).

접미사가 유실된 색인 레코드가 있었다: 재청킹 도구가 ``display_arxiv_id``를 bare로 써서
실제로는 v7만 저장된 논문을 화면이 v1로 조회했다(배포 색인 3,248편 중 1,023편). 빌드 큐가
없는 배포에서는 그 미스가 ``building``이 아니라 ``source_unavailable``로 굳어, 넷이 한꺼번에
"원문을 가져올 수 없어요"가 됐다.

색인은 따로 고치지만 읽기 경로도 혼자 버틸 수 있어야 한다 — 어느 판이 실제로 있는지는
레이아웃을 소유한 리더가 ``latest_version``으로 프리픽스 목록 1회에 답한다. **미스일 때만**
부르므로 정상 경로에는 왕복이 늘지 않는다.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

__all__ = ["fallback_version"]


def fallback_version(reader: object | None, paper_id: str, requested: int) -> int | None:
    """``requested``에 산출물이 없을 때 대신 읽어 볼 판. 더 볼 것이 없으면 None.

    리더가 ``latest_version``을 가질 때만 동작한다 — evidence의 조회부와 같은 덕타이핑이라
    (``adapters/sources.py``) 읽기 포트 프로토콜을 넓히지 않는다. 테스트 스텁이나 큐만 물린
    배선처럼 그 메서드가 없는 리더에서는 조용히 폴백 없음이 된다.

    조회 실패는 삼킨다. 이 함수는 **이미 미스인** 경로의 보정이라, 여기서 예외를 올리면
    ``source_unavailable``이 될 응답을 500으로 바꾼다 — 화면이 나빠지는 쪽으로만 움직인다.
    """
    lookup = getattr(reader, "latest_version", None)
    if not callable(lookup):
        return None
    try:
        latest = lookup(paper_id)
    except Exception:  # noqa: BLE001 — 폴백 실패는 폴백 없음이지 요청 실패가 아니다
        logger.warning("latest_version lookup failed for %s", paper_id, exc_info=True)
        return None
    if not isinstance(latest, int) or latest <= 0 or latest == requested:
        return None
    return latest
