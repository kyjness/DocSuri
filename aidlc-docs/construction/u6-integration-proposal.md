# U6 통합 라스트마일 제안 (Integration Last-Mile Proposal)

**작성일**: 2026-06-17 · **상태**: 제안(미적용) · **맥락**: `feature/track6` 딥리뷰 후속
**참조**: `aidlc-state.md` §검증 재기준선 · 크리티컬 패스 ④(U6 통합)

> 본 문서는 **정밀 diff 제안**이다. 코드를 적용하지 않았다. 세 개 레인(app-shell·discovery·U6)을
> 교차하므로 각 diff에 소유자를 표기했다. **전제: `feature/track6`이 `develop`에 머지되어
> `backend/middleware/`·`ops/` 트리가 존재해야 한다.**

---

## 1. 배경 (왜 필요한가)

`feature/track6`은 U6 컴포넌트(게이트웨이 미들웨어 + `ops/` 검출 파이프라인 + 실 grounding hook)를
**빌드 완료**했고 전 스위트 green이다. 그러나 **라이브 경로에 미연결**이라, 단순 머지만으로는:

- `create_app`이 게이트웨이를 설치하지 않는다(테스트만 `configure_u6_middleware` 호출).
- discovery 프로덕션 와이어링이 여전히 `StubGroundingHook`(항상 `pass`)을 주입한다 →
  **환각/날조 방지(INV-1·US-D5/US-R1)가 실 경로에서 작동하는 곳이 전무**(Blocker).
- `backend/pyproject.toml`이 `docsuri-discovery`를 미선언 → app-shell 부팅 시 discovery가
  매번 graceful-skip → 통합 앱에 `/api/search` 자체가 없음.

## 2. 핵심 통찰 — 통합은 **독립적인 두 스레드**다

근거화 enforcement 지점은 **discovery 게이트웨이 시임**(`build_router` → `run_search` →
`grounding_hook.enforce`)이지 `backend/middleware/` 게이트웨이가 **아니다**. 따라서:

- **스레드 A — 근거화 Blocker 해소**: 패키지 설치 + 주입 시임 추가 + 실 hook 전달.
  HTTP 미들웨어 게이트웨이가 **필요 없다**. 제품의 신뢰 보증을 복원하는 **우선 작업**이며 규모가 작다.
- **스레드 B — HTTP 게이트웨이 설치/하드닝**: 보안 헤더·레이트리밋·요청ID 중앙화. 근거화와 독립.

두 스레드를 혼동한 것이 키스톤을 XL로 보이게 했다. 실제로 Blocker를 닫는 스레드 A는 작다.

---

## 3. 스레드 A — 근거화 복원 (Blocker + U2 미마운트 동시 해소)

### A1 · `backend/pyproject.toml` — discovery·ops를 app-shell venv에 설치 · _소유: app-shell (@revenantonthemission)_

```diff
 dependencies = [
     # Shared contracts (DTOs/events/vector-spec/ports) — single source of truth, never forked.
     "docsuri-shared",
+    # U2 search domain (mounted by _mount_discovery) + U6 reliability/grounding (real hook).
+    "docsuri-discovery",
+    "docsuri-ops",
     # CG-1: backend web framework = FastAPI (app-shell decision, owner @revenantonthemission).
     "fastapi>=0.110",
@@
-# docsuri-shared comes from the in-repo path (shared/ is on develop). docsuri-discovery is
-# NOT declared here: discovery isn't on develop yet, and a path source to a missing dir would
-# break `uv sync`. The assembled backend installs docsuri-discovery; until then the app-shell
-# imports `discovery` optionally at runtime (graceful skip). See backend/README.md §Assembly.
+# In-repo path sources. discovery + ops are on develop (track6 merged), so the app-shell
+# installs them directly and `_mount_discovery` resolves instead of graceful-skipping.
 [tool.uv.sources]
 docsuri-shared = { path = "../shared/python", editable = true }
+docsuri-discovery = { path = "modules/discovery", editable = true }
+docsuri-ops = { path = "../ops", editable = true }
```

> ⚠️ **최고 위험 단계.** `discovery`·`ops` 각각이 자체 `[tool.uv.sources] docsuri-shared`를 가진다.
> editable path dep + transitive path source는 대개 해소되지만, `uv sync`가 소스 충돌을 일으키면
> **uv workspace**로 승격한다(루트 `pyproject`에
> `[tool.uv.workspace] members=["backend","backend/modules/discovery","ops","shared/python"]`).
> "그냥 되겠지" 가정 금지 — 반드시 검증.

### A2 · `discovery/testing/wiring.py` — `grounding_hook` 주입 시임 추가 · _소유: discovery / Track 3 (@kyjness)_

블로커 트랩: 현재 팩토리가 stub을 하드코딩하고 실 hook을 받을 인자가 없다.

