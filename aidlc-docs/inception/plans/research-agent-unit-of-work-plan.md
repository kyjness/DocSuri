# 연구 에이전트 유닛 분해 계획

**단계**: INCEPTION → Units Generation (Part 1: 계획)
**일자**: 2026-06-24
**입력**: `requirements.md`(FR-22~25, NFR-P5, NFR-C1 Agent 보강, QT-8, §12 Agent 카브아웃, C-2 경계), `stories.md`(에픽 9 US-RA1~8), 기존 `unit-of-work*.md`(U1~U9)

본 계획은 연구 에이전트를 기존 유닛 구조에 편입하는 방법을 정의한다. **HOW(코퍼스 확장 방식·외부 API·근거표 컬럼·LLM 모델·멀티턴·UI·캐시 키)는 Construction 라운드로 이월**한다.

> **상태 (2026-06-24)**: UQ1~5 **전부 권장안(A) 승인**(팀). **UQ2=A → 유닛 번호 U11**(U10=마이페이지 타 팀원 작업·머지 대기 가정). Part 2 실행 → `unit-of-work.md`·`-dependency.md`·`-story-map.md` 개정.

---

## 분해 질문

## UQ1 — 유닛 경계
연구 에이전트를 어떤 개발 단위로 둘까? *(요구사항 Q2=A에서 신규 유닛으로 결정됨 — 확인)*

A) **별도 신규 유닛 Research Agent API 모듈(권장)** — `backend/modules/research_agent/`가 대화 세션·다논문 근거 정리·(차기)novelty 비교를 소유하고, U2 검색·U7 doc-model/근거화·U8 외부 API 캐시·U9 개인화 신호를 **소비**한다.

B) U2 Discovery 확장 — 검색의 대화형 모드로 흡수(범위·소유권이 U2 밖으로 샘).

C) U7 Summarization 확장 — 요약의 다논문 버전으로 흡수(요약 단일 논문 경계와 충돌).

X) 기타 (아래 [Answer]: A 태그 뒤에 기술)

[Answer]: A

## UQ2 — 유닛 번호 배정 — **핵심**
**현황(팀 확인)**: 마이페이지가 **U10으로 이미 구현 중**(다른 팀원 작업, 커밋/푸시 전이라 `unit-of-work.md`엔 아직 미반영). 따라서 **U10=마이페이지를 가정**하고 시작한다. 로드맵 예정: 개인화 추천·트렌드/알림·구독제(번호 미정). 본 유닛 번호는?

A) **U11로 배정(권장)** — AI-DLC 관례상 번호는 *정식 생성 시점*에 부여한다(U7/U8/U9도 추가 시점에 받음, 사전 예약 없음). U10=마이페이지가 점유했으니 **지금 정식 생성하는 본 유닛 = 다음 번호 U11**. 예정 유닛(개인화추천 등)은 정식 spec 시 U12+ 부여. `unit-of-work.md`에 "U10=마이페이지(타 팀원, 머지 대기)" 자리만 표시.

B) 예정 로드맵 유닛 뒤로 배정(개인화추천=U11·트렌드=U12·구독제=U13 가정 → 본 유닛 U14) — 로드맵 순서를 번호에 반영하나, 미생성 유닛 번호를 선점해 변동 위험.

C) 번호 미확정(U-RA, TBD).

X) 기타 (아래 [Answer]: A 태그 뒤에 기술 — 팀 로드맵 번호를 알려주면 그대로 배정)

[Answer]: A

## UQ3 — 배포 단위
연구 에이전트 런타임은 어디에 배치할까?

A) **기존 API 서비스 ①에 모듈로 추가 + 긴 분석은 비동기 잡(권장)** — U2/U3/U4/U7/U8/U9와 같은 배포 단위에 넣고, 다논문 교차확인 같은 장시간 작업은 U7 초장문 잡 큐/워커 패턴을 재사용(NFR-P5). 별도 상시 서비스는 만들지 않는다.

