# U5 Frontend — 파이프라인 상세 (검색 화면 → U2까지)

> 학습용 메모. **커밋하지 않는다.** 근거: `frontend/` 실제 코드.
> 형식: **[받음] → [함] → [내보냄]**. 먼저 `00-project-overview.md`·`u2`·`u3`·`u6` 가정.
> ★유일하게 TypeScript/React/Next.js. 사용자가 **실제로 보는 층**이자, 지금까지 배운 U6→U2의 **입구**.

---

## 0. 이 유닛이 하는 일 / 코드 구성

검색 화면·라이브러리/이력·**폰 목업 UI**. (※ "React Native"가 아니라 **웹앱을 폰 모양 틀로 렌더**.) 두 가지가 핵심 주제:
1. **토큰을 브라우저 JS에 절대 노출하지 않는다** (BFF가 방화벽).
2. **mock ↔ real 교체가 컴포넌트를 안 건드린다** (transport만 바꿈).

```
frontend/
├── components/SearchScreen.tsx     ← 검색 화면 (클라 상태기계 + in-flight 락)
├── lib/api/
│   ├── validate.ts                 ← 클라 입력검증 (UX 보조)
│   ├── apiClient.ts                ← ★백엔드 단일 진입점 (timeout·재시도·dedup)
│   ├── transport.ts                ← Transport 인터페이스(seam)
│   ├── index.ts                    ← ★transport 팩토리 (mock vs real 선택)
│   ├── mockTransport.ts            ← 인-브라우저 픽스처
│   ├── routeHandlerTransport.ts    ← 클라 → /bff/* (동일 출처)
│   ├── httpTransport.ts            ← ★server-only, BFF → U6 게이트웨이
│   ├── classify.ts                 ← 응답 union을 구조로 판별
│   └── errors.ts                   ← UserFacingError (fail-closed)
└── app/bff/[...path]/route.ts      ← ★BFF (서버 전용 seam)
```

---

## 데이터가 흐르는 큰 길 (검색 1회)

```
SearchScreen (브라우저)
   → getApiClient().search(query)           lib/api/index.ts 팩토리
   → ApiClient.search()                     timeout·재시도·dedup 정책
   → Transport.send()                       ┌ mock: MockTransport (브라우저 안 픽스처)
                                            └ real: RouteHandlerTransport → /bff/*
   → BFF route.ts (Next 서버)               ★토큰·게이트웨이URL은 여기서만 보임
   → HttpTransport (server-only) → U6 게이트웨이 → U2 (앞서 배운 그 파이프라인)
   ← SearchResponse (4종단)
   → classifySearchResponse()               구조로 판별 → SearchOutcome
   → SearchScreen 렌더 분기
```

---

## ① SearchScreen — 클라이언트 상태기계 (`SearchScreen.tsx`)

**[받음]** 사용자 입력(검색어 + 제출).
**[함]**
- **상태기계**: `idle → loading → outcome | error`.
- **in-flight 락**(`useRef`): 이미 요청 중이면 중복 제출 무시(`if (inFlight.current) return`).
- 제출 시 `validateQuery`(클라 검증) → 통과하면 `getApiClient().search()`.
- 에러가 `UserFacingError`이고 `isAuth`(401)면 → `/login?redirect=/search`로 라우팅.

**[내보냄]** `SearchOutcome`에 따라 렌더 분기:

| outcome.kind | 화면 |
|---|---|
| `page` | ResultList(결과 카드) |
| `degraded` | ResultList + 저하 배너 |
| `empty` | "결과 없음" |
| `abstain` | "기권" |
| `invalid` | 입력 오류 |

> *상태기계(state machine)* = 화면이 가질 수 있는 상태를 **정해진 몇 개로 한정**하고 그 사이만 전이. "로딩 중인데 또 결과가 뜨는" 같은 모순 상태를 코드 구조로 차단.

### 클라 검증 — `validate.ts`

```typescript
const value = raw.normalize('NFC').trim();   // U2 ①과 같은 NFC·trim
if (value.length === 0) return { ok: false, ... };
if (value.length > 500) return { ok: false, ... };
```
**[핵심]** 클라 검증은 **UX 보조일 뿐, 권위는 백엔드**(U2/U6). 빠른 피드백용이고, 진짜 검증은 서버가 또 한다(우회 가능하니까).

---

## ② ApiClient — 백엔드 단일 진입점 (`apiClient.ts`)

**모든 백엔드 호출이 여기 한 곳**을 거친다(직접 모듈 호출 금지). 정책 3종:

- **timeout 8000ms** — 무한 로딩 방지(`withTimeout`).
- **재시도**: **멱등(idempotent) 요청만 2회**, 5xx일 때만, backoff `200ms × (i+1)`. (GET·search 같은 안전한 것만; POST 가입 등은 1회.)
- **in-flight dedup**: 같은 요청(method+path+body 키)이 이미 진행 중이면 **그 Promise를 재사용**(중복 호출 차단).

```typescript
async search(query): Promise<SearchOutcome> {
  const res = await this.request({ method:'POST', path:'/api/search', body:{query}, idempotent:true });
  if (res.status === 200 || res.status === 400) return classifySearchResponse(res.body);
  throw normalizeHttpError(res.status, ...);   // 그 외 → UserFacingError
}
```

> **이중 안전장치**: SearchScreen의 `useRef` 락(화면 레벨) + ApiClient의 dedup(요청 레벨). 사용자 대면이라 "한 번에 한 요청"을 두 겹으로 보장.

