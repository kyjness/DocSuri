# business-logic-model.md — U3 Accounts 비즈니스 로직 및 알고리즘 설계

**단계**: CONSTRUCTION → Functional Design (유닛별 루프, Track 2 첫 유닛) · **유닛**: U3 Accounts · **일자**: 2026-06-16
**근거(SSOT)**: `construction/plans/u3-accounts-functional-design-plan.md` (Q1~Q7 답변 반영)

---

## 1. 공개 셀프 가입 오케스트레이션 (SignupService.register)

새로운 사용자가 시스템에 계정 등록을 요청할 때 수행되는 오케스트레이션 프로세스입니다.

### 1.1. 가입 등록 알고리즘
1. **입력 수신**: `SignupCommand` (이메일, 평문 비밀번호, 요청 컨텍스트)
2. **비밀번호 정책 검증**:
   - `PasswordPolicy.evaluate(password)`를 호출합니다.
   - 비밀번호 길이가 **10자 이상**이며, **영문 대문자, 소문자, 숫자, 특수문자**가 각각 최소 1개 이상 포함되어 있는지 검증합니다 (Q1 답변 반영).
   - 로컬 1만 개 최다 취약 패스워드 블랙리스트를 조회하여 매칭되는 경우 `POLICY_VIOLATION` 에러를 반환하고 중단합니다 (외부 API 호출은 가용성 보장을 위해 배제).
3. **이메일 유일성(중복) 검증**:
   - `CredentialStore`에서 입력 이메일의 계정 존재 여부를 조회합니다.
   - 만약 이미 가입된 이메일인 경우:
     - 중복 회원가입 요청 임계치(단위 시간당 특정 대역/IP)를 검증하고, 초과 시 `SignupAbuseSignal`을 이벤트 버스로 발행합니다 (SEC-11).
     - 보안 상의 사용자 존재 노출을 차단하기 위해 일반화된 성공 결과처럼 응답하거나(비밀번호 재설정 유도), 일반화된 가입 충돌 응답(`EMAIL_TAKEN`)을 반환합니다 (SEC-9/12).
4. **암호학적 해싱 (Argon2id)**:
   - 보안 난수 생성기를 사용하여 최소 16바이트 크기의 독립 솔트(Salt)를 생성합니다.
   - **Argon2id** KDF 파라미터(OWASP 권장 메모리 하드 강도 기준: m=65536 KB, t=3, p=4)를 적용하여 비밀번호를 단방향 해싱합니다 (Q2 답변 반영).
5. **계정 및 자격증명 영속화**:
   - 계정을 **`PENDING`** 상태(이메일 인증 대기)로 설정하여 저장소에 기록합니다 (Q5 답변 반영).
   - 해싱된 결과값(`PasswordHash`)과 해시 매개변수(`HashParameters`)를 `CredentialStore`에 영속화합니다.
6. **이메일 인증 토큰 생성**:
   - 암호학적으로 안전한 임의의 인증 링크 토큰(24시간 유효)을 생성하여 영속화하고, 사용자 이메일로 링크 발송 이벤트를 발행합니다 (Q5).
7. **도메인 이벤트 발행**:
   - `AccountCreated` 이벤트를 이벤트 백본으로 발행합니다 (민감 정보 제외, PII 최소화).
8. **출력**: 성공 시 `AccountId` 반환.

---

## 2. 로그인 및 자격증명 검증 (AuthenticationService.authenticate)

사용자의 자격증명을 확인하고 세션을 수립하는 프로세스입니다.

### 2.1. 인증 처리 알고리즘
1. **입력 수신**: `LoginCommand` (이메일, 평문 비밀번호, 요청 컨텍스트)
2. **자격증명 조회**:
   - `CredentialStore`에서 입력 이메일에 해당하는 해시값 및 해시 매개변수를 조회합니다.
   - **타이밍 공격 방어 (Constant-Time)**: 만약 일치하는 계정이 존재하지 않는 경우, 임의의 더미 해시값과 비교 연산을 동일한 시간 동안 실행하여 계정 존재 여부가 외부에서 유추되지 않도록 처리합니다 (SEC-12).
