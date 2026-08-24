"""§6 평가 — 골든셋과 3층 채점 중 1층(결정론)·2층(심판) 입구.

`golden_set`은 문항, `layer1`은 코드 채점, `judge`는 2층 심판의 프롬프트·집계다.
1층은 CI에서 **녹화 픽스처**로 돌아 비용이 0이고, 2층은 실모델이 필요해 수동이다.
"""

from .golden_set import GOLDEN_CASES, GoldenCase, QuestionType
from .layer1 import Layer1Report, score_turn, summarise

__all__ = [
    "GOLDEN_CASES",
    "GoldenCase",
    "Layer1Report",
    "QuestionType",
    "score_turn",
    "summarise",
]
