# Story Generation Plan — U3 Accounts 프로덕션화

**단계**: INCEPTION → User Stories 재진입 (기존 에픽 2 — 계정 확장) · **일자**: 2026-06-24 · **브랜치**: `feature/u3-accounts-production`
**입력**: `requirements.md` FR-26~29 (계정 프로덕션화) + `requirement-verification-questions-account-production.md` 확정 답변.
**승인**: 사용자 "approved & continue" — 본 계획의 권장안(PQ1~5) 일괄 채택.

## 평가 (Step 1 — User Stories 실행 정당성)
- **User Impact**: Direct (가입/로그인/계정관리 = 사용자 직접 상호작용). **High Priority — Security Enhancements + New User Features** → 실행 확정.
- 본 작업은 신규 사용자 표면(재설정·소셜·라이프사이클) + 보안 민감 → 스토리 + 인수 기준으로 테스트 가능 사양화 필요.

## 계획 질문 (PQ) — 권장안 일괄 채택
- **PQ1. 분해 접근** — **Epic-Based(권장)**: 기존 9개 에픽 선례와 동일. 본 기능은 **에픽 2(계정)** 확장으로 편입(신규 에픽 아님). `[Answer]`: 권장
- **PQ2. 스토리 입도** — **권장**: 역량 단위 1 스토리, 비번/이메일 변경은 자가관리 1 스토리로 묶고 삭제는 분리(비가역성·캐스케이드로 독립 테스트 가치). `[Answer]`: 권장
- **PQ3. 포맷** — **권장**: 기존 `As/I want/so that` + `Given/When/Then` 인수 기준 + `Traces`. `[Answer]`: 권장
- **PQ4. 페르소나** — **권장**: 신규 페르소나 없음(P1 박지훈·P2 일반 사용자가 계정 기능 전수 커버); 매핑만 US-A1..A7로 확장. `[Answer]`: 권장
- **PQ5. 추적성** — **권장**: FR-26~29 ↔ US-A3~A7 1:1 매핑 + 커버 푸터 갱신. `[Answer]`: 권장

## 생성 체크리스트 (Step 4 — 필수 산출물)
- [x] `stories.md` 에픽 2에 INVEST 스토리 추가: US-A3(FR-26 재설정)·US-A4(FR-27 소셜 OIDC)·US-A5(FR-28 비번/이메일 변경)·US-A6(FR-28 삭제)·US-A7(FR-29 입력 견고화·에러 표면화)
- [x] 각 스토리 Given/When/Then 인수 기준 (보안 경로: 열거 방지·세션 무효화·미검증 이메일 연결 거부·캐스케이드 파기)
- [x] `personas.md` 신규 불요 — P1/P2 매핑만 US-A1..A7 확장(stories.md 페르소나 표)
- [x] 추적성 행 FR-26~29 → 스토리 + 커버 푸터
- [x] INVEST 점검: 각 스토리 독립·협상가능·가치·추정가능·작음·테스트가능

## 다음
User Stories 리뷰 게이트 승인 → Units Generation(U3 확장·U10 경계 주석) → Construction(U3 Functional/NFR/Infra Design HOW 라운드 → Code → Build&Test).
