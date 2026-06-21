# U3 Accounts — 파이프라인 상세 (로그인·세션)

> 학습용 메모. **커밋하지 않는다.** 근거: `backend/modules/accounts/` 실제 코드.
> 형식: 각 단계를 **[받음] → [함] → [내보냄]** + "어디서/어떻게"(실물)까지.
> 먼저 `00-project-overview.md`(포트·어댑터·배선) 읽었다고 가정. 이 유닛은 **FastAPI async**.

---

## 0. 이 유닛이 하는 일 / 코드 구성

**누가 접속했는지**를 책임진다 — 회원가입·로그인·세션·로그아웃·관리자 2단계 인증(MFA). 다른 유닛(U2·U4)은 "이 요청의 주인이 누구인가(principal)"를 U3가 만들어준 세션으로 안다.

```
accounts/
├── controller.py            ← FastAPI 라우터 (/auth/*). HTTP ↔ 서비스 연결
├── services/
│   ├── auth.py              ← ★로그인 핵심 (자격증명 비교·방어·세션 발급)
│   ├── session_manager.py   ← 세션 발급/검증/만료 (Redis)
│   ├── signup.py            ← 회원가입
│   └── totp.py              ← 관리자 2단계 인증(TOTP)
├── password.py              ← 비밀번호 해싱(Argon2id) + 정책 검사
├── guard.py                 ← AuthorizationGuard (인가 단일 권위 — U4가 갖다 씀)
├── repository/
│   ├── credential.py        ← 계정 저장소 (PostgreSQL)
│   └── session.py           ← 세션 저장소 (Redis)
└── integrations/
    ├── recaptcha.py         ← 봇 방지(reCAPTCHA)
    └── email.py             ← 가입 인증 메일(SES)
```

**핵심 데이터 저장 두 곳** (이게 U3 이해의 절반):
- **PostgreSQL** = 계정(이메일·비밀번호 해시·역할·실패 횟수·상태). 영구.
- **Redis** = 세션(로그인 후 발급되는 임시 출입증). 만료됨.

---

## 진입: 로그인 요청 — `controller.py` `POST /auth/login`

**[받음]** `{ email, password }` (+ 선택적 헤더 `X-Recaptcha-Token`).
**[함]** `auth_svc.authenticate(email, password, recaptcha_token)` 호출 → 성공하면 세션 핸들(토큰)을 받아 **쿠키로** 심는다.
**[내보냄]** 성공: `Set-Cookie: session_id=...` + body는 `{status, message}`뿐. 실패: `401`.

```python
session_handle = await auth_svc.authenticate(email, password, recaptcha_token)
db.commit()
response.set_cookie("session_id", session_handle,
    httponly=True, secure=True, samesite="lax", max_age=30*24*60*60)  # 30일
return {"status": "success", "message": "로그인에 성공했습니다."}
```

> ★SEC-12: **토큰은 절대 body에 안 싣는다.** `httpOnly` 쿠키로만 → 브라우저 JS가 못 읽음(XSS로도 탈취 불가). `secure`=HTTPS만, `samesite=lax`=CSRF 완화.

---

## 로그인 핵심 — `services/auth.py` `authenticate()`

`SearchOrchestrationService`처럼 한 메서드가 단계를 순서대로 밟는다.

### ① 계정 조회
**[함]** `self._repo.get_by_email(email)` → **PostgreSQL**에서 계정 1건. 없으면 `account=None`(여기서 바로 안 끊는다 — 아래 ③ 타이밍 방어 때문).

### ② 봇/브루트포스 방어 — reCAPTCHA 강제
**[함]** 계정의 `failure_count >= 10`(`CAPTCHA_THRESHOLD`)이면 → reCAPTCHA 토큰을 **요구**하고 `recaptcha.verify_token`으로 검증. 토큰 없음/검증 실패 → 즉시 거부(fail-closed).
**[왜]** 무차별 대입(brute-force) 시도가 쌓인 계정만 사람임을 증명하게.

### ③ 자격증명 비교 — 타이밍 공격·계정 부존재 은닉
**[함]**
- 비교 대상 해시: 계정 있으면 그 해시, **없으면 `dummy_hash`**(가짜 해시).
- `await asyncio.to_thread(self._hasher.verify, target_hash, password)` 로 **Argon2id 해시 비교**.
- 계정이 없으면 결과를 **강제로 False**.

