# requirement-verification-questions-u10-mypage.md — U10 마이페이지 요구사항 질문지

**단계**: INCEPTION → Requirements Analysis 재진입
**대상 유닛 후보**: U10 My Page
**목적**: 사용자가 선정한 6개 마이페이지 메뉴(ORCID 정보·관심 논문·최근 본 논문·로그인 경로/가입날짜·설정[동의 철회/로그아웃/회원탈퇴]·구독 관리)의 범위와 기존 유닛(U3/U4/U9) 의존성을 확정한다.

## 작성 방법

각 질문의 `[Answer]:` 뒤에 선택지 문자를 입력해 주세요. 선택지가 맞지 않으면 마지막 `X) Other`를 고르고 같은 줄 또는 다음 줄에 원하는 방식을 적어 주세요.

---

## Question 1 — U10의 유닛 성격
U10은 신규 도메인 로직을 갖는 독립 모듈인가, 기존 유닛(U3/U4/U9)의 데이터를 모아 보여주는 **조합형(Composite) 뷰**인가?

A) U10은 주로 **조합형 뷰**다. 관심 논문(U4)·최근 본 논문(U9)·로그인 정보(U3)는 각 유닛 API를 그대로 호출/조립하고, U10 고유 모듈(`backend/modules/mypage/`)은 ORCID 연동·구독 관리·동의/탈퇴 오케스트레이션만 소유한다. (권장)

B) U10이 모든 마이페이지 데이터(관심 논문·최근 본 논문 포함)를 자체 테이블로 복제해 단일 모듈에서 서빙한다.

C) 메뉴별로 각 유닛(U3/U4/U9)에 화면 전용 엔드포인트를 직접 추가하고, U10은 프런트엔드 화면 묶음일 뿐 백엔드 모듈을 따로 두지 않는다.

X) Other (please describe after [Answer]: tag below)

[Answer]: 권장)

## Question 2 — "최근 본 논문"과 U9 의존성
"최근 본 논문 목록"은 U9 Personalization의 `paper_opened` BehaviorEvent와 개념이 일치하지만, **U9는 현재 설계 문서만 있고 코드 구현이 안 되어 있습니다.** 어떻게 진행할까요?

A) U10 착수 전에 **U9 Construction(코드 생성)을 먼저 완료**하고, U10은 U9의 `paper_opened` 이벤트를 조회해 "최근 본" 목록을 만든다. (권장 — 중복 구현 방지)

B) U9 완료를 기다리지 않고, U10 자체에 경량 "최근 조회" 기록(예: U4 history 패턴처럼 `paper_opened` 이벤트만 별도 테이블에 기록)을 만든다. 이후 U9가 구현되면 통합/마이그레이션한다.

C) "최근 본 논문"은 v1 범위에서 제외하고 차기 사이클로 미룬다.

X) Other (please describe after [Answer]: tag below)

[Answer]: 권장)

## Question 3 — "최근 본 논문" 데이터 보관/표시 정책
Q2에서 자체 기록 또는 U9 연동을 택하더라도, 목록의 보관 기간·표시 개수 기준이 필요합니다.

A) 최근 50건 또는 최근 30일 중 먼저 도달하는 기준으로 롤링 보관(U4 `history.py`의 `RETENTION_LIMIT` 패턴과 동일). (권장)

B) 무기한 보관, 사용자가 직접 삭제하기 전까지 유지.

C) 세션 단위(로그아웃 시 초기화)로만 유지.

X) Other (please describe after [Answer]: tag below)

[Answer]: 권장)

## Question 4 — "관심 논문 목록"과 U4 Library 재사용
"관심 논문 목록"은 U4 Library의 `LibraryService`(저장된 논문)와 동일 데이터로 보입니다.

A) U10은 U4 `LibraryService.list()`를 그대로 호출해 마이페이지에 표시한다. 별도 저장소를 만들지 않는다. (권장)

B) "관심 논문"은 U4 라이브러리와 별개 개념(예: 즐겨찾기 vs 저장)으로, 신규 테이블을 추가한다.

X) Other (please describe after [Answer]: tag below)

[Answer]: 권장)

## Question 5 — 소셜로그인 미구현 상태 처리
"로그인 경로(소셜로그인 아이콘 표시)" 메뉴를 요구했지만, 현재 `backend/modules/accounts/`에는 이메일+비밀번호+TOTP만 있고 **소셜로그인(OAuth) 자체가 구현되어 있지 않습니다.**

A) U10 범위에 **소셜로그인(Google/GitHub 등 OAuth) 구현을 U3 확장 작업으로 포함**시킨다. U10은 그 결과(provider 필드)를 표시만 한다. (권장 — 다만 U3 작업 범위가 커짐)

B) 소셜로그인 구현은 별도 유닛/사이클로 분리하고, U10에서는 현재 가능한 "이메일 가입" 표시만 우선 처리한 뒤 추후 provider 필드를 확장한다.