---

## ③ Transport seam + 팩토리 — mock↔real 교체 (`transport.ts`, `index.ts`)

`ApiClient`는 `Transport` **인터페이스에만** 의존(`send(req) → res`). 실제 구현은 팩토리가 빌드 플래그로 선택:

```typescript
const REAL_API = Boolean(process.env.NEXT_PUBLIC_DOCSURI_REAL_API);
export function getApiClient() {
  if (!REAL_API) return new ApiClient(new MockTransport());        // 기본 = mock
  return new ApiClient(new RouteHandlerTransport());               // real = BFF 경유
}
```

**[교체 두 단계]**
1. **클라 레벨**: `NEXT_PUBLIC_DOCSURI_REAL_API` → mock(브라우저 픽스처) vs real(BFF 경유).
2. **BFF 안**: `DOCSURI_GATEWAY_URL` 유무 → 실 게이트웨이 vs mock.

**[핵심]** 화면·`ApiClient`는 **한 글자도 안 바뀐다.** transport만 갈아끼움 → 인프라 없이도 프리뷰가 돈다. (U2의 포트/어댑터와 같은 발상, 프론트 버전.)

---

## ④ BFF — 토큰 방화벽 (`app/bff/[...path]/route.ts`) ★U5의 핵심

**BFF(Backend-for-Frontend)** = 브라우저와 U6 게이트웨이 **사이의 서버 전용 중계층**(Next 서버에서 실행).

**[받음]** 클라가 보낸 동일 출처 `/bff/...` 요청.
**[함]**
```typescript
const baseUrl = process.env.DOCSURI_GATEWAY_URL;
if (baseUrl) return new HttpTransport({ baseUrl, cookieHeader: req.headers.get('cookie') });
return new MockTransport();
// ... 업스트림 응답의 Set-Cookie를 브라우저로 릴레이
```
- **게이트웨이 URL과 세션 쿠키는 여기(서버)서만** 보인다.
- 클라(`RouteHandlerTransport`)는 항상 **동일 출처 `/bff/*`로만** 보냄 → 브라우저가 httpOnly 쿠키를 자동 첨부 → BFF가 서버↔게이트웨이 구간에서만 그 쿠키를 전달.
- 로그인 응답의 `Set-Cookie`(세션 쿠키)를 브라우저로 **릴레이**.

**[왜 이게 방화벽?]** `httpTransport.ts` 맨 위 `import 'server-only'` — 이 파일을 **클라이언트 코드가 import하면 빌드 에러**. 즉 게이트웨이 URL·세션 쿠키가 **브라우저 번들에 새어들 수 없게 컴파일러가 강제**(SEC-3/12). 토큰은 절대 클라 JS에 안 들어온다. (U3에서 본 httpOnly 쿠키 + SEC-12의 프론트 쪽 짝.)

---

## ⑤ 응답 분류 — 구조로 판별 (`classify.ts`)

**[받음]** 백엔드 `SearchResponse`(4종단). **판별 필드(discriminant)가 없음.**
**[함]** 그래서 **키 모양(구조)으로** 판별:

```
{ reason }              → abstain
{ cards, meta, mode }   → degraded
{ cards, meta }         → page  (meta.resultCount===0 이면 empty)
{ message }             → invalid
```

**[왜 되나]** DTO가 `additionalProperties:false`(정의된 키 외엔 못 붙임)라 **모양이 안 겹친다** → 구조만으로 명확히 구분 가능.

---

## ⑥ 에러 — fail-closed 일반화 (`errors.ts`)

**[함]** HTTP 상태 → `UserFacingError`로 정규화, **비기술 메시지만** 노출(스택·내부 식별자 없음, SEC-15):

| status | kind | 처리 |
|---|---|---|
| 401 | auth | **재로그인 라우팅**(isAuth) |
| 403 | forbidden | "권한 없음" |
| 429 | rateLimited | "잠시 후 다시" |
| 5xx | server | "일시 오류" |
| 네트워크/timeout | network | "연결 확인" |

401만 특별 취급(재로그인), 나머지는 사용자 친화 메시지 + 재시도 경로.

---

## 한 장 요약

```
SearchScreen (클라 상태기계 idle→loading→outcome|error, in-flight 락 useRef)
   ① validateQuery (NFC·trim·≤500, UX 보조 — 권위는 백엔드)
   → ApiClient.search (timeout 8s · 5xx 2회 재시도(멱등만) · in-flight dedup)
   → Transport (팩토리: NEXT_PUBLIC_DOCSURI_REAL_API)
        mock → MockTransport (브라우저 픽스처)
        real → RouteHandlerTransport → /bff/* (동일 출처, httpOnly 쿠키 자동첨부)
   → BFF route.ts (서버 전용; 게이트웨이URL·쿠키 여기서만)
        DOCSURI_GATEWAY_URL 있음 → HttpTransport(server-only) → U6 게이트웨이 → U2
        없음 → MockTransport
        ← 업스트림 Set-Cookie를 브라우저로 릴레이
   → classifySearchResponse (구조로 판별: reason/cards+mode/cards/message)
   → 렌더 분기 (page·degraded·empty·abstain·invalid)
   에러: UserFacingError fail-closed (401→재로그인, 그 외 비기술 메시지)
```

**전체 그림**: U5가 BFF로 토큰을 가두고 → U6 게이트웨이(인증·rate-limit) → U2 검색 → U1이 채운 코퍼스. **7개 유닛 한 바퀴 완주.**
```
