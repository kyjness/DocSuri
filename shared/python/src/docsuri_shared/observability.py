"""Best-effort observability emission — the cross-Unit metric wrapper.

``ObservabilityHub``(ports.py)는 공유 포트지만, 모든 소비자가 필요로 하는
"advisory 방출은 절대 호출자를 실패시키지 않는다"는 방어 래퍼는 유닛마다
사본이었다. 이 헬퍼가 그 메커니즘(None 가드·예외 삼킴)과 포트 시그니처
``emit_metric(name, value, tags)``를 한 곳에서 강제한다 — 유닛 래퍼의 인자
드리프트(예: 1-인자 호출이 실허브에서 TypeError로 삼켜져 메트릭이 영영
방출되지 않는 문제)를 구조적으로 차단한다. 어떤 이벤트가 어떤 카운터를
쏘는가는 유닛 정책으로 남는다.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

__all__ = ["emit_metric"]

log = logging.getLogger("docsuri.shared.observability")


def emit_metric(
    hub: Any,
    name: str,
    value: float = 1.0,
    tags: Mapping[str, str] | None = None,
) -> None:
    """허브가 없거나 방출이 실패해도 호출자를 실패시키지 않는다(best-effort)."""
    if hub is None:
        return
    try:
        hub.emit_metric(name, value, dict(tags or {}))
    except Exception:  # noqa: BLE001 — 계측은 advisory side path
        log.debug("metric emit failed: %s", name, exc_info=True)