B) 별도 에이전트 워커/서비스 — 확장성은 좋지만 v1(모드 A) 범위엔 과하다.

C) 프런트엔드 로컬 상태 중심 — 서버 세션 영속·근거화·비용 게이트 요구와 맞지 않는다.

X) 기타 (아래 [Answer]: A 태그 뒤에 기술)

[Answer]: A

## UQ4 — 의존성 연동 방식
기존 유닛/공유 계약을 어떻게 소비할까?

A) **`shared/ports` lib 경유 — U6 근거화 `enforce`·CostGuard 재사용 + U2 검색·U7 doc-model capability 소비, 코드 DAG 비순환 유지(권장)** — U7/U8와 동일 패턴(코드 순환 없음). U9 개인화 신호는 비차단 소비.

B) 각 유닛 직접 호출 — 결합도가 올라가고 순환 위험.

C) 이벤트 백본만 — 동기 근거 정리 응답 경로와 맞지 않는다.

X) 기타 (아래 [Answer]: A 태그 뒤에 기술)

[Answer]: A

## UQ5 — 스토리 소유권
US-RA1~8의 Owner를 어떻게 배정할까?

A) **US-RA1~6·RA8 Owner=Research Agent, US-RA7 Owner=U6 기여=Research Agent(권장)** — 제품 기능은 신규 유닛, 비용 게이트/근거화 운영 관측성은 U6 단일 권위에 둔다(U7 US-S6·U9 US-P7과 동일 패턴). US-RA8(novelty)은 Owner=Research Agent이나 **다음 사이클 구현**으로 표시.

B) US-RA3 근거형성은 U7 Owner — 근거화 재사용엔 가까우나 다논문/세션 소유권이 분산된다.

C) 전부 Research Agent Owner — 운영 관측성 단일 권위(U6)가 약해진다.

X) 기타 (아래 [Answer]: A 태그 뒤에 기술)

[Answer]: A

---

## Part 2 실행 체크리스트 *(계획 승인 후 실행)*
- [x] `application-design/unit-of-work.md`에 Research Agent 유닛 정의 추가(번호=UQ2 결정 반영) + 주석(v1=모드 A·모드 B 차기·추출 경계·HOW 이월).
- [x] API 배포 단위와 코드 조직 전략에 `backend/modules/research_agent/` 추가 + 긴 분석 비동기 잡 옵션 표기.
- [x] `application-design/unit-of-work-dependency.md`에 Research Agent 행/열 추가 — Agent→U6(`enforce`/CostGuard, shared/ports)·Agent→U2(검색)·Agent→U7(doc-model/근거화)·Agent→U8(외부 API 캐시·차기)·Agent→U9(개인화 신호, 비차단) 정리, 코드 DAG 비순환 검증, 근거형성 ASCII 흐름.
- [x] `application-design/unit-of-work-story-map.md`에 US-RA1~8 매핑(Owner=UQ5 결정) 추가.
- [x] 전체 스토리 수를 48개로 갱신하고 미할당 0 검증.
- [x] 유닛 수·배포 단위 갱신(신규 유닛 1개 추가, 배포 단위 ① API).
- [x] **공유 계약(원본 UQ5 참고)**: 신규 DTO(연구 세션·근거 정리·novelty 비교)는 `shared/` 단일 소유로 두되, 스키마 상세는 Construction Functional Design 이월임을 명시(지금은 소유 위치만 고정).

## 확장 규칙 준수 요약
- **Security Baseline**: 적용. Agent는 owner-scoped 세션·결과·첨부, 외부 데이터 출력 콘텐츠 삽입 방어, 외부 API SSRF·남용 방어를 유지한다.
- **Resiliency Baseline**: 적용. Agent 실패는 U2 검색 등 본 기능을 막지 않는 비차단 저하로 둔다(RES-9).
- **Property-Based Testing Partial**: 적용. 근거표/비교 DTO 라운드트립·세션 불변식을 QT-8 Construction 검증 대상으로 넘긴다.
