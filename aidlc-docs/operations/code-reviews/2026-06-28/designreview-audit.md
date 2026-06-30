# AIDLC Design-Review Audit — 2026-06-28

Audit of an automated design review of `aidlc-docs/`, plus net-new findings the
tool missed. Produced by running the repo's own `tools/aidlc-designreview` over the
docs, then verifying **every** finding against the actual source documents and
hunting for issues outside the tool's output.

| Field | Value |
|-------|-------|
| Tool | `tools/aidlc-designreview` (strands-agents → Amazon Bedrock) |
| Model | `claude-sonnet-4-6` (critique / alternatives / gap) |
| Scope | 139 artifacts, 12 units, `aidlc-docs/` |
| Tool verdict | **Poor — 66/100 — Request Changes** (0 Critical / 6 High / 24 Medium) |
| Raw output | `tools/aidlc-designreview/review.{md,html}` |

## Headline

**The tool's "Poor / Request Changes" verdict is inflated.** Several High/Medium
findings are false positives caused by the tool ingesting *legacy* docs
(`inception/`, superseded by `construction/`) and **its own prior report** (under
`operations/code-reviews/`) as if authoritative. Of 6 HIGH findings: **1 bogus,
2 overstated, 3 real**. The tool also *under-detected* — it missed a genuine
contradiction between two FROZEN-adjacent contracts (N1 below).

---

## 1. Audit of the tool's HIGH findings