3. **자격증명 비교**:
   - 조회한 파라미터(Argon2id)로 입력 비밀번호를 해싱하여 데이터베이스에 저장된 값과 상수시간 내에 비교합니다 (`verifyCredential`).
4. **결과 처리**:
   - **검증 실패 시**:
     - 대상 계정의 실패 횟수(`FailureCount`)를 1 증가시킵니다.
     - `AuthFailureSignal`을 발행하여 보안 관측 시스템에 전달합니다 (SEC-12).
     - **점진적 시간 지연 (Exponential Backoff Delay)**: 실패 횟수가 3회 이상일 경우, `2^(실패 횟수 - 3)` 초 동안 스레드를 인위적으로 대기(delay)한 후 에러를 반환합니다. 10회 연속 실패 시 다음 로그인 요청에 프런트엔드 CAPTCHA 토큰 검증 필드를 필수로 설정하도록 클라이언트에 플래그를 전달합니다 (Q4 답변 반영 - DoS 방어 정책).
     - 일반화된 인증 에러(`INVALID_CREDENTIALS`, 401)를 반환합니다.
   - **검증 성공 시**:
     - 계정의 `status`가 **`ACTIVE`** 인지 확인합니다. 만약 `PENDING`이거나 `LOCKED`인 경우, 인증을 거부하고 일반화된 오류를 반환합니다 (Q5).
     - 로그인 실패 횟수를 0으로 리셋합니다.
     - **해시 자동 업그레이드 (Rehash)**: 저장된 해시 파라미터가 최신 권장 강도보다 낮을 경우, 성공한 현재 평문 비밀번호를 활용하여 백그라운드에서 최신 Argon2id 파라미터로 재해싱(`rehash`)하여 업데이트합니다 (SEC-12).
     - `SessionManager.issue(principal)`를 호출하여 신규 세션을 생성합니다.
5. **출력**: `IssuedSession` 반환 (세션 토큰 및 쿠키 메타데이터).

---

## 3. 세션 수명주기 관리 (SessionManager & SessionVerifier)

요청별 세션 검증 및 Sliding Expiration을 구현합니다.

### 3.1. 세션 발급 (`issue`)
1. 사용자 식별자 및 역할을 포함하는 `Principal`을 정의합니다.
2. 32바이트의 보안 난수로 서버측 세션 핸들(`SessionHandle`)을 생성합니다.
3. 세션 절대 만료 일시(`expiresAt = 현재 시각 + 30일`)와 Sliding 만료 일시(`expiresAtLimit = 현재 시각 + 2시간`)를 설정합니다.
4. `SessionRecord`를 `SessionStore`에 영속화합니다.

### 3.2. 요청별 토큰 검증 및 Sliding Expiration (`verify`)
1. **토큰 수신**: HTTP 요청 헤더 또는 보안 쿠키로부터 `SessionToken`을 획득합니다 (SessionVerifier).
2. **세션 로드**: `SessionStore.load(sessionHandle)`를 호출하여 세션 레코드를 불러옵니다.
3. **만료 검증 (Q3 답변 반영)**:
   - **Sliding 만료 검사**: `현재 시각 > lastActiveAt + 2시간`인 경우 만료 판정합니다.
   - **절대 만료 검사**: `현재 시각 > expiresAt (최초 생성 + 30일)`인 경우 만료 판정합니다.
   - 만료되었거나 세션 레코드가 존재하지 않는 경우 `SessionError.EXPIRED`를 반환하고, 저장소에서 해당 세션을 즉시 삭제하여 무효화합니다 (Fail-Closed, US-A2).
4. **활성 시각 갱신 (Sliding)**:
   - 세션이 유효한 경우, `lastActiveAt`을 `현재 시각`으로 즉시 업데이트하고 `SessionStore`에 다시 저장합니다.
