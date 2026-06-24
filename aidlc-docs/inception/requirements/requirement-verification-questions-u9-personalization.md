# requirement-verification-questions-u9-personalization.md — U9 개인화 / 행동 로그 요구사항 질문지

**단계**: INCEPTION → Requirements Analysis 재진입  
**대상 유닛 후보**: U9 Personalization / Behavior Intelligence  
**목적**: 사용자 행동 로그를 수집·분석하여 검색, 추천, 요약/번역 기본값, 용어 선호를 개인화하는 기능의 요구사항을 확정한다.  

## 작성 방법

각 질문의 `[Answer]:` 뒤에 선택지 문자를 입력해 주세요. 선택지가 맞지 않으면 마지막 `X) Other`를 고르고 같은 줄 또는 다음 줄에 원하는 방식을 적어 주세요.

---

## Question 1
U9 개인화 기능의 v1 범위를 어디까지로 둘까요?

A) 행동 로그 저장 + 간단한 관심사 프로필 집계 + 검색 rerank/요약 기본값 반영까지 포함한다. (권장)

B) 행동 로그 저장과 프로필 집계까지만 포함하고, 실제 개인화 적용은 다음 사이클로 미룬다.

C) 검색 rerank 없이 추천 논문 목록만 제공한다.

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 2
v1에서 기록할 행동 이벤트는 어디까지 포함할까요?

A) 검색 실행, 논문 상세 조회, 라이브러리 저장/해제, 요약/번역 요청, 출처 보기 클릭, 용어집 수정만 기록한다. (권장)

B) A에 더해 탭 전환, 정렬 변경, 필터 변경 같은 주요 UI 조작도 기록한다.

C) 논문 상세 조회와 라이브러리 저장/해제만 기록한다.

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 3
클릭 로그는 어느 수준으로 수집할까요?

A) 도메인 의미가 있는 클릭만 기록한다. 예: 출처 보기, 논문 저장, 요약 요청. (권장)

B) UX 분석을 위해 주요 버튼 클릭 전부를 기록한다.

C) 클릭 로그는 수집하지 않고 서버 상태 변화 이벤트만 기록한다.

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 4
행동 이벤트는 어디에서 확정 기록할까요?

A) 백엔드에서 API 성공 후 기록한다. 프론트 전용 행동만 별도 `POST /behavior-events`로 보낸다. (권장)

B) 프론트에서 모든 행동을 즉시 전송하고 백엔드는 저장만 한다.

C) 기존 U4/U7/U2 서비스 내부에서만 기록하고 별도 behavior API는 만들지 않는다.

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 5
라이브러리 저장 해제 같은 상태 변경 이벤트는 어떤 기준으로 기록할까요?

A) 삭제 대상 row를 owner 검증으로 읽고, 실제 삭제 성공 후 `library_removed`를 기록한다. arXiv ID는 삭제 전에 확보한다. (권장)

B) 프론트에서 저장 해제 버튼 클릭 즉시 `library_removed`를 기록한다.

C) 저장 해제는 개인화 신호로 쓰지 않고 기록하지 않는다.

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 6
행동 이벤트 전달 방식은 어떻게 할까요?

A) 동기 API 성공 경로에서 RDS에 짧게 기록하고, 실패해도 사용자 응답은 성공시킨다. (권장)

B) EventBridge/SQS 비동기 이벤트 백본으로만 기록한다.

C) CloudWatch 로그에만 남기고 RDS 사용자 이벤트 테이블은 만들지 않는다.

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 7
행동 이벤트 저장소는 어떤 형태가 좋을까요?

A) 기존 RDS에 `user_behavior_events`와 `user_interest_profile` 테이블을 추가한다. (권장)

B) S3에 append-only JSONL로 저장하고 배치 분석한다.

C) Redis에 최근 행동만 TTL로 저장한다.

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 8
개인화 이벤트 원본(raw event)의 보관 기간은 어떻게 할까요?

A) 90일 보관 후 삭제하고, 집계 프로필만 유지한다. (권장)

B) 30일 보관 후 삭제한다.

C) 사용자가 삭제하기 전까지 무기한 보관한다.

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 9
사용자에게 어떤 개인정보 제어를 제공할까요?

A) 개인화 켜기/끄기, 행동 로그 삭제, 개인화 프로필 초기화를 제공한다. (권장)

B) 행동 로그 삭제만 제공한다.

C) v1에서는 내부 기능으로만 운영하고 사용자 제어는 다음 사이클로 미룬다.

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 10
개인화 프로필은 언제 갱신할까요?

