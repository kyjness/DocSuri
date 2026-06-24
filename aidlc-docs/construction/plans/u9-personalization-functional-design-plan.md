# u9-personalization-functional-design-plan.md — Functional Design 계획 + 질문 게이트

**단계**: CONSTRUCTION -> Functional Design (유닛별 루프) · **유닛**: U9 Personalization · **일자**: 2026-06-23  
**근거(SSOT)**: `requirements.md`(FR-18~20, NFR-P4, QT-7, U9 제외), `stories.md`(US-P1~P7), `application-design/{unit-of-work,unit-of-work-dependency,unit-of-work-story-map}.md`  
**원칙**: 이 단계는 **기술 무관**이다. RDS schema, migration, API framework, job scheduler, cache, index integration 세부는 NFR/Infra/Code Generation에서 확정한다.

> 본 계획서는 리뷰 게이트다. 아래 `[Answer]:`가 모두 확정되기 전에는 FD 산출물(`domain-entities.md`, `business-logic-model.md`, `business-rules.md`)을 만들지 않는다.

---

## 1. 유닛 컨텍스트

- **책임**: 사용자별 의미 행동 이벤트 기록, 관심 프로필 집계, 개인화 설정/삭제/초기화, 검색 boost와 요약/번역 기본값 제공.
- **Owner 스토리**: US-P1, US-P2, US-P3, US-P4, US-P5, US-P6.
- **기여 스토리**: US-P7(Owner=U6, U9는 저하/집계 신호원).
- **범위 내**: 검색 실행, 논문 조회, 라이브러리 저장/해제, 요약/번역 요청, 출처 앵커 클릭, 용어집 수정 이벤트; 사용자 관심 프로필; 개인화 on/off, 원시 로그 삭제, 프로필 초기화; 비차단 저하.
- **범위 밖**: 전체 클릭스트림, hover/scroll 추적, 별도 추천 논문 목록, 강한 리랭크, 실시간 ML 추천 파이프라인, U6 운영 텔레메트리와 사용자 행동 데이터 통합.
- **예비 컴포넌트**:
  - `BehaviorEventRecorder`
  - `UserInterestProfileService`
  - `PersonalizationSettingsService`
  - `PersonalizationPolicy`
  - `ProfileAggregator`
  - `PersonalizationReadPort`
  - `PersonalizationTelemetryPublisher`

---

## 2. Functional Design 실행 계획

답변 확정 후 아래 산출물을 `aidlc-docs/construction/u9-personalization/functional-design/`에 작성한다.

- [x] **domain-entities.md**
  - `BehaviorEvent`
  - `BehaviorEventType`
  - `BehaviorSubject`
  - `BehaviorEventMetadata`
  - `UserInterestProfile`
  - `InterestSignal`
  - `PersonalizationSettings`
  - `PersonalizationDecision`
  - `PersonalizationError`
- [x] **business-logic-model.md**
  - `recordBehaviorEvent(event)`
  - `aggregateInterestProfile(userId)`
  - `getSearchPersonalization(userId, queryContext)`
  - `getSummaryTranslationDefaults(userId)`
  - `setPersonalizationEnabled(userId, enabled)`
  - `deleteBehaviorEvents(userId)`
  - `resetInterestProfile(userId)`
  - failure path: default non-personalized behavior
- [x] **business-rules.md**
  - meaningful-event-only rule
  - owner-scoped access rule
  - record-after-success rule
  - raw event retention rule
  - profile aggregation invariant
  - bounded boost/default override rule
  - user control/delete/reset rule
  - NFR-P4 fail-open-to-default rule
  - QT-7 property candidates
  - traceability matrix

---

## 3. 가정

- **AS-1**: U9는 API 모듈이며 별도 배포 서비스를 만들지 않는다.
- **AS-2**: U9는 개인화 도메인 데이터를 소유하고, U6 운영 텔레메트리와 섞지 않는다.
- **AS-3**: U2/U4/U7/U5는 성공 경로에서 U9를 비차단 호출한다.
- **AS-4**: U9 실패는 검색/요약/번역/라이브러리 본 기능 실패로 승격하지 않는다.
- **AS-5**: 프런트엔드 화면 구현은 U5 책임이다. U9 Functional Design은 API/도메인 계약까지만 정의한다.

---

## 4. 명확화 질문

### Q1 — 행동 이벤트 envelope
행동 이벤트의 공통 구조를 어떻게 잡을까요?

A) **공통 envelope + 이벤트별 최소 metadata(권장)** — `eventId`, `userId`, `eventType`, `subject`, `occurredAt`, `source`, `metadata`, `dedupeKey`를 공통으로 두고 metadata는 이벤트별 최소 필드만 허용한다.

B) 이벤트 타입마다 완전히 다른 구조를 둔다.

C) 자유 JSON payload로 저장한다.

X) 기타.

[Answer]: A

### Q2 — 기록 대상 이벤트
v1에서 기록할 이벤트 타입은?

A) **요구사항 범위 그대로 7종(권장)** — `search_executed`, `paper_opened`, `library_added`, `library_removed`, `summary_translation_requested`, `source_anchor_clicked`, `glossary_updated`.

B) 검색/논문 조회/라이브러리 저장만.

C) 프런트 클릭 이벤트까지 포함.

X) 기타.

[Answer]: A

### Q3 — 기록 시점
행동 이벤트는 언제 확정 기록할까요?