5. **출력**: `Principal`을 반환하여 다운스트림의 보안 컨텍스트에 주입합니다.

---

## 4. 객체 단위 소유권 인가 (AuthorizationGuard)

### 4.1. Stateless 소유권 검증 알고리즘 (`authorize`)
U3의 `AuthorizationGuard`는 타 도메인의 데이터 모델에 종속되지 않도록 완전한 **Stateless 인가 결정**을 내립니다 (Q6 답변 반영).
1. **입력**: `principal: Principal`, `action: Action`, `resourceOwnerId: UserId`
2. **판정 흐름**:
   - `principal`이 존재하지 않거나(비인증 요청) `principal.userId`가 비어있으면 즉시 **`DENY`**를 반환합니다.
   - 요청된 `action`이 사용자 데이터 관리(`READ`, `WRITE`, `DELETE`, `RERUN`)에 해당하는 경우:
     - `principal.userId`와 전달받은 `resourceOwnerId`를 일치 비교합니다.
     - 일치하면 **`ALLOW`**, 일치하지 않으면 **`DENY`**를 반환합니다.
   - 기본적으로 매칭되지 않는 모든 인가 시도는 **`DENY`**로 수렴합니다 (기본 거부 정책 - SEC-8).

### 4.2. 관리자 권한 및 MFA 검증 (`authorizeAdmin`)
1. **입력**: `principal: Principal`, `action: AdminAction`, `mfaContext: MfaContext`
2. **판정 흐름**:
   - `principal.role`이 `ADMIN`이 아니면 즉시 **`DENY`**를 반환합니다 (Fail-Closed).
   - `mfaContext.mfaVerified`가 `false`이면(MFA 완료되지 않음) **`DENY`**를 반환합니다 (Q7 답변 반영 - 관리자 기능 보호).
   - 두 조건이 모두 충족되면 **`ALLOW`**를 반환합니다.

---

## 5. 비밀번호 재설정 (PasswordResetService) — FR-26 / BR-A8 *(2026-06-24)*

### 5.1. 재설정 요청 (`requestReset`)
1. **입력**: `email`, 요청 컨텍스트. 요청에 **레이트 리밋** 적용(SEC-11).
2. 이메일 정규화(trim+lowercase) 후 계정 조회. 존재/상태와 **무관하게 항상 동일한 일반 응답**을 반환한다(계정 열거 방지, SEC-BR-2).
3. 대상이 활성 계정이면: 암호학적 난수 토큰 생성 → **해시만 저장**(`PasswordResetToken`, `expiresAt = 현재+30분`) → 평문 토큰 링크를 **Resend**로 발송(평문·토큰 비로깅, SEC-BR-1).

### 5.2. 재설정 확정 (`confirmReset`)
1. **입력**: `token`(평문), `newPassword`. 토큰을 해시해 조회.
2. 토큰이 없음·만료·이미 사용됨이면 **거부**(재요청 안내).
3. `newPassword`를 **BR-A1 정책 재검증** → Argon2id 해싱 → `CredentialStore` 갱신.
4. 토큰 `usedAt` 설정(단일 사용) + **해당 계정의 전 세션 무효화**(SessionStore에서 `userId`의 모든 세션 삭제).

---

## 6. 소셜 로그인 OIDC (SocialLoginService) — FR-27 / BR-A9 *(2026-06-24)*

### 6.1. 인가 시작 (`start`)
1. `provider = GOOGLE`. **`state`(CSRF)·`nonce`(replay)** 를 생성·서버측 바인딩 후 프로바이더 authorization endpoint로 리다이렉트.

