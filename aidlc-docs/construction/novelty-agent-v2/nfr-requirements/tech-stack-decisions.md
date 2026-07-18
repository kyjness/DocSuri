# Novelty Agent v2 — Tech Stack Decisions

**Unit**: Novelty Agent v2 (U12)
**Stage**: NFR Requirements (2026-07-18, 질문 게이트 Q1~Q6=A)
**원칙**: 각 결정은 "포트 → 1차 어댑터(로컬) → 배포 재개 시 교체 경로"로 기술한다. 도메인·루프 코어는 어댑터를 모른다.

| ID | 포트/관심사 | 1차 어댑터 (로컬 컨테이너 체제) | 배포 재개 시 교체 경로 |
|---|---|---|---|
| TD-NV2-1 | 잡 큐 포트 | **redis** 기반 잡 큐(기존 컨테이너 재사용) + 실행 잠금 | SQS 어댑터 — 기존 `real_wiring` 워커 계약 기준선 복원 |
| TD-NV2-2 | 워커 실행 | backend 모듈 워커 엔트리포인트를 **별도 프로세스**로 기동(로컬: uv run / 컨테이너) | 배포 워커(컨테이너/서비스)로 동일 엔트리포인트 재사용 |
| TD-NV2-3 | LLM tool-calling 포트 | 기존 프로바이더 스위치 뒤 **OpenAI function-calling 어댑터** 신규 | Bedrock(구 기준선)·Anthropic 어댑터 추가 — 루프 코어 무변경 |
| TD-NV2-4 | 외부 탐색 포트(⑤ 2단계) | **검증된 기존 MCP 서버 셀프호스트**(arXiv·GitHub·Notion — 로컬 컨테이너). 서버는 신뢰 경계 밖 — payload allowlist는 우리 어댑터가 강제 | 동일 서버를 배포 환경에 셀프호스트 또는 호스티드 MCP로 교체(어댑터 접속 정보만 변경). 구체 서버 리포지토리 선정은 ⑤ 2단계 착수 시 확정 기록 |
| TD-NV2-5 | 산출물·트레이스 저장 | **postgres** — 잡 귀속 테이블(`ToolCallRecord`는 `(job_id, seq)` 인덱스, cascade 삭제) | RDS — 스키마 동일, 연결 설정만 |
| TD-NV2-6 | 원고 첨부 저장 | 기존 첨부 경로(s3proxy) 재사용 | S3 — 기존 계약 그대로 |
| TD-NV2-7 | 진행 피드 | 폴링 seam(커서 기반 증분 조회) — U13 timeline seam 재사용 | 동일(SSE 도입은 후속 개선 — 어댑터가 아니라 API 표면 추가) |
| TD-NV2-8 | 예산 집행 | `LoopBudget` 영속(AgentLoopRun) + U6 `get_budget_state()` 연동 | 동일 — U6 비용 권위 불변 |

## 근거 요약

- **redis 큐(TD-NV2-1)**: 로컬 이관 컨테이너 4종에 이미 포함 — 신규 인프라 0. 큐 포트 인터페이스는 SQS 어댑터가 만족하던 계약(가시성 타임아웃 → 실행 잠금으로 대응)과 호환되게 설계한다.
- **OpenAI 1차(TD-NV2-3)**: 로컬 이관에서 이미 임베딩·요약 프로바이더로 검증됨. tool-calling 어댑터만 신규. 프로바이더 비교 실험(Anthropic 병행)은 `solo-local-migration.md` §7 미룬 결정과 연동 — 어댑터 추가만으로 가능함을 계약 수준에서 보장.
- **MCP 셀프호스트(TD-NV2-4)**: 자작 서버 대비 ⑤ 2단계 기간 최소화. 보안 근거: 프라이버시 방어선은 서버가 아니라 우리 어댑터의 allowlist(BR-RA7)이므로 서버 신뢰도가 안전 전제 조건이 아니다.
- **postgres 트레이스(TD-NV2-5)**: owner-scoped 삭제(BR-NV18 개정)를 트랜잭션 경계 하나로 보장. 별도 로그 스토어는 삭제 정합 위험.

## Traceability

| Source | Covered By |
|---|---|
| NFR-P5 / NFR-NV2-1~3 | TD-NV2-1·2 |
| FR-30(루프) | TD-NV2-3 |
| FR-31(외부 탐색 중립화)·⑤ 2단계 | TD-NV2-4 |
| FR-45 | TD-NV2-8 |
| FR-46 / NFR-NV2-12 | TD-NV2-5 |
| FR-35 / NFR-NV2-14 | TD-NV2-7 |
| FR-30 원고 입력 | TD-NV2-6 |
