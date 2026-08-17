# Novelty Agent v2 재설계 (U12) — NFR Design Plan + 질문 게이트

**단계**: CONSTRUCTION → NFR Design
**일자**: 2026-07-18
**상태**: ✅ 확정 (2026-07-18) — 네 문항 모두 선행 결정(FD·NFR Requirements)의 직접 귀결이라 권장안을 일괄 적용(사용자 연속 진행 지시). 리뷰에서 이의 시 개정한다.
**전제**: FD 4종 + NFR Requirements 2종 확정. 여기서는 컴포넌트 배치·복원력 패턴·관측·캐시만 다룬다.

## 1. 산출물

`aidlc-docs/solo-agent/novelty-agent-v2/nfr-design/`에 작성:

- [x] `logical-components.md`
- [x] `nfr-design-patterns.md`

## 2. 명확화 질문

### Q1 — 컴포넌트 배치
- **A) `backend/modules/novelty/` 내부 재작성 구조** — 루프 코어(도메인) / 포트 / 어댑터(local·real wiring) / API / 워커의 헥사고날 분리, 기존 conditional mounting 관례 유지. (권장)
- B) 신규 모듈 분리 — 모듈 경로 유지 결정(arch Q4=A·⑤ 제약)과 상충.

[Answer]: A

### Q2 — 재시도·서킷 브레이커
- **A) u2/u7 검증 패턴 재사용** — 의존성별 서킷 브레이커(LLM·U2·evidence 엔진·외부 탐색 어댑터·저장소 단위), 도구 단건 재시도는 1회(outage는 abstain 정신), 그 이상의 재시도 판단은 에이전트 자율 + 예산 상한. (권장)
- B) 신규 재시도 프레임워크 — 검증 안 된 복잡도.

[Answer]: A

### Q3 — 관측 신호
- **A) 트레이스 = 1차 관측** — `ToolCallRecord`가 구조화 관측의 SSOT. 보조로 기존 텔레메트리 경로(best-effort)에 잡 완료율·partial 비율·예산 소진율·게이트 거부율 카운터를 발행. (권장)
- B) 별도 APM 도입 — 로컬 체제에 과함.

[Answer]: A

### Q4 — 캐시
- **A) v2 신규 캐시 없음** — 조사 결과는 잡으로 영속되므로 재생성 캐시가 불필요. 하부 캐시(U2 검색·요약)는 그대로 재사용. 온디맨드 생성물도 잡에 영속(중복 요청 시 기존 산출물 반환). (권장)
- B) 보고 캐시 신설 — 무효화 키 관리 비용만 추가.

[Answer]: A

## 3. 산출물 요약

- `logical-components.md`: 모듈 내부 배치(루프 코어·도구 레지스트리·저장 게이트·트레이스 기록기·투영기·워커·API), 포트/어댑터 목록, 잡 수명 시퀀스, conditional mounting 조건
- `nfr-design-patterns.md`: 의존성별 서킷 브레이커, 재시도·저하 계단, 멱등 실행 잠금, 예산 집행 지점, 관측 신호, 테스트 전략(포트 대역·PBT 배치)