### 6.2. 콜백 처리 (`callback`)
1. **입력**: `code`, `state`. **`state` 일치 검증**(불일치 시 거부 — CSRF).
2. `code`↔토큰 교환 → `id_token` 서명·`nonce`·`aud`·`iss` 검증.
3. 클레임에서 `email`·`email_verified`·`sub` 추출. **`email_verified=false`면 자동 연결 거부**(명시적 에러).
4. `(provider, sub)`로 `SocialIdentity` 조회 — 있으면 연결된 계정 사용.
5. 없으면 정규화 이메일로 계정 조회 — 있고 **사용 가능한 비밀번호 자격증명이 없으면** `SocialIdentity` 자동 연결; 있고 **비밀번호 계정이면 자동 병합 금지 → 명시적 연결 단계**(현 비밀번호 입력/소유 확인) 요구(**H1 pre-hijacking 방어**). 계정이 없으면 **`ACTIVE` 신규 계정 생성**(role=`USER`) + `SocialIdentity` 연결.
6. `SessionManager.issue(principal)` → 비밀번호 로그인과 **동일한 세션 쿠키** 발급.

---

## 7. 계정 자가 관리 (AccountManagementService) — FR-28 / BR-A10 *(2026-06-24)*

### 7.1. 비밀번호 변경 (`changePassword`) — 로그인 필수
1. **현재 비밀번호 재인증**(`verifyCredential`) 실패 시 거부.
2. `newPassword` BR-A1 검증 → Argon2id 해싱 → 갱신 → **전 세션 무효화**(현 세션 재발급 옵션).

### 7.2. 이메일 변경 (`requestEmailChange` / `confirmEmailChange`) — BR-A10
1. `newEmail` 중복 검사(존재 비노출 거부) → `EmailChangeRequest` 생성(토큰 해시·만료) → `newEmail`로 검증 링크 발송 + **현재(기존) 이메일로 변경 시도 알림 발송(M2 — 탈취 탐지)**.
2. 검증 확정 시에만 `Account.email`을 `newEmail`로 반영(그 전까지 현 이메일이 로그인 식별자).

---

## 8. 계정 삭제 — 소프트 삭제 + 유예 파기 (AccountDeletionService) — FR-28 / BR-A11 *(2026-06-24)*

### 8.1. 삭제 요청 (`requestDeletion`) — 로그인 필수
1. `Account.status = DEACTIVATED`, `AccountDeletion` 레코드(`purgeAfter = 현재+N일`) 생성. **전 세션 즉시 무효화**(로그인 차단). 감사 로그 기록(SEC-14). **이 시점엔 owner-scoped 데이터를 보존**(복구 가능) — `AccountDeleted` **미발행**(H2).
2. 유예 동안 소유자는 **재활성화(복구)** 가능(M1); 동일 이메일 신규 가입 요청은 본인 확인 후 **재활성화 경로**로 처리(거부 아님).

### 8.2. 유예 파기 잡 (`purgeJob`) — 비동기
1. `purgeAfter` 경과한 `DEACTIVATED` 계정을 선별 → **`AccountDeleted` 이벤트 발행(H2 — 이 시점에 발행)** → U4/U2/U11이 구독해 각자 owner-scoped 데이터 파기(직접 호출 아님 → DAG 비순환·멱등·DLQ). 이어 계정·자격증명·소셜 신원·잔여 토큰을 영구 삭제(`PURGED`). 멱등(이미 파기 시 무시).

---

## 9. 인증 입력 견고화 (공개 인증 엔드포인트) — FR-29 / BR-A12 *(2026-06-24)*
- login/signup/password-reset 등 **공개 인증 입력 모델은 알 수 없는 추가 필드를 무시**(거부 아님)하고 **필수 필드만 강제**한다 → 프런트/백 버전 스큐가 인증을 전면 차단하지 못한다. (인가·소유권 경로의 엄격 검증 SEC-5/8은 불변.)
- 컨트롤러는 4xx/422를 **구체·비기술적 메시지**로 매핑하고, 프런트는 빈 화면·원시 JSON·모호한 generic 대신 명확 메시지를 표면화하며 인증 메일 재발송 경로를 제공한다(SEC-15·NFR-R1).