A) 이벤트 저장 후 가벼운 온디맨드/배치 집계로 갱신한다. 실시간 ML 파이프라인은 만들지 않는다. (권장)

B) 매 이벤트마다 즉시 프로필을 동기 갱신한다.

C) 하루 1회 배치로만 갱신한다.

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 11
개인화 프로필에는 어떤 신호를 포함할까요?

A) 관심 arXiv 카테고리, 키워드 가중치, 저장/반복 조회 논문, 요약 persona 선호, 번역 scope 선호, 용어집 버전을 포함한다. (권장)

B) 관심 카테고리와 키워드 가중치만 포함한다.

C) 저장 논문과 검색 이력만 포함한다.

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 12
검색 결과 개인화는 어떤 방식으로 적용할까요?

A) 기존 관련도 점수를 유지하고, 사용자 관심사로 작은 boost만 주는 rerank로 시작한다. (권장)

B) 사용자 관심사 기반 추천 점수를 강하게 반영해 결과 순서를 크게 바꾼다.

C) 검색 결과에는 개인화를 적용하지 않고 별도 추천 영역에만 사용한다.

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 13
추천 기능은 v1에 포함할까요?

A) "최근 관심 주제 기반 추천" 정도의 간단한 목록을 포함한다.

B) 추천은 제외하고 검색 rerank와 요약/번역 기본값만 개인화한다. (권장)

C) 라이브러리 저장 논문 기반 관련 논문 추천까지 포함한다.

X) Other (please describe after [Answer]: tag below)

[Answer]: B

## Question 14
요약/번역 개인화는 어디까지 자동화할까요?

A) 최근 선택을 기본값으로 기억하되 사용자가 매번 바꿀 수 있게 한다. 예: expert/beginner, 초록/전문 번역. (권장)

B) 프로필이 자동으로 persona와 번역 scope를 선택하고 사용자는 결과만 본다.

C) U7 기존 개인 용어집만 사용하고 요약/번역 기본값은 개인화하지 않는다.

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 15
개인화 적용 결과를 사용자에게 어떻게 설명할까요?

A) 과한 설명 없이 "내 관심 주제 반영" 정도의 짧은 표시와 개인화 끄기 토글을 제공한다. (권장)

B) 각 결과마다 어떤 행동 때문에 boost되었는지 상세 설명한다.

C) 개인화 적용 여부를 UI에 표시하지 않는다.

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 16
개인화 저장/분석 실패 시 사용자 경험은 어떻게 할까요?

A) 핵심 기능은 계속 동작하고, 개인화만 비활성/기본값으로 저하한다. 사용자에게 필요할 때만 짧게 표시한다. (권장)

B) 개인화 실패를 모든 검색/요약 요청 실패로 처리한다.

C) 실패를 사용자에게 표시하지 않고 내부 로그만 남긴다.

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 17
U9 성공 기준은 무엇으로 잡을까요?

A) 재방문 검색 클릭률, 저장률, 요약/번역 재사용률, 개인화 끄기 비율, 검색 rerank 품질 평가를 추적한다. (권장)

B) 저장률과 재방문율만 추적한다.

C) 정량 성공 기준 없이 기능 완성 여부만 본다.

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 18
Security Baseline을 U9에도 어떻게 적용할까요?

A) 기존 프로젝트 설정대로 모든 Security 규칙을 차단성으로 적용한다. 행동 로그는 사용자 데이터로 보고 owner-scoped 접근, 암호화, 삭제/초기화, PII 최소화를 요구한다. (권장)

B) U9에는 Security 규칙을 완화 적용한다.

C) U9에는 Security 확장을 적용하지 않는다.

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 19
Resiliency Baseline을 U9에도 어떻게 적용할까요?

A) 기존 프로젝트 설정대로 적용하되, 개인화는 비핵심 의존성으로 분류해 실패 시 기본 검색/요약으로 저하한다. (권장)

B) U9를 핵심 경로로 분류해 개인화 실패도 주요 장애로 본다.

C) U9에는 Resiliency 확장을 적용하지 않는다.

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 20
Property-Based Testing 적용 범위는 어떻게 할까요?

A) 기존 Partial 모드를 유지하고, 이벤트 DTO 라운드트립·프로필 집계 불변식·dedupe key 안정성에 PBT를 적용한다. (권장)

B) U9는 상태/집계 로직이 있으므로 PBT Full 모드로 올린다.

C) U9에는 PBT를 적용하지 않는다.

X) Other (please describe after [Answer]: tag below)

[Answer]: A
