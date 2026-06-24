# AIDLC Code Reviewer — Analysis Report

**Generated**: 2026-06-22T06:38:31Z  
**Target**: `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend`  
**Detected languages**: Python  
**Total findings**: 1182  
**Overall verdict**: **Needs Attention**

## 1. Executive Summary

**Needs Attention** — 1182 findings (269 MEDIUM, 125 LOW, 788 INFO)

> 15 code sections flagged for human review — see Critical Code Findings below. Address 269 MEDIUM findings during regular development.

### Tool Summary

| Category | Tool | Status | Findings |
|----------|------|--------|----------|
| Linting / Style Conformance | ruff | ✓ Ran | 0 |
| Complexity | radon | ✓ Ran | 824 |
| Dead Code | vulture | ✓ Ran | 94 |
| Type Safety | mypy | ✓ Ran | 264 |
| Security | bandit | ✓ Ran | 0 |

## Critical Code Findings — Review Required

**15** critical code sections identified for human review.

### 1. 🔢 [COMPUTATION] `modules/accounts/services/auth.py`:55-103 🤖 Agent-identified

**Finding**: Argon2 password verification with timing-attack defense and post-verification account-None guard that mypy flags as unsafe attribute access on a potentially-None object.  
**Action**: Replace the mutable dummy-hash constant with a freshly computed Argon2 hash at startup, add an explicit `assert account is not None` before the success path, and annotate `account` as non-None after the early-return guard to satisfy mypy and make the invariant compiler-checked.  

**Why it matters**:

If the dummy_hash ever accidentally verifies against a real password (malformed dummy or future library version change), the `if not account: is_verified = False` guard is the only barrier preventing login to a non-existent account; mypy also flags multiple None-attribute accesses on `account` downstream after this guard, indicating the type system has not enforced the guarantee.

**Code**:

```
            account = self._repo.get_by_email(email)
            
            # 1. 봇 및 브루트포스 남용 방어: reCAPTCHA 검증 강제 (실패 횟수 >= 임계치) (BR-A4)
            if account and account.failure_count >= CAPTCHA_THRESHOLD:
                if not recaptcha_token:
>>>                 raise DomainException("보안 강화를 위해 봇 방지 인증(CAPTCHA)이 필요합니다.")
                
                captcha_ok = await self._recaptcha_client.verify_token(recaptcha_token, remote_ip)
                if not captcha_ok:
>>>                 raise DomainException("봇 방지(CAPTCHA) 검증에 실패했습니다. (Fail-Closed)")
>>> 
            # 2. 자격증명 비교 및 타이밍 공격 방어 (Constant-Time Verification) (SEC-12)
            target_hash = account.password_hash if account else self._repo.dummy_hash
>>>         
>>>         is_verified = False
>>>         needs_rehash = False
            
>>>         try:
                # 해시 비교 연산 실행. Argon2 KDF(m=64MB)는 수십 ms를 소모하는 CPU 바운드 동기 작업이므로
>>>             # asyncio.to_thread로 워커 스레드에 위임해 이벤트 루프 차단(동시 로그인 직렬화/DoS)을 방지한다.
>>>             is_verified = await asyncio.to_thread(self._hasher.verify, target_hash, password)
>>>             # 해시 강도 업그레이드 필요 여부 체크 (인코딩 파라미터 파싱만 하므로 KDF 미수행 → 동기 호출로 충분)
>>>             needs_rehash = self._hasher.check_needs_rehash(target_hash)
            except (VerificationError, InvalidHash):
                # 자격증명 불일치 혹은 해시 깨짐
                is_verified = False
            
            # 실제 데이터베이스에 계정이 존재하지 않는 경우, 
            # 비교 연산 결과가 True 일지라도 강제로 False 처리하여 계정 부존재 상태를 숨깁니다 (타이밍 공격 차단)
            if not account:
                is_verified = False
```

### 2. 🔢 [COMPUTATION] `modules/accounts/services/session_manager.py`:49-98 🤖 Agent-identified

**Finding**: Session sliding-expiration and absolute-expiration checks use naive datetime.now(UTC) compared against Redis-stored ISO timestamps that may be timezone-naive or timezone-aware depending on serialization path.  
**Action**: Audit the isoformat/fromisoformat round-trip in `SessionRepository.save`/`get` to guarantee all stored datetimes include timezone information, and add a normalization guard (`if dt.tzinfo is None: dt = dt.replace(tzinfo=UTC)`) in the `get` deserializer before returning the SessionRecord.  

**Why it matters**:

In `SessionRepository.get`, `datetime.fromisoformat` reconstructs timestamps from Redis; the `save` path stores `datetime.now(UTC)` which is timezone-aware, but old session records stored with naive UTC (e.g. from a prior code version) will cause a `TypeError: can't compare offset-naive and offset-aware datetimes` on the comparison at lines 71/74, silently letting the comparison throw rather than correctly expiring the session.

**Code**:

```
        async def verify(self, session_token: str) -> Principal:
            """
            요청 토큰의 유효성을 검사합니다.
            Sliding 만료 정책 및 Absolute 만료 정책을 물리적으로 강제합니다. (BR-A3)
            Fail-Closed 원칙에 따라, Redis 장애 시 PostgreSQL로 폴백하지 않고 거부합니다. (Q1 NFR Design)
            """
            if not session_token:
                raise UnauthorizedException("인증 토큰이 누락되었습니다.")
    
            try:
                session = await self._repo.get(session_token)
            except SessionStoreUnavailableException as e:
                # 피드백 ② 반영: Redis 연결 장애 시 Fail-Closed 정책 적용 (DB 폴백 배제, 즉각 거부)
                logger.critical(f"Redis session storage failure (Fail-Closed triggered): {str(e)}")
>>>             raise UnauthorizedException("세션 저장소 일시 장애로 인해 서비스를 이용할 수 없습니다.") from e
    
            if not session:
                raise SessionExpiredException("세션이 유효하지 않거나 만료되었습니다.")
>>> 
            now = datetime.now(UTC)
    
            # 1. Sliding Expiration 만료 검사 (BR-A3 Idle Timeout)
>>>         if now > session.last_active_at + timedelta(hours=self._idle_timeout_hours):
                await self._repo.delete(session_token)
                raise SessionExpiredException("비활성화 상태가 2시간 이상 지속되어 세션이 만료되었습니다.")
>>> 
            # 2. Absolute Expiration 만료 검사 (BR-A3 Max Lifetime)
            if now > session.expires_at:
                await self._repo.delete(session_token)
                raise SessionExpiredException("세션의 최대 사용 기간(30일)이 만료되었습니다. 다시 로그인해 주세요.")
    
>>>         # 3. Sliding Expiration 활성 시각 갱신
            session.last_active_at = now
            try:
                await self._repo.save(session)
>>>         except SessionStoreUnavailableException as e:
                # 갱신 저장 실패 시에도 보안을 위해 Fail-Closed 정책 적용
                logger.critical(f"Failed to update session active timestamp: {str(e)}")
                raise UnauthorizedException("세션 만료 갱신 실패로 인증을 거부합니다.") from e
>>> 
            # 발급 시 세션에 보존해 둔 역할을 복원한다 (USER 하드코딩 제거 — 그래야 ADMIN 인가가 세션으로 전파된다).
            # 알 수 없는/누락된 값은 최소 권한(USER)으로 안전하게 폴백한다 (Fail-safe).
>>>         try:
                role = UserRole(session.role)
            except ValueError:
                role = UserRole.USER
            return Principal(
                user_id=session.user_id,
                role=role,
                mfa_verified=session.mfa_verified,  # BR-A7: 세션에 보존된 MFA 통과 여부 복원
            )
```

### 3. 🔢 [COMPUTATION] `modules/accounts/services/signup.py`:50-56 🤖 Agent-identified

**Finding**: Email verification token expiry comparison mixes a timezone-aware `datetime.now(UTC)` with a timezone-naive `expires_at` stored in the database, which will raise a TypeError at runtime.  
**Action**: Standardize on timezone-aware datetimes throughout the token lifecycle by using `DateTime(timezone=True)` in the SQLAlchemy column and removing the `.replace(tzinfo=None)` stripping, or add a clear module-level comment and a runtime assertion that both sides of the comparison are naive.  

**Why it matters**:

The `verify_email` method at line ~107 compares `datetime.now(UTC).replace(tzinfo=None) > token_record.expires_at`, which is consistent when both are naive, but `datetime.now(UTC)` is tz-aware before `.replace(tzinfo=None)` is called — if the `.replace()` is ever accidentally removed, the comparison raises TypeError and crashes email verification silently, failing all new account activations.

**Code**:

```
            # 5. 이메일 인증 링크용 보안 토큰 생성 (24시간 유효) (BR-A5)
            token = secrets.token_urlsafe(32)
            # naive UTC — matches SQLAlchemy DateTime(timezone=False) column storage.
>>>         expires_at = datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=24)
            self._repo.create_verification_token(email_vo.value, token, expires_at)
```

### 4. 🔢 [COMPUTATION] `modules/accounts/repository/credential.py`:37-42 🤖 Agent-identified

**Finding**: The timing-attack dummy hash is a hardcoded static string that may not match the configured Argon2 parameters, silently degrading the constant-time defense.  
**Action**: Replace the hardcoded string with a module-level constant computed at import time via `get_password_hasher().hash('dummy-sentinel-value')` so the defense always costs the same as a real verification.  

**Why it matters**:

The hardcoded dummy hash has a malformed base64 digest (`abcdefghijklmnopqrstuvwxyz0123456789abcd` is 40 chars, not 32 bytes base64url), meaning `argon2.verify` will raise `InvalidHash` immediately rather than performing the full KDF, so the timing-attack defense is completely nullified for non-existent accounts.

**Code**:

```
        def __init__(self, db_session: Session):
>>>         self._session = db_session
>>>         # 타이밍 공격 방어용 더미 해시 (argon2 KDF로 미리 만들어둔 일반적인 형태의 더미 값)
            # 실제 계정이 없을 때 이 더미 해시와 입력 패스워드를 대조 연산함으로써 시간 유추를 불가능하게 함
            self.dummy_hash = "$argon2id$v=19$m=65536,t=3,p=4$c29tZXNhbHQ$abcdefghijklmnopqrstuvwxyz0123456789abcd"
```

### 5. 🔢 [COMPUTATION] `modules/accounts/services/totp.py`:26-33 🤖 Agent-identified

**Finding**: TOTP verification uses `valid_window=1` (±30 seconds) but performs no replay protection — the same OTP code is valid for up to 60 seconds and can be reused for multiple admin privilege escalations.  
**Action**: Add a short-lived Redis set (keyed by `account_id:totp_code`, TTL=90s) to reject reuse of any TOTP code that has already been accepted within its validity window.  

**Why it matters**:

Without a used-OTP cache, an attacker who intercepts a valid TOTP code can replay it within the 90-second window to gain admin MFA-elevated access multiple times, undermining the entire BR-A7 second-factor requirement.

**Code**:

```
        def verify(self, account: AccountTable, code: str) -> bool:
            """제출된 코드를 계정의 TOTP 시크릿으로 검증한다. 미등록 계정/빈 코드는 항상 False(Fail-Closed).
            valid_window=1로 ±1 타임스텝(30초) 시계 오차를 허용한다."""
            if not account.totp_secret or not code:
>>>             return False
            return pyotp.TOTP(account.totp_secret).verify(code, valid_window=1)
```

### 6. 🔢 [COMPUTATION] `modules/accounts/services/session_manager.py`:101-119 🤖 Agent-identified

**Finding**: MFA elevation in `elevate_mfa` calls `verify()` (which re-saves the session with a new `last_active_at`) then immediately fetches the session again and saves it a second time — creating a TOCTOU window where the session could expire between the two operations.  
**Action**: Pass the `session` object returned inside `verify()` directly to `elevate_mfa` (or extend `verify` to accept a mutation callback) so the MFA flag is set on the already-verified, already-updated snapshot in a single atomic save.  

**Why it matters**:

The second `self._repo.get(session_token)` re-fetches the session from Redis; if this fetch returns an older snapshot (e.g. Redis replication lag), the `mfa_verified=True` write overwrites the `last_active_at` that `verify()` just updated, potentially resurrecting a session that should have been sliding-expired.

**Code**:

```
        async def elevate_mfa(self, session_token: str) -> Principal:
            """BR-A7: TOTP 검증 통과 후 현재 세션을 MFA 통과 상태로 승격한다 (2단계 인증).
            세션을 먼저 재검증(만료/sliding 갱신)한 뒤 mfa_verified=True로 저장한다."""
>>>         principal = await self.verify(session_token)  # 만료 검증 + sliding 갱신
            session = await self._repo.get(session_token)
>>>         if not session:
                raise SessionExpiredException("세션이 유효하지 않거나 만료되었습니다.")
>>>         session.mfa_verified = True
            try:
                await self._repo.save(session)
>>>         except SessionStoreUnavailableException as e:
                logger.critical(f"Failed to persist MFA elevation: {str(e)}")
>>>             raise UnauthorizedException("MFA 승격 저장 실패로 인증을 거부합니다.") from e
            return Principal(user_id=principal.user_id, role=principal.role, mfa_verified=True)
```

### 7. 🔀 [CONTROL_FLOW] `middleware/auth.py`:39-79 🤖 Agent-identified

**Finding**: Auth injection middleware path-matching uses plain `str.startswith` prefix checks, making it possible to bypass authentication for protected routes by crafting paths that match a public prefix.  
**Action**: Replace bare `startswith` prefix matching with exact-path or path-segment comparison (e.g. split on `/` and check the first segment), or use FastAPI's `request.scope['route']` path template after routing rather than raw URL path.  

**Why it matters**:

A request to `/auth/login.evil` or `/healthcheck-forged` would match `/health` or `/auth/login` respectively via `startswith`, setting `principal=None` and bypassing authentication for what might be a sensitive route if path normalization is not applied by FastAPI before this middleware runs.

**Code**:

```
    async def inject_principal(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
        *,
        session_manager,
    ) -> Response:
        """Middleware logic: resolve session cookie into Principal on request.state.
    
        Designed to be called from inside the gateway middleware (not installed separately)
>>>     so that request_id and rate-limit have already been applied.
        """
        path = request.url.path
>>> 
        if _is_public(path):
            request.state.principal = None
>>>         return await call_next(request)
    
        session_id = request.cookies.get("session_id")
>>>     optional = _is_auth_optional(path)
    
        if not session_id:
            if optional:
                request.state.principal = None
>>>             return await call_next(request)
            from fastapi.responses import JSONResponse
    
            return JSONResponse(status_code=401, content={"message": "authentication required"})
>>> 
        try:
>>>         principal = await session_manager.verify(session_id)
        except Exception:
            if optional:
>>>             request.state.principal = None
                return await call_next(request)
            from fastapi.responses import JSONResponse
>>> 
            return JSONResponse(status_code=401, content={"message": "session expired or invalid"})
    
        request.state.principal = principal
        return await call_next(request)
```

### 8. 🔀 [CONTROL_FLOW] `middleware/gateway.py`:139-161 🤖 Agent-identified

**Finding**: X-Forwarded-For hop selection logic for rate-limit keying counts from the right, but index arithmetic `len(hops) - max(trusted_proxy_count, 1)` can silently select an attacker-controlled hop when the total hop count equals `trusted_proxy_count`.  
**Action**: Change the guard from `idx < 0` to `idx <= 0` (or `idx < 1`) to ensure the selected hop is never the leftmost client-controlled entry, falling back to `request.client.host` when there are not enough trusted proxy hops.  

**Why it matters**:

When `len(hops) == trusted_proxy_count`, `idx` equals 0 (the leftmost, fully client-controlled hop), so an attacker who injects exactly N fake hops into X-Forwarded-For gains control of the rate-limit key, achieving complete rate-limit evasion despite `trust_proxy_headers=True`.

**Code**:

```
    def _forwarded_client(request: Request, trusted_proxy_count: int) -> str | None:
        raw = request.headers.get("X-Forwarded-For")
        if not raw:
            return None
        hops = [hop.strip() for hop in raw.split(",") if hop.strip()]
        # The LEFTMOST entry is fully client-controlled (spoofable) — keying on it lets an attacker
        # rotate it to evade per-IP limits. Trust only what our own proxies stamped: count
>>>     # `trusted_proxy_count` from the right and take the hop our outermost trusted proxy recorded.
        # Require a valid IP so a spoofed/garbage value can't mint unlimited rate-limit buckets.
        idx = len(hops) - max(trusted_proxy_count, 1)
>>>     if idx < 0:
>>>         return None  # fewer hops than trusted proxies → header is not trustworthy
        candidate = hops[idx]
>>>     return candidate if _is_ip(candidate) else None
```

### 9. 🔀 [CONTROL_FLOW] `modules/accounts/controller.py`:259-284 🤖 Agent-identified

**Finding**: MFA verify endpoint checks `account` and TOTP code in a combined condition that generalizes both 'account not found' and 'wrong code' into the same 401 — correct for SEC-9, but the TOTP `verify()` call returning False for a registered account is never distinguished from a missing account, masking potential TOTP secret corruption.  
**Action**: Add an explicit check after `get_by_id` that raises 401 if `account` is None before calling `totp_svc.verify`, and add a server-side log (without PII) when account is not found to distinguish the operational anomaly from a routine wrong-code event.  

**Why it matters**:

A session that passes `session_mgr.verify()` but whose user_id no longer exists in the credentials DB (e.g. account deleted but Redis session still valid) reaches `totp_svc.verify(None, ...)` — but `get_by_id` returning None is handled by the combined `not account or not totp_svc.verify` guard correctly, while a `None` account being passed would be caught by `TotpService.verify`'s first check; the real risk is that `elevate_mfa` is called with a session whose account is deleted, promoting a ghost session to MFA-verified ADMIN.

**Code**:

```
        try:
            principal = await session_mgr.verify(session_id)
            account = credential_repo.get_by_id(principal.user_id)
            if not account or not totp_svc.verify(account, req.code):
                # 코드 불일치/미등록 — 자격증명 비노출(SEC-9) 일반화 메시지로 거부 (Fail-Closed)
                raise HTTPException(status_code=401, detail="MFA 코드 검증에 실패했습니다.")
            await session_mgr.elevate_mfa(session_id)
>>>         return {"status": "success", "message": "MFA 인증이 완료되었습니다."}
>>>     except (UnauthorizedException, SessionExpiredException) as e:
>>>         raise HTTPException(status_code=401, detail=str(e)) from e
>>>     except HTTPException:
>>>         raise
>>>     except Exception:
            raise HTTPException(status_code=500, detail="MFA 검증 중 서버 오류가 발생했습니다. (Fail-Closed)") from None
```

### 10. 🔀 [CONTROL_FLOW] `modules/accounts/guard.py`:17-35 🤖 Agent-identified

**Finding**: Authorization guard compares `principal.user_id` (a plain `str`) against `resource_owner_id.value` (also a `str`) with `==`, which is correct, but the ADMIN role receives no special treatment — an ADMIN cannot read or modify another user's resources through this guard.  
**Action**: Add a comment asserting the intentional ADMIN-cannot-cross-own design decision, and normalize both `principal.user_id` and `resource_owner_id.value` via `UUID(x)` comparison rather than raw string equality to prevent case/encoding mismatches from silently failing legitimate access.  

**Why it matters**:

The ownership check is purely string equality with no type coercion protection — if `principal.user_id` is ever populated with something other than a canonical UUID string (e.g. a JWT sub claim with different casing or encoding), authorization silently denies the legitimate owner; more importantly, the design intentionally denies ADMINs cross-owner access, but this is not documented as a conscious decision and could be a functional gap for administrative operations.

**Code**:

```
        @classmethod
        def authorize(cls, principal: Principal | None, action: Action, resource_owner_id: AccountId | None) -> Decision:
            """
            사용자 데이터 관리 액션(READ, WRITE, DELETE, RERUN)에 대해 객체 소유권을 Stateless 검증합니다.
            피드백 ④ 반영: principal과 함께 타 서비스가 먼저 조회한 resource_owner_id를 명시적 인자로 받습니다.
            """
            # 1. 기본 거부 정책 (Default Deny - SEC-8)
>>>         if not principal or not principal.user_id:
                return Decision.DENY
>>> 
            if not resource_owner_id or not resource_owner_id.value:
                return Decision.DENY
>>> 
            # 2. 소유권 일치 판단 (BR-A6)
            if principal.user_id == resource_owner_id.value:
>>>             return Decision.ALLOW
    
>>>         # 3. 소유자가 다르면 기본 거부
            return Decision.DENY
```

### 11. 🔀 [CONTROL_FLOW] `migrations/__init__.py`:29-57 🤖 Agent-identified

**Finding**: Migration runner executes raw .sql files read from the filesystem without any content validation, then records them in a `_migrations` ledger — a compromised or accidentally-modified SQL file will be executed once and permanently recorded as applied with no rollback.  
**Action**: Wrap each migration's DDL execution and ledger insertion in a single transaction (use a savepoint or a nested `with conn.transaction():` block) so both the schema change and the ledger entry commit atomically or both roll back.  

**Why it matters**:

Each migration is committed individually (`conn.commit()` inside the loop), so if `conn.execute(sql)` partially succeeds and then the `INSERT INTO _migrations` fails, the DDL change is committed without being recorded — causing the migration to re-run on the next startup and potentially producing duplicate-key or data corruption errors.

**Code**:

```
    def apply_migrations(dsn: str, paths: list[str | Path]) -> list[str]:
        """Apply all pending migrations in order. Returns names of newly applied scripts."""
        import psycopg
    
        applied: list[str] = []
        with psycopg.connect(dsn) as conn:
            conn.execute(_TRACKING_DDL)
>>>         conn.commit()
>>> 
            already_applied = {
>>>             row[0] for row in conn.execute("SELECT name FROM _migrations").fetchall()
            }
    
>>>         for migrations_dir in paths:
                scripts = sorted(Path(migrations_dir).glob("*.sql"))
>>>             for script in scripts:
>>>                 if script.name in already_applied:
>>>                     continue
>>>                 log.info("applying migration: %s", script.name)
>>>                 sql = script.read_text(encoding="utf-8")
>>>                 conn.execute(sql)
>>>                 conn.execute(
                        "INSERT INTO _migrations (name) VALUES (%s)", (script.name,)
                    )
                    conn.commit()
                    applied.append(script.name)
                    log.info("applied: %s", script.name)
```

### 12. 🔀 [CONTROL_FLOW] `modules/accounts/services/signup.py`:84-122 🤖 Agent-identified

**Finding**: Email verification token comparison uses `datetime.now(UTC).replace(tzinfo=None)` for the expiry check, but `delete_verification_token` is called both on expired tokens (line 97) and on already-active accounts (line 104) — an already-active account re-clicking the link deletes the token but returns `True`, creating an idempotency window where re-activation attempts could race.  
**Action**: Add a database-level SELECT FOR UPDATE (or equivalent advisory lock) around the token lookup and account status update, or use a single UPDATE statement that atomically sets status=ACTIVE WHERE status=PENDING to make the operation idempotent under concurrent requests.  

**Why it matters**:

There is no database-level uniqueness or row-level lock on the token verification flow — two concurrent requests with the same token will both pass the `get_verification_token` check, both find the account PENDING, and both call `update_account(ACTIVE)` followed by `delete_verification_token`, resulting in a benign double-write but also confirming that the caller has no transactional atomicity guarantee.

**Code**:

