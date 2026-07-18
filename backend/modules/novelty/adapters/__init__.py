"""Novelty 어댑터 패키지.

v2 재작성 경과 조치: 기존 `adapters.py` 전체를 `_legacy.py`로 옮기고 공개·내부
심볼을 그대로 재수출한다 — wiring·worker·기존 테스트가 무변경으로 동작한다.
v2 어댑터(local_wiring/real_wiring/external/evidence)가 이 패키지에 추가되며,
컷오버 시 `_legacy.py`와 이 재수출은 제거된다.
"""

from __future__ import annotations

from . import _legacy

# 언더스코어 헬퍼( `_fallback_experiment_plan` 등)까지 기존 모듈 경로 그대로 노출.
for _name in dir(_legacy):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_legacy, _name)
del _name
