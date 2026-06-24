# U9 개인화 유닛 분해 계획

**단계**: INCEPTION -> Units Generation (Part 1: 계획)  
**일자**: 2026-06-23  
**입력**: `requirements.md`(FR-18, FR-19, FR-20, NFR-P4, QT-7), `stories.md`(US-P1..P7), 기존 `unit-of-work*.md`

본 계획은 U9 Personalization / Behavior Intelligence를 기존 유닛 구조에 편입하는 방법을 정의한다. 아래 질문에 답하거나 **"전부 권장안으로 진행"**이라고 승인하면 Part 2에서 `unit-of-work.md`, `unit-of-work-dependency.md`, `unit-of-work-story-map.md`를 개정한다.

---

## 분해 질문

## UQ1 - 유닛 경계
U9를 어떤 개발 단위로 둘까?

A) **별도 U9 Personalization API 모듈(권장)** - 행동 이벤트 기록, 관심 프로필 집계, 개인화 설정/삭제 API를 `backend/modules/personalization/`이 소유하고 U2/U7/U4/U5는 얇게 연동한다.

B) U6 Reliability/Ops에 흡수 - 관측/로그 성격은 맞지만 사용자 개인화 도메인과 개인정보 제어가 운영 유닛에 섞인다.

C) U2 Discovery에 흡수 - 검색 개인화는 단순하지만 요약/번역/라이브러리 신호와 사용자 제어가 U2 밖으로 샌다.

X) 기타 (아래 [Answer]: 태그 뒤에 기술)

[Answer]: A

## UQ2 - 배포 단위
U9 런타임은 어디에 배치할까?

A) **기존 API 서비스에 모듈로 추가(권장)** - U2/U3/U4/U7/U8과 같은 배포 단위 ① API에 넣고, 별도 서비스는 만들지 않는다.

B) 별도 개인화 워커/서비스 - 확장성은 좋지만 v1의 집계와 API 범위에는 과하다.

C) 프런트엔드 로컬 상태 중심 - 서버 프로필/삭제 제어 요구와 맞지 않는다.

X) 기타 (아래 [Answer]: 태그 뒤에 기술)

[Answer]: A

## UQ3 - 이벤트 기록 연동 방식
기존 기능에서 U9 행동 이벤트를 어떻게 기록할까?

A) **각 성공 경로에서 U9 event recorder를 비차단 호출(권장)** - U2/U4/U7/U5 source-anchor 액션이 성공한 뒤 U9에 기록하고, 실패해도 본 기능을 막지 않는다.

B) 모든 클릭을 프런트엔드 SDK로 전송 - 전체 클릭스트림 제외 결정과 어긋난다.

C) DB 트리거 중심 - 앱 의미 이벤트 구분이 어렵고 source-anchor 같은 프런트 이벤트를 놓친다.

X) 기타 (아래 [Answer]: 태그 뒤에 기술)

[Answer]: A

## UQ4 - 집계 책임
관심 프로필 집계는 어디가 소유할까?

A) **U9가 원시 이벤트와 집계 프로필을 모두 소유(권장)** - `user_behavior_events`와 `user_interest_profile`의 schema/집계/삭제를 한곳에서 관리한다.

B) 이벤트는 U6, 프로필은 U9 - 저장 책임이 갈라져 삭제/초기화 경계가 복잡해진다.

C) 각 기능 유닛이 자기 프로필 조각을 소유 - 빠르게 분산되고 추적성이 떨어진다.

X) 기타 (아래 [Answer]: 태그 뒤에 기술)

[Answer]: A

## UQ5 - 스토리 소유권
US-P1..P7의 Owner를 어떻게 배정할까?

A) **US-P1..P6 Owner=U9, US-P7 Owner=U6 기여=U9(권장)** - 제품 기능은 U9, 운영 관측성/저하는 U6 단일 권위에 둔다.

B) US-P4 검색 개인화는 U2 Owner, US-P5 요약 개인화는 U7 Owner - 사용자 가치는 가까우나 프로필/제어 추적성이 분산된다.

C) 전부 U9 Owner - 운영 관측성 단일 권위(U6)가 약해진다.

X) 기타 (아래 [Answer]: 태그 뒤에 기술)

[Answer]: A

---

## Part 2 실행 체크리스트
- [x] `application-design/unit-of-work.md`에 U9 Personalization 정의 추가.
- [x] API 배포 단위와 코드 조직 전략에 `backend/modules/personalization/` 추가.
- [x] U9 주석에 v1 제외 범위와 비차단 개인화 경계를 명시.
- [x] `application-design/unit-of-work-dependency.md`에 U9 행/열 추가.
- [x] U2/U4/U7/U5 -> U9 이벤트 기록 의존성과 U9 -> U3/U6/shared 의존성 정리.
- [x] 비순환 검증과 개인화 이벤트 흐름을 갱신.
- [x] `application-design/unit-of-work-story-map.md`에 US-P1..P7 매핑 추가.
- [x] 전체 스토리 수를 40개로 갱신하고 미할당 0을 검증.

## 확장 규칙 준수 요약
- **Security Baseline**: 적용. U9는 사용자별 행동 데이터와 삭제/초기화 제어를 소유하므로 owner-scoped 저장과 최소 수집 경계를 유지한다.
- **Resiliency Baseline**: 적용. U9 실패는 U2/U7/U4 본 기능을 막지 않는 비차단 의존성으로 둔다.
- **Property-Based Testing Partial**: 적용. QT-7의 이벤트 DTO roundtrip, 프로필 집계 불변식, 중복 이벤트 안정성을 U9 Construction에서 검증 대상으로 넘긴다.