```
        async def verify_email(self, token: str) -> bool:
            """이메일 인증 링크로 전달된 토큰을 검증하고 계정을 ACTIVE 상태로 활성화합니다."""
            if not token:
                raise DomainException("유효하지 않은 인증 토큰입니다.")
    
            token_record = self._repo.get_verification_token(token)
            if not token_record:
                raise DomainException("인증 토큰이 존재하지 않거나 만료되었습니다.")
    
            # 토큰 유효 기간 검증 (24시간)
>>>         if datetime.now(UTC).replace(tzinfo=None) > token_record.expires_at:
                self._repo.delete_verification_token(token)
>>>             raise DomainException("인증 링크 유효 기간(24시간)이 만료되었습니다. 다시 가입해 주십시오.")
>>> 
            # 계정 ACTIVE 상태 업데이트
            account = self._repo.get_by_email(token_record.email)
>>>         if not account:
                raise DomainException("활성화할 계정을 찾을 수 없습니다.")
>>> 
            if account.status == AccountStatus.ACTIVE.value:
                # 이미 활성화된 상태인 경우 성공으로 간주
>>>             self._repo.delete_verification_token(token)
>>>             return True
>>> 
            account.status = AccountStatus.ACTIVE.value
            self._repo.update_account(account)
            self._repo.delete_verification_token(token)
```

### 13. 🔀 [CONTROL_FLOW] `modules/ops/controller.py`:53-64 🤖 Agent-identified

**Finding**: Admin dashboard endpoints rely on `enforce_admin_mfa` dependency which delegates to `AuthorizationGuard.authorize_admin`, but the principal is obtained from `request.state.principal` — if the gateway's session_manager is None (local dev), `principal` is never set and the guard sees `None`, silently returning DENY and raising 403 instead of the intended 401.  
**Action**: Add an integration test or startup check that verifies the ops endpoints are reachable (returning 401, not 500) when Redis is absent, and document that `session_manager=None` disables all authenticated endpoints including ops/dashboard.  

**Why it matters**:

In production, the session manager is always active, but if `session_manager` is None (dev/CI without Redis) the gateway skips auth injection, `request.state.principal` is not set, `get_principal` raises 401 — but the ops endpoints are admin-only and the entire ops control plane becomes unreachable in those environments, masking misconfiguration as an auth error rather than a service-configuration error.

**Code**:

```
    def get_principal(request: Request) -> Principal:
        principal = getattr(request.state, "principal", None)
        if principal is None:
            raise HTTPException(status_code=401, detail="authentication required")
>>>     return principal
>>> 
>>> 
>>> def enforce_admin_mfa(principal: Principal = Depends(get_principal)) -> None:
        decision = AuthorizationGuard.authorize_admin(principal, mfa_verified=principal.mfa_verified)
>>>     if decision != Decision.ALLOW:
>>>         raise HTTPException(status_code=403, detail="forbidden")
```

### 14. 🔄 [DATA_TRANSFORM] `modules/accounts/repository/session.py`:73-95 🤖 Agent-identified

**Finding**: Session deserialization from Redis JSON uses `datetime.fromisoformat` without timezone normalization, so old session records stored as naive datetimes will produce a Principal whose expiry comparisons will raise TypeError in the session manager.  
**Action**: Add a `_ensure_aware(dt)` helper that calls `dt.replace(tzinfo=UTC)` if `dt.tzinfo is None` after every `fromisoformat` call in the `get` deserializer, and add a unit test with a naive-datetime Redis payload.  

**Why it matters**:

Python's `datetime.fromisoformat` in Python <3.11 does not parse the `+00:00` suffix from `datetime.now(UTC).isoformat()` correctly in all edge cases, and a session record stored without timezone suffix (e.g. from a rollback or older code version) will be deserialized as naive, causing a TypeError crash in `verify()` when compared against `datetime.now(UTC)`.

**Code**:

```
        async def get(self, handle: str) -> SessionRecord | None:
            """세션 핸들러로 세션을 조회합니다."""
            key = f"session:{handle}"
            try:
                data_str = await self._redis.get(key)
                if not data_str:
                    return None
>>>             
>>>             data = json.loads(data_str)
>>>             return SessionRecord(
>>>                 handle=data["handle"],
>>>                 user_id=data["user_id"],
>>>                 created_at=datetime.fromisoformat(data["created_at"]),
>>>                 last_active_at=datetime.fromisoformat(data["last_active_at"]),
>>>                 expires_at=datetime.fromisoformat(data["expires_at"]),
>>>                 role=data.get("role", UserRole.USER.value),  # 구버전 레코드 호환: 누락 시 USER
                    mfa_verified=bool(data.get("mfa_verified", False)),  # 누락 시 MFA 미통과로 안전 폴백
                )
```

### 15. 🔄 [DATA_TRANSFORM] `modules/library/validation.py`:119-131 🤖 Agent-identified

**Finding**: Pagination cursor is base64url-decoded and JSON-parsed from user input with a bare `except Exception` that raises `ValidationException` — a tampered cursor with valid base64 but invalid JSON structure could silently expose internal field names via the error message.  
**Action**: Replace `raise ValidationException(...) from exc` with `raise ValidationException(...) from None` to suppress the exception chain, and add explicit type checks for `obj['ts']` and `obj['id']` before passing to `fromisoformat`.  

**Why it matters**:

The `datetime.fromisoformat(obj['ts'])` call will raise `ValueError` with an error message containing the attacker-supplied value; while `ValidationException` generalizes the response, the `from exc` chain preserves the original exception — if the caller ever logs `repr(exc)` or its `__cause__`, the internal field name `ts` and attacker input are exposed in logs.

**Code**:

```
    def decode_cursor(cursor: str | None) -> CursorKey | None:
        if cursor is None:
            return None
        try:
            raw = base64.urlsafe_b64decode(cursor.encode("ascii"))
>>>         obj = json.loads(raw)
>>>         return datetime.fromisoformat(obj["ts"]), str(obj["id"])
>>>     except Exception as exc:  # tampered / garbage cursor → 422 (not a 500)
>>>         raise ValidationException("invalid pagination cursor") from exc
```

## 2. Code Structure Critique

*Code structure critique not available.*

## 3. Code Quality Analysis

### 3.3 Linting / Style Conformance (ruff)

No findings.

### 3.5 Complexity (radon)

**Findings**: 824
  (MEDIUM: 7, LOW: 44, INFO: 773)