```diff
 from dataclasses import dataclass
 
+from docsuri_shared.ports import GroundingEnforcementHook
+
 from ..cache.embedding_cache import EmbeddingCache
@@ class MockBundle:
     orchestrator: SearchOrchestrationService
-    grounding_hook: StubGroundingHook
+    # Typed against the shared Protocol so the real docsuri_ops hook can be injected in
+    # production without changing the call site (INV-1 single authority).
+    grounding_hook: GroundingEnforcementHook
     event_publisher: InMemoryEventPublisher
@@ def build_mock_orchestrator(
     lexical_index=None,
     ttl_seconds: float = 300.0,
+    grounding_hook: GroundingEnforcementHook | None = None,
 ) -> MockBundle:
-    """Wire the U2 pipeline with mocks. Override any adapter (e.g. a Failing* one) for tests."""
+    """Wire the U2 pipeline with mocks. Override any adapter (e.g. a Failing* one) for tests.
+
+    Pass ``grounding_hook`` to inject the real U6 enforcement hook in production; when None,
+    StubGroundingHook(verdict=grounding_verdict) is used (mock-first)."""
@@ return MockBundle(
         orchestrator=orchestrator,
-        grounding_hook=StubGroundingHook(verdict=grounding_verdict),
+        grounding_hook=grounding_hook or StubGroundingHook(verdict=grounding_verdict),
         event_publisher=publisher,
     )
```

### A3 · `backend/wiring.py` — 실 ops hook을 라이브 경로에 주입 · _소유: app-shell (@revenantonthemission)_

```diff
     from discovery.api.router import build_router
     from discovery.testing.wiring import build_mock_orchestrator
+    from docsuri_ops.grounding import GroundingEnforcementHook as OpsGroundingHook
 
-    # Mock-first (MR-1/4): real OpenSearch/Bedrock adapters and the U6 grounding hook swap in
-    # later via the same constructor args without touching the contract.
-    bundle = build_mock_orchestrator()
+    # Real U6 grounding hook (INV-1 single authority) injected via the factory seam (A2);
+    # OpenSearch/Bedrock retrieval adapters still swap in later via the same constructor args.
+    bundle = build_mock_orchestrator(grounding_hook=OpsGroundingHook())
     app.state.discovery_bundle = bundle
     app.include_router(build_router(bundle.orchestrator, bundle.grounding_hook))
     result.mounted.append("discovery")
```

> **계약 정합 검증 완료**: `run_search`가 `grounding_hook.enforce(...)` 호출 →
> `map_decision`은 `.verdict`만 읽음(`"pass"`→grounded·`"block"`/`"abstain"`→abstain) →
> `IndexRecord`의 camelCase `arxivId/paperId/arxivUrl`가 ops hook이 읽는 키와 일치. **어댑터 불필요.**
> ops `GroundingDecision`은 `docsuri_ops` 병렬 타입이나 `.verdict`만 소비되어 duck-type 안전.

---

## 4. 스레드 B — HTTP 게이트웨이 설치·하드닝 (보안헤더·레이트리밋)

### B1 · `backend/app.py` — 게이트웨이 설치, 요청ID 소유권 이전 · _소유: app-shell (@revenantonthemission)_

```diff
-import logging
-from contextlib import asynccontextmanager
-from uuid import uuid4
-
-from fastapi import FastAPI, Request
+import logging
+from contextlib import asynccontextmanager
+
+from fastapi import FastAPI
 from fastapi.middleware.cors import CORSMiddleware
@@
 from .health import router as health_router
+from .middleware import configure_u6_middleware
 from .wiring import mount_modules
@@ def create_app
-    _add_middleware(app, settings)
+    # U6 gateway: security headers + fail-closed envelope + request-id (rate-limit opt-in).
+    # Installed before CORS so CORS stays outermost — its headers apply to gateway 429/500 too.
+    configure_u6_middleware(app, production=True)  # TODO: production/rate_limiter from settings
+    _add_middleware(app, settings)
@@ def _add_middleware
-    # Explicit origin allow-list + credentials (cookie sessions). U6's authn/authz/rate-limit
-    # and the grounding post-handler are layered in later via backend/middleware/ (Track 1).
+    # Explicit origin allow-list + credentials. Request-id + X-Request-ID are now owned by the
+    # U6 gateway (configure_u6_middleware); this adds only CORS.
     app.add_middleware(
         CORSMiddleware,
         allow_origins=list(settings.cors_origins),
         allow_credentials=True,
         allow_methods=["*"],
         allow_headers=["*"],
     )
-
-    @app.middleware("http")
-    async def _request_id(request: Request, call_next):
-        request_id = request.headers.get("X-Request-ID") or uuid4().hex
-        request.state.request_id = request_id
-        response = await call_next(request)
-        response.headers["X-Request-ID"] = request_id
-        return response
```

> **기존 테스트 보존**: 게이트웨이도 `request.state.request_id`를 설정(`errors.py`가 읽음)하고
> `X-Request-ID`를 echo하므로 `test_request_id_is_echoed`·`test_unhandled_error_is_generic_and_leak_free`
> 가 그대로 통과. 레이트리밋은 `rate_limiter=None`으로 보류 — 켜려면 **B2** 선행.