C) 소셜로그인 메뉴 항목 자체를 v1 범위에서 제외한다.

X) Other (please describe after [Answer]: tag below)

[Answer]: 권장)

## Question 6 — ORCID 연동 방식
ORCID는 Public API(인증 없이 공개 레코드 조회)와 OAuth 기반 본인 인증 연결(Member API) 두 방식이 있습니다.

A) **ORCID OAuth로 사용자가 본인 ORCID iD를 계정에 연결**(다른 서비스의 "계정 연동"과 동일 패턴)하고, 연결된 iD로 Public API 레코드를 조회해 표시한다. (권장 — 본인 확인 가능)

B) 사용자가 ORCID iD를 **직접 텍스트로 입력**만 하면, 그 iD로 Public API 공개 레코드를 조회해 표시한다(본인 인증 없음).

C) ORCID 연동은 v1에서 보류하고 메뉴만 노출(빈 상태)한다.

X) Other (please describe after [Answer]: tag below)

[Answer]: X) 소셜 로그인에 ORCID를 추가할거고 사용자가 ORCID로 로그인하지않았다면 노출하지않음

## Question 7 — ORCID로 가져올 정보 범위
"ORCID 무료 API로 받을 수 있는 정보 모두"라고 하셨는데, 구체적으로 어느 섹션까지 표시할까요?

A) 이름·소속(affiliation)·학위·논문/저작물 목록(works)까지 표시한다. (권장 — 연구자 프로필의 핵심)

B) 이름·소속만 표시하고 works(논문 목록)는 제외한다(데이터량/레이트리밋 부담 축소).

C) ORCID record 전체(biography, funding, peer-review 등 모든 섹션)를 가능한 만큼 표시한다.

X) Other (please describe after [Answer]: tag below)

[Answer]: 권장)

## Question 8 — ORCID 데이터 캐시/동기화 정책
ORCID Public API는 외부 호출이므로 매번 실시간 조회하면 지연·레이트리밋 위험이 있습니다.

A) 최초 연결 시 + 사용자가 "새로고침" 버튼을 누를 때만 조회해 짧은 TTL로 캐시(예: 24시간)한다. (권장)

B) 마이페이지 진입마다 항상 실시간으로 ORCID API를 호출한다.

C) 연결 시 1회만 가져오고 이후 자동 갱신 없음(수동 재연결 시에만 갱신).

X) Other (please describe after [Answer]: tag below)

[Answer]: X) account table에 ORCID 관련 컬럼 추가

## Question 9 — ORCID 연동 해제(unlink)
ORCID 연결을 사용자가 해제할 수 있어야 할까요?

A) 설정 메뉴에서 ORCID 연동 해제 가능. 해제 시 캐시된 ORCID 데이터를 즉시 삭제한다. (권장)

B) 연동은 1회성이며 해제 기능은 제공하지 않는다(재연결로 덮어쓰기만 가능).

X) Other (please describe after [Answer]: tag below)

[Answer]: 권장)

## Question 10 — 구독 관리의 성격
"내 구독 관리(가입/해지)"가 유료 결제 구독인지, 무료 알림/토픽 구독인지에 따라 작업 범위가 크게 달라집니다. 레포 전체에 결제(PG)/빌링 코드가 전혀 없는 상태입니다.

A) **유료 결제 구독**이다. PG(예: 토스페이먼츠/포트원 등) 연동, 정기결제, 웹훅 처리가 필요한 별도 큰 작업이므로 U10에서는 "구독 상태 표시 + 해지 버튼"까지만 만들고, 실제 결제 연동은 **별도 유닛(U11 등)으로 분리**한다. (권장)

B) 유료 결제 구독이며, PG 연동까지 U10 범위에 전부 포함한다(작업량 큼 — 별도 일정 필요).

C) 결제가 아니라 **무료 토픽/카테고리 구독**(예: 관심 분야 알림)이다. 이 경우 U2 Discovery의 카테고리 정보를 활용한 단순 on/off 토글에 가깝다.

X) Other (please describe after [Answer]: tag below)

[Answer]: X) 유료 결제 구독은 맞지만 PG, 빌링 등 연동하지않음(하는 척만)

## Question 11 — 구독 해지 시 처리
Q10에서 유료 결제를 선택했다면, 해지 시점 정책이 필요합니다.

A) 해지 신청 시 **결제 주기 종료일까지 유지**되고 그 후 자동 만료(즉시 차단 아님). (권장)

B) 해지 신청 즉시 구독 혜택을 차단한다.

C) 해당 없음(Q10에서 무료 토픽 구독을 선택함).

X) Other (please describe after [Answer]: tag below)

[Answer]: 권장)

## Question 12 — "선택적 동의" 항목 신설
현재 가입 흐름(`signup.py`)에는 선택적 동의 필드가 전혀 없습니다. 어떤 동의 항목을 신설할까요?

