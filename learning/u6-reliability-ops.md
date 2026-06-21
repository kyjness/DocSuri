# U6 Reliability / Ops — 파이프라인 상세 (게이트웨이·근거화·비용·인시던트)

> 학습용 메모. **커밋하지 않는다.** 근거: `backend/middleware/` + `ops/src/docsuri_ops/` 실제 코드.
> 형식: **[받음] → [함] → [내보냄]**. 먼저 `00-project-overview.md`·`u2`·`u3`·`u4` 가정.
> ★U6는 U2·U3·U4가 "갖다 쓰기만" 한 **단일 권위들의 실체**다. 지금까지 "U6가 한다"고 넘어간 게 다 여기 있다.

---

## 0. 이 유닛이 하는 일 / 코드 구성

U6 = **횡단 관심사(cross-cutting)의 단일 권위**. 모든 유닛에 공통으로 필요한 것(검문·안전·비용·관측)을 한 곳이 소유하고, 나머지는 **호출/조회만** 한다(재구현 금지 → 정책이 한 군데서만 바뀜).

**두 반쪽**:
- **ⓐ 요청 엣지 게이트웨이** (`backend/middleware/`) — 모든 HTTP 요청을 감싸는 **동기 미들웨어**.
- **ⓑ 단일 권위 컴포넌트** (`ops/src/docsuri_ops/`) — 다른 유닛이 호출/조회. **비동기 운영 워커** 포함.

```
backend/middleware/          ← ⓐ 게이트웨이
├── gateway.py               ← ★미들웨어 본체 (요청을 감싸는 순서)
├── rate_limit.py            ← 요청 속도 제한 (InMemoryRateLimiter)
├── auth.py                  ← 세션 쿠키 → principal 주입
├── request_context.py       ← request_id 컨텍스트
└── security_headers.py      ← 보안 헤더

ops/src/docsuri_ops/         ← ⓑ 단일 권위
├── grounding.py             ← GroundingEnforcementHook  (U2 ⑦이 부른 것)
├── cost_guard.py            ← CostGuardCircuitBreaker   (U2 ②·U7이 읽은 것)
├── observability.py         ← ObservabilityHub (관측, 비차단)
├── detectors.py             ← 인시던트 탐지기 3종
├── incidents.py             ← 탐지 묶음 + 발행
└── worker.py                ← 운영 워커 (텔레메트리 → 인시던트)
```

---

## ⓐ 요청 엣지 게이트웨이 — `gateway.py` `install_gateway_middleware`

**[받음]** 모든 들어오는 HTTP 요청(U5/BFF에서).
**[함]** 요청 하나를 **이 순서로** 감싼다:

```
① request_id 부여   X-Request-ID 헤더 있으면 그것, 없으면 uuid4 → request.state에 저장
② rate limit        rate_limiter.allow(key) → 초과면 즉시 429 (라우팅 전에 끊음)
③ auth 주입         세션 쿠키 → verify → request.state.principal (아래 auth.py)
④ call_next         → 실제 도메인 모듈(U2/U3/U4/U7)
⑤ 예외 처리         도메인이 던진 예외 → 일반화 500 (스택 비노출), 에러 로그 emit
⑥ 응답 가공         보안 헤더 + X-Request-ID 부착
⑦ finally           latency + throughput 메트릭 emit (★모든 경로에서 1회, 예외 포함)
```

**[내보냄]** 가공된 응답(보안 헤더·X-Request-ID 부착). 또는 차단 응답(429/401/500).

### ② rate limit — 속도 제한, 키 위조 방지

`rate_limit.py` `InMemoryRateLimiter`: **슬라이딩 윈도우**, 기본 **60초당 60요청**(`max_requests=60, window_seconds=60`). 초과 → 429.

**[키를 뭘로 잡나]** = 누구를 "한 사용자"로 셀까. → IP 기준. 그런데:
```python
# X-Forwarded-For의 맨 왼쪽 = 클라가 조작 가능(spoofable) → 무시
# 우리 프록시가 찍은 오른쪽에서 trusted_proxy_count번째 hop만 신뢰
# 유효한 IP가 아니면 버킷 안 만듦(가짜 값으로 무제한 버킷 생성 차단)
```
**[왜]** 공격자가 `X-Forwarded-For`를 매번 바꿔 IP를 위조하면 속도 제한을 우회한다 → **신뢰할 수 있는(우리 프록시가 찍은) hop만** 키로 쓴다.