### B2 · `backend/middleware/gateway.py` (+ `wiring.py`) — 스푸핑 가능한 레이트리밋 키 수정 · _소유: U6 / Track 1 (@ELSAPHABA)_

```diff
 def install_gateway_middleware(
     app: FastAPI, *, observability=None, rate_limiter=None,
+    trust_proxy: bool = False,
     production: bool = True,
 ) -> None:
@@
         if rate_limiter is not None:
-            key = request.headers.get("X-Forwarded-For") or request.client.host
-            if not rate_limiter.allow(str(key)):
+            if not rate_limiter.allow(_client_key(request, trust_proxy)):
                 response = JSONResponse(status_code=429, ...)
@@ (new module-level helper)
+def _client_key(request: Request, trust_proxy: bool) -> str:
+    """Rate-limit identity. X-Forwarded-For is client-spoofable, so honour it only behind a
+    trusted proxy and then only its first hop; otherwise fall back to the socket peer (which
+    may be None for some transports → 'unknown' instead of AttributeError→500)."""
+    if trust_proxy:
+        forwarded = request.headers.get("X-Forwarded-For")
+        if forwarded:
+            return forwarded.split(",")[0].strip()
+    client = request.client
+    return client.host if client is not None else "unknown"
```

```diff
 # backend/middleware/wiring.py — trust_proxy 전달
 def configure_u6_middleware(
     app: FastAPI, *, observability=None, rate_limiter: InMemoryRateLimiter | None = None,
+    trust_proxy: bool = False,
     production: bool = True,
 ) -> None:
     install_gateway_middleware(
-        app, observability=observability, rate_limiter=rate_limiter, production=production,
+        app, observability=observability, rate_limiter=rate_limiter,
+        trust_proxy=trust_proxy, production=production,
     )
```

> 추가로 `InMemoryRateLimiter`는 프로세스 로컬(N 워커 → N배 한도)·무제한 증가. 단일 작업엔 무방하나
> 프로덕션 의존 전 **Redis 백엔드**로 교체. `ops/detectors.py`·`incidents.py`의 `_seen` 셋 누수는 별건.

---

## 5. 신규 테스트 · `backend/tests/test_discovery_grounding_integration.py` · _소유: app-shell_

```python
"""Integration: discovery (U2) actually mounts AND the real U6 grounding hook (docsuri_ops)
blocks fabricated references / abstains on no-evidence — the INV-1 guard StubGroundingHook
silently bypassed. Requires docsuri-discovery + docsuri-ops installed (A1)."""
from __future__ import annotations

import pytest

from backend.app import create_app
from backend.config import Settings

_TEST_SETTINGS = Settings(env="test", database_url="sqlite://")


def test_discovery_actually_mounts_not_skipped() -> None:
    result = create_app(_TEST_SETTINGS).state.mount_result
    assert "discovery" in result.mounted, f"discovery skipped: {result.skipped}"


def test_real_grounding_hook_blocks_fabrication_and_abstains() -> None:
    grounding = pytest.importorskip("docsuri_ops.grounding")
    hook = grounding.GroundingEnforcementHook()
    grounded = {"cards": [{"record": {"paperId": "2401.00001"}}]}
    assert hook.enforce(grounded, [{"paperId": "2401.00001"}]).verdict == "pass"
    assert hook.enforce(grounded, [{"paperId": "2401.99999"}]).verdict == "block"   # fabricated
    assert hook.enforce({"cards": []}, []).verdict == "abstain"                       # no evidence
```

> 리뷰가 지적한 갭(`test_app_shell`은 레지스트리 *집합*만 단언하고 실제 마운트는 미단언)을 닫고,
> 실 hook의 세 verdict를 증명한다.

---

## 6. 순서·소유권·검증

1. **스레드 A 우선**(A1 → A2 → A3) — 근거화를 복원하는 핵심. A2는 @kyjness 레인.
2. **스레드 B**(B1 → 레이트리밋 켜기 전 @ELSAPHABA의 B2) — 독립.
3. 변경별 검증: `cd backend && uv sync && uv run pytest -q && uv run ruff check .`
   (GHA CI 도입 후 리포 전역 실행).

## 7. 의도적 범위 외(후속)

- `block`/`abstain` → `AbstainResult` 손실 매핑 전에 `GroundingViolation` 상세를 로깅(관측성).
- `ops` 검출 파이프라인을 실 이벤트 소스에 연결(현재 CLI/로컬 전용 → US-R4 알림 미작동).
- Redis 백엔드 레이트리밋 · `worker.poll()` vs Protocol `receive()` 계약 불일치 수정.

## 8. 완료 정의(U6 live 선언 조건)

스레드 A 머지 + §5 통합 테스트 green + (스레드 B 보안헤더 적용 확인) 후에만 "U6 live" 선언.
그 전까지 `aidlc-state.md` §검증 재기준선의 "근거화 실효 없음(Blocker)"은 유효하다.
