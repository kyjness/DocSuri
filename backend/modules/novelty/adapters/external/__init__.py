"""외부 탐색 어댑터 — GitHub·데이터셋(⑤ 2단계에서 MCP 어댑터로 교체 예정).

도구별 payload allowlist는 sanitize.py가 기계식으로 강제한다(BR-RA7) —
MCP 서버 등 외부 구현은 신뢰 경계 밖이며 allowlist는 항상 우리 어댑터에 건다.
"""