A) 마케팅/이메일 수신 동의, 개인화(U9) 데이터 활용 동의 2가지를 신설한다. (권장 — U9 PersonalizationSettings.enabled와 연동 가능)

B) 마케팅 수신 동의 1가지만 신설한다.

C) U9 PersonalizationSettings.enabled 토글만 "동의 철회"로 간주하고, 별도 동의 항목은 신설하지 않는다.

X) Other (please describe after [Answer]: tag below)

[Answer]: X) 야간 푸시 동의만, 마케팅 수신 동의는 하지않을 예정

## Question 13 — 동의 철회의 효과
선택적 동의를 철회하면 어떤 동작이 즉시 일어나야 할까요?

A) 마케팅 동의 철회 → 발송 큐에서 즉시 제외. 개인화 동의 철회 → U9 `PersonalizationSettings.enabled=false`로 전환되어 기존 프로필 비활성화(삭제는 아님). (권장)

B) 동의 철회는 향후 신규 활동에만 적용되고, 이미 발송 예약된 메일이나 기존 프로필에는 영향 없음.

X) Other (please describe after [Answer]: tag below)

[Answer]: B)

## Question 14 — 회원탈퇴 시 데이터 처리
`backend/modules/accounts/`에 탈퇴 로직이 없습니다. 탈퇴 시 라이브러리·검색 이력·개인화 프로필·ORCID 연동 데이터를 어떻게 처리할까요?

A) 계정은 **soft-delete**(상태만 비활성화, 로그인 차단) 처리하고, 연관 데이터(U4 라이브러리/이력, U9 프로필, ORCID 연동)는 **즉시 익명화하거나 N일 후 하드 삭제**하는 배치를 둔다. (권장 — 법적 유예기간 대응 가능)

B) 탈퇴 즉시 계정과 연관 데이터를 모두 **하드 삭제**한다(되돌릴 수 없음).

C) 탈퇴는 로그인만 차단하고 연관 데이터는 무기한 보존한다.

X) Other (please describe after [Answer]: tag below)

[Answer]: X) soft-delete + 연관 데이터는 DB에 백업용 테이블에 저장(5년간 보관), 백업용 테이블은 추후 작업 예정

## Question 15 — 탈퇴 시 진행 중인 구독 처리
Q10에서 유료 구독을 선택했다면, 탈퇴 신청 시점에 활성 구독이 있는 경우 처리 방식이 필요합니다.

A) 활성 구독이 있으면 탈퇴 전 **구독 해지를 먼저 요구**(또는 안내)한다. (권장 — 환불/결제 분쟁 예방)

B) 구독 상태와 무관하게 탈퇴를 즉시 허용하고, 결제는 별도 절차로 정산한다.

C) 해당 없음(무료 서비스 또는 구독 기능 미포함).

X) Other (please describe after [Answer]: tag below)

[Answer]: 권장)

## Question 16 — 신규 백엔드 모듈 위치
U10 고유 로직(ORCID 연동, 구독 오케스트레이션, 동의/탈퇴)은 어디에 둘까요?

A) 신규 `backend/modules/mypage/` 모듈을 만들고, U3/U4/U9는 포트(인터페이스)로 의존한다(U2가 U1을, U7이 U1/U6를 참조하는 기존 패턴과 동일). (권장)

B) 회원탈퇴·동의는 `backend/modules/accounts/`에 추가하고, ORCID·구독은 별도 `mypage` 모듈로 분리한다(기능별 소유권 분산).

C) 별도 모듈 없이 프런트엔드에서 U3/U4/U9 API를 직접 조합하고, 백엔드에는 ORCID/구독용 엔드포인트만 기존 accounts 모듈에 추가한다.

X) Other (please describe after [Answer]: tag below)

[Answer]: 권장)

## Question 17 — v1 출시 범위 (단계적 출시 여부)
6개 메뉴의 작업 난이도가 크게 다릅니다(가입날짜 표시는 즉시 가능, 구독/ORCID는 신규 외부 연동).

A) **1차**: 관심 논문·로그인 정보(이메일만)·가입날짜·로그아웃·회원탈퇴(soft-delete). **2차**: 최근 본 논문(U9 의존), ORCID 연동, 소셜로그인 표시. **3차**: 구독 관리(PG 연동 별도 유닛). (권장 — 의존성 적은 것부터)

B) 6개 메뉴를 한 번에 동시 개발해 단일 릴리즈로 출시한다.

X) Other (please describe after [Answer]: tag below)

[Answer]: 권장)

## Question 18 — 가입날짜 표시 근거 데이터
"가입날짜" 표시는 기존 계정 데이터로 가능한지 확인이 필요합니다.

A) 기존 `accounts` 테이블에 가입 시각 컬럼이 있다고 가정하고 그대로 재사용한다(확인 후 없으면 마이그레이션 추가). (권장)

B) 별도로 가입 시각을 새로 기록하는 컬럼/이벤트를 신설한다.

X) Other (please describe after [Answer]: tag below)

[Answer]: 권장)