**[용어/왜]**
- *Argon2id* = 비밀번호 해싱 알고리즘. 일부러 **느리고 메모리를 많이 먹게**(여기 m=64MB·t=3·p=4) 설계 → 공격자가 대량으로 빠르게 대입 못 함.
- *타이밍 공격(timing attack)* = "응답이 빠르면 계정 없음, 느리면 있음"으로 **존재 여부를 추측**하는 공격. → 계정이 없어도 `dummy_hash`로 **똑같은 시간만큼** 비교해서 시간차를 없앤다.
- *`asyncio.to_thread`* = Argon2 비교는 수십 ms CPU를 잡아먹는 동기 작업. 그냥 돌리면 **서버 전체(이벤트 루프)가 멈춘다**. 워커 스레드에 던져서 다른 요청이 안 막히게.

### ④ 실패 처리 — 지수 백오프(점점 길어지는 지연)
**[함]** 비교 실패 시:
- 계정 있으면 `failure_count += 1` 기록(PostgreSQL).
- **3회차부터** 지연: `min(2^(실패횟수-3), 120)` 초 → **3회:1초, 4회:2초, 5회:4초, 6회:8초… 최대 120초**.
- 지연은 `await asyncio.sleep`(비차단) — `time.sleep`(차단) 쓰면 워커 스레드 고갈 DoS.
- 관측 신호 발행: 어떤 게 틀렸는지/이메일 파생값은 **안 싣고** `reason="invalid_credentials"`로 **일반화**만.
- → `401 "이메일 또는 비밀번호가 올바르지 않습니다."`

**[왜 자동 잠금(LOCKED)을 안 하나]** 실패가 쌓여도 계정을 자동으로 못 잠근다. 잠그면 **공격자가 남의 계정을 일부러 잠그는 DoS**가 되니까. 대신 10회 CAPTCHA + backoff로 방어. `LOCKED`는 **관리자 수동**만.

### ⑤ 성공 후 상태 검증
**[함]** 비교 성공이어도 계정 상태가:
- `PENDING`(이메일 미인증) → 거부.
- `LOCKED`(관리자 수동 잠금) → 거부.

### ⑥ 성공 마무리 + 해시 자동 업그레이드
**[함]** `failure_count`를 0으로 리셋. 해시 강도가 옛 기준이면(`check_needs_rehash`) 새 파라미터로 **다시 해싱해 저장**(rehash) — 사용자 모르게 보안 강화.

### ⑦ Principal 생성
**[함]**
```python
account_role = UserRole(account.role)   # ★역할은 DB가 단일 출처
principal = Principal(user_id=account.id, role=account_role, mfa_verified=False)
```
**[왜]** 역할(ADMIN/USER)은 **DB값만** 신뢰. 이메일 접두사 같은 사용자 입력으로 절대 안 줌(`admin@...`로 가입하면 관리자 되는 권한상승 결함 차단). `mfa_verified`는 로그인 시점엔 **항상 False** — 관리자 기능은 별도 2단계를 또 통과해야.

### ⑧ 세션 발급 — `services/session_manager.py` `issue()`
**[함]**
```python
session_handle = secrets.token_hex(32)   # 32바이트 보안 난수 = 출입증
session = SessionRecord(handle=..., user_id=..., role=..., mfa_verified=...,
    created_at=now, last_active_at=now, expires_at=now+30일)
await self._repo.save(session)           # ★Redis에 저장
return session
```
**[내보냄]** 세션 핸들(토큰) → 컨트롤러가 쿠키로 심음.
**[수명 두 종류]** *sliding(idle) 2시간* = 2시간 활동 없으면 만료. *absolute 30일* = 발급 후 30일이면 무조건 만료.

---

## 이후 모든 요청의 인증 — `session_manager.verify()`

로그인 후 다른 요청(`GET /auth/session`, `/library/*`, `/api/search`)이 오면:

**[받음]** 쿠키의 `session_id` 토큰.
**[함]**
1. `self._repo.get(token)` → **Redis** 조회.
   - **Redis 장애 → fail-closed: 즉시 401 거부.** PostgreSQL로 폴백 안 함(만료 검증을 우회하느니 막는다).
2. 없으면 → 만료/무효(401).
3. *sliding 검사*: `now > last_active_at + 2시간` → 삭제 + 만료.
4. *absolute 검사*: `now > expires_at(30일)` → 삭제 + 만료.
5. 통과 → `last_active_at = now`로 갱신(sliding 연장) 후 Redis 저장.
**[내보냄]** `Principal(user_id, role, mfa_verified)` 복원 → 이 요청의 "주인". 역할도 세션에 보존돼 있던 걸 복원(그래야 ADMIN 권한이 전파됨).

---

## 관리자 제어평면 (2단계 인증) — `guard.py` + `totp.py`

관리자 기능(`/auth/admin/*`)은 **두 조건을 동시에** 만족해야:

1. `role == ADMIN` (DB값)
2. `mfa_verified == True` (TOTP 통과)

**흐름:**
- `/auth/mfa/enroll` → TOTP 등록, QR용 `otpauth://` URI 반환(평문 시크릿은 응답에 안 넣음).
- `/auth/mfa/verify` → 사용자가 인증앱 6자리 코드 제출 → `totp.verify` 통과 시 `session_manager.elevate_mfa` → 세션을 `mfa_verified=True`로 승격.
- `/auth/admin/whoami` → `AuthorizationGuard.authorize_admin(principal, mfa_verified)` 가 판정. 둘 중 하나라도 안 되면 **403**(구체 사유 비노출).

**[용어]** *TOTP* = Time-based One-Time Password. 인증앱(Google Authenticator 등)이 **30초마다 바뀌는 6자리 코드**를 만들고, 서버도 같은 시크릿으로 같은 코드를 계산해 맞춰본다.

> **`AuthorizationGuard`는 "인가 단일 권위"** — 소유권 판정(`authorize`)과 관리자 판정(`authorize_admin`)을 여기 한 곳에서만 한다. **U4(라이브러리)가 "이 논문이 이 사용자 것인가"를 판단할 때 이 가드를 갖다 쓴다**(재구현 안 함). 그래서 U3을 먼저 배웠다.

---

## 비밀번호 정책 — `password.py` `PasswordPolicy` (가입 시)

**[함]** 가입 비밀번호 검사: **최소 10자** + 대문자 + 소문자 + 숫자 + 특수문자 + **취약 비밀번호 블랙리스트 1만개에 없을 것**. 블랙리스트는 모듈 로딩 시 메모리 set에 1회 캐싱(O(1) 조회).
**[주의]** 블랙리스트 파일 로딩 실패는 **fail-open**(검사 무력화)이라 ERROR 로그를 크게 남겨 운영이 즉시 인지하게 함.

---

## 한 장 요약

```
POST /auth/login {email, password}
 ① get_by_email                ← PostgreSQL
 ② 실패 10회↑ → reCAPTCHA 강제   ← reCAPTCHA (fail-closed)
 ③ Argon2id 비교(워커스레드)     계정 없으면 dummy_hash로 동일시간(타이밍 방어)
 ④ 실패 → failure_count++, 3회차부터 backoff(1·2·4…120s, asyncio.sleep), 401
 ⑤ 상태검사 PENDING/LOCKED → 거부
 ⑥ 성공 → 통계 리셋 + 필요시 rehash
 ⑦ Principal(role=DB값, mfa=False)
 ⑧ 세션 발급 token_hex(32)       → Redis (sliding 2h / absolute 30d)
        ↓
 Set-Cookie session_id (httpOnly·secure·samesite=lax·30d)   body엔 토큰 없음(SEC-12)

이후 요청: 쿠키 → verify() → Redis 조회(장애=401 fail-closed) → Principal 복원
관리자:   role=ADMIN AND mfa_verified(TOTP) → AuthorizationGuard → 아니면 403
```

**갈림길 요약**: Redis 장애 → 401(폴백 없음). 실패 누적 → CAPTCHA+backoff(자동잠금 X). 계정 부존재 → dummy_hash로 은닉. 권한 → DB 단일출처 + 관리자 2단계.
```