### ③ auth 주입 — `auth.py` `inject_principal`

**[함]** 세션 쿠키(`session_id`)를 **U3의 `session_manager.verify`로 검증** → `request.state.principal`에 심는다. 경로별로 다름:
- **public**(`/health`, `/auth/login`, `/auth/signup`, `/docs`…) → 검사 안 함, principal=None.
- **optional**(`/api/search`, `/auth/session`) → 쿠키 있으면 심고, 없어도 통과(차단 안 함).
- **나머지**(`/library/*` 등) → 쿠키 없거나 검증 실패 → **401**.
- **세션 저장소(Redis) 장애 → 401 fail-closed** (인증 안 된 채 통과시키지 않음, U3 정책과 일치).

> ★여기가 U2·U4가 읽던 `request.state.principal`을 **실제로 채우는 곳**이다. (U3에서 만든 세션을 U6 게이트웨이가 검증해 principal로 푼다 → U2/U4가 사용.)
> ⚠️ 단, 이 주입은 `session_manager`가 주입됐을 때만(= `REDIS_HOST` 설정 시). 미설정(로컬/테스트)이면 주입을 건너뛰고 U2는 dev 헤더 `X-User-Id`로 폴백.

### ⑥ 보안 헤더 — `security_headers.py`

모든 응답에 5개 부착: `Content-Security-Policy`(self만) · `Referrer-Policy: no-referrer` · `Strict-Transport-Security`(HSTS 1년) · `X-Content-Type-Options: nosniff` · `X-Frame-Options: SAMEORIGIN`. (클릭재킹·MIME스니핑·정보유출 방어.)

### ⑤⑦ 전역 fail-closed + 관측

미처리 예외 → 스택·내부 식별자 **없이** 일반화 500(`{message, requestId}`). 그리고 `finally`에서 **모든 요청(예외 포함)**에 대해 지연시간·처리량 메트릭을 1회 emit — 5xx 상태 태그에서 에러율을 파생(따로 안 셈 → 이중집계 방지).

---

## ⓑ-1 근거화 — `grounding.py` `GroundingEnforcementHook.enforce`

**(U2 ⑦에서 `gateway_seam`이 부른 바로 그것.)**

**[받음]** candidate(U2가 만든 후보 응답) + retrieved(검색된 실재 레코드들).
**[함]** 후보가 노출하는 식별자(`arxivId`/`paperId`/`arxivUrl`)가 **검색된 레코드 집합에 실재하는가?**

```python
retrieved_ids = 검색 레코드들의 식별자 집합 (정규화)
exposed       = 후보가 노출하는 참조들

retrieved_ids 비어있음 → verdict="abstain"  (검증할 근거 자체가 없음)
exposed 비어있음        → verdict="abstain"  (후보에 참조가 없음)
exposed 중 retrieved에 없는 게 있음 → verdict="block"  (날조)
전부 실재               → verdict="pass"
```

**[정규화]** `arxiv.org/abs/`·`arxiv:` 접두사 벗기고, 버전 `vN` 제거 → "URL이든 버전이든 같은 논문은 같게" 비교.

**[내보냄]** `GroundingDecision(verdict)`. U2는 이걸 받아 pass→결과, block/abstain→기권으로 매핑.

> **왜 U6가?** 검색(U2)과 "날조 검열"을 **권한 분리**. enforce는 **이 한 곳에서만** 호출(INV-1). 검열관을 단 하나로.

---

## ⓑ-2 비용 가드 — `cost_guard.py` `CostGuardCircuitBreaker`

**(U2 ②와 U7 cost gate가 `get_budget_state()`로 읽던 그것.)**

**[상태]** `cap_usd=1600`. 누적 지출 `spend_usd` 대비 비율(`ratio = spend/cap`)로 단계 결정:

| ratio | degrade_mode | circuit_state | tier |
|---|---|---|---|
| < 0.80 | NORMAL | CLOSED | normal |
| ≥ 0.80 | **RERANK_OFF** | HALF_OPEN | warning |
| ≥ 0.95 | **LEXICAL_ONLY** | HALF_OPEN | critical |
| ≥ 1.0 | LEXICAL_ONLY | **OPEN** | hard_cap |

**[함]**
- `record_spend(event)` — 지출 누적. **`event_id` 멱등** — 같은 사용 이벤트가 두 번 와도 중복 합산 안 함.
- `get_budget_state()` — 현재 degrade_mode + circuit_state 반환. **U2·U7은 이걸 읽기만** 한다.

**[연결]** U2 ②는 이 `degrade_mode`를 읽어 임베딩을 켤지(NORMAL/RERANK_OFF) 끌지(LEXICAL_ONLY) 정했고, U7은 normal이 아니면 LLM 지출 전에 `CostDegradedDTO`로 끊었다.

> **왜 비율로 단계적?** 한 번에 끊지 않고 0.80→리랭킹끄기, 0.95→어휘검색만, 1.0→완전차단 으로 **점진적으로 죈다**. 비싼 기능부터 순서대로 내려놓아 서비스를 최대한 살린다.

---

## ⓑ-3 운영 워커 + 인시던트 탐지 — `worker.py` + `detectors.py`

**[받음]** 텔레메트리 이벤트(시스템이 뱉는 운영 신호, SQS 등).
**[함]** `run_polling_loop`: 소스에서 최대 10개씩 받아(`max_messages=10`) → `suite.evaluate`로 인시던트 후보 판정 → 후보 있으면 `publisher.publish_candidate` → **발행 성공해야 ack**.
```python
candidate = suite.evaluate(event)
if candidate is None:
    source.ack(event)             # 인시던트 아님 → 처리완료 ack
elif publisher.publish_candidate(candidate):
    source.ack(event)             # 발행 성공 → ack
# else: 발행 실패 → ack 안 함 → 소스가 재배달 (조용한 유실 없음, at-least-once)
```

**[탐지기 3종]** (`detectors.py`):
- **CostExplosionDetector** — 비용 폭발. 단일 이벤트 $50↑, 하드캡 초과, rate-limit 급증(100↑) → CRITICAL/WARNING.
- **HallucinationDetector** — 환각. 근거화 `block`→CRITICAL, `abstain`→WARNING. (ⓑ-1 근거화 결과가 인시던트로 연결.)
- **PartialResultDetector** — 부분 실패 은폐. `status=success`인데 실제론 결과 0건/저하/검색실패인 경우 탐지("성공이라 보고했지만 실은 실패").

**[내보냄]** `IncidentCandidate` → 발행 → 대시보드/경보.

> **왜 발행 성공해야 ack?** 인시던트를 발행도 못 했는데 ack하면 **조용히 사라진다**. 미ack로 두면 소스가 다시 보낸다(at-least-once).

---

## 한 장 요약

```
ⓐ 요청 엣지 게이트웨이 (동기, 모든 요청을 감쌈)
  U5/BFF → ① request_id → ② rate-limit(60/60s, 위조불가 키, 초과 429)
         → ③ auth 주입(쿠키→U3 verify→principal, Redis장애=401)
         → ④ 도메인(U2/U3/U4/U7) → ⑤ 예외=일반화500 → ⑥ 보안헤더+ID → ⑦ 메트릭

ⓑ 단일 권위 (다른 유닛은 호출/조회만)
  grounding.enforce(candidate, retrieved) → pass/block/abstain   ← U2 ⑦
  cost_guard.get_budget_state() → degrade_mode + circuit         ← U2 ②·U7
     cap $1600 · 0.80 RERANK_OFF · 0.95 LEXICAL_ONLY · 1.0 OPEN
  worker: 텔레메트리 → detectors(비용/환각/부분실패) → 발행성공시 ack(at-least-once)
```

**전체 그림 완성**: U2 ⑦이 부른 enforce = ⓑ-1, U2 ②·U7이 읽은 비용 = ⓑ-2, U2/U4가 읽은 principal = ⓐ-③이 채움. **U6는 모든 유닛이 기대던 공통 바닥**이다.
```
