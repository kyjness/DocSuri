# QA — Full user-story verification pass

**Date:** 2026-07-10
**Scope:** All 70 user stories in `aidlc-docs/inception/user-stories/stories.md`
(epics 0–11: US-H1, D1–7, A1–7, L1–3, I1–3, R1–5, S1–6, CG1–6, P1–7, NV1–9, EV1–9, AG1–7).
**Method:** three evidence layers —
(1) **automated gates**: all 7 CI jobs replicated locally on `develop` (d7fce61d + a cosmetic
working-tree diff adding OpenAPI `tags=` to discovery/summarization routers);
(2) **story→evidence mapping**: per-epic sweep of implementation + test files against each
acceptance criterion;
(3) **live production smoke**: read-only probes against https://docsuri.org (no accounts
created, no LLM spend, no writes).

---

## Verdict

**Ship-shape overall — no NOT-IMPL stories, all 7 CI gates green, prod healthy — but two
live P1 findings and a cluster of "implemented-yet-untested" acceptance criteria.**

| Verdict | Count | Stories |
|---|---|---|
| PASS-tested (impl + criteria-level tests) | 45 | D1/D2/D5/D6/D7, A5, L1–3, I1/I3, R1/R2/R5, S1–S5, CG1/CG2/CG4/CG5, P2/P3/P6, NV1–4/NV6–9, EV1/EV4–8, AG2–5/AG7 |
| IMPL-partial-tests (impl complete, some criteria untested) | 22 | H1, D3, D4, A1–4, A6, A7, I2, R3, S6, CG3, P1, P4, P7, NV5, EV2, EV3, EV9, AG1, AG6 |
| PARTIAL-impl (acceptance criteria partly unbuilt) | 2 | **R4** (dashboard omits watermark/DLQ backlog), **CG6** (log-only telemetry, no QT-6 property test) |
| DEFERRED (intentional, confirmed) | 1 | **P5** (backend plumbed, zero consumers — matches team decision) |
| NOT-IMPL | 0 | — |

---

## 1 · Automated gates (CI parity, local)

All 7 lanes green on the QA'd tree.

| Lane | Result |
|---|---|
| shared (SSOT drift + ruff + pytest) | ✅ drift clean ("ok: _generated/ matches the schemas"), ~74 tests pass |
| ingestion (U1) | ✅ ~350 pass, 1 skip |
| ops (U6) | ✅ ~53 pass |
| discovery (U2, `--extra api`) | ✅ pass |
| backend app-shell | ✅ pass (mount assertions incl.) |
| root-suites (accounts U3 + library U4) | ✅ 169 pass |
| frontend (tsc + type-drift + lint + vitest + `next build`) | ✅ 274/274 tests in 46 files, build clean |

Caveat: the local `gen:types` run printed `fetch failed` yet exited 0 with no diff — the
local drift check was likely vacuous (generator needs network). CI runs it for real; not a
release blocker, but don't trust a *local* green on that one step.

## 2 · Live production smoke (docsuri.org, read-only)

| Check | Story | Result |
|---|---|---|
| `GET /` · `/search` · `/agent` · `/mypage` · `/paper/{id}`×4 | US-D4, AG1, SSR-500 watch | ✅ all 200, paper page 0.08–0.32s (known intermittent SSR 500 did not reproduce) |
| `GET /bff/readyz` | US-R5, silent-mount watch | ✅ `ready`, **11/11 modules mounted, 0 skipped, 0 blocking** |
| Anonymous `POST /bff/api/search` | US-H1/D2 | ✅ works — anonymous search is a documented product feature (`_AUTH_OPTIONAL_PREFIXES`); real arXiv records with `sourceName`/`sourceUrl` (D4/D5 fields present) |
| Search validation: empty · >500 chars | US-D1 | ✅ 422 both (FE additionally validates client-side before sending) |
| Auth gates unauthenticated: papers meta, summarize, glossary, novelty jobs, library, history | SEC-8 | ✅ all 401 |
| Wrong-credential login | US-A7 regression | ✅ 401 + clean non-technical body `{"message":"authentication required"}` (the June 422 incident stays fixed) |
| **Cold-query search latency** | US-H1 (<3s P50), NFR-P1 | ⚠️ **FINDING 1** below |
| **Out-of-corpus abstain** | US-D6 | ⚠️ **FINDING 2** below |

## 3 · P1 findings (live behavior)

### F1 — Novel-query search takes 3–10s; first attempt frequently 504s
Five data points, two distinct queries:

| Attempt | transformer query | kimchi query |
|---|---|---|
| 1 (cold) | **504 @ 10.4s** | **504 @ 10.1s** |
| 2 | 200 @ 9.6s | 200 @ 3.1s |
| 3 (cached) | 200 @ 0.5s | — |

Every *never-seen* query risks blowing the BFF's ~10s ceiling and surfacing the
"일시적인 오류" page — on the **hero first-search moment**, whose acceptance is **<3s P50**.
The graceful error page itself is correct US-D7 behavior; the latency is the defect.
Warm/cached path (0.5s) is fine. Suspects: embedding call cold path + k-NN cold segments
(echoes the 2026-07-01 503 incident class). Recommend: measure the embed-vs-knn split in
CloudWatch, then either budget the cold path (pre-warm, tighter embed timeout + lexical
fallback) or raise the BFF timeout above worst-case cold p99.
Related test gap: **no latency assertion exists anywhere in the repo** (the <3s SLA is
comment-only), so this can't regress-fail.

