"""외부 탐색 어댑터 — GitHub·데이터셋(직접 구현, TD-NV2-4).

도구별 payload allowlist는 sanitize.py가 기계식으로 강제한다(BR-RA7) —
구현을 무엇으로 바꾸든 외부 서비스는 신뢰 경계 밖이며 allowlist는 항상
우리 어댑터에 건다.
"""