| # | Severity | Rule | File | Line | Message |
|---|----------|------|------|------|---------|
| 1 | MEDIUM | `CCC` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_ops_endpoints.py` | 194:0 | block 'test_ops_incidents_filtering_and_query' has cyclomatic complexity 13 (rank C) |
| 2 | MEDIUM | `CCC` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_ops_endpoints.py` | 83:0 | block 'test_ops_dashboard_metrics_aggregation' has cyclomatic complexity 11 (rank C) |
| 3 | MEDIUM | `CCC` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/grounding.py` | 40:0 | block 'GroundingValidator' has cyclomatic complexity 13 (rank C) |
| 4 | MEDIUM | `CCC` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/grounding.py` | 41:4 | block 'validate' has cyclomatic complexity 12 (rank C) |
| 5 | MEDIUM | `CCC` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/services/auth.py` | 35:4 | block 'authenticate' has cyclomatic complexity 20 (rank C) |
| 6 | MEDIUM | `CCC` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/services/auth.py` | 18:0 | block 'AuthenticationService' has cyclomatic complexity 12 (rank C) |
| 7 | MEDIUM | `CCC` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/ops/controller.py` | 137:0 | block 'list_incidents' has cyclomatic complexity 11 (rank C) |
| 8 | LOW | `CCB` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/app.py` | 35:0 | block 'lifespan' has cyclomatic complexity 10 (rank B) |
| 9 | LOW | `CCB` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/middleware/auth.py` | 39:0 | block 'inject_principal' has cyclomatic complexity 6 (rank B) |
| 10 | LOW | `CCB` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/middleware/gateway.py` | 139:0 | block '_forwarded_client' has cyclomatic complexity 6 (rank B) |
| 11 | LOW | `CCB` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/middleware/rate_limit.py` | 56:4 | block '_maybe_sweep' has cyclomatic complexity 6 (rank B) |
| 12 | LOW | `CCB` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/migrations/__main__.py` | 21:0 | block 'main' has cyclomatic complexity 8 (rank B) |
| 13 | LOW | `CCB` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_ops_endpoints.py` | 57:0 | block 'test_ops_authentication_and_authorization_guards' has cyclomatic complexity 10 (rank B) |
| 14 | LOW | `CCB` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_citation_graph.py` | 59:0 | block 'test_citation_tree_bounds_and_unresolved' has cyclomatic complexity 8 (rank B) |
| 15 | LOW | `CCB` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_app_shell.py` | 84:0 | block 'test_paper_metadata_endpoint_is_live' has cyclomatic complexity 6 (rank B) |
| 16 | LOW | `CCB` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_u6_middleware.py` | 136:0 | block 'test_in_memory_rate_limiter_evicts_lru_over_max_keys' has cyclomatic complexity 6 (rank B) |
| 17 | LOW | `CCB` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/citation_graph/controller.py` | 151:0 | block '_node' has cyclomatic complexity 10 (rank B) |
| 18 | LOW | `CCB` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/citation_graph/controller.py` | 179:0 | block '_build_tree' has cyclomatic complexity 9 (rank B) |
| 19 | LOW | `CCB` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/citation_graph/controller.py` | 237:0 | block 'get_citation_tree' has cyclomatic complexity 8 (rank B) |
| 20 | LOW | `CCB` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/citation_graph/controller.py` | 92:4 | block 'references' has cyclomatic complexity 8 (rank B) |
| 21 | LOW | `CCB` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/citation_graph/controller.py` | 88:0 | block 'SemanticScholarProvider' has cyclomatic complexity 6 (rank B) |
| 22 | LOW | `CCB` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/stubs.py` | 133:0 | block 'make_orchestrator' has cyclomatic complexity 6 (rank B) |
| 23 | LOW | `CCB` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_domain_refiner.py` | 24:0 | block 'test_derives_sections' has cyclomatic complexity 6 (rank B) |
| 24 | LOW | `CCB` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/prompts/templates.py` | 29:0 | block '_glossary_block' has cyclomatic complexity 6 (rank B) |
| 25 | LOW | `CCB` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/api/router.py` | 121:0 | block '_parse_glossary_term' has cyclomatic complexity 6 (rank B) |
| 26 | LOW | `CCB` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/service/orchestrator.py` | 75:4 | block 'run' has cyclomatic complexity 6 (rank B) |
| 27 | LOW | `CCB` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/service/orchestrator.py` | 112:4 | block '_run_summary' has cyclomatic complexity 6 (rank B) |
| 28 | LOW | `CCB` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/service/orchestrator.py` | 133:4 | block '_run_translate' has cyclomatic complexity 6 (rank B) |
| 29 | LOW | `CCB` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/refiner.py` | 38:0 | block '_strip_noise_lines' has cyclomatic complexity 7 (rank B) |
| 30 | LOW | `CCB` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/source_selector.py` | 22:4 | block 'select' has cyclomatic complexity 6 (rank B) |
| 31 | LOW | `CCB` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_paper_metadata.py` | 21:0 | block 'test_known_paper_by_paper_id_projects_full_metadata' has cyclomatic complexity 8 (rank B) |
| 32 | LOW | `CCB` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_orchestrator.py` | 25:0 | block 'test_success_returns_ranked_page_and_publishes' has cyclomatic complexity 8 (rank B) |
| 33 | LOW | `CCB` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_opensearch_adapter.py` | 33:0 | block 'test_knn_search_builds_query_and_deserializes_index_record' has cyclomatic complexity 6 (rank B) |
| 34 | LOW | `CCB` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/adapters/bedrock_embedding.py` | 34:4 | block 'embed_query' has cyclomatic complexity 6 (rank B) |
| 35 | LOW | `CCB` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/adapters/settings.py` | 60:4 | block 'from_env' has cyclomatic complexity 8 (rank B) |
| 36 | LOW | `CCB` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/adapters/settings.py` | 37:0 | block 'DiscoverySettings' has cyclomatic complexity 6 (rank B) |
| 37 | LOW | `CCB` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/domain/assembler.py` | 41:0 | block 'ResultAssembler' has cyclomatic complexity 7 (rank B) |
| 38 | LOW | `CCB` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/domain/assembler.py` | 42:4 | block 'assemble' has cyclomatic complexity 6 (rank B) |
| 39 | LOW | `CCB` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/controller.py` | 259:0 | block 'mfa_verify' has cyclomatic complexity 7 (rank B) |
| 40 | LOW | `CCB` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/controller.py` | 228:0 | block 'mfa_enroll' has cyclomatic complexity 6 (rank B) |
| 41 | LOW | `CCB` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/controller.py` | 287:0 | block 'admin_whoami' has cyclomatic complexity 6 (rank B) |
| 42 | LOW | `CCB` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/models.py` | 55:0 | block 'EmailAddress' has cyclomatic complexity 6 (rank B) |
| 43 | LOW | `CCB` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/guard.py` | 10:0 | block 'AuthorizationGuard' has cyclomatic complexity 6 (rank B) |
| 44 | LOW | `CCB` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/guard.py` | 17:4 | block 'authorize' has cyclomatic complexity 6 (rank B) |
| 45 | LOW | `CCB` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/password.py` | 54:0 | block 'PasswordPolicy' has cyclomatic complexity 8 (rank B) |
| 46 | LOW | `CCB` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/password.py` | 63:4 | block 'evaluate' has cyclomatic complexity 7 (rank B) |
| 47 | LOW | `CCB` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/integrations/recaptcha.py` | 14:4 | block 'verify_token' has cyclomatic complexity 9 (rank B) |
| 48 | LOW | `CCB` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/integrations/recaptcha.py` | 7:0 | block 'RecaptchaClient' has cyclomatic complexity 6 (rank B) |
| 49 | LOW | `CCB` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/services/signup.py` | 84:4 | block 'verify_email' has cyclomatic complexity 7 (rank B) |
| 50 | LOW | `CCB` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/services/session_manager.py` | 49:4 | block 'verify' has cyclomatic complexity 8 (rank B) |
| 51 | LOW | `CCB` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/ops/controller.py` | 77:0 | block 'get_dashboard' has cyclomatic complexity 8 (rank B) |
| 52 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/db.py` | 18:0 | block 'make_engine' has cyclomatic complexity 4 (rank A) |
| 53 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/db.py` | 52:0 | block 'make_session_factory' has cyclomatic complexity 1 (rank A) |
| 54 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/config.py` | 66:4 | block 'from_env' has cyclomatic complexity 5 (rank A) |
| 55 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/config.py` | 43:0 | block 'Settings' has cyclomatic complexity 4 (rank A) |
| 56 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/config.py` | 15:0 | block '_resolve_database_url' has cyclomatic complexity 3 (rank A) |
| 57 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/config.py` | 62:4 | block 'is_local' has cyclomatic complexity 1 (rank A) |
| 58 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/health.py` | 28:0 | block 'readyz' has cyclomatic complexity 4 (rank A) |
| 59 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/health.py` | 17:0 | block 'health' has cyclomatic complexity 1 (rank A) |
| 60 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/health.py` | 22:0 | block 'healthz' has cyclomatic complexity 1 (rank A) |
| 61 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/app.py` | 102:0 | block '_apply_startup_migrations' has cyclomatic complexity 4 (rank A) |
| 62 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/app.py` | 134:0 | block '_build_observability' has cyclomatic complexity 3 (rank A) |
| 63 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/app.py` | 194:0 | block '_build_session_manager' has cyclomatic complexity 3 (rank A) |
| 64 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/app.py` | 64:0 | block 'create_app' has cyclomatic complexity 2 (rank A) |
| 65 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/app.py` | 218:0 | block '_build_ops_dashboard_service' has cyclomatic complexity 2 (rank A) |
| 66 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/app.py` | 167:0 | block '_add_middleware' has cyclomatic complexity 1 (rank A) |
| 67 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/errors.py` | 26:0 | block 'register_error_handlers' has cyclomatic complexity 1 (rank A) |
| 68 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/wiring.py` | 42:0 | block 'mount_modules' has cyclomatic complexity 5 (rank A) |
| 69 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/wiring.py` | 149:0 | block '_mount_library' has cyclomatic complexity 4 (rank A) |
| 70 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/wiring.py` | 96:0 | block '_mount_discovery' has cyclomatic complexity 2 (rank A) |
| 71 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/wiring.py` | 217:0 | block '_mount_summarization' has cyclomatic complexity 2 (rank A) |
| 72 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/wiring.py` | 264:0 | block '_mount_citation_graph' has cyclomatic complexity 2 (rank A) |
| 73 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/wiring.py` | 64:0 | block '_mount_accounts' has cyclomatic complexity 1 (rank A) |
| 74 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/wiring.py` | 145:0 | block '_is_postgres' has cyclomatic complexity 1 (rank A) |
| 75 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/wiring.py` | 253:0 | block '_mount_ops' has cyclomatic complexity 1 (rank A) |
| 76 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/wiring.py` | 36:0 | block 'MountResult' has cyclomatic complexity 1 (rank A) |
| 77 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/middleware/auth.py` | 81:0 | block '_is_public' has cyclomatic complexity 2 (rank A) |
| 78 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/middleware/auth.py` | 85:0 | block '_is_auth_optional' has cyclomatic complexity 2 (rank A) |
| 79 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/middleware/gateway.py` | 123:0 | block '_rate_limit_key' has cyclomatic complexity 4 (rank A) |
| 80 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/middleware/gateway.py` | 163:0 | block '_emit_error' has cyclomatic complexity 3 (rank A) |
| 81 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/middleware/gateway.py` | 14:0 | block '_route_label' has cyclomatic complexity 2 (rank A) |
| 82 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/middleware/gateway.py` | 155:0 | block '_is_ip' has cyclomatic complexity 2 (rank A) |
| 83 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/middleware/gateway.py` | 31:0 | block 'install_gateway_middleware' has cyclomatic complexity 1 (rank A) |
| 84 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/middleware/request_context.py` | 7:0 | block 'RequestContext' has cyclomatic complexity 1 (rank A) |
| 85 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/middleware/security_headers.py` | 16:0 | block 'apply_security_headers' has cyclomatic complexity 2 (rank A) |
| 86 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/middleware/security_headers.py` | 12:0 | block 'build_security_headers' has cyclomatic complexity 1 (rank A) |
| 87 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/middleware/rate_limit.py` | 10:0 | block 'InMemoryRateLimiter' has cyclomatic complexity 5 (rank A) |
| 88 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/middleware/rate_limit.py` | 32:4 | block 'allow' has cyclomatic complexity 5 (rank A) |
| 89 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/middleware/rate_limit.py` | 49:4 | block '_evict_over_cap' has cyclomatic complexity 2 (rank A) |
| 90 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/middleware/wiring.py` | 9:0 | block 'configure_u6_middleware' has cyclomatic complexity 1 (rank A) |
| 91 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/migrations/__init__.py` | 29:0 | block 'apply_migrations' has cyclomatic complexity 5 (rank A) |
| 92 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/migrations/__init__.py` | 60:0 | block 'pending_migrations' has cyclomatic complexity 5 (rank A) |
| 93 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_ops_endpoints.py` | 18:0 | block 'FakeSessionManager' has cyclomatic complexity 5 (rank A) |
| 94 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_ops_endpoints.py` | 19:4 | block 'verify' has cyclomatic complexity 4 (rank A) |
| 95 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_ops_endpoints.py` | 43:0 | block 'client_with_auth' has cyclomatic complexity 1 (rank A) |
| 96 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_citation_graph.py` | 76:0 | block 'test_citation_tree_cache_hit' has cyclomatic complexity 4 (rank A) |
| 97 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_citation_graph.py` | 88:0 | block 'test_depth_query_does_not_create_duplicate_cache' has cyclomatic complexity 4 (rank A) |
| 98 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_citation_graph.py` | 46:0 | block '_client' has cyclomatic complexity 3 (rank A) |
| 99 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_citation_graph.py` | 100:0 | block 'test_citation_tree_rate_limited_and_unavailable' has cyclomatic complexity 3 (rank A) |
| 100 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_citation_graph.py` | 115:0 | block 'test_citation_tree_expand_returns_depth_two' has cyclomatic complexity 3 (rank A) |
| 101 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_citation_graph.py` | 124:0 | block 'test_save_citation_node' has cyclomatic complexity 3 (rank A) |
| 102 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_citation_graph.py` | 134:0 | block 'test_save_nulls_out_of_range_year' has cyclomatic complexity 3 (rank A) |
| 103 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_citation_graph.py` | 17:0 | block 'FixtureProvider' has cyclomatic complexity 3 (rank A) |
| 104 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_citation_graph.py` | 71:0 | block 'test_feature_flag_blocks_endpoint_by_default' has cyclomatic complexity 2 (rank A) |
| 105 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_citation_graph.py` | 145:0 | block 'test_save_rejects_unsaveable_node' has cyclomatic complexity 2 (rank A) |
| 106 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_citation_graph.py` | 153:0 | block 'test_semantic_scholar_provider_url_encodes_path' has cyclomatic complexity 2 (rank A) |
| 107 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_citation_graph.py` | 211:0 | block 'test_semantic_scholar_contract_test_is_opt_in' has cyclomatic complexity 2 (rank A) |
| 108 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_citation_graph.py` | 22:4 | block 'references' has cyclomatic complexity 2 (rank A) |
| 109 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_citation_graph.py` | 186:0 | block 'test_emit_ignores_observability_without_emit_log' has cyclomatic complexity 1 (rank A) |
| 110 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_citation_graph.py` | 18:4 | block '__init__' has cyclomatic complexity 1 (rank A) |
| 111 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_app_shell.py` | 131:0 | block 'test_unhandled_error_is_generic_and_leak_free' has cyclomatic complexity 5 (rank A) |
| 112 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_app_shell.py` | 150:0 | block 'test_u6_gateway_security_headers_and_request_id_live' has cyclomatic complexity 5 (rank A) |
| 113 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_app_shell.py` | 43:0 | block 'test_module_registry_complete_and_disjoint' has cyclomatic complexity 4 (rank A) |
| 114 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_app_shell.py` | 31:0 | block 'test_health_and_liveness' has cyclomatic complexity 3 (rank A) |
| 115 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_app_shell.py` | 37:0 | block 'test_openapi_generates' has cyclomatic complexity 3 (rank A) |
| 116 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_app_shell.py` | 60:0 | block 'test_discovery_and_accounts_actually_mount' has cyclomatic complexity 3 (rank A) |
| 117 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_app_shell.py` | 74:0 | block 'test_discovery_search_endpoint_is_live' has cyclomatic complexity 3 (rank A) |
| 118 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_app_shell.py` | 99:0 | block 'test_absent_module_skips_gracefully_not_fatal' has cyclomatic complexity 3 (rank A) |
| 119 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_app_shell.py` | 111:0 | block 'test_mount_modules_never_raises_and_records_reasons' has cyclomatic complexity 3 (rank A) |
| 120 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_app_shell.py` | 160:0 | block 'test_u6_real_grounding_hook_is_wired_not_stub' has cyclomatic complexity 3 (rank A) |
| 121 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_app_shell.py` | 170:0 | block 'test_u6_observability_captures_gateway_error' has cyclomatic complexity 3 (rank A) |
| 122 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_app_shell.py` | 26:0 | block 'test_app_boots_and_is_fastapi' has cyclomatic complexity 2 (rank A) |
| 123 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_app_shell.py` | 126:0 | block 'test_request_id_is_echoed' has cyclomatic complexity 2 (rank A) |
| 124 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_app_shell.py` | 22:0 | block '_client' has cyclomatic complexity 1 (rank A) |
| 125 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_u6_middleware.py` | 117:0 | block 'test_in_memory_rate_limiter_compacts_expired_keys' has cyclomatic complexity 5 (rank A) |
| 126 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_u6_middleware.py` | 280:0 | block 'test_gateway_emits_telemetry_for_production_exception' has cyclomatic complexity 5 (rank A) |
| 127 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_u6_middleware.py` | 10:0 | block 'test_u6_middleware_adds_security_headers_and_request_id' has cyclomatic complexity 4 (rank A) |
| 128 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_u6_middleware.py` | 25:0 | block 'test_u6_middleware_maps_unhandled_errors_to_generic_response' has cyclomatic complexity 4 (rank A) |
| 129 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_u6_middleware.py` | 68:0 | block 'test_u6_middleware_trusts_proxy_stamped_hop_not_spoofable_leftmost' has cyclomatic complexity 4 (rank A) |
| 130 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_u6_middleware.py` | 153:0 | block '_FakeSessionManager' has cyclomatic complexity 4 (rank A) |
| 131 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_u6_middleware.py` | 40:0 | block 'test_u6_middleware_rate_limit_seam_fails_closed' has cyclomatic complexity 3 (rank A) |
| 132 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_u6_middleware.py` | 54:0 | block 'test_u6_middleware_does_not_trust_forwarded_for_by_default' has cyclomatic complexity 3 (rank A) |
| 133 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_u6_middleware.py` | 171:0 | block 'test_auth_injection_sets_principal_on_request_state' has cyclomatic complexity 3 (rank A) |
| 134 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_u6_middleware.py` | 196:0 | block 'test_auth_injection_rejects_unauthenticated_protected_route' has cyclomatic complexity 3 (rank A) |
| 135 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_u6_middleware.py` | 229:0 | block 'test_auth_injection_optional_for_search_without_cookie' has cyclomatic complexity 3 (rank A) |
| 136 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_u6_middleware.py` | 246:0 | block 'test_auth_injection_fail_closed_on_session_store_failure' has cyclomatic complexity 3 (rank A) |
| 137 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_u6_middleware.py` | 160:4 | block 'verify' has cyclomatic complexity 3 (rank A) |
| 138 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_u6_middleware.py` | 96:0 | block 'test_rate_limit_key_handles_missing_client' has cyclomatic complexity 2 (rank A) |
| 139 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_u6_middleware.py` | 104:0 | block 'test_rate_limit_key_ignores_non_ip_forwarded_value' has cyclomatic complexity 2 (rank A) |
| 140 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_u6_middleware.py` | 213:0 | block 'test_auth_injection_skips_public_paths' has cyclomatic complexity 2 (rank A) |
| 141 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_u6_middleware.py` | 156:4 | block '__init__' has cyclomatic complexity 2 (rank A) |
| 142 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_u6_middleware.py` | 263:0 | block '_RecordingHub' has cyclomatic complexity 2 (rank A) |
| 143 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_u6_middleware.py` | 264:4 | block '__init__' has cyclomatic complexity 1 (rank A) |
| 144 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_u6_middleware.py` | 268:4 | block 'emit_metric' has cyclomatic complexity 1 (rank A) |
| 145 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_u6_middleware.py` | 271:4 | block 'emit_log' has cyclomatic complexity 1 (rank A) |
| 146 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_u6_middleware.py` | 274:4 | block 'start_span' has cyclomatic complexity 1 (rank A) |
| 147 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_u6_middleware.py` | 277:4 | block 'audit_append' has cyclomatic complexity 1 (rank A) |
| 148 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/citation_graph/controller.py` | 173:0 | block '_library_year' has cyclomatic complexity 4 (rank A) |
| 149 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/citation_graph/controller.py` | 273:0 | block 'save_citation_node' has cyclomatic complexity 3 (rank A) |
| 150 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/citation_graph/controller.py` | 69:0 | block 'InMemorySnapshotStore' has cyclomatic complexity 3 (rank A) |
| 151 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/citation_graph/controller.py` | 74:4 | block 'get' has cyclomatic complexity 3 (rank A) |
| 152 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/citation_graph/controller.py` | 116:0 | block '_feature_enabled' has cyclomatic complexity 2 (rank A) |
| 153 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/citation_graph/controller.py` | 130:0 | block 'get_principal' has cyclomatic complexity 2 (rank A) |
| 154 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/citation_graph/controller.py` | 214:0 | block '_emit' has cyclomatic complexity 2 (rank A) |
| 155 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/citation_graph/controller.py` | 20:0 | block '_max_visible_nodes' has cyclomatic complexity 1 (rank A) |
| 156 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/citation_graph/controller.py` | 24:0 | block '_snapshot_ttl_seconds' has cyclomatic complexity 1 (rank A) |
| 157 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/citation_graph/controller.py` | 137:0 | block 'get_snapshot_store' has cyclomatic complexity 1 (rank A) |
| 158 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/citation_graph/controller.py` | 141:0 | block 'get_provider' has cyclomatic complexity 1 (rank A) |
| 159 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/citation_graph/controller.py` | 28:0 | block 'CitationNode' has cyclomatic complexity 1 (rank A) |
| 160 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/citation_graph/controller.py` | 40:0 | block 'CitationEdge' has cyclomatic complexity 1 (rank A) |
| 161 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/citation_graph/controller.py` | 46:0 | block 'UnresolvedCitation' has cyclomatic complexity 1 (rank A) |
| 162 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/citation_graph/controller.py` | 52:0 | block 'CitationTreeResponse' has cyclomatic complexity 1 (rank A) |
| 163 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/citation_graph/controller.py` | 65:0 | block 'SaveCitationNodeRequest' has cyclomatic complexity 1 (rank A) |
| 164 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/citation_graph/controller.py` | 71:4 | block '__init__' has cyclomatic complexity 1 (rank A) |
| 165 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/citation_graph/controller.py` | 84:4 | block 'set' has cyclomatic complexity 1 (rank A) |
| 166 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/citation_graph/controller.py` | 89:4 | block '__init__' has cyclomatic complexity 1 (rank A) |
| 167 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_domain_grounding.py` | 16:0 | block 'test_valid_draft_passes' has cyclomatic complexity 3 (rank A) |
| 168 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_domain_grounding.py` | 22:0 | block 'test_fabricated_anchor_fails' has cyclomatic complexity 3 (rank A) |
| 169 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_domain_grounding.py` | 32:0 | block 'test_numeric_mismatch_fails' has cyclomatic complexity 3 (rank A) |
| 170 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_domain_grounding.py` | 39:0 | block 'test_schema_incomplete_fails' has cyclomatic complexity 3 (rank A) |
| 171 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_domain_grounding.py` | 12:0 | block '_gi' has cyclomatic complexity 1 (rank A) |
| 172 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/conftest.py` | 12:0 | block 'sample_paper' has cyclomatic complexity 1 (rank A) |
| 173 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/conftest.py` | 17:0 | block 'valid_draft_fixture' has cyclomatic complexity 1 (rank A) |
| 174 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_glossary_upsert.py` | 131:0 | block 'test_glossary_endpoint_rejects_blank_missing_or_oversized' has cyclomatic complexity 5 (rank A) |
| 175 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_glossary_upsert.py` | 92:0 | block '_endpoint' has cyclomatic complexity 4 (rank A) |
| 176 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_glossary_upsert.py` | 112:0 | block 'test_glossary_endpoint_upserts_and_returns_version' has cyclomatic complexity 4 (rank A) |
| 177 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_glossary_upsert.py` | 140:0 | block 'test_glossary_list_returns_owner_terms' has cyclomatic complexity 4 (rank A) |
| 178 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_glossary_upsert.py` | 36:0 | block 'test_resolver_upsert_delegates_and_defaults_to_post_substitution' has cyclomatic complexity 3 (rank A) |
| 179 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_glossary_upsert.py` | 153:0 | block 'test_glossary_endpoint_fails_closed_on_repo_error' has cyclomatic complexity 3 (rank A) |
| 180 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_glossary_upsert.py` | 73:0 | block '_FakeOrchestrator' has cyclomatic complexity 3 (rank A) |
| 181 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_glossary_upsert.py` | 49:0 | block 'test_post_substitute_inserts_term_to_literally' has cyclomatic complexity 2 (rank A) |
| 182 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_glossary_upsert.py` | 123:0 | block 'test_glossary_endpoint_requires_principal' has cyclomatic complexity 2 (rank A) |
| 183 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_glossary_upsert.py` | 148:0 | block 'test_glossary_list_requires_principal' has cyclomatic complexity 2 (rank A) |
| 184 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_glossary_upsert.py` | 21:0 | block '_FakeRepo' has cyclomatic complexity 2 (rank A) |
| 185 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_glossary_upsert.py` | 60:0 | block '_FakeState' has cyclomatic complexity 2 (rank A) |
| 186 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_glossary_upsert.py` | 65:0 | block '_FakeRequest' has cyclomatic complexity 2 (rank A) |
| 187 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_glossary_upsert.py` | 74:4 | block '__init__' has cyclomatic complexity 2 (rank A) |
| 188 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_glossary_upsert.py` | 79:4 | block 'upsert_glossary_term' has cyclomatic complexity 2 (rank A) |
| 189 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_glossary_upsert.py` | 85:4 | block 'list_glossary_terms' has cyclomatic complexity 2 (rank A) |
| 190 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_glossary_upsert.py` | 44:0 | block 'test_resolver_upsert_without_repo_raises' has cyclomatic complexity 1 (rank A) |
| 191 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_glossary_upsert.py` | 102:0 | block '_invoke' has cyclomatic complexity 1 (rank A) |
| 192 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_glossary_upsert.py` | 107:0 | block '_invoke_list' has cyclomatic complexity 1 (rank A) |
| 193 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_glossary_upsert.py` | 22:4 | block '__init__' has cyclomatic complexity 1 (rank A) |
| 194 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_glossary_upsert.py` | 25:4 | block 'get_user_glossary' has cyclomatic complexity 1 (rank A) |
| 195 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_glossary_upsert.py` | 28:4 | block 'get_glossary_version' has cyclomatic complexity 1 (rank A) |
| 196 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_glossary_upsert.py` | 31:4 | block 'upsert_term' has cyclomatic complexity 1 (rank A) |
| 197 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_glossary_upsert.py` | 61:4 | block '__init__' has cyclomatic complexity 1 (rank A) |
| 198 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_glossary_upsert.py` | 68:4 | block '__init__' has cyclomatic complexity 1 (rank A) |
| 199 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_domain_source_cache_length.py` | 63:0 | block 'test_cache_key_scope_dimension' has cyclomatic complexity 5 (rank A) |
| 200 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_domain_source_cache_length.py` | 55:0 | block 'test_cache_key_is_immutable_and_pathed' has cyclomatic complexity 4 (rank A) |
| 201 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_domain_source_cache_length.py` | 78:0 | block 'test_length_router_branches' has cyclomatic complexity 4 (rank A) |
| 202 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_domain_source_cache_length.py` | 25:0 | block 'test_summary_falls_back_to_abstract' has cyclomatic complexity 3 (rank A) |
| 203 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_domain_source_cache_length.py` | 47:0 | block 'test_translate_full_falls_back_to_abstract' has cyclomatic complexity 3 (rank A) |
| 204 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_domain_source_cache_length.py` | 20:0 | block 'test_summary_uses_full_text' has cyclomatic complexity 2 (rank A) |
| 205 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_domain_source_cache_length.py` | 31:0 | block 'test_summary_none_when_no_source' has cyclomatic complexity 2 (rank A) |
| 206 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_domain_source_cache_length.py` | 35:0 | block 'test_translate_uses_abstract' has cyclomatic complexity 2 (rank A) |
| 207 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_domain_source_cache_length.py` | 40:0 | block 'test_translate_full_uses_full_text' has cyclomatic complexity 2 (rank A) |
| 208 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_domain_source_cache_length.py` | 12:0 | block '_req' has cyclomatic complexity 1 (rank A) |
| 209 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_integration_real.py` | 29:0 | block 'test_real_bundle_builds' has cyclomatic complexity 3 (rank A) |
| 210 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_integration_real.py` | 15:0 | block '_missing' has cyclomatic complexity 2 (rank A) |
| 211 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_pbt.py` | 67:0 | block 'test_pbt_response_to_dict_sec9' has cyclomatic complexity 4 (rank A) |
| 212 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_pbt.py` | 34:0 | block 'test_pbt_cache_key_deterministic' has cyclomatic complexity 3 (rank A) |
| 213 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_pbt.py` | 44:0 | block 'test_pbt_refine_idempotent' has cyclomatic complexity 2 (rank A) |
| 214 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_pbt.py` | 52:0 | block 'test_pbt_post_substitution_idempotent' has cyclomatic complexity 2 (rank A) |
| 215 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_pbt.py` | 60:0 | block 'test_pbt_keep_as_is_invariant' has cyclomatic complexity 2 (rank A) |
| 216 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_orchestrator.py` | 36:0 | block 'test_cache_hit_skips_llm' has cyclomatic complexity 4 (rank A) |
| 217 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_orchestrator.py` | 70:0 | block 'test_grounding_failure_abstains_after_retry' has cyclomatic complexity 4 (rank A) |
| 218 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_orchestrator.py` | 91:0 | block 'test_translate_path' has cyclomatic complexity 4 (rank A) |
| 219 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_orchestrator.py` | 62:0 | block 'test_summary_ok_writes_through' has cyclomatic complexity 3 (rank A) |
| 220 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_orchestrator.py` | 50:0 | block 'test_cost_degraded_abstains_before_llm' has cyclomatic complexity 2 (rank A) |
| 221 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_orchestrator.py` | 56:0 | block 'test_source_unavailable' has cyclomatic complexity 2 (rank A) |
| 222 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_orchestrator.py` | 84:0 | block 'test_llm_outage_then_recovery' has cyclomatic complexity 2 (rank A) |
| 223 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_orchestrator.py` | 28:0 | block '_ctx' has cyclomatic complexity 1 (rank A) |
| 224 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_orchestrator.py` | 32:0 | block '_req' has cyclomatic complexity 1 (rank A) |
| 225 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/stubs.py` | 61:0 | block 'StubLlm' has cyclomatic complexity 4 (rank A) |
| 226 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/stubs.py` | 67:4 | block 'summarize' has cyclomatic complexity 3 (rank A) |
| 227 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/stubs.py` | 73:4 | block 'translate' has cyclomatic complexity 3 (rank A) |
| 228 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/stubs.py` | 81:0 | block 'StubStore' has cyclomatic complexity 2 (rank A) |
| 229 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/stubs.py` | 94:0 | block 'StubFullText' has cyclomatic complexity 2 (rank A) |
| 230 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/stubs.py` | 109:0 | block 'StubCostGuard' has cyclomatic complexity 2 (rank A) |
| 231 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/stubs.py` | 116:0 | block 'StubObservability' has cyclomatic complexity 2 (rank A) |
| 232 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/stubs.py` | 45:0 | block 'valid_draft' has cyclomatic complexity 1 (rank A) |
| 233 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/stubs.py` | 85:4 | block 'get' has cyclomatic complexity 1 (rank A) |
| 234 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/stubs.py` | 88:4 | block 'put' has cyclomatic complexity 1 (rank A) |
| 235 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/stubs.py` | 97:4 | block 'get_full_text' has cyclomatic complexity 1 (rank A) |
| 236 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/stubs.py` | 102:0 | block '_Budget' has cyclomatic complexity 1 (rank A) |
| 237 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/stubs.py` | 112:4 | block 'get_budget_state' has cyclomatic complexity 1 (rank A) |
| 238 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/stubs.py` | 117:4 | block '__init__' has cyclomatic complexity 1 (rank A) |
| 239 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/stubs.py` | 120:4 | block 'emit_metric' has cyclomatic complexity 1 (rank A) |
| 240 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/stubs.py` | 123:4 | block 'emit_log' has cyclomatic complexity 1 (rank A) |
| 241 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/stubs.py` | 126:4 | block 'start_span' has cyclomatic complexity 1 (rank A) |
| 242 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/stubs.py` | 129:4 | block 'audit_append' has cyclomatic complexity 1 (rank A) |
| 243 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_domain_refiner.py` | 15:0 | block 'test_preserves_captions_appendix_and_results' has cyclomatic complexity 5 (rank A) |
| 244 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_domain_refiner.py` | 8:0 | block 'test_removes_references_and_copyright' has cyclomatic complexity 4 (rank A) |
| 245 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_domain_glossary.py` | 9:0 | block 'test_post_substitute_applies_user_simple_noun' has cyclomatic complexity 3 (rank A) |
| 246 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_domain_glossary.py` | 32:0 | block 'test_resolve_includes_seed_keep_as_is' has cyclomatic complexity 3 (rank A) |
| 247 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_domain_glossary.py` | 18:0 | block 'test_post_substitute_is_idempotent' has cyclomatic complexity 2 (rank A) |
| 248 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_domain_glossary.py` | 25:0 | block 'test_prompt_enforced_overrides_are_not_post_substituted' has cyclomatic complexity 2 (rank A) |
| 249 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/real_wiring.py` | 34:0 | block 'build_real_orchestrator' has cyclomatic complexity 2 (rank A) |
| 250 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/real_wiring.py` | 29:0 | block 'SummarizationBundle' has cyclomatic complexity 1 (rank A) |
| 251 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/adapters/s3_redis_store.py` | 40:4 | block 'get' has cyclomatic complexity 5 (rank A) |
| 252 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/adapters/s3_redis_store.py` | 16:0 | block 'S3RedisSummaryStore' has cyclomatic complexity 4 (rank A) |
| 253 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/adapters/s3_redis_store.py` | 17:4 | block '__init__' has cyclomatic complexity 4 (rank A) |
| 254 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/adapters/s3_redis_store.py` | 68:4 | block '_backfill_hot' has cyclomatic complexity 3 (rank A) |
| 255 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/adapters/s3_redis_store.py` | 57:4 | block 'put' has cyclomatic complexity 1 (rank A) |
| 256 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/adapters/s3_full_text.py` | 15:0 | block 'S3FullTextSource' has cyclomatic complexity 3 (rank A) |
| 257 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/adapters/s3_full_text.py` | 16:4 | block '__init__' has cyclomatic complexity 2 (rank A) |
| 258 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/adapters/s3_full_text.py` | 32:4 | block 'get_full_text' has cyclomatic complexity 2 (rank A) |
| 259 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/adapters/bedrock_llm.py` | 82:4 | block '_stream_text' has cyclomatic complexity 4 (rank A) |
| 260 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/adapters/bedrock_llm.py` | 101:0 | block '_parse_json' has cyclomatic complexity 3 (rank A) |
| 261 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/adapters/bedrock_llm.py` | 108:0 | block '_to_summary_draft' has cyclomatic complexity 3 (rank A) |
| 262 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/adapters/bedrock_llm.py` | 28:0 | block 'BedrockLlmGateway' has cyclomatic complexity 3 (rank A) |
| 263 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/adapters/bedrock_llm.py` | 66:4 | block '_invoke_json' has cyclomatic complexity 3 (rank A) |
| 264 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/adapters/bedrock_llm.py` | 130:0 | block '_anchor_target' has cyclomatic complexity 2 (rank A) |
| 265 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/adapters/bedrock_llm.py` | 29:4 | block '__init__' has cyclomatic complexity 2 (rank A) |
| 266 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/adapters/bedrock_llm.py` | 48:4 | block 'summarize' has cyclomatic complexity 1 (rank A) |
| 267 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/adapters/bedrock_llm.py` | 55:4 | block 'translate' has cyclomatic complexity 1 (rank A) |
| 268 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/adapters/rds_glossary.py` | 17:0 | block 'RdsGlossaryRepository' has cyclomatic complexity 3 (rank A) |
| 269 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/adapters/rds_glossary.py` | 22:4 | block '_connect' has cyclomatic complexity 2 (rank A) |
| 270 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/adapters/rds_glossary.py` | 29:4 | block 'get_user_glossary' has cyclomatic complexity 2 (rank A) |
| 271 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/adapters/rds_glossary.py` | 41:4 | block 'get_glossary_version' has cyclomatic complexity 2 (rank A) |
| 272 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/adapters/rds_glossary.py` | 48:4 | block 'upsert_term' has cyclomatic complexity 2 (rank A) |
| 273 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/adapters/rds_glossary.py` | 18:4 | block '__init__' has cyclomatic complexity 1 (rank A) |
| 274 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/adapters/settings.py` | 20:0 | block 'SummarizationSettings' has cyclomatic complexity 3 (rank A) |
| 275 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/adapters/settings.py` | 40:4 | block 'from_env' has cyclomatic complexity 2 (rank A) |
| 276 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/adapters/settings.py` | 35:4 | block 'summarization_enabled' has cyclomatic complexity 1 (rank A) |
| 277 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/prompts/templates.py` | 43:0 | block 'build_summary_prompt' has cyclomatic complexity 1 (rank A) |
| 278 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/prompts/templates.py` | 64:0 | block 'build_translate_prompt' has cyclomatic complexity 1 (rank A) |
| 279 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/api/router.py` | 104:0 | block '_principal_user_id' has cyclomatic complexity 5 (rank A) |
| 280 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/api/router.py` | 135:0 | block '_parse_request' has cyclomatic complexity 4 (rank A) |
| 281 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/api/router.py` | 159:0 | block '_enum_or_default' has cyclomatic complexity 3 (rank A) |
| 282 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/api/router.py` | 29:0 | block 'build_router' has cyclomatic complexity 1 (rank A) |
| 283 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/api/gateway_seam.py` | 15:0 | block 'run_summarization' has cyclomatic complexity 2 (rank A) |
| 284 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/service/orchestrator.py` | 40:0 | block '_is_cost_degraded' has cyclomatic complexity 4 (rank A) |
| 285 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/service/orchestrator.py` | 47:0 | block 'SummarizationOrchestrationService' has cyclomatic complexity 4 (rank A) |
| 286 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/service/orchestrator.py` | 174:4 | block '_glossary_version' has cyclomatic complexity 3 (rank A) |
| 287 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/service/orchestrator.py` | 183:4 | block '_emit' has cyclomatic complexity 3 (rank A) |
| 288 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/service/orchestrator.py` | 152:4 | block 'list_glossary_terms' has cyclomatic complexity 2 (rank A) |
| 289 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/service/orchestrator.py` | 194:0 | block '_CachedResult' has cyclomatic complexity 2 (rank A) |
| 290 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/service/orchestrator.py` | 48:4 | block '__init__' has cyclomatic complexity 1 (rank A) |
| 291 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/service/orchestrator.py` | 160:4 | block 'upsert_glossary_term' has cyclomatic complexity 1 (rank A) |
| 292 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/service/orchestrator.py` | 168:4 | block 'full_text' has cyclomatic complexity 1 (rank A) |
| 293 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/service/orchestrator.py` | 199:4 | block '__init__' has cyclomatic complexity 1 (rank A) |
| 294 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/service/orchestrator.py` | 203:4 | block 'to_dict' has cyclomatic complexity 1 (rank A) |
| 295 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/ports/ports.py` | 37:0 | block 'LlmGatewayPort' has cyclomatic complexity 2 (rank A) |
| 296 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/ports/ports.py` | 58:0 | block 'SummaryStorePort' has cyclomatic complexity 2 (rank A) |
| 297 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/ports/ports.py` | 71:0 | block 'FullTextSourcePort' has cyclomatic complexity 2 (rank A) |
| 298 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/ports/ports.py` | 80:0 | block 'GlossaryRepositoryPort' has cyclomatic complexity 2 (rank A) |
| 299 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/ports/ports.py` | 32:0 | block 'LlmUnavailable' has cyclomatic complexity 1 (rank A) |
| 300 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/ports/ports.py` | 44:4 | block 'summarize' has cyclomatic complexity 1 (rank A) |
| 301 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/ports/ports.py` | 50:4 | block 'translate' has cyclomatic complexity 1 (rank A) |
| 302 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/ports/ports.py` | 61:4 | block 'get' has cyclomatic complexity 1 (rank A) |
| 303 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/ports/ports.py` | 65:4 | block 'put' has cyclomatic complexity 1 (rank A) |
| 304 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/ports/ports.py` | 74:4 | block 'get_full_text' has cyclomatic complexity 1 (rank A) |
| 305 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/ports/ports.py` | 83:4 | block 'get_user_glossary' has cyclomatic complexity 1 (rank A) |
| 306 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/ports/ports.py` | 87:4 | block 'get_glossary_version' has cyclomatic complexity 1 (rank A) |
| 307 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/ports/ports.py` | 91:4 | block 'upsert_term' has cyclomatic complexity 1 (rank A) |
| 308 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/refiner.py` | 58:0 | block 'InputRefiner' has cyclomatic complexity 4 (rank A) |
| 309 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/refiner.py` | 59:4 | block 'refine' has cyclomatic complexity 4 (rank A) |
| 310 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/refiner.py` | 84:4 | block '_derive_sections' has cyclomatic complexity 2 (rank A) |
| 311 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/refiner.py` | 53:0 | block '_estimate_tokens' has cyclomatic complexity 1 (rank A) |
| 312 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/models.py` | 188:0 | block 'SummaryResultDTO' has cyclomatic complexity 5 (rank A) |
| 313 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/models.py` | 195:4 | block 'to_dict' has cyclomatic complexity 4 (rank A) |
| 314 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/models.py` | 77:0 | block 'SummaryCacheKey' has cyclomatic complexity 2 (rank A) |
| 315 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/models.py` | 231:0 | block 'AbstainDTO' has cyclomatic complexity 2 (rank A) |
| 316 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/models.py` | 239:0 | block 'CostDegradedDTO' has cyclomatic complexity 2 (rank A) |
| 317 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/models.py` | 247:0 | block 'SourceUnavailableDTO' has cyclomatic complexity 2 (rank A) |
| 318 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/models.py` | 15:0 | block 'Task' has cyclomatic complexity 1 (rank A) |
| 319 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/models.py` | 20:0 | block 'Persona' has cyclomatic complexity 1 (rank A) |
| 320 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/models.py` | 25:0 | block 'Scope' has cyclomatic complexity 1 (rank A) |
| 321 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/models.py` | 32:0 | block 'TargetLang' has cyclomatic complexity 1 (rank A) |
| 322 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/models.py` | 36:0 | block 'SourceKind' has cyclomatic complexity 1 (rank A) |
| 323 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/models.py` | 41:0 | block 'AnchorTarget' has cyclomatic complexity 1 (rank A) |
| 324 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/models.py` | 49:0 | block 'AuthSession' has cyclomatic complexity 1 (rank A) |
| 325 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/models.py` | 56:0 | block 'RequestContext' has cyclomatic complexity 1 (rank A) |
| 326 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/models.py` | 62:0 | block 'SummaryRequest' has cyclomatic complexity 1 (rank A) |
| 327 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/models.py` | 88:4 | block 'object_path' has cyclomatic complexity 1 (rank A) |
| 328 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/models.py` | 96:4 | block 'redis_key' has cyclomatic complexity 1 (rank A) |
| 329 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/models.py` | 103:0 | block 'SourceText' has cyclomatic complexity 1 (rank A) |
| 330 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/models.py` | 110:0 | block 'Section' has cyclomatic complexity 1 (rank A) |
| 331 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/models.py` | 117:0 | block 'RefinedSource' has cyclomatic complexity 1 (rank A) |
| 332 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/models.py` | 127:0 | block 'TermMapping' has cyclomatic complexity 1 (rank A) |
| 333 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/models.py` | 134:0 | block 'Glossary' has cyclomatic complexity 1 (rank A) |
| 334 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/models.py` | 142:0 | block 'Anchor' has cyclomatic complexity 1 (rank A) |
| 335 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/models.py` | 150:0 | block 'SummaryDraft' has cyclomatic complexity 1 (rank A) |
| 336 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/models.py` | 161:0 | block 'TranslationDraft' has cyclomatic complexity 1 (rank A) |
| 337 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/models.py` | 168:0 | block 'GroundingInput' has cyclomatic complexity 1 (rank A) |
| 338 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/models.py` | 174:0 | block 'Violation' has cyclomatic complexity 1 (rank A) |
| 339 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/models.py` | 180:0 | block 'AnchorVerdict' has cyclomatic complexity 1 (rank A) |
| 340 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/models.py` | 234:4 | block 'to_dict' has cyclomatic complexity 1 (rank A) |
| 341 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/models.py` | 242:4 | block 'to_dict' has cyclomatic complexity 1 (rank A) |
| 342 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/models.py` | 250:4 | block 'to_dict' has cyclomatic complexity 1 (rank A) |
| 343 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/cache_key.py` | 16:0 | block 'build_cache_key' has cyclomatic complexity 2 (rank A) |
| 344 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/assembler.py` | 21:0 | block 'ResultAssembler' has cyclomatic complexity 3 (rank A) |
| 345 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/assembler.py` | 22:4 | block 'assemble_summary' has cyclomatic complexity 2 (rank A) |
| 346 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/assembler.py` | 28:4 | block 'assemble_translation' has cyclomatic complexity 2 (rank A) |
| 347 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/grounding.py` | 25:0 | block '_normalize_number' has cyclomatic complexity 3 (rank A) |
| 348 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/grounding.py` | 72:0 | block '_source_numbers' has cyclomatic complexity 3 (rank A) |
| 349 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/grounding.py` | 80:0 | block 'is_empty_draft' has cyclomatic complexity 2 (rank A) |
| 350 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/length_router.py` | 24:0 | block 'LengthRouter' has cyclomatic complexity 3 (rank A) |
| 351 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/length_router.py` | 34:4 | block 'route' has cyclomatic complexity 3 (rank A) |
| 352 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/length_router.py` | 18:0 | block 'LengthRoute' has cyclomatic complexity 1 (rank A) |
| 353 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/length_router.py` | 25:4 | block '__init__' has cyclomatic complexity 1 (rank A) |
| 354 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/source_selector.py` | 14:0 | block 'SourceSelector' has cyclomatic complexity 4 (rank A) |
| 355 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/source_selector.py` | 15:4 | block '__init__' has cyclomatic complexity 1 (rank A) |
| 356 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/source_selector.py` | 18:4 | block 'fetch_full_text' has cyclomatic complexity 1 (rank A) |
| 357 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/glossary.py` | 66:4 | block 'post_substitute' has cyclomatic complexity 4 (rank A) |
| 358 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/glossary.py` | 32:0 | block 'GlossaryResolver' has cyclomatic complexity 3 (rank A) |
| 359 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/glossary.py` | 36:4 | block 'resolve' has cyclomatic complexity 3 (rank A) |
| 360 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/glossary.py` | 46:4 | block 'list_user_terms' has cyclomatic complexity 2 (rank A) |
| 361 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/glossary.py` | 53:4 | block 'upsert_term' has cyclomatic complexity 2 (rank A) |
| 362 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/glossary.py` | 33:4 | block '__init__' has cyclomatic complexity 1 (rank A) |
| 363 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_paper_metadata.py` | 33:0 | block 'test_known_paper_by_display_arxiv_id' has cyclomatic complexity 3 (rank A) |
| 364 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_paper_metadata.py` | 40:0 | block 'test_unknown_paper_returns_none' has cyclomatic complexity 2 (rank A) |
| 365 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_paper_metadata.py` | 17:0 | block '_service' has cyclomatic complexity 1 (rank A) |
| 366 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_paper_metadata.py` | 44:0 | block 'test_store_outage_is_fail_closed' has cyclomatic complexity 1 (rank A) |
| 367 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_event_publisher.py` | 30:0 | block 'test_publish_sends_one_eventbridge_entry' has cyclomatic complexity 5 (rank A) |
| 368 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_event_publisher.py` | 13:0 | block 'FakeEvents' has cyclomatic complexity 3 (rank A) |
| 369 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_event_publisher.py` | 18:4 | block 'put_events' has cyclomatic complexity 2 (rank A) |
| 370 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_event_publisher.py` | 24:0 | block '_event' has cyclomatic complexity 1 (rank A) |
| 371 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_event_publisher.py` | 45:0 | block 'test_publish_swallows_send_errors' has cyclomatic complexity 1 (rank A) |
| 372 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_event_publisher.py` | 14:4 | block '__init__' has cyclomatic complexity 1 (rank A) |
| 373 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_validator_pbt.py` | 22:0 | block 'test_normalize_has_no_double_spaces_and_is_trimmed' has cyclomatic complexity 3 (rank A) |
| 374 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_validator_pbt.py` | 28:0 | block 'test_empty_and_whitespace_rejected' has cyclomatic complexity 3 (rank A) |
| 375 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_validator_pbt.py` | 37:0 | block 'test_too_long_rejected' has cyclomatic complexity 3 (rank A) |
| 376 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_validator_pbt.py` | 14:0 | block 'test_normalize_is_idempotent' has cyclomatic complexity 2 (rank A) |
| 377 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_validator_pbt.py` | 33:0 | block 'test_control_chars_rejected' has cyclomatic complexity 2 (rank A) |
| 378 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_validator_pbt.py` | 42:0 | block 'test_korean_query_accepted' has cyclomatic complexity 2 (rank A) |
| 379 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_router.py` | 33:0 | block 'test_global_catch_all_handler_is_generic_500' has cyclomatic complexity 5 (rank A) |
| 380 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_router.py` | 25:0 | block 'test_search_unavailable_handler_is_generic_503' has cyclomatic complexity 3 (rank A) |
| 381 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_router.py` | 20:0 | block '_app' has cyclomatic complexity 1 (rank A) |
| 382 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_opensearch_integration.py` | 70:0 | block 'test_knn_returns_real_index_records' has cyclomatic complexity 5 (rank A) |
| 383 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_opensearch_integration.py` | 89:0 | block 'test_hybrid_retrieve_dedups_by_paper_id' has cyclomatic complexity 4 (rank A) |
| 384 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_opensearch_integration.py` | 82:0 | block 'test_bm25_matches_lexical_terms' has cyclomatic complexity 3 (rank A) |
| 385 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_opensearch_integration.py` | 42:0 | block 'live' has cyclomatic complexity 2 (rank A) |
| 386 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_opensearch_integration.py` | 63:0 | block 'settings_or_skip' has cyclomatic complexity 2 (rank A) |
| 387 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_orchestrator.py` | 41:0 | block 'test_no_match_is_empty_page_not_abstain' has cyclomatic complexity 5 (rank A) |
| 388 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_orchestrator.py` | 63:0 | block 'test_validation_error_does_not_publish' has cyclomatic complexity 3 (rank A) |
| 389 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_orchestrator.py` | 72:0 | block 'test_korean_query_matches_english_paper_cross_lingual' has cyclomatic complexity 3 (rank A) |
| 390 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_orchestrator.py` | 54:0 | block 'test_grounding_verdict_abstain_maps_to_abstain' has cyclomatic complexity 2 (rank A) |
| 391 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_orchestrator.py` | 21:0 | block '_ctx' has cyclomatic complexity 1 (rank A) |
| 392 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_observability_wiring.py` | 53:0 | block 'test_injected_hub_receives_grounding_health_metric' has cyclomatic complexity 5 (rank A) |
| 393 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_observability_wiring.py` | 68:0 | block 'test_no_match_does_not_emit_grounding_health' has cyclomatic complexity 4 (rank A) |
| 394 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_observability_wiring.py` | 46:0 | block 'test_injected_hub_receives_search_candidates_metric' has cyclomatic complexity 2 (rank A) |
| 395 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_observability_wiring.py` | 16:0 | block 'RecordingHub' has cyclomatic complexity 2 (rank A) |
| 396 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_observability_wiring.py` | 32:0 | block '_ctx' has cyclomatic complexity 1 (rank A) |
| 397 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_observability_wiring.py` | 36:0 | block '_run' has cyclomatic complexity 1 (rank A) |
| 398 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_observability_wiring.py` | 19:4 | block '__init__' has cyclomatic complexity 1 (rank A) |
| 399 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_observability_wiring.py` | 22:4 | block 'emit_metric' has cyclomatic complexity 1 (rank A) |
| 400 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_observability_wiring.py` | 25:4 | block 'emit_log' has cyclomatic complexity 1 (rank A) |
| 401 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_observability_wiring.py` | 26:4 | block 'start_span' has cyclomatic complexity 1 (rank A) |
| 402 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_observability_wiring.py` | 29:4 | block 'audit_append' has cyclomatic complexity 1 (rank A) |
| 403 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_bedrock_embedding.py` | 39:0 | block 'test_embed_query_uses_search_query_input_type' has cyclomatic complexity 5 (rank A) |
| 404 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_bedrock_embedding.py` | 22:0 | block 'FakeBedrock' has cyclomatic complexity 3 (rank A) |
| 405 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_bedrock_embedding.py` | 28:4 | block 'invoke_model' has cyclomatic complexity 3 (rank A) |
| 406 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_bedrock_embedding.py` | 52:0 | block 'test_embed_query_handles_bare_list_embeddings_shape' has cyclomatic complexity 2 (rank A) |
| 407 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_bedrock_embedding.py` | 14:0 | block '_Body' has cyclomatic complexity 2 (rank A) |
| 408 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_bedrock_embedding.py` | 35:0 | block '_vec' has cyclomatic complexity 1 (rank A) |
| 409 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_bedrock_embedding.py` | 58:0 | block 'test_transient_failure_raises_embedding_unavailable' has cyclomatic complexity 1 (rank A) |
| 410 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_bedrock_embedding.py` | 66:0 | block 'test_empty_embedding_raises_embedding_unavailable' has cyclomatic complexity 1 (rank A) |
| 411 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_bedrock_embedding.py` | 73:0 | block 'test_dimension_mismatch_fails_loud' has cyclomatic complexity 1 (rank A) |
| 412 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_bedrock_embedding.py` | 15:4 | block '__init__' has cyclomatic complexity 1 (rank A) |
| 413 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_bedrock_embedding.py` | 18:4 | block 'read' has cyclomatic complexity 1 (rank A) |
| 414 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_bedrock_embedding.py` | 23:4 | block '__init__' has cyclomatic complexity 1 (rank A) |
| 415 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_fault_injection.py` | 23:0 | block 'test_embedding_outage_falls_back_to_lexical_only' has cyclomatic complexity 3 (rank A) |
| 416 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_fault_injection.py` | 19:0 | block '_ctx' has cyclomatic complexity 1 (rank A) |
| 417 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_fault_injection.py` | 33:0 | block 'test_index_outage_fails_closed' has cyclomatic complexity 1 (rank A) |
| 418 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_fault_injection.py` | 42:0 | block 'test_vector_store_outage_fails_closed' has cyclomatic complexity 1 (rank A) |
| 419 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_dto_roundtrip_pbt.py` | 46:0 | block 'test_success_page_roundtrip_and_card_shape' has cyclomatic complexity 5 (rank A) |
| 420 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_dto_roundtrip_pbt.py` | 32:0 | block 'test_empty_page_roundtrip' has cyclomatic complexity 3 (rank A) |
| 421 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_dto_roundtrip_pbt.py` | 57:0 | block 'test_degraded_roundtrip' has cyclomatic complexity 3 (rank A) |
| 422 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_dto_roundtrip_pbt.py` | 23:0 | block '_roundtrip' has cyclomatic complexity 2 (rank A) |
| 423 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_dto_roundtrip_pbt.py` | 27:0 | block 'test_abstain_roundtrip' has cyclomatic complexity 1 (rank A) |
| 424 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_dto_roundtrip_pbt.py` | 41:0 | block 'test_validation_error_roundtrip' has cyclomatic complexity 1 (rank A) |
| 425 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_degradation.py` | 16:0 | block 'test_rerank_off_is_degraded_banner' has cyclomatic complexity 4 (rank A) |
| 426 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_degradation.py` | 29:0 | block 'test_lexical_only_english_returns_degraded_results' has cyclomatic complexity 3 (rank A) |
| 427 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_degradation.py` | 41:0 | block 'test_lexical_only_korean_is_empty_page' has cyclomatic complexity 3 (rank A) |
| 428 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_degradation.py` | 12:0 | block '_ctx' has cyclomatic complexity 1 (rank A) |
| 429 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_retriever_pbt.py` | 15:0 | block 'test_dedup_unique_paper_ids_and_preserves_set' has cyclomatic complexity 5 (rank A) |
| 430 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_retriever_pbt.py` | 26:0 | block 'test_two_lists_merge_preserves_union' has cyclomatic complexity 5 (rank A) |
| 431 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_retriever_pbt.py` | 33:0 | block 'test_fusion_is_deterministic' has cyclomatic complexity 5 (rank A) |
| 432 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_ranker_pbt.py` | 35:0 | block 'test_truncates_to_top_n_and_sorted_descending' has cyclomatic complexity 4 (rank A) |
| 433 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_ranker_pbt.py` | 26:0 | block '_candidates' has cyclomatic complexity 2 (rank A) |
| 434 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_ranker_pbt.py` | 43:0 | block 'test_order_is_stable_deterministic' has cyclomatic complexity 2 (rank A) |
| 435 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_ranker_pbt.py` | 50:0 | block 'test_fewer_than_n_returns_all' has cyclomatic complexity 2 (rank A) |
| 436 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_assembler.py` | 18:0 | block 'test_no_match_is_empty_page_not_abstain' has cyclomatic complexity 4 (rank A) |
| 437 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_assembler.py` | 38:0 | block 'test_no_match_degraded_is_empty_page_no_banner' has cyclomatic complexity 4 (rank A) |
| 438 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_assembler.py` | 25:0 | block 'test_empty_grounded_normal_is_empty_page' has cyclomatic complexity 3 (rank A) |
| 439 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_assembler.py` | 31:0 | block 'test_empty_grounded_degraded_is_empty_page_no_banner' has cyclomatic complexity 3 (rank A) |
| 440 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_assembler.py` | 46:0 | block 'test_grounding_refusal_is_abstain' has cyclomatic complexity 3 (rank A) |
| 441 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_opensearch_adapter.py` | 48:0 | block 'test_bm25_search_builds_match_query_over_lexical_terms' has cyclomatic complexity 3 (rank A) |
| 442 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_opensearch_adapter.py` | 20:0 | block 'FakeSearchClient' has cyclomatic complexity 3 (rank A) |
| 443 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_opensearch_adapter.py` | 21:4 | block '__init__' has cyclomatic complexity 2 (rank A) |
| 444 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_opensearch_adapter.py` | 26:4 | block 'search' has cyclomatic complexity 2 (rank A) |
| 445 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_opensearch_adapter.py` | 16:0 | block '_hit' has cyclomatic complexity 1 (rank A) |
| 446 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_opensearch_adapter.py` | 60:0 | block 'test_knn_failure_raises_index_unavailable' has cyclomatic complexity 1 (rank A) |
| 447 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_opensearch_adapter.py` | 69:0 | block 'test_bm25_failure_raises_index_unavailable' has cyclomatic complexity 1 (rank A) |
| 448 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/real_wiring.py` | 50:0 | block 'build_real_orchestrator' has cyclomatic complexity 5 (rank A) |
| 449 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/real_wiring.py` | 44:0 | block 'RealBundle' has cyclomatic complexity 1 (rank A) |
| 450 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/mocks/port_stubs.py` | 21:0 | block 'StubGroundingHook' has cyclomatic complexity 2 (rank A) |
| 451 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/mocks/port_stubs.py` | 46:0 | block 'StubCostGuard' has cyclomatic complexity 2 (rank A) |
| 452 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/mocks/port_stubs.py` | 56:0 | block 'NoopObservabilityHub' has cyclomatic complexity 2 (rank A) |
| 453 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/mocks/port_stubs.py` | 67:0 | block 'InMemoryEventPublisher' has cyclomatic complexity 2 (rank A) |
| 454 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/mocks/port_stubs.py` | 14:0 | block '_Decision' has cyclomatic complexity 1 (rank A) |
| 455 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/mocks/port_stubs.py` | 27:4 | block '__init__' has cyclomatic complexity 1 (rank A) |
| 456 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/mocks/port_stubs.py` | 30:4 | block 'enforce' has cyclomatic complexity 1 (rank A) |
| 457 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/mocks/port_stubs.py` | 33:4 | block 'run_eval_set' has cyclomatic complexity 1 (rank A) |
| 458 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/mocks/port_stubs.py` | 38:0 | block '_Budget' has cyclomatic complexity 1 (rank A) |
| 459 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/mocks/port_stubs.py` | 49:4 | block '__init__' has cyclomatic complexity 1 (rank A) |
| 460 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/mocks/port_stubs.py` | 52:4 | block 'get_budget_state' has cyclomatic complexity 1 (rank A) |
| 461 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/mocks/port_stubs.py` | 59:4 | block 'emit_metric' has cyclomatic complexity 1 (rank A) |
| 462 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/mocks/port_stubs.py` | 60:4 | block 'emit_log' has cyclomatic complexity 1 (rank A) |
| 463 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/mocks/port_stubs.py` | 61:4 | block 'start_span' has cyclomatic complexity 1 (rank A) |
| 464 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/mocks/port_stubs.py` | 63:4 | block 'audit_append' has cyclomatic complexity 1 (rank A) |
| 465 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/mocks/port_stubs.py` | 72:4 | block 'publish_search_executed' has cyclomatic complexity 1 (rank A) |
| 466 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/mocks/fixtures.py` | 27:0 | block 'embed' has cyclomatic complexity 4 (rank A) |
| 467 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/mocks/fixtures.py` | 37:0 | block '_record' has cyclomatic complexity 2 (rank A) |
| 468 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/mocks/wiring.py` | 39:0 | block 'build_mock_orchestrator' has cyclomatic complexity 5 (rank A) |
| 469 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/mocks/wiring.py` | 32:0 | block 'MockBundle' has cyclomatic complexity 1 (rank A) |
| 470 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/mocks/adapters.py` | 23:0 | block 'MockVectorStoreAdapter' has cyclomatic complexity 4 (rank A) |
| 471 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/mocks/adapters.py` | 29:4 | block 'knn_search' has cyclomatic complexity 4 (rank A) |
| 472 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/mocks/adapters.py` | 39:0 | block 'MockLexicalIndexAdapter' has cyclomatic complexity 4 (rank A) |
| 473 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/mocks/adapters.py` | 48:4 | block 'bm25_search' has cyclomatic complexity 4 (rank A) |
| 474 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/mocks/adapters.py` | 60:0 | block 'MockPaperLookupAdapter' has cyclomatic complexity 3 (rank A) |
| 475 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/mocks/adapters.py` | 67:4 | block 'fetch_paper' has cyclomatic complexity 3 (rank A) |
| 476 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/mocks/adapters.py` | 16:0 | block 'MockEmbeddingAdapter' has cyclomatic complexity 2 (rank A) |
| 477 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/mocks/adapters.py` | 74:0 | block 'FailingEmbeddingAdapter' has cyclomatic complexity 2 (rank A) |
| 478 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/mocks/adapters.py` | 81:0 | block 'FailingVectorStoreAdapter' has cyclomatic complexity 2 (rank A) |
| 479 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/mocks/adapters.py` | 86:0 | block 'FailingLexicalIndexAdapter' has cyclomatic complexity 2 (rank A) |
| 480 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/mocks/adapters.py` | 19:4 | block 'embed_query' has cyclomatic complexity 1 (rank A) |
| 481 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/mocks/adapters.py` | 26:4 | block '__init__' has cyclomatic complexity 1 (rank A) |
| 482 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/mocks/adapters.py` | 45:4 | block '__init__' has cyclomatic complexity 1 (rank A) |
| 483 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/mocks/adapters.py` | 64:4 | block '__init__' has cyclomatic complexity 1 (rank A) |
| 484 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/mocks/adapters.py` | 77:4 | block 'embed_query' has cyclomatic complexity 1 (rank A) |
| 485 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/mocks/adapters.py` | 82:4 | block 'knn_search' has cyclomatic complexity 1 (rank A) |
| 486 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/mocks/adapters.py` | 89:4 | block 'bm25_search' has cyclomatic complexity 1 (rank A) |
| 487 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/cache/embedding_cache.py` | 20:0 | block 'EmbeddingCache' has cyclomatic complexity 3 (rank A) |
| 488 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/cache/embedding_cache.py` | 39:4 | block 'embed_query' has cyclomatic complexity 3 (rank A) |
| 489 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/cache/embedding_cache.py` | 23:4 | block '__init__' has cyclomatic complexity 2 (rank A) |
| 490 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/cache/embedding_cache.py` | 49:4 | block '_evict_if_full' has cyclomatic complexity 2 (rank A) |
| 491 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/adapters/bedrock_embedding.py` | 21:0 | block 'BedrockCohereQueryEmbedder' has cyclomatic complexity 5 (rank A) |
| 492 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/adapters/bedrock_embedding.py` | 24:4 | block '__init__' has cyclomatic complexity 2 (rank A) |
| 493 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/adapters/opensearch_index.py` | 24:0 | block 'OpenSearchClientFactory' has cyclomatic complexity 4 (rank A) |
| 494 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/adapters/opensearch_index.py` | 47:0 | block '_to_scored' has cyclomatic complexity 3 (rank A) |
| 495 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/adapters/opensearch_index.py` | 28:4 | block 'build' has cyclomatic complexity 3 (rank A) |
| 496 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/adapters/opensearch_index.py` | 56:0 | block 'OpenSearchVectorStoreAdapter' has cyclomatic complexity 3 (rank A) |
| 497 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/adapters/opensearch_index.py` | 76:0 | block 'OpenSearchPaperLookupAdapter' has cyclomatic complexity 3 (rank A) |
| 498 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/adapters/opensearch_index.py` | 84:4 | block 'fetch_paper' has cyclomatic complexity 3 (rank A) |
| 499 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/adapters/opensearch_index.py` | 109:0 | block 'OpenSearchLexicalIndexAdapter' has cyclomatic complexity 3 (rank A) |
| 500 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/adapters/opensearch_index.py` | 63:4 | block 'knn_search' has cyclomatic complexity 2 (rank A) |
| 501 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/adapters/opensearch_index.py` | 116:4 | block 'bm25_search' has cyclomatic complexity 2 (rank A) |
| 502 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/adapters/opensearch_index.py` | 59:4 | block '__init__' has cyclomatic complexity 1 (rank A) |
| 503 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/adapters/opensearch_index.py` | 80:4 | block '__init__' has cyclomatic complexity 1 (rank A) |
| 504 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/adapters/opensearch_index.py` | 112:4 | block '__init__' has cyclomatic complexity 1 (rank A) |
| 505 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/adapters/event_publisher.py` | 25:0 | block 'EventBridgeEventPublisher' has cyclomatic complexity 3 (rank A) |
| 506 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/adapters/event_publisher.py` | 28:4 | block '__init__' has cyclomatic complexity 3 (rank A) |
| 507 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/adapters/event_publisher.py` | 49:4 | block 'publish_search_executed' has cyclomatic complexity 2 (rank A) |
| 508 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/adapters/event_publisher.py` | 57:4 | block '_send' has cyclomatic complexity 2 (rank A) |
| 509 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/adapters/event_publisher.py` | 72:4 | block 'close' has cyclomatic complexity 1 (rank A) |
| 510 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/adapters/settings.py` | 29:0 | block '_flag' has cyclomatic complexity 2 (rank A) |
| 511 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/adapters/settings.py` | 55:4 | block 'search_enabled' has cyclomatic complexity 2 (rank A) |
| 512 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/scripts/seed_local_opensearch.py` | 61:0 | block 'create_index' has cyclomatic complexity 4 (rank A) |
| 513 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/scripts/seed_local_opensearch.py` | 68:0 | block 'bulk_index' has cyclomatic complexity 3 (rank A) |
| 514 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/scripts/seed_local_opensearch.py` | 81:0 | block 'seed' has cyclomatic complexity 3 (rank A) |
| 515 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/scripts/seed_local_opensearch.py` | 97:0 | block 'main' has cyclomatic complexity 1 (rank A) |
| 516 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/api/router.py` | 29:0 | block 'build_router' has cyclomatic complexity 2 (rank A) |
| 517 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/api/router.py` | 68:0 | block 'build_app' has cyclomatic complexity 1 (rank A) |
| 518 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/api/gateway_seam.py` | 19:0 | block 'run_search' has cyclomatic complexity 3 (rank A) |
| 519 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/service/orchestrator.py` | 119:4 | block 'plan_and_retrieve' has cyclomatic complexity 5 (rank A) |
| 520 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/service/orchestrator.py` | 74:0 | block '_derive_degradation' has cyclomatic complexity 4 (rank A) |
| 521 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/service/orchestrator.py` | 93:0 | block 'SearchOrchestrationService' has cyclomatic complexity 3 (rank A) |
| 522 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/service/orchestrator.py` | 85:0 | block 'result_count' has cyclomatic complexity 2 (rank A) |
| 523 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/service/orchestrator.py` | 177:4 | block '_emit_grounding_health' has cyclomatic complexity 2 (rank A) |
| 524 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/service/orchestrator.py` | 195:4 | block '_publish' has cyclomatic complexity 2 (rank A) |
| 525 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/service/orchestrator.py` | 56:0 | block 'GroundingPending' has cyclomatic complexity 1 (rank A) |
| 526 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/service/orchestrator.py` | 67:0 | block 'SearchOutcome' has cyclomatic complexity 1 (rank A) |
| 527 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/service/orchestrator.py` | 94:4 | block '__init__' has cyclomatic complexity 1 (rank A) |
| 528 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/service/orchestrator.py` | 169:4 | block 'finalize' has cyclomatic complexity 1 (rank A) |
| 529 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/service/paper_metadata.py` | 36:0 | block 'PaperMetadataService' has cyclomatic complexity 3 (rank A) |
| 530 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/service/paper_metadata.py` | 40:4 | block 'get_paper_meta' has cyclomatic complexity 3 (rank A) |
| 531 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/service/paper_metadata.py` | 22:0 | block 'PaperMetaDTO' has cyclomatic complexity 1 (rank A) |
| 532 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/service/paper_metadata.py` | 37:4 | block '__init__' has cyclomatic complexity 1 (rank A) |
| 533 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/ports/search_ports.py` | 52:0 | block 'EmbeddingAdapter' has cyclomatic complexity 2 (rank A) |
| 534 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/ports/search_ports.py` | 61:0 | block 'VectorStoreAdapter' has cyclomatic complexity 2 (rank A) |
| 535 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/ports/search_ports.py` | 70:0 | block 'LexicalIndexAdapter' has cyclomatic complexity 2 (rank A) |
| 536 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/ports/search_ports.py` | 79:0 | block 'PaperLookupAdapter' has cyclomatic complexity 2 (rank A) |
| 537 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/ports/search_ports.py` | 92:0 | block 'EventPublisher' has cyclomatic complexity 2 (rank A) |
| 538 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/ports/search_ports.py` | 35:0 | block 'EmbeddingUnavailable' has cyclomatic complexity 1 (rank A) |
| 539 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/ports/search_ports.py` | 39:0 | block 'IndexUnavailable' has cyclomatic complexity 1 (rank A) |
| 540 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/ports/search_ports.py` | 43:0 | block 'SearchUnavailable' has cyclomatic complexity 1 (rank A) |
| 541 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/ports/search_ports.py` | 55:4 | block 'embed_query' has cyclomatic complexity 1 (rank A) |
| 542 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/ports/search_ports.py` | 64:4 | block 'knn_search' has cyclomatic complexity 1 (rank A) |
| 543 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/ports/search_ports.py` | 73:4 | block 'bm25_search' has cyclomatic complexity 1 (rank A) |
| 544 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/ports/search_ports.py` | 85:4 | block 'fetch_paper' has cyclomatic complexity 1 (rank A) |
| 545 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/ports/search_ports.py` | 95:4 | block 'publish_search_executed' has cyclomatic complexity 1 (rank A) |
| 546 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/domain/validator.py` | 22:4 | block 'validate' has cyclomatic complexity 5 (rank A) |
| 547 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/domain/validator.py` | 19:0 | block 'QueryValidator' has cyclomatic complexity 4 (rank A) |
| 548 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/domain/validator.py` | 34:4 | block 'normalize' has cyclomatic complexity 1 (rank A) |
| 549 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/domain/models.py` | 17:0 | block 'DegradeMode' has cyclomatic complexity 1 (rank A) |
| 550 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/domain/models.py` | 29:0 | block 'RetrievalMode' has cyclomatic complexity 1 (rank A) |
| 551 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/domain/models.py` | 35:0 | block 'AuthSession' has cyclomatic complexity 1 (rank A) |
| 552 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/domain/models.py` | 42:0 | block 'RequestContext' has cyclomatic complexity 1 (rank A) |
| 553 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/domain/models.py` | 50:0 | block 'ValidationResult' has cyclomatic complexity 1 (rank A) |
| 554 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/domain/models.py` | 59:0 | block 'NormalizedQuery' has cyclomatic complexity 1 (rank A) |
| 555 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/domain/models.py` | 66:0 | block 'DegradationSignal' has cyclomatic complexity 1 (rank A) |
| 556 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/domain/models.py` | 74:0 | block 'QueryPlan' has cyclomatic complexity 1 (rank A) |
| 557 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/domain/models.py` | 83:0 | block 'Candidate' has cyclomatic complexity 1 (rank A) |
| 558 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/domain/models.py` | 94:0 | block 'CandidateSet' has cyclomatic complexity 1 (rank A) |
| 559 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/domain/models.py` | 102:0 | block 'RankedResults' has cyclomatic complexity 1 (rank A) |
| 560 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/domain/models.py` | 110:0 | block 'GroundedResults' has cyclomatic complexity 1 (rank A) |
| 561 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/domain/models.py` | 117:0 | block 'AbstainResult' has cyclomatic complexity 1 (rank A) |
| 562 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/domain/models.py` | 125:0 | block 'NoMatchResult' has cyclomatic complexity 1 (rank A) |
| 563 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/domain/models.py` | 132:0 | block 'GroundingInput' has cyclomatic complexity 1 (rank A) |
| 564 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/domain/retriever.py` | 40:0 | block '_reciprocal_rank_fusion' has cyclomatic complexity 5 (rank A) |
| 565 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/domain/retriever.py` | 21:0 | block 'HybridRetriever' has cyclomatic complexity 4 (rank A) |
| 566 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/domain/retriever.py` | 27:4 | block 'retrieve' has cyclomatic complexity 4 (rank A) |
| 567 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/domain/retriever.py` | 22:4 | block '__init__' has cyclomatic complexity 1 (rank A) |
| 568 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/domain/assembler.py` | 26:0 | block '_card' has cyclomatic complexity 1 (rank A) |
| 569 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/domain/ranker.py` | 16:0 | block 'RelevanceRanker' has cyclomatic complexity 2 (rank A) |
| 570 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/domain/ranker.py` | 17:4 | block 'rank' has cyclomatic complexity 1 (rank A) |
| 571 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/domain/expander.py` | 17:0 | block '_tokenize' has cyclomatic complexity 3 (rank A) |
| 572 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/domain/expander.py` | 22:0 | block 'QueryUnderstandingExpander' has cyclomatic complexity 3 (rank A) |
| 573 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/domain/expander.py` | 26:4 | block 'expand' has cyclomatic complexity 2 (rank A) |
| 574 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/domain/expander.py` | 23:4 | block '__init__' has cyclomatic complexity 1 (rank A) |
| 575 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/domain/grounding_adapter.py` | 20:0 | block 'GroundingAdapter' has cyclomatic complexity 3 (rank A) |
| 576 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/domain/grounding_adapter.py` | 21:4 | block 'to_grounding_input' has cyclomatic complexity 2 (rank A) |
| 577 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/domain/grounding_adapter.py` | 26:4 | block 'map_decision' has cyclomatic complexity 2 (rank A) |
| 578 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/gateway.py` | 17:0 | block 'StubSearchGateway' has cyclomatic complexity 2 (rank A) |
| 579 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/gateway.py` | 22:4 | block 'search' has cyclomatic complexity 1 (rank A) |
| 580 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/controller.py` | 93:0 | block '_to_http' has cyclomatic complexity 4 (rank A) |
| 581 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/controller.py` | 61:0 | block 'get_principal' has cyclomatic complexity 2 (rank A) |
| 582 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/controller.py` | 109:0 | block 'create_saved_search' has cyclomatic complexity 2 (rank A) |
| 583 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/controller.py` | 121:0 | block 'list_saved_searches' has cyclomatic complexity 2 (rank A) |
| 584 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/controller.py` | 134:0 | block 'delete_saved_search' has cyclomatic complexity 2 (rank A) |
| 585 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/controller.py` | 147:0 | block 'rerun_saved_search' has cyclomatic complexity 2 (rank A) |
| 586 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/controller.py` | 163:0 | block 'add_library_item' has cyclomatic complexity 2 (rank A) |
| 587 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/controller.py` | 175:0 | block 'list_library' has cyclomatic complexity 2 (rank A) |
| 588 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/controller.py` | 188:0 | block 'remove_library_item' has cyclomatic complexity 2 (rank A) |
| 589 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/controller.py` | 205:0 | block 'list_history' has cyclomatic complexity 2 (rank A) |
| 590 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/controller.py` | 218:0 | block 'rerun_history_entry' has cyclomatic complexity 2 (rank A) |
| 591 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/controller.py` | 230:0 | block 'clear_history' has cyclomatic complexity 2 (rank A) |
| 592 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/controller.py` | 47:0 | block 'get_user_data_repo' has cyclomatic complexity 1 (rank A) |
| 593 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/controller.py` | 52:0 | block 'get_search_gateway' has cyclomatic complexity 1 (rank A) |
| 594 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/controller.py` | 57:0 | block 'get_audit_sink' has cyclomatic complexity 1 (rank A) |
| 595 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/controller.py` | 70:0 | block 'get_saved_search_service' has cyclomatic complexity 1 (rank A) |
| 596 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/controller.py` | 78:0 | block 'get_library_service' has cyclomatic complexity 1 (rank A) |
| 597 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/controller.py` | 85:0 | block 'get_history_service' has cyclomatic complexity 1 (rank A) |
| 598 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/audit.py` | 26:0 | block 'InMemoryAuditSink' has cyclomatic complexity 2 (rank A) |
| 599 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/audit.py` | 40:0 | block 'make_event' has cyclomatic complexity 1 (rank A) |
| 600 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/audit.py` | 18:0 | block 'AuditEvent' has cyclomatic complexity 1 (rank A) |
| 601 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/audit.py` | 29:4 | block '__init__' has cyclomatic complexity 1 (rank A) |
| 602 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/audit.py` | 32:4 | block 'record' has cyclomatic complexity 1 (rank A) |
| 603 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/audit.py` | 36:4 | block 'events' has cyclomatic complexity 1 (rank A) |
| 604 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/models.py` | 47:0 | block '_now' has cyclomatic complexity 1 (rank A) |
| 605 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/models.py` | 22:0 | block 'DomainException' has cyclomatic complexity 1 (rank A) |
| 606 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/models.py` | 26:0 | block 'ValidationException' has cyclomatic complexity 1 (rank A) |
| 607 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/models.py` | 30:0 | block 'QuotaExceededError' has cyclomatic complexity 1 (rank A) |
| 608 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/models.py` | 34:0 | block 'NotFoundError' has cyclomatic complexity 1 (rank A) |
| 609 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/models.py` | 43:0 | block 'AuthorizationError' has cyclomatic complexity 1 (rank A) |
| 610 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/models.py` | 54:0 | block 'SavedSearch' has cyclomatic complexity 1 (rank A) |
| 611 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/models.py` | 66:0 | block 'LibraryItem' has cyclomatic complexity 1 (rank A) |
| 612 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/models.py` | 79:0 | block 'HistoryEntry' has cyclomatic complexity 1 (rank A) |
| 613 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/history_consumer.py` | 17:0 | block 'SearchHistoryEventConsumer' has cyclomatic complexity 3 (rank A) |
| 614 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/history_consumer.py` | 21:4 | block 'consume' has cyclomatic complexity 2 (rank A) |
| 615 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/history_consumer.py` | 18:4 | block '__init__' has cyclomatic complexity 1 (rank A) |
| 616 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/ports.py` | 27:0 | block 'SavedSearchRepository' has cyclomatic complexity 2 (rank A) |
| 617 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/ports.py` | 42:0 | block 'LibraryRepository' has cyclomatic complexity 2 (rank A) |
| 618 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/ports.py` | 54:0 | block 'SearchHistoryRepository' has cyclomatic complexity 2 (rank A) |
| 619 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/ports.py` | 75:0 | block 'SearchGatewayPort' has cyclomatic complexity 2 (rank A) |
| 620 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/ports.py` | 84:0 | block 'AuditSink' has cyclomatic complexity 2 (rank A) |
| 621 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/ports.py` | 28:4 | block 'get' has cyclomatic complexity 1 (rank A) |
| 622 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/ports.py` | 29:4 | block 'find_by_normalized' has cyclomatic complexity 1 (rank A) |
| 623 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/ports.py` | 30:4 | block 'count' has cyclomatic complexity 1 (rank A) |
| 624 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/ports.py` | 31:4 | block 'insert' has cyclomatic complexity 1 (rank A) |
| 625 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/ports.py` | 32:4 | block 'delete' has cyclomatic complexity 1 (rank A) |
| 626 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/ports.py` | 33:4 | block 'update_label' has cyclomatic complexity 1 (rank A) |
| 627 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/ports.py` | 36:4 | block 'list_page' has cyclomatic complexity 1 (rank A) |
| 628 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/ports.py` | 43:4 | block 'get' has cyclomatic complexity 1 (rank A) |
| 629 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/ports.py` | 44:4 | block 'find_by_arxiv' has cyclomatic complexity 1 (rank A) |
| 630 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/ports.py` | 45:4 | block 'count' has cyclomatic complexity 1 (rank A) |
| 631 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/ports.py` | 46:4 | block 'insert' has cyclomatic complexity 1 (rank A) |
| 632 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/ports.py` | 47:4 | block 'delete' has cyclomatic complexity 1 (rank A) |
| 633 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/ports.py` | 48:4 | block 'list_page' has cyclomatic complexity 1 (rank A) |
| 634 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/ports.py` | 55:4 | block 'get' has cyclomatic complexity 1 (rank A) |
| 635 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/ports.py` | 56:4 | block 'find_by_dedupe_key' has cyclomatic complexity 1 (rank A) |
| 636 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/ports.py` | 57:4 | block 'insert' has cyclomatic complexity 1 (rank A) |
| 637 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/ports.py` | 58:4 | block 'clear' has cyclomatic complexity 1 (rank A) |
| 638 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/ports.py` | 59:4 | block 'prune_to' has cyclomatic complexity 1 (rank A) |
| 639 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/ports.py` | 60:4 | block 'list_page' has cyclomatic complexity 1 (rank A) |
| 640 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/ports.py` | 66:0 | block 'UserDataRepository' has cyclomatic complexity 1 (rank A) |
| 641 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/ports.py` | 80:4 | block 'search' has cyclomatic complexity 1 (rank A) |
| 642 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/ports.py` | 87:4 | block 'record' has cyclomatic complexity 1 (rank A) |
| 643 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/schemas.py` | 46:0 | block 'LibraryItemMeta' has cyclomatic complexity 1 (rank A) |
| 644 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/authz.py` | 18:0 | block 'authorize_owned' has cyclomatic complexity 3 (rank A) |
| 645 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/validation.py` | 86:0 | block 'validate_arxiv_id' has cyclomatic complexity 5 (rank A) |
| 646 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/validation.py` | 68:0 | block 'validate_query' has cyclomatic complexity 4 (rank A) |
| 647 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/validation.py` | 77:0 | block 'validate_label' has cyclomatic complexity 4 (rank A) |
| 648 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/validation.py` | 95:0 | block 'validate_limit' has cyclomatic complexity 4 (rank A) |
| 649 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/validation.py` | 105:0 | block 'validate_meta' has cyclomatic complexity 4 (rank A) |
| 650 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/validation.py` | 165:0 | block 'build_page' has cyclomatic complexity 4 (rank A) |
| 651 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/validation.py` | 124:0 | block 'decode_cursor' has cyclomatic complexity 3 (rank A) |
| 652 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/validation.py` | 47:0 | block 'normalize_query' has cyclomatic complexity 1 (rank A) |
| 653 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/validation.py` | 55:0 | block 'normalize_arxiv_id' has cyclomatic complexity 1 (rank A) |
| 654 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/validation.py` | 61:0 | block 'dedupe_key' has cyclomatic complexity 1 (rank A) |
| 655 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/validation.py` | 118:0 | block 'encode_cursor' has cyclomatic complexity 1 (rank A) |
| 656 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/validation.py` | 136:0 | block 'to_saved_dto' has cyclomatic complexity 1 (rank A) |
| 657 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/validation.py` | 142:0 | block 'to_library_dto' has cyclomatic complexity 1 (rank A) |
| 658 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/validation.py` | 151:0 | block 'to_history_dto' has cyclomatic complexity 1 (rank A) |
| 659 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/memory.py` | 20:0 | block '_page' has cyclomatic complexity 4 (rank A) |
| 660 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/memory.py` | 126:4 | block 'prune_to' has cyclomatic complexity 4 (rank A) |
| 661 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/memory.py` | 39:4 | block 'find_by_normalized' has cyclomatic complexity 3 (rank A) |
| 662 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/memory.py` | 78:4 | block 'find_by_arxiv' has cyclomatic complexity 3 (rank A) |
| 663 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/memory.py` | 110:4 | block 'find_by_dedupe_key' has cyclomatic complexity 3 (rank A) |
| 664 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/memory.py` | 28:0 | block 'InMemorySavedSearchRepository' has cyclomatic complexity 2 (rank A) |
| 665 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/memory.py` | 52:4 | block 'update_label' has cyclomatic complexity 2 (rank A) |
| 666 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/memory.py` | 68:0 | block 'InMemoryLibraryRepository' has cyclomatic complexity 2 (rank A) |
| 667 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/memory.py` | 100:0 | block 'InMemorySearchHistoryRepository' has cyclomatic complexity 2 (rank A) |
| 668 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/memory.py` | 143:0 | block 'InMemoryUserDataRepository' has cyclomatic complexity 2 (rank A) |
| 669 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/memory.py` | 29:4 | block '__init__' has cyclomatic complexity 1 (rank A) |
| 670 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/memory.py` | 33:4 | block '_owner' has cyclomatic complexity 1 (rank A) |
| 671 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/memory.py` | 36:4 | block 'get' has cyclomatic complexity 1 (rank A) |
| 672 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/memory.py` | 45:4 | block 'count' has cyclomatic complexity 1 (rank A) |
| 673 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/memory.py` | 48:4 | block 'insert' has cyclomatic complexity 1 (rank A) |
| 674 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/memory.py` | 59:4 | block 'delete' has cyclomatic complexity 1 (rank A) |
| 675 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/memory.py` | 62:4 | block 'list_page' has cyclomatic complexity 1 (rank A) |
| 676 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/memory.py` | 69:4 | block '__init__' has cyclomatic complexity 1 (rank A) |
| 677 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/memory.py` | 72:4 | block '_owner' has cyclomatic complexity 1 (rank A) |
| 678 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/memory.py` | 75:4 | block 'get' has cyclomatic complexity 1 (rank A) |
| 679 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/memory.py` | 84:4 | block 'count' has cyclomatic complexity 1 (rank A) |
| 680 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/memory.py` | 87:4 | block 'insert' has cyclomatic complexity 1 (rank A) |
| 681 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/memory.py` | 91:4 | block 'delete' has cyclomatic complexity 1 (rank A) |
| 682 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/memory.py` | 94:4 | block 'list_page' has cyclomatic complexity 1 (rank A) |
| 683 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/memory.py` | 101:4 | block '__init__' has cyclomatic complexity 1 (rank A) |
| 684 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/memory.py` | 104:4 | block '_owner' has cyclomatic complexity 1 (rank A) |
| 685 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/memory.py` | 107:4 | block 'get' has cyclomatic complexity 1 (rank A) |
| 686 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/memory.py` | 116:4 | block 'insert' has cyclomatic complexity 1 (rank A) |
| 687 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/memory.py` | 120:4 | block 'clear' has cyclomatic complexity 1 (rank A) |
| 688 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/memory.py` | 137:4 | block 'list_page' has cyclomatic complexity 1 (rank A) |
| 689 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/memory.py` | 146:4 | block '__init__' has cyclomatic complexity 1 (rank A) |
| 690 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/sql.py` | 154:4 | block 'list_page' has cyclomatic complexity 3 (rank A) |
| 691 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/sql.py` | 214:4 | block 'list_page' has cyclomatic complexity 3 (rank A) |
| 692 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/sql.py` | 224:0 | block 'SqlSearchHistoryRepository' has cyclomatic complexity 3 (rank A) |
| 693 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/sql.py` | 268:4 | block 'prune_to' has cyclomatic complexity 3 (rank A) |
| 694 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/sql.py` | 285:4 | block 'list_page' has cyclomatic complexity 3 (rank A) |
| 695 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/sql.py` | 90:0 | block 'SqlSavedSearchRepository' has cyclomatic complexity 2 (rank A) |
| 696 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/sql.py` | 94:4 | block 'get' has cyclomatic complexity 2 (rank A) |
| 697 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/sql.py` | 102:4 | block 'find_by_normalized' has cyclomatic complexity 2 (rank A) |
| 698 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/sql.py` | 134:4 | block 'update_label' has cyclomatic complexity 2 (rank A) |
| 699 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/sql.py` | 164:0 | block 'SqlLibraryRepository' has cyclomatic complexity 2 (rank A) |
| 700 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/sql.py` | 168:4 | block 'get' has cyclomatic complexity 2 (rank A) |
| 701 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/sql.py` | 176:4 | block 'find_by_arxiv' has cyclomatic complexity 2 (rank A) |
| 702 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/sql.py` | 228:4 | block 'get' has cyclomatic complexity 2 (rank A) |
| 703 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/sql.py` | 236:4 | block 'find_by_dedupe_key' has cyclomatic complexity 2 (rank A) |
| 704 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/sql.py` | 295:0 | block 'SqlUserDataRepository' has cyclomatic complexity 2 (rank A) |
| 705 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/sql.py` | 58:0 | block '_saved_to_domain' has cyclomatic complexity 1 (rank A) |
| 706 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/sql.py` | 69:0 | block '_library_to_domain' has cyclomatic complexity 1 (rank A) |
| 707 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/sql.py` | 79:0 | block '_history_to_domain' has cyclomatic complexity 1 (rank A) |
| 708 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/sql.py` | 22:0 | block 'Base' has cyclomatic complexity 1 (rank A) |
| 709 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/sql.py` | 26:0 | block 'SavedSearchTable' has cyclomatic complexity 1 (rank A) |
| 710 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/sql.py` | 37:0 | block 'LibraryItemTable' has cyclomatic complexity 1 (rank A) |
| 711 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/sql.py` | 47:0 | block 'SearchHistoryTable' has cyclomatic complexity 1 (rank A) |
| 712 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/sql.py` | 91:4 | block '__init__' has cyclomatic complexity 1 (rank A) |
| 713 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/sql.py` | 113:4 | block 'count' has cyclomatic complexity 1 (rank A) |
| 714 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/sql.py` | 120:4 | block 'insert' has cyclomatic complexity 1 (rank A) |
| 715 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/sql.py` | 146:4 | block 'delete' has cyclomatic complexity 1 (rank A) |
| 716 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/sql.py` | 165:4 | block '__init__' has cyclomatic complexity 1 (rank A) |
| 717 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/sql.py` | 186:4 | block 'count' has cyclomatic complexity 1 (rank A) |
| 718 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/sql.py` | 193:4 | block 'insert' has cyclomatic complexity 1 (rank A) |
| 719 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/sql.py` | 206:4 | block 'delete' has cyclomatic complexity 1 (rank A) |
| 720 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/sql.py` | 225:4 | block '__init__' has cyclomatic complexity 1 (rank A) |
| 721 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/sql.py` | 247:4 | block 'insert' has cyclomatic complexity 1 (rank A) |
| 722 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/sql.py` | 261:4 | block 'clear' has cyclomatic complexity 1 (rank A) |
| 723 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/sql.py` | 298:4 | block '__init__' has cyclomatic complexity 1 (rank A) |
| 724 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/services/library.py` | 19:0 | block 'LibraryService' has cyclomatic complexity 3 (rank A) |
| 725 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/services/library.py` | 24:4 | block 'add' has cyclomatic complexity 3 (rank A) |
| 726 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/services/library.py` | 56:4 | block 'remove' has cyclomatic complexity 2 (rank A) |
| 727 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/services/library.py` | 20:4 | block '__init__' has cyclomatic complexity 1 (rank A) |
| 728 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/services/library.py` | 46:4 | block 'list' has cyclomatic complexity 1 (rank A) |
| 729 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/services/saved_search.py` | 38:4 | block 'save' has cyclomatic complexity 5 (rank A) |
| 730 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/services/saved_search.py` | 30:0 | block 'SavedSearchService' has cyclomatic complexity 3 (rank A) |
| 731 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/services/saved_search.py` | 79:4 | block 'delete' has cyclomatic complexity 2 (rank A) |
| 732 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/services/saved_search.py` | 89:4 | block 'rerun' has cyclomatic complexity 2 (rank A) |
| 733 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/services/saved_search.py` | 31:4 | block '__init__' has cyclomatic complexity 1 (rank A) |
| 734 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/services/saved_search.py` | 69:4 | block 'list' has cyclomatic complexity 1 (rank A) |
| 735 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/services/history.py` | 26:0 | block 'SearchHistoryService' has cyclomatic complexity 2 (rank A) |
| 736 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/services/history.py` | 34:4 | block 'record_search' has cyclomatic complexity 2 (rank A) |
| 737 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/services/history.py` | 66:4 | block 'rerun' has cyclomatic complexity 2 (rank A) |
| 738 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/services/history.py` | 27:4 | block '__init__' has cyclomatic complexity 1 (rank A) |
| 739 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/services/history.py` | 56:4 | block 'list' has cyclomatic complexity 1 (rank A) |
| 740 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/services/history.py` | 74:4 | block 'clear' has cyclomatic complexity 1 (rank A) |
| 741 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/controller.py` | 182:0 | block 'get_session' has cyclomatic complexity 4 (rank A) |
| 742 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/controller.py` | 88:0 | block 'signup' has cyclomatic complexity 3 (rank A) |
| 743 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/controller.py` | 121:0 | block 'login' has cyclomatic complexity 3 (rank A) |
| 744 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/controller.py` | 163:0 | block 'verify_email' has cyclomatic complexity 3 (rank A) |
| 745 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/controller.py` | 210:0 | block 'logout' has cyclomatic complexity 3 (rank A) |
| 746 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/controller.py` | 45:0 | block 'get_session_repo' has cyclomatic complexity 2 (rank A) |
| 747 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/controller.py` | 33:0 | block 'get_db_session' has cyclomatic complexity 1 (rank A) |
| 748 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/controller.py` | 37:0 | block 'get_credential_repo' has cyclomatic complexity 1 (rank A) |
| 749 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/controller.py` | 54:0 | block 'get_recaptcha_client' has cyclomatic complexity 1 (rank A) |
| 750 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/controller.py` | 58:0 | block 'get_session_manager' has cyclomatic complexity 1 (rank A) |
| 751 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/controller.py` | 61:0 | block 'get_signup_service' has cyclomatic complexity 1 (rank A) |
| 752 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/controller.py` | 74:0 | block 'get_auth_service' has cyclomatic complexity 1 (rank A) |
| 753 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/controller.py` | 81:0 | block 'get_totp_service' has cyclomatic complexity 1 (rank A) |
| 754 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/controller.py` | 29:0 | block 'MfaVerifyRequest' has cyclomatic complexity 1 (rank A) |
| 755 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/models.py` | 61:4 | block '__post_init__' has cyclomatic complexity 5 (rank A) |
| 756 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/models.py` | 44:0 | block 'AccountId' has cyclomatic complexity 3 (rank A) |
| 757 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/models.py` | 74:0 | block 'Principal' has cyclomatic complexity 3 (rank A) |
| 758 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/models.py` | 47:4 | block '__post_init__' has cyclomatic complexity 2 (rank A) |
| 759 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/models.py` | 79:4 | block '__post_init__' has cyclomatic complexity 2 (rank A) |
| 760 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/models.py` | 8:0 | block 'DomainException' has cyclomatic complexity 1 (rank A) |
| 761 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/models.py` | 12:0 | block 'InvalidEmailException' has cyclomatic complexity 1 (rank A) |
| 762 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/models.py` | 15:0 | block 'InvalidPasswordException' has cyclomatic complexity 1 (rank A) |
| 763 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/models.py` | 18:0 | block 'SessionExpiredException' has cyclomatic complexity 1 (rank A) |
| 764 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/models.py` | 21:0 | block 'UnauthorizedException' has cyclomatic complexity 1 (rank A) |
| 765 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/models.py` | 24:0 | block 'SessionStoreUnavailableException' has cyclomatic complexity 1 (rank A) |
| 766 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/models.py` | 28:0 | block 'AccountStatus' has cyclomatic complexity 1 (rank A) |
| 767 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/models.py` | 33:0 | block 'UserRole' has cyclomatic complexity 1 (rank A) |
| 768 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/models.py` | 37:0 | block 'Action' has cyclomatic complexity 1 (rank A) |
| 769 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/models.py` | 70:0 | block 'PasswordHash' has cyclomatic complexity 1 (rank A) |
| 770 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/models.py` | 87:0 | block 'SessionRecord' has cyclomatic complexity 1 (rank A) |
| 771 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/guard.py` | 37:4 | block 'authorize_admin' has cyclomatic complexity 4 (rank A) |
| 772 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/guard.py` | 6:0 | block 'Decision' has cyclomatic complexity 1 (rank A) |
| 773 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/password.py` | 40:0 | block 'get_password_hasher' has cyclomatic complexity 1 (rank A) |
| 774 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/seed_admin.py` | 56:0 | block 'main' has cyclomatic complexity 4 (rank A) |
| 775 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/seed_admin.py` | 30:0 | block 'seed_admin' has cyclomatic complexity 2 (rank A) |
| 776 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/repository/session.py` | 46:4 | block 'save' has cyclomatic complexity 4 (rank A) |
| 777 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/repository/session.py` | 73:4 | block 'get' has cyclomatic complexity 4 (rank A) |
| 778 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/repository/session.py` | 11:0 | block 'SessionRepository' has cyclomatic complexity 3 (rank A) |
| 779 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/repository/session.py` | 96:4 | block 'delete' has cyclomatic complexity 3 (rank A) |
| 780 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/repository/session.py` | 17:4 | block '__init__' has cyclomatic complexity 2 (rank A) |
| 781 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/repository/session.py` | 106:4 | block 'close' has cyclomatic complexity 2 (rank A) |
| 782 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/repository/session.py` | 42:4 | block '_wrap_exception' has cyclomatic complexity 1 (rank A) |
| 783 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/repository/credential.py` | 34:0 | block 'CredentialRepository' has cyclomatic complexity 2 (rank A) |
| 784 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/repository/credential.py` | 51:4 | block 'create_account' has cyclomatic complexity 2 (rank A) |
| 785 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/repository/credential.py` | 11:0 | block 'AccountTable' has cyclomatic complexity 1 (rank A) |
| 786 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/repository/credential.py` | 26:0 | block 'VerificationTokenTable' has cyclomatic complexity 1 (rank A) |
| 787 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/repository/credential.py` | 37:4 | block '__init__' has cyclomatic complexity 1 (rank A) |
| 788 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/repository/credential.py` | 43:4 | block 'get_by_email' has cyclomatic complexity 1 (rank A) |
| 789 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/repository/credential.py` | 47:4 | block 'get_by_id' has cyclomatic complexity 1 (rank A) |
| 790 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/repository/credential.py` | 74:4 | block 'update_account' has cyclomatic complexity 1 (rank A) |
| 791 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/repository/credential.py` | 79:4 | block 'create_verification_token' has cyclomatic complexity 1 (rank A) |
| 792 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/repository/credential.py` | 93:4 | block 'get_verification_token' has cyclomatic complexity 1 (rank A) |
| 793 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/repository/credential.py` | 97:4 | block 'delete_verification_token' has cyclomatic complexity 1 (rank A) |
| 794 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/integrations/email.py` | 44:4 | block 'send_verification_email' has cyclomatic complexity 4 (rank A) |
| 795 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/integrations/email.py` | 122:0 | block 'get_email_client' has cyclomatic complexity 3 (rank A) |
| 796 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/integrations/email.py` | 28:0 | block 'SESEmailClient' has cyclomatic complexity 3 (rank A) |
| 797 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/integrations/email.py` | 8:0 | block 'EmailClientInterface' has cyclomatic complexity 2 (rank A) |
| 798 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/integrations/email.py` | 15:0 | block 'MockEmailClient' has cyclomatic complexity 2 (rank A) |
| 799 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/integrations/email.py` | 37:4 | block '_get_client' has cyclomatic complexity 2 (rank A) |
| 800 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/integrations/email.py` | 10:4 | block 'send_verification_email' has cyclomatic complexity 1 (rank A) |
| 801 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/integrations/email.py` | 18:4 | block 'send_verification_email' has cyclomatic complexity 1 (rank A) |
| 802 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/integrations/email.py` | 31:4 | block '__init__' has cyclomatic complexity 1 (rank A) |
| 803 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/integrations/recaptcha.py` | 8:4 | block '__init__' has cyclomatic complexity 1 (rank A) |
| 804 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/services/totp.py` | 16:0 | block 'TotpService' has cyclomatic complexity 3 (rank A) |
| 805 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/services/totp.py` | 28:4 | block 'verify' has cyclomatic complexity 3 (rank A) |
| 806 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/services/totp.py` | 17:4 | block '__init__' has cyclomatic complexity 1 (rank A) |
| 807 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/services/totp.py` | 20:4 | block 'enroll' has cyclomatic complexity 1 (rank A) |
| 808 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/services/auth.py` | 21:4 | block '__init__' has cyclomatic complexity 1 (rank A) |
| 809 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/services/signup.py` | 15:0 | block 'SignupService' has cyclomatic complexity 5 (rank A) |
| 810 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/services/signup.py` | 25:4 | block 'register' has cyclomatic complexity 5 (rank A) |
| 811 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/services/signup.py` | 18:4 | block '__init__' has cyclomatic complexity 1 (rank A) |
| 812 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/services/session_manager.py` | 17:0 | block 'SessionManager' has cyclomatic complexity 4 (rank A) |
| 813 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/services/session_manager.py` | 101:4 | block 'elevate_mfa' has cyclomatic complexity 3 (rank A) |
| 814 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/services/session_manager.py` | 116:4 | block 'invalidate' has cyclomatic complexity 3 (rank A) |
| 815 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/services/session_manager.py` | 20:4 | block '__init__' has cyclomatic complexity 1 (rank A) |
| 816 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/services/session_manager.py` | 25:4 | block 'issue' has cyclomatic complexity 1 (rank A) |
| 817 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/ops/controller.py` | 53:0 | block 'get_principal' has cyclomatic complexity 2 (rank A) |
| 818 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/ops/controller.py` | 60:0 | block 'enforce_admin_mfa' has cyclomatic complexity 2 (rank A) |
| 819 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/ops/controller.py` | 66:0 | block 'get_dashboard_service' has cyclomatic complexity 2 (rank A) |
| 820 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/ops/controller.py` | 16:0 | block 'WindowDTO' has cyclomatic complexity 1 (rank A) |
| 821 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/ops/controller.py` | 20:0 | block 'BudgetStateDTO' has cyclomatic complexity 1 (rank A) |
| 822 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/ops/controller.py` | 28:0 | block 'HealthStatusDTO' has cyclomatic complexity 1 (rank A) |
| 823 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/ops/controller.py` | 34:0 | block 'DashboardViewDTO' has cyclomatic complexity 1 (rank A) |
| 824 | INFO | `CCA` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/ops/controller.py` | 45:0 | block 'IncidentRecordDTO' has cyclomatic complexity 1 (rank A) |

