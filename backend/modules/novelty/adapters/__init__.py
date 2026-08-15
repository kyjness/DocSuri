"""Novelty v2 어댑터 — logical-components.md §1의 adapters/ 배치.

local_wiring(redis·postgres, 로컬 1차)과 real_wiring(SQS·RDS,
배포 기준선 — 계약 보존)이 조립 루트다. 도메인·루프 코어는 여기 구현을 모른다.
"""