A) **도메인 액션 성공 후 기록(권장)** — API 성공 후 기록하며, `library_removed`는 삭제 전 subject id를 확보하고 삭제 성공 후 기록한다. 출처 앵커처럼 프런트 전용 이벤트만 별도 API로 기록한다.

B) 요청이 들어오는 즉시 먼저 기록한다.

C) 배치 로그 분석으로 나중에 추출한다.

X) 기타.

[Answer]: A

### Q4 — dedupe 기준
중복 이벤트는 어떻게 막을까요?

A) **명시적 dedupeKey + 짧은 시간창 보조(권장)** — caller가 제공하는 요청/액션 ID를 우선하고, 없으면 사용자·타입·subject·근접 시간으로 중복을 제한한다.

B) 중복을 허용하고 집계에서만 완화한다.

C) timestamp가 같을 때만 중복으로 본다.

X) 기타.

[Answer]: A

### Q5 — 관심 프로필 신호 가중치
행동 이벤트를 관심 프로필로 바꿀 때 어떤 신호를 강하게 볼까요?

A) **저장/반복 조회/요약 요청을 강한 양의 신호로, 단순 조회는 약한 신호로 본다(권장)**. `library_removed`는 "싫어요"가 아니라 저장 신호 철회로 처리한다.

B) 모든 이벤트를 같은 가중치로 본다.

C) `library_removed`를 강한 음의 선호로 본다.

X) 기타.

[Answer]: A

### Q6 — 프로필 집계 방식
프로필 집계는 어떤 비즈니스 의미를 가질까요?

A) **동일 입력 이벤트 집합이면 동일 프로필(권장)** — arXiv 카테고리, 키워드, 저장/반복 조회 논문, summary persona, translation scope, glossary version을 bounded weights로 산출한다.

B) 최근 이벤트 순서에 따라 결과가 달라져도 된다.

C) 저장 논문 목록만 프로필로 쓴다.

X) 기타.

[Answer]: A

### Q7 — 개인화 적용 강도
검색 개인화와 요약/번역 기본값을 어떻게 적용할까요?

A) **작은 boost/default suggestion만 제공(권장)** — U2는 기존 랭킹 위에 bounded boost만 적용하고, U7은 기본값 제안만 받으며 사용자의 현재 선택이 항상 우선한다.

B) U9가 최종 검색 순위를 직접 결정한다.

C) 요약/번역 기본값만 개인화하고 검색은 제외한다.

X) 기타.

[Answer]: A

### Q8 — 개인화 on/off 의미
사용자가 개인화를 끄면 무엇이 멈출까요?

A) **프로필 사용과 향후 개인화 이벤트 기록을 멈춘다(권장)**. 기존 원시 로그/프로필은 보관 정책에 따르며, 별도 삭제/초기화 요청으로 제거한다.

B) 프로필 적용만 끄고 이벤트 기록은 계속한다.

C) off 즉시 원시 로그와 프로필을 모두 삭제한다.

X) 기타.

[Answer]: A

### Q9 — 삭제/초기화 의미
사용자 제어 API의 의미를 어떻게 나눌까요?

A) **행동 로그 삭제와 프로필 초기화를 분리(권장)** — 로그 삭제는 raw events를 삭제하고, 프로필 초기화는 aggregate/defaults를 지운다. 둘 다 owner-scoped다.

B) 하나의 "모두 삭제" 액션만 제공한다.

C) 운영자만 삭제할 수 있다.

X) 기타.

[Answer]: A

### Q10 — 실패 처리
U9 저장소/집계가 실패하면 사용자 경험은?

A) **기본 비개인화 경로로 fail-open(권장)** — 검색/요약/번역/라이브러리는 성공시키고 U9 실패는 저하 신호로만 남긴다.

B) 개인화 실패면 전체 요청도 실패시킨다.

C) 사용자에게 매번 경고 모달을 띄운다.

X) 기타.

[Answer]: A

### Q11 — Functional Design의 프런트엔드 산출물
U9 Functional Design에서 `frontend-components.md`를 만들까요?

A) **만들지 않는다(권장)** — U9는 API 모듈이고, U5가 설정 UI/표시를 구현한다. U9 FD에는 UI 계약만 business logic/rules에 적는다.

B) U9 폴더에 별도 frontend-components.md를 만든다.

X) 기타.

[Answer]: A

### Q12 — QT-7 속성 후보
Functional Design에서 QT-7 후보를 어디까지 고정할까요?

A) **DTO roundtrip, dedupe stability, owner isolation, retention/delete/reset, deterministic aggregation(권장)**.

B) DTO roundtrip만.

C) QT-7은 Code Generation에서만 결정한다.

X) 기타.

[Answer]: A

---

## 5. 결정 예정 불변식

- **INV-U9-1**: U9는 meaningful domain event만 기록한다.
- **INV-U9-2**: 모든 이벤트와 프로필 접근은 owner-scoped다.
- **INV-U9-3**: U9 실패는 본 기능 실패로 승격하지 않는다.
- **INV-U9-4**: 사용자는 개인화 off, raw log delete, profile reset을 분리해서 실행할 수 있다.
- **INV-U9-5**: U9 v1은 별도 추천 목록과 전체 클릭스트림을 만들지 않는다.

---

## 6. 현재 상태와 다음 절차

1. Q1~Q12는 전부 권장안(A)으로 확정했다.
2. `u9-personalization/functional-design/` 산출물 3개를 생성했다.
3. Functional Design 승인 후 **NFR Requirements**에서 성능, 저장소, 보안, 운영, 테스트 전략을 확정한다.