### 3.7 Dead Code (vulture)

**Findings**: 94
  (MEDIUM: 13, LOW: 81)

| # | Severity | Rule | File | Line | Message |
|---|----------|------|------|------|---------|
| 1 | MEDIUM | `VU002` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/mocks/port_stubs.py` | 33 | unused variable 'eval_set' (100% confidence) |
| 2 | MEDIUM | `VU002` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/mocks/port_stubs.py` | 61 | unused variable 'context' (100% confidence) |
| 3 | MEDIUM | `VU002` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_bedrock_embedding.py` | 28 | unused variable 'accept' (100% confidence) |
| 4 | MEDIUM | `VU002` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_bedrock_embedding.py` | 28 | unused variable 'contentType' (100% confidence) |
| 5 | MEDIUM | `VU002` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_bedrock_embedding.py` | 28 | unused variable 'modelId' (100% confidence) |
| 6 | MEDIUM | `VU002` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_observability_wiring.py` | 26 | unused variable 'context' (100% confidence) |
| 7 | MEDIUM | `VU002` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/stubs.py` | 126 | unused variable 'context' (100% confidence) |
| 8 | MEDIUM | `VU002` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_integration_real.py` | 48 | unused variable 'k' (100% confidence) |
| 9 | MEDIUM | `VU002` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_integration_real.py` | 51 | unused variable 'k' (100% confidence) |
| 10 | MEDIUM | `VU002` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_integration_real.py` | 54 | unused variable 'k' (100% confidence) |
| 11 | MEDIUM | `VU002` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_integration_real.py` | 57 | unused variable 'k' (100% confidence) |
| 12 | MEDIUM | `VU002` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_citation_graph.py` | 172 | unused variable 'args' (100% confidence) |
| 13 | MEDIUM | `VU002` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_u6_middleware.py` | 274 | unused variable 'context' (100% confidence) |
| 14 | LOW | `VU004` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/errors.py` | 27 | unused function '_on_unhandled' (60% confidence) |
| 15 | LOW | `VU004` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/health.py` | 21 | unused function 'healthz' (60% confidence) |
| 16 | LOW | `VU004` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/middleware/gateway.py` | 43 | unused function '_u6_gateway' (60% confidence) |
| 17 | LOW | `VU003` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/middleware/gateway.py` | 48 | unused attribute 'context' (60% confidence) |
| 18 | LOW | `VU002` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/middleware/request_context.py` | 9 | unused variable 'principal_id' (60% confidence) |
| 19 | LOW | `VU004` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/controller.py` | 87 | unused function 'signup' (60% confidence) |
| 20 | LOW | `VU004` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/controller.py` | 120 | unused function 'login' (60% confidence) |
| 21 | LOW | `VU004` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/controller.py` | 181 | unused function 'get_session' (60% confidence) |
| 22 | LOW | `VU004` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/controller.py` | 209 | unused function 'logout' (60% confidence) |
| 23 | LOW | `VU004` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/controller.py` | 227 | unused function 'mfa_enroll' (60% confidence) |
| 24 | LOW | `VU004` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/controller.py` | 258 | unused function 'mfa_verify' (60% confidence) |
| 25 | LOW | `VU004` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/controller.py` | 286 | unused function 'admin_whoami' (60% confidence) |
| 26 | LOW | `VU002` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/models.py` | 38 | unused variable 'READ' (60% confidence) |
| 27 | LOW | `VU002` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/models.py` | 39 | unused variable 'WRITE' (60% confidence) |
| 28 | LOW | `VU005` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/models.py` | 69 | unused class 'PasswordHash' (60% confidence) |
| 29 | LOW | `VU002` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/repository/credential.py` | 20 | unused variable 'last_failed_at' (60% confidence) |
| 30 | LOW | `VU003` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/services/auth.py` | 77 | unused attribute 'last_failed_at' (60% confidence) |
| 31 | LOW | `VU003` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/services/auth.py` | 117 | unused attribute 'last_failed_at' (60% confidence) |
| 32 | LOW | `VU002` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/citation_graph/controller.py` | 17 | unused variable 'MAX_DEPTH' (60% confidence) |
| 33 | LOW | `VU002` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/citation_graph/controller.py` | 32 | unused variable 'citationCount' (60% confidence) |
| 34 | LOW | `VU002` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/citation_graph/controller.py` | 37 | unused variable 'alreadyShown' (60% confidence) |
| 35 | LOW | `VU002` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/citation_graph/controller.py` | 41 | unused variable 'fromNodeId' (60% confidence) |
| 36 | LOW | `VU002` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/citation_graph/controller.py` | 42 | unused variable 'toNodeId' (60% confidence) |
| 37 | LOW | `VU002` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/citation_graph/controller.py` | 60 | unused variable 'remainingEstimate' (60% confidence) |
| 38 | LOW | `VU004` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/citation_graph/controller.py` | 236 | unused function 'get_citation_tree' (60% confidence) |
| 39 | LOW | `VU004` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/citation_graph/controller.py` | 272 | unused function 'save_citation_node' (60% confidence) |
| 40 | LOW | `VU004` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/api/router.py` | 55 | unused function 'paper_meta' (60% confidence) |
| 41 | LOW | `VU004` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/api/router.py` | 77 | unused function '_on_unavailable' (60% confidence) |
| 42 | LOW | `VU004` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/api/router.py` | 81 | unused function '_on_unexpected' (60% confidence) |
| 43 | LOW | `VU002` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/domain/models.py` | 70 | unused variable 'rerank_enabled' (60% confidence) |
| 44 | LOW | `VU002` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/domain/models.py` | 98 | unused variable 'retrieval_mode' (60% confidence) |
| 45 | LOW | `VU002` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/domain/models.py` | 106 | unused variable 'ranking_mode' (60% confidence) |
| 46 | LOW | `VU002` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/mocks/fixtures.py` | 115 | unused variable 'EVAL_CASES' (60% confidence) |
| 47 | LOW | `VU006` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/mocks/port_stubs.py` | 33 | unused method 'run_eval_set' (60% confidence) |
| 48 | LOW | `VU006` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/mocks/port_stubs.py` | 61 | unused method 'start_span' (60% confidence) |
| 49 | LOW | `VU006` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/mocks/port_stubs.py` | 63 | unused method 'audit_append' (60% confidence) |
| 50 | LOW | `VU002` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/service/paper_metadata.py` | 26 | unused variable 'model_config' (60% confidence) |
| 51 | LOW | `VU006` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_observability_wiring.py` | 26 | unused method 'start_span' (60% confidence) |
| 52 | LOW | `VU006` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_observability_wiring.py` | 29 | unused method 'audit_append' (60% confidence) |
| 53 | LOW | `VU002` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_opensearch_integration.py` | 38 | unused variable 'pytestmark' (60% confidence) |
| 54 | LOW | `VU002` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/audit.py` | 23 | unused variable 'at' (60% confidence) |
| 55 | LOW | `VU004` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/controller.py` | 108 | unused function 'create_saved_search' (60% confidence) |
| 56 | LOW | `VU004` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/controller.py` | 120 | unused function 'list_saved_searches' (60% confidence) |
| 57 | LOW | `VU004` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/controller.py` | 133 | unused function 'delete_saved_search' (60% confidence) |
| 58 | LOW | `VU004` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/controller.py` | 146 | unused function 'rerun_saved_search' (60% confidence) |
| 59 | LOW | `VU004` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/controller.py` | 162 | unused function 'add_library_item' (60% confidence) |
| 60 | LOW | `VU004` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/controller.py` | 174 | unused function 'list_library' (60% confidence) |
| 61 | LOW | `VU004` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/controller.py` | 187 | unused function 'remove_library_item' (60% confidence) |
| 62 | LOW | `VU004` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/controller.py` | 204 | unused function 'list_history' (60% confidence) |
| 63 | LOW | `VU004` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/controller.py` | 217 | unused function 'rerun_history_entry' (60% confidence) |
| 64 | LOW | `VU004` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/controller.py` | 229 | unused function 'clear_history' (60% confidence) |
| 65 | LOW | `VU006` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/history_consumer.py` | 21 | unused method 'consume' (60% confidence) |
| 66 | LOW | `VU005` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/models.py` | 43 | unused class 'AuthorizationError' (60% confidence) |
| 67 | LOW | `VU002` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/schemas.py` | 53 | unused variable 'model_config' (60% confidence) |
| 68 | LOW | `VU004` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/api/router.py` | 51 | unused function 'list_glossary' (60% confidence) |
| 69 | LOW | `VU004` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/grounding.py` | 80 | unused function 'is_empty_draft' (60% confidence) |
| 70 | LOW | `VU002` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/models.py` | 44 | unused variable 'FIGURE' (60% confidence) |
| 71 | LOW | `VU004` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/conftest.py` | 16 | unused function 'valid_draft_fixture' (60% confidence) |
| 72 | LOW | `VU006` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/stubs.py` | 126 | unused method 'start_span' (60% confidence) |
| 73 | LOW | `VU006` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/stubs.py` | 129 | unused method 'audit_append' (60% confidence) |
| 74 | LOW | `VU002` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_integration_real.py` | 23 | unused variable 'pytestmark' (60% confidence) |
| 75 | LOW | `VU006` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_integration_real.py` | 54 | unused method 'start_span' (60% confidence) |
| 76 | LOW | `VU006` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_integration_real.py` | 57 | unused method 'audit_append' (60% confidence) |
| 77 | LOW | `VU004` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_app_shell.py` | 134 | unused function '_boom' (60% confidence) |
| 78 | LOW | `VU004` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_app_shell.py` | 175 | unused function '_boom' (60% confidence) |
| 79 | LOW | `VU003` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_ops_endpoints.py` | 45 | unused attribute 'return_value' (60% confidence) |
| 80 | LOW | `VU004` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_u6_middleware.py` | 29 | unused function 'boom' (60% confidence) |
| 81 | LOW | `VU004` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_u6_middleware.py` | 44 | unused function 'limited' (60% confidence) |
| 82 | LOW | `VU004` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_u6_middleware.py` | 58 | unused function 'limited' (60% confidence) |
| 83 | LOW | `VU004` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_u6_middleware.py` | 80 | unused function 'limited' (60% confidence) |
| 84 | LOW | `VU004` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_u6_middleware.py` | 184 | unused function 'protected' (60% confidence) |
| 85 | LOW | `VU004` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_u6_middleware.py` | 202 | unused function 'protected' (60% confidence) |
| 86 | LOW | `VU004` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_u6_middleware.py` | 252 | unused function 'protected' (60% confidence) |
| 87 | LOW | `VU006` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_u6_middleware.py` | 274 | unused method 'start_span' (60% confidence) |
| 88 | LOW | `VU006` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_u6_middleware.py` | 277 | unused method 'audit_append' (60% confidence) |
| 89 | LOW | `VU004` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_u6_middleware.py` | 298 | unused function 'boom' (60% confidence) |
| 90 | LOW | `VU003` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/wiring.py` | 60 | unused attribute 'mounted_modules' (60% confidence) |
| 91 | LOW | `VU003` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/wiring.py` | 134 | unused attribute 'discovery_bundle' (60% confidence) |
| 92 | LOW | `VU003` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/wiring.py` | 210 | unused attribute 'library_repo' (60% confidence) |
| 93 | LOW | `VU003` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/wiring.py` | 211 | unused attribute 'library_history_consumer' (60% confidence) |
| 94 | LOW | `VU003` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/wiring.py` | 240 | unused attribute 'summarization_bundle' (60% confidence) |