| # | Tool finding | Verdict | Evidence |
|---|--------------|---------|----------|
| H1 | `REDACTED_SECRET` placeholders = censored design | ❌ **FALSE POSITIVE** | Literal string exists **only** in the tool's own prior report `operations/code-reviews/2026-06-22/designreview-aidlc-docs.{md,html}`. Zero matches in any real design doc. Tool reviewed its own output. |
| H2 | U6 `ApiGatewayMiddleware` deep sync chain threatens NFR-P1 P50<3s; SPOF | 🟡 **OVERSTATED → MEDIUM** | Chain is sync, but `u2 nfr-requirements §1` already splits latency budgets (U2 stages vs U6 enforce, "종단 합이 NFR-P1 충족"); observability emit is sync-return then async event fan-out (`services.md`). Real residual: session verification has **no caching**. SPOF claim weak for a modular monolith. |
| H3 | Single-writer/**single-reader** corpus index = read outage on rebuild | ❌ **MOSTLY FALSE POSITIVE → LOW** | Reviewer conflated writer with reader. `shared/vector-spec.md §1` documents **lexical-only fallback**; `u1 business-rules BR-13` REBUILD_LOCK blocks **writes only**; `BR-C10` builds a new generation and keeps the old alias serving until smoke-tests pass. Reads stay up. |
| H4 | U4 `StubSearchGateway` stub-in-prod, no runtime guard | ✅ **CONFIRMED** | `u4 BLM:168` + `business-rules:82-83` give only an ENV doc-note + CI `ContractTestHarness`. No startup/runtime assertion. Real risk. |
| H5 | VectorSpec same-space not atomic at cutover; "no vector-spec.md exists" | 🟡 **REVIEWER WRONG — real bug is different (see N1)** | `shared/vector-spec.md` **exists** (gap claim false) and `§4` defines `assert_same_space()`; cutover **is** atomic (alias swap). The actual defect is the modelVer contradiction the tool missed (N1). |
| H6 | U3 GDPR cascade deletion has no enforced completion | ✅ **CONFIRMED (partial)** | Terminal `PURGED` + `CascadeOverdue` exist, but SLA is "예: 7일" (example), retry/DLQ is just "멱등·재시도·DLQ 보장" (no algorithm), and the undeployed-subscriber (U11 absent) case is unspecified. |

## 2. Audit of key MEDIUM findings

| Tool finding | Verdict | Note |
|--------------|---------|------|
| U9 boost bounds trusted, not clamped by U2 | ✅ **CONFIRMED** | `u2 BLM §3.5`: "U9가 강제하는 bounds를 **신뢰하여**". No server-side clamp. |
| Dual/triple grounding authority will drift | ❌ **FALSE POSITIVE** | `ports.md §2` documents the parallel design as **intentional**; "단일 권위=U6" is search-scoped; U7 is doc-fidelity (SOFT, different concern); U11 reuses U6's contract. |
| `SearchExecutedEvent.requestId` drift | 🟡 **REAL — see N2** | Not merely stale inception doc; the live U2 construction doc omits it too. |
| Email/Resend infra not specified | ❌ **ALREADY ADDRESSED** | `TD-U3-7` confirms `EMAIL_PROVIDER=resend`; `BR-A8` flow; soft-fallback pattern. Templates/bounce = deployment detail. |
| GROBID availability/fallback | ❌ **ALREADY ADDRESSED** | Sidecar container (`u1 infra §0.1`), fallback ladder `BR-30`, DLQ `BR-17`, threshold alert. |
| U8 citation provider/quota | 🟡 **PARTIAL** | Provider + timeout/retry config exist; **no link to U6 CostGuard (NFR-C1)** — that half is real. |
| U3 PENDING signup cleanup batch | ✅ **CONFIRMED** | `BR-A5` "배치 작업 **등**" — no scheduler/DLQ/infra. |
| U10 Mypage FD absent | ✅ **TRUE** | No `construction/u10*` dir (known/deliberate — reserved for another owner). |
| "no `shared/vector-spec.md`" | ❌ **FALSE** | The file exists. |

## 3. Meta-findings about the review tool

1. **No authoritative-vs-legacy filtering.** It feeds `inception/` (superseded) and
   `operations/` (its own past reports) into the same context → root cause of H1,
   the requestId confusion, and the "vector-spec.md missing" error.
2. **Ran blind on tech context.** No top-level `technical-environment.md`
   (per-unit `tech-stack-decisions.md` exist but aren't the file it looks for) →
   every infra finding is weaker than it could be.
3. **All 18 gap recommendations are blank** — tool defect; descriptions only.
4. **Under-detects.** It missed the N1 contract contradiction — exactly the kind of
   cross-contract inconsistency a design review should catch.

**Fix before any re-run:** exclude `aidlc-docs/operations/` and `aidlc-docs/inception/`
from the scan, and populate `technical-environment.md`.

---

## 4. Net-new findings (verified, not in the tool's report)

| # | Finding | Severity | Evidence |
|---|---------|----------|----------|
| **N1** | **`modelVer` contract contradiction** | **MED-HIGH → ✅ RESOLVED** | `shared/vector-spec.md` (per-record modelVer clause): per-record `modelVer` is **NOT** in the FROZEN IndexRecord contract — vs `u2-discovery/.../business-rules.md` §6: `HybridRetriever.retrieve()` **must validate `modelVer` per record at query time**. U2 relied on a field the contract excludes. **RESOLVED (2026-06-28, @kyjness — option b refined):** U2 §6 revised to a **one-time `specVersion` check at index-open** (manifest vs compiled reader spec); per-record `modelVer` dropped (redundant with the cutover `assert_same_space()` invariant — alias only swaps after a candidate index passes the full same-space gate — and `modelVer` alone is a partial guard missing dim/metric/normalize). `vector-spec.md §4` FROZEN unchanged; §6 lexical-fallback+alert safety net retained. |
| **N2** | **`requestId` omitted in the live U2 functional design** | **MED** | `u2-discovery/.../business-logic-model.md` L42 & L51 call `publishSearchExecuted(userId, query, timestamp, resultCount)` — no `requestId` — contradicting FROZEN `shared/events.md §2` `(userId, requestId, query, timestamp, resultCount)`. Dedup key `BR-L7 sha256(owner_id\|requestId\|query)` depends on it. **Fixed in this PR** (doc-to-SoT alignment). |
| **N3** | SocialIdentity `PENDING_CONFIRMATION` has no timeout/cleanup | LOW | `u3 BR-A9` says "미승격(만료) 연결은 폐기" but `domain-entities §4.2` defines no expiry field/duration/sweeper. |
| **N4** | Email-change duplicate check scope undefined | LOW | `u3 §7.2` / `domain-entities §4.3` reject if `newEmail` "기존 사용 중" but don't say whether *pending* `EmailChangeRequest`s count → two users can request the same new email. |
| **N5** | U11 `AgentCacheKey` attachment-hash undefined | LOW | `BR-RA-12` includes "첨부 해시" in the cache key but never defines content-vs-filename hashing (cost-only impact). |
| **N6** | U9 `dedupeKey` canonical format undefined | LOW | `BR-P5` relies on `dedupeKey` but gives no structure (has a time-window fallback, so partially mitigated). |

### Rejected after verification (do not chase)
- **U1 `ackEvent` ordering** (claimed HIGH) — not real. `BR-12` at-least-once +
  `BR-7`/`DeduplicationGuard` idempotent re-upsert make a crash-before-ack just
  redeliver safely. Wording nit at most.
- **U3 social login: unverified email + existing account "undefined"** — false
  positive. `BLM §6.2 step 3` rejects `email_verified=false` with an explicit
  error **before** the account lookup runs, so the branch is unreachable (fail-closed).

---

## 5. Action list (the real work)

1. **U4 stub** (H4): add a startup assertion rejecting `StubSearchGateway` when `ENV=PROD`.
2. ~~**N1 modelVer**: team decides~~ ✅ **RESOLVED (@kyjness)**: U2 §6 → one-time index-open
   `specVersion` check; per-record check dropped; FROZEN `vector-spec.md §4` unchanged.
3. **U3 cascade** (H6): finalize the SLA, retry/DLQ algorithm, undeployed-subscriber terminal state.
4. **U9 boosts** (Medium): add a server-side clamp in U2; don't trust U9.
5. **Minor**: U8↔CostGuard link; U3 PENDING-cleanup scheduler; N3–N6 spec gaps; delete/scope
   the stale `inception/component-methods.md` signature.

## Changes applied in this PR
- **N2 fixed**: `requestId` added to both `publishSearchExecuted(...)` call sites in
  `u2-discovery/.../business-logic-model.md` (aligned to FROZEN `events.md §2`).
- **N1 RESOLVED**: U2 `business-rules.md §6` revised (per-record `modelVer` → one-time
  index-open `specVersion` check); ⚠️ flags removed from both sites; `vector-spec.md §4`
  FROZEN unchanged. Decision by @kyjness (option b refined).
- **Regenerated** `tools/aidlc-designreview/review.{md,html}` (this run).
- Everything else documented here for the owners; FROZEN-contract resolutions deferred.