### F2 — US-D6 abstain state appears unreachable for out-of-domain queries
`"best kimchi fermentation recipe for home cooking"` → 200 with tangentially-related
(real, non-fabricated) ML papers at `relevance: 1`, not "관련 논문 없음". k-NN always
returns nearest neighbors, and no relevance floor gates the no-match state, so the
abstain criterion ("코퍼스에 관련 논문 없음 → 명확히 표시") is effectively dead code for
most out-of-corpus queries. No fabrication occurred (QT-1 core holds). Recommend: a
documented score threshold for the empty-page state, plus a QT-2 eval case for it.
(Also: `relevance: 1` on every top card suggests display normalization worth a look.)

## 4 · P2 findings (test/criteria gaps on shipped behavior)

1. **QT-2 relevance quality harness does not exist** (US-D3: "Recall@10 ≥ 0.7" — no golden
   set, no recall runner). Ranking is verified structurally only; a semantic-quality
   regression ships undetected. Highest-value single test to add.
2. **US-P4 transparency AC unmet in FE while boost is LIVE in prod**: no
   "내 관심 주제 반영" indicator and no in-results off-switch (`SearchScreen.tsx` has
   neither; kill-switch only in settings). Personalized reordering is currently silent.
3. **US-CG6 / QT-6**: citation-graph telemetry is one `emit_log` line — no metrics, no
   dashboard/alarm wiring, and **no QT-6 property test** ("날조 인용 0건·그래프 불변식
   위반 0건" is asserted nowhere).
4. **US-R4 dashboard omits two AC'd panels**: per-source watermark lag and DLQ backlog
   depth (ingestion emits the raw signals; nothing consumes them). Incident→alert routing
   inside the ops module is an injected publisher; the infra-level CloudWatch/SNS path
   (ops hardening, 2026-06-18) covers alarms, but the two panels are genuinely missing.
5. **US-S6 threshold recalibration still pending in substance**: the QT-1 fidelity harness
   now exists (`eval/grounding_eval.py` + seed corpus — story's "부재" is resolved), but
   `_NUMERIC_MISMATCH_THRESHOLD` remains the pre-Phase-3 `0.5` estimate on synthetic data,
   with a known false-pass probe case at 0.5.
6. **Accounts controller layer has zero endpoint-level tests** (all service-level): cookie
   flags (secure/httpOnly/sameSite), 429-on-signup wiring, OIDC callback-failure recovery,
   and the 30-min reset-token *expiry* branch are implemented but unasserted.
   (Library, by contrast, tests over HTTP via TestClient — pattern to copy.)
7. **US-I1 raw-PDF nuance**: non-arXiv PDFs stay in-memory ✅, but `adapters/arxiv.py`
   persists raw arXiv PDF bytes via `RawContentStorePort.put_raw` (B3 re-parse cache).
   Strictly read, "원시 PDF는 저장하지 않는다" is contradicted for arXiv OA content, and no
   negative test guards the gated path. Needs story-owner sign-off or an AC amendment.
8. **NFR-P6 / EV2 streaming**: evidence turns are sync/async jobs, not token-streamed;
   first-token SLA has no timing test (novelty SSE, by contrast, is real and tested).

## 5 · P3 notes (lower risk)

- FE error boundaries (`app/error.tsx`, `global-error.tsx`) have no direct render test.
- US-D4 responsive criteria (no h-scroll @360–430px, desktop phone-mockup centering) untested.
- US-CG3 duplicate/cycle collapse (`alreadyShown`) implemented, untested; `seen` resets per
  response so cross-expand dedup is client-trusting.
- US-P1 store-failure fail-open path (AC3) has no fault-injection test.
- `LibraryItemMeta` is hand-mirrored in `citation_graph/controller.py` (drift risk vs U4).
- Email rate-limiter fails open on Redis outage (documented; gateway per-IP is the backstop).
- Playwright e2e (`hero.spec.ts`, `agent-chat.spec.ts`) exists but isn't in CI and the
  WebKit binary is missing locally — the only true end-to-end flows are effectively unrun.

## 6 · Documented deviations needing story-owner sign-off

| Story | Deviation | Where documented |
|---|---|---|
| US-A2 | No account lockout — deliberate (targeted-DoS avoidance); delay + CAPTCHA instead, codified by `test_no_account_lockout_after_many_failures` | BR-A4 |
| US-A6 | Audit "log" is structured `logger.info`, not a durable audit store | SEC-14 "인프라 이월" note |
| US-P5 | Fully deferred; backend defaults endpoint has zero consumers | team decision (U9) |
| US-I1 | arXiv raw-PDF B3 cache vs strict AC reading (above, P2 #7) | code comment |

## 7 · Recommended next actions (ranked)

1. **F1 cold-search latency** — instrument embed/knn split; fix or re-budget. Add the
   repo's first latency test while there.
2. **QT-2 recall harness** (P2 #1) — small golden set + Recall@10 runner; also covers F2's
   threshold work.
3. **US-P4 FE indicator + off-entry** — small FE change, closes a live transparency AC.
4. **Accounts endpoint-level tests** (P2 #6) — copy the library TestClient pattern; assert
   cookie flags, 429, OIDC failure path, expired reset token.
5. **QT-6 property test + citation metrics** (P2 #3).
6. Story-owner sign-offs for §6 and an AC decision on the arXiv raw-PDF cache.

---

*Working-tree note: QA ran with the uncommitted cosmetic router `tags=` diff present; it
touches OpenAPI grouping only. Full per-story evidence (file paths + test names per
acceptance criterion) was gathered per-epic; this report keeps the roll-up — ask if you
want the raw per-criterion tables appended.*