### 3.4 Type Safety (mypy)

**Findings**: 264
  (MEDIUM: 249, INFO: 15)

| # | Severity | Rule | File | Line | Message |
|---|----------|------|------|------|---------|
| 1 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/schemas.py:8` | 1 | Cannot find implementation or library stub for module named "docsuri_shared.dtos" |
| 2 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/health.py:11` | 1 | Cannot find implementation or library stub for module named "fastapi" |
| 3 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/db.py:13` | 1 | Cannot find implementation or library stub for module named "sqlalchemy" |
| 4 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/db.py:14` | 1 | Cannot find implementation or library stub for module named "sqlalchemy.engine" |
| 5 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/db.py:15` | 1 | Cannot find implementation or library stub for module named "sqlalchemy.orm" |
| 6 | MEDIUM | `misc` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/config.py:75` | 48 | "database_url" in __slots__ conflicts with class variable access |
| 7 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_pbt.py:5` | 1 | Cannot find implementation or library stub for module named "hypothesis" |
| 8 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_pbt.py:8` | 1 | Cannot find implementation or library stub for module named "summarization.domain.cache_key" |
| 9 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_pbt.py:9` | 1 | Cannot find implementation or library stub for module named "summarization.domain.glossary" |
| 10 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_pbt.py:10` | 1 | Cannot find implementation or library stub for module named "summarization.domain.models" |
| 11 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_pbt.py:19` | 1 | Cannot find implementation or library stub for module named "summarization.domain.refiner" |
| 12 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_orchestrator.py:6` | 1 | Cannot find implementation or library stub for module named "summarization.domain.models" |
| 13 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_orchestrator.py:18` | 1 | Cannot find implementation or library stub for module named "tests.stubs" |
| 14 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_integration_real.py:12` | 1 | Cannot find implementation or library stub for module named "pytest" |
| 15 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_integration_real.py:30` | 1 | Cannot find implementation or library stub for module named "docsuri_shared.ports" |
| 16 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_integration_real.py:32` | 1 | Cannot find implementation or library stub for module named "summarization.adapters.settings" |
| 17 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_integration_real.py:33` | 1 | Cannot find implementation or library stub for module named "summarization.real_wiring" |
| 18 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_domain_source_cache_length.py:5` | 1 | Cannot find implementation or library stub for module named "summarization.domain.cache_key" |
| 19 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_domain_source_cache_length.py:6` | 1 | Cannot find implementation or library stub for module named "summarization.domain.length_router" |
| 20 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_domain_source_cache_length.py:7` | 1 | Cannot find implementation or library stub for module named "summarization.domain.models" |
| 21 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_domain_source_cache_length.py:8` | 1 | Cannot find implementation or library stub for module named "summarization.domain.source_selector" |
| 22 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_domain_source_cache_length.py:9` | 1 | Cannot find implementation or library stub for module named "tests.stubs" |
| 23 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_domain_refiner.py:5` | 1 | Cannot find implementation or library stub for module named "summarization.domain.refiner" |
| 24 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_domain_grounding.py:7` | 1 | Cannot find implementation or library stub for module named "summarization.domain.grounding" |
| 25 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_domain_grounding.py:8` | 1 | Cannot find implementation or library stub for module named "summarization.domain.models" |
| 26 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_domain_grounding.py:9` | 1 | Cannot find implementation or library stub for module named "summarization.domain.refiner" |
| 27 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_domain_glossary.py:5` | 1 | Cannot find implementation or library stub for module named "summarization.domain.glossary" |
| 28 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_domain_glossary.py:6` | 1 | Cannot find implementation or library stub for module named "summarization.domain.models" |
| 29 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/stubs.py:11` | 1 | Cannot find implementation or library stub for module named "summarization.domain.assembler" |
| 30 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/stubs.py:12` | 1 | Cannot find implementation or library stub for module named "summarization.domain.glossary" |
| 31 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/stubs.py:13` | 1 | Cannot find implementation or library stub for module named "summarization.domain.grounding" |
| 32 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/stubs.py:14` | 1 | Cannot find implementation or library stub for module named "summarization.domain.length_router" |
| 33 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/stubs.py:15` | 1 | Cannot find implementation or library stub for module named "summarization.domain.models" |
| 34 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/stubs.py:22` | 1 | Cannot find implementation or library stub for module named "summarization.domain.refiner" |
| 35 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/stubs.py:23` | 1 | Cannot find implementation or library stub for module named "summarization.domain.source_selector" |
| 36 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/stubs.py:24` | 1 | Cannot find implementation or library stub for module named "summarization.ports.ports" |
| 37 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/stubs.py:25` | 1 | Cannot find implementation or library stub for module named "summarization.service.orchestrator" |
| 38 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/conftest.py:5` | 1 | Cannot find implementation or library stub for module named "pytest" |
| 39 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/conftest.py:7` | 1 | Cannot find implementation or library stub for module named "summarization.domain.models" |
| 40 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/conftest.py:8` | 1 | Cannot find implementation or library stub for module named "tests.stubs" |
| 41 | MEDIUM | `no-any-return` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/conftest.py:13` | 5 | Returning Any from function declared to return "str" |
| 42 | MEDIUM | `import-untyped` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/adapters/s3_full_text.py:25` | 1 | Skipping analyzing "boto3": module is installed, but missing library stubs or py.typed marker |
| 43 | MEDIUM | `no-any-return` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/adapters/s3_full_text.py:36` | 13 | Returning Any from function declared to return "str \| None" |
| 44 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_validator_pbt.py:5` | 1 | Cannot find implementation or library stub for module named "hypothesis" |
| 45 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_validator_pbt.py:8` | 1 | Cannot find implementation or library stub for module named "discovery.domain.validator" |
| 46 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_router.py:11` | 1 | Cannot find implementation or library stub for module named "pytest" |
| 47 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_router.py:15` | 1 | Cannot find implementation or library stub for module named "discovery.api.router" |
| 48 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_router.py:16` | 1 | Cannot find implementation or library stub for module named "discovery.mocks" |
| 49 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_router.py:17` | 1 | Cannot find implementation or library stub for module named "discovery.service.orchestrator" |
| 50 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_retriever_pbt.py:5` | 1 | Cannot find implementation or library stub for module named "hypothesis" |
| 51 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_retriever_pbt.py:8` | 1 | Cannot find implementation or library stub for module named "discovery.domain.retriever" |
| 52 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_retriever_pbt.py:9` | 1 | Cannot find implementation or library stub for module named "discovery.mocks.fixtures" |
| 53 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_ranker_pbt.py:5` | 1 | Cannot find implementation or library stub for module named "hypothesis" |
| 54 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_ranker_pbt.py:8` | 1 | Cannot find implementation or library stub for module named "discovery.domain.models" |
| 55 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_ranker_pbt.py:15` | 1 | Cannot find implementation or library stub for module named "discovery.domain.ranker" |
| 56 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_ranker_pbt.py:16` | 1 | Cannot find implementation or library stub for module named "discovery.mocks.fixtures" |
| 57 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_paper_metadata.py:10` | 1 | Cannot find implementation or library stub for module named "pytest" |
| 58 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_paper_metadata.py:12` | 1 | Cannot find implementation or library stub for module named "discovery.mocks.adapters" |
| 59 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_paper_metadata.py:13` | 1 | Cannot find implementation or library stub for module named "discovery.ports.search_ports" |
| 60 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_paper_metadata.py:14` | 1 | Cannot find implementation or library stub for module named "discovery.service.paper_metadata" |
| 61 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_orchestrator.py:9` | 1 | Cannot find implementation or library stub for module named "docsuri_shared.dtos" |
| 62 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_orchestrator.py:16` | 1 | Cannot find implementation or library stub for module named "discovery.api" |
| 63 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_orchestrator.py:17` | 1 | Cannot find implementation or library stub for module named "discovery.domain.models" |
| 64 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_orchestrator.py:18` | 1 | Cannot find implementation or library stub for module named "discovery.mocks" |
| 65 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_opensearch_integration.py:19` | 1 | Cannot find implementation or library stub for module named "pytest" |
| 66 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_opensearch_integration.py:23` | 1 | Cannot find implementation or library stub for module named "discovery.adapters.opensearch_index" |
| 67 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_opensearch_integration.py:28` | 1 | Cannot find implementation or library stub for module named "discovery.adapters.settings" |
| 68 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_opensearch_integration.py:29` | 1 | Cannot find implementation or library stub for module named "discovery.domain.models" |
| 69 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_opensearch_integration.py:34` | 1 | Cannot find implementation or library stub for module named "discovery.domain.retriever" |
| 70 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_opensearch_integration.py:35` | 1 | Cannot find implementation or library stub for module named "discovery.mocks" |
| 71 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_opensearch_integration.py:36` | 1 | Cannot find implementation or library stub for module named "discovery.scripts.seed_local_opensearch" |
| 72 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_opensearch_adapter.py:5` | 1 | Cannot find implementation or library stub for module named "pytest" |
| 73 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_opensearch_adapter.py:6` | 1 | Cannot find implementation or library stub for module named "docsuri_shared.vector_spec" |
| 74 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_opensearch_adapter.py:8` | 1 | Cannot find implementation or library stub for module named "discovery.adapters.opensearch_index" |
| 75 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_opensearch_adapter.py:12` | 1 | Cannot find implementation or library stub for module named "discovery.mocks" |
| 76 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_opensearch_adapter.py:13` | 1 | Cannot find implementation or library stub for module named "discovery.ports.search_ports" |
| 77 | MEDIUM | `misc` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_opensearch_adapter.py:42` | 19 | "None" object is not iterable |
| 78 | MEDIUM | `misc` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_opensearch_adapter.py:56` | 15 | "None" object is not iterable |
| 79 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_observability_wiring.py:9` | 1 | Cannot find implementation or library stub for module named "docsuri_shared.dtos" |
| 80 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_observability_wiring.py:11` | 1 | Cannot find implementation or library stub for module named "discovery.api" |
| 81 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_observability_wiring.py:12` | 1 | Cannot find implementation or library stub for module named "discovery.domain.models" |
| 82 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_observability_wiring.py:13` | 1 | Cannot find implementation or library stub for module named "discovery.mocks" |
| 83 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_fault_injection.py:5` | 1 | Cannot find implementation or library stub for module named "pytest" |
| 84 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_fault_injection.py:6` | 1 | Cannot find implementation or library stub for module named "docsuri_shared.dtos" |
| 85 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_fault_injection.py:8` | 1 | Cannot find implementation or library stub for module named "discovery.api" |
| 86 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_fault_injection.py:9` | 1 | Cannot find implementation or library stub for module named "discovery.domain.models" |
| 87 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_fault_injection.py:10` | 1 | Cannot find implementation or library stub for module named "discovery.mocks" |
| 88 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_fault_injection.py:11` | 1 | Cannot find implementation or library stub for module named "discovery.mocks.adapters" |
| 89 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_fault_injection.py:16` | 1 | Cannot find implementation or library stub for module named "discovery.service.orchestrator" |
| 90 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_dto_roundtrip_pbt.py:5` | 1 | Cannot find implementation or library stub for module named "docsuri_shared.dtos" |
| 91 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_dto_roundtrip_pbt.py:12` | 1 | Cannot find implementation or library stub for module named "hypothesis" |
| 92 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_dto_roundtrip_pbt.py:15` | 1 | Cannot find implementation or library stub for module named "discovery.domain.assembler" |
| 93 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_dto_roundtrip_pbt.py:16` | 1 | Cannot find implementation or library stub for module named "discovery.domain.models" |
| 94 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_dto_roundtrip_pbt.py:17` | 1 | Cannot find implementation or library stub for module named "discovery.mocks.fixtures" |
| 95 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_degradation.py:5` | 1 | Cannot find implementation or library stub for module named "docsuri_shared.dtos" |
| 96 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_degradation.py:7` | 1 | Cannot find implementation or library stub for module named "discovery.api" |
| 97 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_degradation.py:8` | 1 | Cannot find implementation or library stub for module named "discovery.domain.models" |
| 98 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_degradation.py:9` | 1 | Cannot find implementation or library stub for module named "discovery.mocks" |
| 99 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_assembler.py:10` | 1 | Cannot find implementation or library stub for module named "docsuri_shared.dtos" |
| 100 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_assembler.py:12` | 1 | Cannot find implementation or library stub for module named "discovery.domain.assembler" |
| 101 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_assembler.py:13` | 1 | Cannot find implementation or library stub for module named "discovery.domain.models" |
| 102 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/ports/search_ports.py:19` | 1 | Cannot find implementation or library stub for module named "docsuri_shared.events" |
| 103 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/ports/search_ports.py:20` | 1 | Cannot find implementation or library stub for module named "docsuri_shared.vector_spec" |
| 104 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/mocks/port_stubs.py:9` | 1 | Cannot find implementation or library stub for module named "docsuri_shared.events" |
| 105 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/mocks/port_stubs.py:10` | 1 | Cannot find implementation or library stub for module named "docsuri_shared.ports" |
| 106 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/mocks/fixtures.py:12` | 1 | Cannot find implementation or library stub for module named "docsuri_shared.ids" |
| 107 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/mocks/fixtures.py:13` | 1 | Cannot find implementation or library stub for module named "docsuri_shared.vector_spec" |
| 108 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/domain/models.py:14` | 1 | Cannot find implementation or library stub for module named "docsuri_shared.vector_spec" |
| 109 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_glossary_upsert.py:14` | 1 | Cannot find implementation or library stub for module named "pytest" |
| 110 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_glossary_upsert.py:16` | 1 | Cannot find implementation or library stub for module named "summarization.api.router" |
| 111 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_glossary_upsert.py:17` | 1 | Cannot find implementation or library stub for module named "summarization.domain.glossary" |
| 112 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_glossary_upsert.py:18` | 1 | Cannot find implementation or library stub for module named "summarization.domain.models" |
| 113 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_bedrock_embedding.py:7` | 1 | Cannot find implementation or library stub for module named "pytest" |
| 114 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_bedrock_embedding.py:8` | 1 | Cannot find implementation or library stub for module named "docsuri_shared.vector_spec" |
| 115 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_bedrock_embedding.py:10` | 1 | Cannot find implementation or library stub for module named "discovery.adapters.bedrock_embedding" |
| 116 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_bedrock_embedding.py:11` | 1 | Cannot find implementation or library stub for module named "discovery.ports.search_ports" |
| 117 | MEDIUM | `import-untyped` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/adapters/s3_redis_store.py:28` | 1 | Skipping analyzing "boto3": module is installed, but missing library stubs or py.typed marker |
| 118 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/adapters/s3_redis_store.py:32` | 1 | Cannot find implementation or library stub for module named "redis" |
| 119 | MEDIUM | `no-any-return` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/adapters/s3_redis_store.py:46` | 21 | Returning Any from function declared to return "dict[Any, Any] \| None" |
| 120 | MEDIUM | `no-any-return` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/adapters/s3_redis_store.py:55` | 9 | Returning Any from function declared to return "dict[Any, Any] \| None" |
| 121 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/adapters/rds_glossary.py:25` | 1 | Cannot find implementation or library stub for module named "psycopg" |
| 122 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/adapters/opensearch_index.py:19` | 1 | Cannot find implementation or library stub for module named "docsuri_shared.vector_spec" |
| 123 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/adapters/opensearch_index.py:36` | 1 | Cannot find implementation or library stub for module named "opensearchpy" |
| 124 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/adapters/bedrock_embedding.py:16` | 1 | Cannot find implementation or library stub for module named "docsuri_shared.vector_spec" |
| 125 | MEDIUM | `import-untyped` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/adapters/bedrock_embedding.py:28` | 1 | Skipping analyzing "boto3": module is installed, but missing library stubs or py.typed marker |
| 126 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/domain/grounding_adapter.py:12` | 1 | Cannot find implementation or library stub for module named "docsuri_shared.ports" |
| 127 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/domain/assembler.py:13` | 1 | Cannot find implementation or library stub for module named "docsuri_shared.dtos" |
| 128 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/gateway.py:12` | 1 | Cannot find implementation or library stub for module named "docsuri_shared.dtos" |
| 129 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/repository/session.py:4` | 1 | Cannot find implementation or library stub for module named "redis.asyncio" |
| 130 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/repository/session.py:4` | 1 | Cannot find implementation or library stub for module named "redis" |
| 131 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/repository/session.py:5` | 1 | Cannot find implementation or library stub for module named "redis.exceptions" |
| 132 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/repository/credential.py:4` | 1 | Cannot find implementation or library stub for module named "sqlalchemy" |
| 133 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/repository/credential.py:5` | 1 | Cannot find implementation or library stub for module named "sqlalchemy.orm" |
| 134 | MEDIUM | `valid-type` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/repository/credential.py:11` | 20 | Variable "backend.modules.accounts.repository.credential.Base" is not valid as a type |
| 135 | MEDIUM | `misc` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/repository/credential.py:11` | 20 | Invalid base class "Base" |
| 136 | MEDIUM | `valid-type` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/repository/credential.py:26` | 30 | Variable "backend.modules.accounts.repository.credential.Base" is not valid as a type |
| 137 | MEDIUM | `misc` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/repository/credential.py:26` | 30 | Invalid base class "Base" |
| 138 | MEDIUM | `no-any-return` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/repository/credential.py:45` | 9 | Returning Any from function declared to return "AccountTable \| None" |
| 139 | MEDIUM | `no-any-return` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/repository/credential.py:49` | 9 | Returning Any from function declared to return "AccountTable \| None" |
| 140 | MEDIUM | `no-any-return` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/repository/credential.py:95` | 9 | Returning Any from function declared to return "VerificationTokenTable \| None" |
| 141 | MEDIUM | `misc` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/glossary.py:81` | 54 | Cannot infer type of lambda |
| 142 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/service/orchestrator.py:20` | 1 | Cannot find implementation or library stub for module named "docsuri_shared.dtos" |
| 143 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/service/orchestrator.py:27` | 1 | Cannot find implementation or library stub for module named "docsuri_shared.events" |
| 144 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/service/orchestrator.py:28` | 1 | Cannot find implementation or library stub for module named "docsuri_shared.ports" |
| 145 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/errors.py:17` | 1 | Cannot find implementation or library stub for module named "fastapi" |
| 146 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/errors.py:18` | 1 | Cannot find implementation or library stub for module named "fastapi.responses" |
| 147 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/password.py:5` | 1 | Cannot find implementation or library stub for module named "argon2" |
| 148 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/migrations/__init__.py:31` | 1 | Cannot find implementation or library stub for module named "psycopg" |
| 149 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/middleware/auth.py:17` | 1 | Cannot find implementation or library stub for module named "fastapi" |
| 150 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/middleware/auth.py:63` | 1 | Cannot find implementation or library stub for module named "fastapi.responses" |
| 151 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/services/totp.py:9` | 1 | Cannot find implementation or library stub for module named "pyotp" |
| 152 | MEDIUM | `no-any-return` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/services/totp.py:26` | 9 | Returning Any from function declared to return "str" |
| 153 | MEDIUM | `no-any-return` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/services/totp.py:33` | 9 | Returning Any from function declared to return "bool" |
| 154 | MEDIUM | `import-untyped` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/adapters/bedrock_llm.py:39` | 1 | Skipping analyzing "boto3": module is installed, but missing library stubs or py.typed marker |
| 155 | MEDIUM | `no-any-return` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/adapters/bedrock_llm.py:105` | 5 | Returning Any from function declared to return "dict[Any, Any]" |
| 156 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/api/gateway_seam.py:12` | 1 | Cannot find implementation or library stub for module named "docsuri_shared.dtos" |
| 157 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/api/gateway_seam.py:13` | 1 | Cannot find implementation or library stub for module named "docsuri_shared.ports" |
| 158 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/seed_admin.py:20` | 1 | Cannot find implementation or library stub for module named "sqlalchemy" |
| 159 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/seed_admin.py:21` | 1 | Cannot find implementation or library stub for module named "sqlalchemy.orm" |
| 160 | MEDIUM | `no-any-return` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/seed_admin.py:53` | 5 | Returning Any from function declared to return "str" |
| 161 | MEDIUM | `arg-type` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/migrations/__main__.py:31` | 43 | Argument 2 to "pending_migrations" has incompatible type "list[str]"; expected "list[str \| Path]" |
| 162 | MEDIUM | `arg-type` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/migrations/__main__.py:41` | 41 | Argument 2 to "apply_migrations" has incompatible type "list[str]"; expected "list[str \| Path]" |
| 163 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/middleware/gateway.py:7` | 1 | Cannot find implementation or library stub for module named "fastapi" |
| 164 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/middleware/gateway.py:8` | 1 | Cannot find implementation or library stub for module named "fastapi.responses" |
| 165 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/service/orchestrator.py:18` | 1 | Cannot find implementation or library stub for module named "docsuri_shared.ports" |
| 166 | MEDIUM | `return-value` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/service/orchestrator.py:84` | 20 | Incompatible return value type (got "_CachedResult", expected "SummaryResultDTO \| AbstainDTO \| CostDegradedDTO \| SourceUnavailableDTO") |
| 167 | MEDIUM | `no-any-return` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/service/orchestrator.py:178` | 17 | Returning Any from function declared to return "int" |
| 168 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/middleware/wiring.py:3` | 1 | Cannot find implementation or library stub for module named "fastapi" |
| 169 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/real_wiring.py:12` | 1 | Cannot find implementation or library stub for module named "docsuri_shared.ports" |
| 170 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/ops/controller.py:7` | 1 | Cannot find implementation or library stub for module named "fastapi" |
| 171 | MEDIUM | `no-any-return` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/ops/controller.py:57` | 5 | Returning Any from function declared to return "Principal" |
| 172 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/ops/controller.py:84` | 1 | Cannot find implementation or library stub for module named "docsuri_ops.domain.models" |
| 173 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/ops/controller.py:144` | 1 | Cannot find implementation or library stub for module named "docsuri_ops.domain.enums" |
| 174 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/schemas.py:17` | 1 | Cannot find implementation or library stub for module named "docsuri_shared.dtos" |
| 175 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/api/router.py:13` | 1 | Cannot find implementation or library stub for module named "fastapi" |
| 176 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/api/router.py:14` | 1 | Cannot find implementation or library stub for module named "fastapi.responses" |
| 177 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_u6_middleware.py:3` | 1 | Cannot find implementation or library stub for module named "fastapi" |
| 178 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_u6_middleware.py:4` | 1 | Cannot find implementation or library stub for module named "fastapi.testclient" |
| 179 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/mocks/adapters.py:10` | 1 | Cannot find implementation or library stub for module named "docsuri_shared.vector_spec" |
| 180 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/api/router.py:14` | 1 | Cannot find implementation or library stub for module named "docsuri_shared.dtos" |
| 181 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/api/router.py:15` | 1 | Cannot find implementation or library stub for module named "docsuri_shared.ports" |
| 182 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/api/router.py:16` | 1 | Cannot find implementation or library stub for module named "fastapi" |
| 183 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/api/router.py:17` | 1 | Cannot find implementation or library stub for module named "fastapi.responses" |
| 184 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_event_publisher.py:8` | 1 | Cannot find implementation or library stub for module named "docsuri_shared.events" |
| 185 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_event_publisher.py:10` | 1 | Cannot find implementation or library stub for module named "discovery.adapters.event_publisher" |
| 186 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/adapters/event_publisher.py:20` | 1 | Cannot find implementation or library stub for module named "docsuri_shared.events" |
| 187 | MEDIUM | `import-untyped` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/adapters/event_publisher.py:38` | 1 | Skipping analyzing "boto3": module is installed, but missing library stubs or py.typed marker |
| 188 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/sql.py:13` | 1 | Cannot find implementation or library stub for module named "sqlalchemy" |
| 189 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/sql.py:14` | 1 | Cannot find implementation or library stub for module named "sqlalchemy.orm" |
| 190 | MEDIUM | `no-any-return` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/sql.py:114` | 9 | Returning Any from function declared to return "int" |
| 191 | MEDIUM | `no-any-return` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/sql.py:152` | 9 | Returning Any from function declared to return "bool" |
| 192 | MEDIUM | `no-any-return` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/sql.py:187` | 9 | Returning Any from function declared to return "int" |
| 193 | MEDIUM | `no-any-return` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/sql.py:212` | 9 | Returning Any from function declared to return "bool" |
| 194 | MEDIUM | `no-any-return` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/sql.py:262` | 9 | Returning Any from function declared to return "int" |
| 195 | MEDIUM | `no-any-return` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/sql.py:279` | 9 | Returning Any from function declared to return "int" |
| 196 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/scripts/seed_local_opensearch.py:23` | 1 | Cannot find implementation or library stub for module named "docsuri_shared.vector_spec" |
| 197 | MEDIUM | `import-untyped` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/integrations/email.py:39` | 1 | Skipping analyzing "boto3": module is installed, but missing library stubs or py.typed marker |
| 198 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/real_wiring.py:19` | 1 | Cannot find implementation or library stub for module named "docsuri_shared.ports" |
| 199 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/services/history.py:12` | 1 | Cannot find implementation or library stub for module named "docsuri_shared.events" |
| 200 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/services/signup.py:6` | 1 | Cannot find implementation or library stub for module named "docsuri_shared.events" |
| 201 | MEDIUM | `no-any-return` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/services/signup.py:82` | 9 | Returning Any from function declared to return "str" |
| 202 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/history_consumer.py:11` | 1 | Cannot find implementation or library stub for module named "docsuri_shared.events" |
| 203 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/controller.py:15` | 1 | Cannot find implementation or library stub for module named "fastapi" |
| 204 | MEDIUM | `return-value` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/controller.py:48` | 12 | Incompatible return value type (got "InMemoryUserDataRepository", expected "UserDataRepository") |
| 205 | MEDIUM | `no-any-return` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/controller.py:67` | 5 | Returning Any from function declared to return "Principal" |
| 206 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/citation_graph/controller.py:9` | 1 | Cannot find implementation or library stub for module named "fastapi" |
| 207 | MEDIUM | `no-any-return` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/citation_graph/controller.py:134` | 5 | Returning Any from function declared to return "Principal" |
| 208 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/services/auth.py:5` | 1 | Cannot find implementation or library stub for module named "argon2.exceptions" |
| 209 | MEDIUM | `union-attr` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/services/auth.py:108` | 12 | Item "None" of "AccountTable \| None" has no attribute "status" |
| 210 | MEDIUM | `union-attr` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/services/auth.py:110` | 14 | Item "None" of "AccountTable \| None" has no attribute "status" |
| 211 | MEDIUM | `union-attr` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/services/auth.py:115` | 12 | Item "None" of "AccountTable \| None" has no attribute "failure_count" |
| 212 | MEDIUM | `union-attr` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/services/auth.py:116` | 13 | Item "None" of "AccountTable \| None" has no attribute "failure_count" |
| 213 | MEDIUM | `union-attr` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/services/auth.py:117` | 13 | Item "None" of "AccountTable \| None" has no attribute "last_failed_at" |
| 214 | MEDIUM | `arg-type` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/services/auth.py:118` | 39 | Argument 1 to "update_account" of "CredentialRepository" has incompatible type "AccountTable \| None"; expected "AccountTable" |
| 215 | MEDIUM | `union-attr` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/services/auth.py:125` | 17 | Item "None" of "AccountTable \| None" has no attribute "password_hash" |
| 216 | MEDIUM | `arg-type` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/services/auth.py:126` | 43 | Argument 1 to "update_account" of "CredentialRepository" has incompatible type "AccountTable \| None"; expected "AccountTable" |
| 217 | MEDIUM | `union-attr` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/services/auth.py:127` | 95 | Item "None" of "AccountTable \| None" has no attribute "id" |
| 218 | MEDIUM | `union-attr` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/services/auth.py:139` | 37 | Item "None" of "AccountTable \| None" has no attribute "role" |
| 219 | MEDIUM | `union-attr` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/services/auth.py:143` | 21 | Item "None" of "AccountTable \| None" has no attribute "id" |
| 220 | MEDIUM | `union-attr` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/services/auth.py:153` | 30 | Item "None" of "AccountTable \| None" has no attribute "id" |
| 221 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/controller.py:5` | 1 | Cannot find implementation or library stub for module named "fastapi" |
| 222 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/controller.py:7` | 1 | Cannot find implementation or library stub for module named "sqlalchemy.orm" |
| 223 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/wiring.py:25` | 1 | Cannot find implementation or library stub for module named "fastapi" |
| 224 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/wiring.py:102` | 1 | Cannot find implementation or library stub for module named "discovery.adapters.settings" |
| 225 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/wiring.py:103` | 1 | Cannot find implementation or library stub for module named "discovery.api.router" |
| 226 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/wiring.py:104` | 1 | Cannot find implementation or library stub for module named "docsuri_ops.grounding" |
| 227 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/wiring.py:118` | 1 | Cannot find implementation or library stub for module named "discovery.real_wiring" |
| 228 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/wiring.py:123` | 1 | Cannot find implementation or library stub for module named "discovery.mocks.wiring" |
| 229 | MEDIUM | `arg-type` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/wiring.py:212` | 30 | Argument 1 to "SearchHistoryService" has incompatible type "InMemoryUserDataRepository"; expected "UserDataRepository" |
| 230 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/wiring.py:223` | 1 | Cannot find implementation or library stub for module named "summarization.adapters.settings" |
| 231 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/wiring.py:231` | 1 | Cannot find implementation or library stub for module named "summarization.api.router" |
| 232 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/wiring.py:232` | 1 | Cannot find implementation or library stub for module named "summarization.real_wiring" |
| 233 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/app.py:21` | 1 | Cannot find implementation or library stub for module named "fastapi" |
| 234 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/app.py:22` | 1 | Cannot find implementation or library stub for module named "fastapi.middleware.cors" |
| 235 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/app.py:144` | 1 | Cannot find implementation or library stub for module named "docsuri_ops.observability" |
| 236 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/app.py:151` | 1 | Cannot find implementation or library stub for module named "docsuri_ops.adapters.cloudwatch" |
| 237 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/app.py:160` | 1 | Cannot find implementation or library stub for module named "docsuri_ops.adapters.local" |
| 238 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/app.py:222` | 1 | Cannot find implementation or library stub for module named "docsuri_ops.cost_guard" |
| 239 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/app.py:223` | 1 | Cannot find implementation or library stub for module named "docsuri_ops.dashboard" |
| 240 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/app.py:224` | 1 | Cannot find implementation or library stub for module named "docsuri_ops.health" |
| 241 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_ops_endpoints.py:6` | 1 | Cannot find implementation or library stub for module named "pytest" |
| 242 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_ops_endpoints.py:7` | 1 | Cannot find implementation or library stub for module named "docsuri_ops.domain.enums" |
| 243 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_ops_endpoints.py:8` | 1 | Cannot find implementation or library stub for module named "docsuri_ops.domain.models" |
| 244 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_ops_endpoints.py:9` | 1 | Cannot find implementation or library stub for module named "fastapi.testclient" |
| 245 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_citation_graph.py:8` | 1 | Cannot find implementation or library stub for module named "pytest" |
| 246 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_citation_graph.py:9` | 1 | Cannot find implementation or library stub for module named "fastapi.testclient" |
| 247 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_app_shell.py:11` | 1 | Cannot find implementation or library stub for module named "fastapi" |
| 248 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_app_shell.py:12` | 1 | Cannot find implementation or library stub for module named "fastapi.testclient" |
| 249 | MEDIUM | `import-not-found` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_app_shell.py:163` | 1 | Cannot find implementation or library stub for module named "docsuri_ops.grounding" |
| 250 | INFO | `note` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/repository/credential.py:11` | 20 | See https://mypy.readthedocs.io/en/stable/common_issues.html#variables-vs-type-aliases |
| 251 | INFO | `note` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/repository/credential.py:26` | 30 | See https://mypy.readthedocs.io/en/stable/common_issues.html#variables-vs-type-aliases |
| 252 | INFO | `note` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/middleware/auth.py:63` | 1 | See https://mypy.readthedocs.io/en/stable/running_mypy.html#missing-imports |
| 253 | INFO | `note` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/migrations/__main__.py:31` | 43 | "list" is invariant -- see https://mypy.readthedocs.io/en/stable/common_issues.html#variance |
| 254 | INFO | `note` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/migrations/__main__.py:31` | 43 | Consider using "Sequence" instead, which is covariant |
| 255 | INFO | `note` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/migrations/__main__.py:41` | 41 | "list" is invariant -- see https://mypy.readthedocs.io/en/stable/common_issues.html#variance |
| 256 | INFO | `note` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/migrations/__main__.py:41` | 41 | Consider using "Sequence" instead, which is covariant |
| 257 | INFO | `note` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/controller.py:48` | 12 | Following member(s) of "InMemoryUserDataRepository" have conflicts: |
| 258 | INFO | `note` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/controller.py:48` | 12 | history: expected "SearchHistoryRepository", got "InMemorySearchHistoryRepository" |
| 259 | INFO | `note` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/controller.py:48` | 12 | library: expected "LibraryRepository", got "InMemoryLibraryRepository" |
| 260 | INFO | `note` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/controller.py:48` | 12 | <1 more conflict(s) not shown> |
| 261 | INFO | `note` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/wiring.py:212` | 30 | Following member(s) of "InMemoryUserDataRepository" have conflicts: |
| 262 | INFO | `note` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/wiring.py:212` | 30 | history: expected "SearchHistoryRepository", got "InMemorySearchHistoryRepository" |
| 263 | INFO | `note` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/wiring.py:212` | 30 | library: expected "LibraryRepository", got "InMemoryLibraryRepository" |
| 264 | INFO | `note` | `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/wiring.py:212` | 30 | <1 more conflict(s) not shown> |

### 3.1 Security (bandit)

No findings.

## 5. Appendix

**Timestamp**: 2026-06-22T06:38:31Z  
**Target path**: `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend`  

### Files Analyzed

- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/app.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/app.py:144`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/app.py:151`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/app.py:160`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/app.py:21`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/app.py:22`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/app.py:222`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/app.py:223`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/app.py:224`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/config.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/config.py:75`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/db.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/db.py:13`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/db.py:14`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/db.py:15`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/errors.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/errors.py:17`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/errors.py:18`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/health.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/health.py:11`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/middleware/auth.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/middleware/auth.py:17`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/middleware/auth.py:63`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/middleware/gateway.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/middleware/gateway.py:7`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/middleware/gateway.py:8`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/middleware/rate_limit.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/middleware/request_context.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/middleware/security_headers.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/middleware/wiring.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/middleware/wiring.py:3`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/migrations/__init__.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/migrations/__init__.py:31`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/migrations/__main__.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/migrations/__main__.py:31`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/migrations/__main__.py:41`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/controller.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/controller.py:5`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/controller.py:7`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/guard.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/integrations/email.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/integrations/email.py:39`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/integrations/recaptcha.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/models.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/password.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/password.py:5`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/repository/credential.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/repository/credential.py:11`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/repository/credential.py:26`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/repository/credential.py:4`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/repository/credential.py:45`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/repository/credential.py:49`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/repository/credential.py:5`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/repository/credential.py:95`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/repository/session.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/repository/session.py:4`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/repository/session.py:5`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/schemas.py:8`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/seed_admin.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/seed_admin.py:20`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/seed_admin.py:21`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/seed_admin.py:53`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/services/auth.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/services/auth.py:108`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/services/auth.py:110`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/services/auth.py:115`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/services/auth.py:116`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/services/auth.py:117`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/services/auth.py:118`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/services/auth.py:125`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/services/auth.py:126`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/services/auth.py:127`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/services/auth.py:139`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/services/auth.py:143`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/services/auth.py:153`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/services/auth.py:5`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/services/session_manager.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/services/signup.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/services/signup.py:6`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/services/signup.py:82`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/services/totp.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/services/totp.py:26`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/services/totp.py:33`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/accounts/services/totp.py:9`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/citation_graph/controller.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/citation_graph/controller.py:134`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/citation_graph/controller.py:9`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/adapters/bedrock_embedding.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/adapters/bedrock_embedding.py:16`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/adapters/bedrock_embedding.py:28`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/adapters/event_publisher.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/adapters/event_publisher.py:20`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/adapters/event_publisher.py:38`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/adapters/opensearch_index.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/adapters/opensearch_index.py:19`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/adapters/opensearch_index.py:36`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/adapters/settings.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/api/gateway_seam.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/api/gateway_seam.py:12`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/api/gateway_seam.py:13`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/api/router.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/api/router.py:14`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/api/router.py:15`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/api/router.py:16`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/api/router.py:17`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/cache/embedding_cache.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/domain/assembler.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/domain/assembler.py:13`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/domain/expander.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/domain/grounding_adapter.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/domain/grounding_adapter.py:12`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/domain/models.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/domain/models.py:14`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/domain/ranker.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/domain/retriever.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/domain/validator.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/mocks/adapters.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/mocks/adapters.py:10`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/mocks/fixtures.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/mocks/fixtures.py:12`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/mocks/fixtures.py:13`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/mocks/port_stubs.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/mocks/port_stubs.py:10`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/mocks/port_stubs.py:9`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/mocks/wiring.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/ports/search_ports.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/ports/search_ports.py:19`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/ports/search_ports.py:20`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/real_wiring.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/real_wiring.py:19`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/scripts/seed_local_opensearch.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/scripts/seed_local_opensearch.py:23`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/service/orchestrator.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/service/orchestrator.py:20`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/service/orchestrator.py:27`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/service/orchestrator.py:28`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/src/discovery/service/paper_metadata.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_assembler.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_assembler.py:10`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_assembler.py:12`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_assembler.py:13`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_bedrock_embedding.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_bedrock_embedding.py:10`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_bedrock_embedding.py:11`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_bedrock_embedding.py:7`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_bedrock_embedding.py:8`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_degradation.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_degradation.py:5`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_degradation.py:7`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_degradation.py:8`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_degradation.py:9`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_dto_roundtrip_pbt.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_dto_roundtrip_pbt.py:12`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_dto_roundtrip_pbt.py:15`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_dto_roundtrip_pbt.py:16`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_dto_roundtrip_pbt.py:17`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_dto_roundtrip_pbt.py:5`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_event_publisher.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_event_publisher.py:10`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_event_publisher.py:8`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_fault_injection.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_fault_injection.py:10`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_fault_injection.py:11`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_fault_injection.py:16`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_fault_injection.py:5`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_fault_injection.py:6`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_fault_injection.py:8`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_fault_injection.py:9`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_observability_wiring.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_observability_wiring.py:11`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_observability_wiring.py:12`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_observability_wiring.py:13`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_observability_wiring.py:9`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_opensearch_adapter.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_opensearch_adapter.py:12`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_opensearch_adapter.py:13`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_opensearch_adapter.py:42`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_opensearch_adapter.py:5`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_opensearch_adapter.py:56`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_opensearch_adapter.py:6`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_opensearch_adapter.py:8`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_opensearch_integration.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_opensearch_integration.py:19`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_opensearch_integration.py:23`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_opensearch_integration.py:28`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_opensearch_integration.py:29`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_opensearch_integration.py:34`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_opensearch_integration.py:35`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_opensearch_integration.py:36`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_orchestrator.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_orchestrator.py:16`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_orchestrator.py:17`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_orchestrator.py:18`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_orchestrator.py:9`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_paper_metadata.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_paper_metadata.py:10`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_paper_metadata.py:12`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_paper_metadata.py:13`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_paper_metadata.py:14`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_ranker_pbt.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_ranker_pbt.py:15`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_ranker_pbt.py:16`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_ranker_pbt.py:5`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_ranker_pbt.py:8`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_retriever_pbt.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_retriever_pbt.py:5`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_retriever_pbt.py:8`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_retriever_pbt.py:9`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_router.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_router.py:11`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_router.py:15`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_router.py:16`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_router.py:17`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_validator_pbt.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_validator_pbt.py:5`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/discovery/tests/test_validator_pbt.py:8`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/audit.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/authz.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/controller.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/controller.py:15`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/controller.py:48`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/controller.py:67`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/gateway.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/gateway.py:12`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/history_consumer.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/history_consumer.py:11`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/models.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/ports.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/memory.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/sql.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/sql.py:114`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/sql.py:13`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/sql.py:14`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/sql.py:152`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/sql.py:187`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/sql.py:212`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/sql.py:262`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/repository/sql.py:279`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/schemas.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/schemas.py:17`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/services/history.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/services/history.py:12`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/services/library.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/services/saved_search.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/library/validation.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/ops/controller.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/ops/controller.py:144`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/ops/controller.py:57`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/ops/controller.py:7`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/ops/controller.py:84`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/adapters/bedrock_llm.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/adapters/bedrock_llm.py:105`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/adapters/bedrock_llm.py:39`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/adapters/rds_glossary.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/adapters/rds_glossary.py:25`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/adapters/s3_full_text.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/adapters/s3_full_text.py:25`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/adapters/s3_full_text.py:36`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/adapters/s3_redis_store.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/adapters/s3_redis_store.py:28`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/adapters/s3_redis_store.py:32`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/adapters/s3_redis_store.py:46`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/adapters/s3_redis_store.py:55`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/adapters/settings.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/api/gateway_seam.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/api/router.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/api/router.py:13`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/api/router.py:14`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/assembler.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/cache_key.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/glossary.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/glossary.py:81`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/grounding.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/length_router.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/models.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/refiner.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/domain/source_selector.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/ports/ports.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/prompts/templates.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/real_wiring.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/real_wiring.py:12`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/service/orchestrator.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/service/orchestrator.py:178`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/service/orchestrator.py:18`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/src/summarization/service/orchestrator.py:84`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/conftest.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/conftest.py:13`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/conftest.py:5`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/conftest.py:7`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/conftest.py:8`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/stubs.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/stubs.py:11`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/stubs.py:12`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/stubs.py:13`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/stubs.py:14`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/stubs.py:15`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/stubs.py:22`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/stubs.py:23`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/stubs.py:24`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/stubs.py:25`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_domain_glossary.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_domain_glossary.py:5`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_domain_glossary.py:6`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_domain_grounding.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_domain_grounding.py:7`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_domain_grounding.py:8`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_domain_grounding.py:9`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_domain_refiner.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_domain_refiner.py:5`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_domain_source_cache_length.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_domain_source_cache_length.py:5`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_domain_source_cache_length.py:6`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_domain_source_cache_length.py:7`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_domain_source_cache_length.py:8`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_domain_source_cache_length.py:9`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_glossary_upsert.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_glossary_upsert.py:14`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_glossary_upsert.py:16`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_glossary_upsert.py:17`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_glossary_upsert.py:18`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_integration_real.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_integration_real.py:12`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_integration_real.py:30`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_integration_real.py:32`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_integration_real.py:33`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_orchestrator.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_orchestrator.py:18`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_orchestrator.py:6`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_pbt.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_pbt.py:10`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_pbt.py:19`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_pbt.py:5`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_pbt.py:8`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/modules/summarization/tests/test_pbt.py:9`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_app_shell.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_app_shell.py:11`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_app_shell.py:12`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_app_shell.py:163`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_citation_graph.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_citation_graph.py:8`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_citation_graph.py:9`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_ops_endpoints.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_ops_endpoints.py:6`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_ops_endpoints.py:7`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_ops_endpoints.py:8`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_ops_endpoints.py:9`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_u6_middleware.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_u6_middleware.py:3`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/tests/test_u6_middleware.py:4`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/wiring.py`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/wiring.py:102`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/wiring.py:103`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/wiring.py:104`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/wiring.py:118`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/wiring.py:123`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/wiring.py:212`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/wiring.py:223`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/wiring.py:231`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/wiring.py:232`
- `/Users/revenantonthemission/.claude/jobs/56eec639/tmp/cr-ds/backend/wiring.py:25`

### Tool Versions

| Tool | Category |
|------|----------|
| ruff | Linting / Style Conformance |
| radon | Complexity |
| vulture | Dead Code |
| mypy | Type Safety |
| bandit | Security |
