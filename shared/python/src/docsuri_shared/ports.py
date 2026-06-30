"""Cross-cutting hook interfaces (ports.md) — the dependency-inversion seam.

These are method interfaces, not data schemas, so they cannot be generated from JSON
Schema; they are authored here from ``ports.md`` (the SSOT for *these*). §5-A is now
decided (backend = Python), which unblocks these ``typing.Protocol`` stubs (§5-B).

Direction: **U6 implements; U2/U1 depend by injection.** Both sides depend on these
abstractions — not on a concrete U6 module — which is what breaks the U2↔U6 sync cycle
(ports.md §1). Single authority: U2 must NOT re-implement grounding/cost (ports.md §5).

State: ``enforce`` and ``get_budget_state`` are 🔒 FROZEN (locked by
``component-methods.md``); everything else is 🟡 PROVISIONAL and syncs when U6 FD lands.
Method names are pythonic ``snake_case``; each docstring cites the spec's camelCase name.
Provisional payload shapes are intentionally loose aliases (``Any``) until U6 FD fixes them.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol, runtime_checkable

from .vector_spec import IndexRecord

__all__ = [
    "Verdict",
    "GroundingDecision",
    "BudgetState",
    "CandidateResponse",
    "RetrievedRecordSet",
    "GroundingEvalSet",
    "GroundingEvalReport",
    "GroundingDomain",
    "GroundingAuthority",
    "ValidatorRegistration",
    "GroundingValidatorRegistry",
    "StructuredLogEntry",
    "AuditEvent",
    "Span",
    "TraceContext",
    "MetricName",
    "MetricValue",
    "TagSet",
    "SpanName",
    "GroundingEnforcementHook",
    "CostGuardCircuitBreaker",
    "ObservabilityHub",
    "EvidenceRequest",
    "EvidenceResult",
    "EvidenceFormationPort",
]

# --- Grounding (ports.md §2) -------------------------------------------------
Verdict = Literal["pass", "block", "abstain"]

# PROVISIONAL opaque shapes — refined in U6/U2 FD (ports.md §2 type cards).
CandidateResponse = Any  # U2 ranked candidate (RankedResults), shaped by GroundingAdapter
RetrievedRecordSet = Sequence[IndexRecord]  # real records grounding is verified against
GroundingEvalSet = Any  # QT-1 evaluation case set
GroundingEvalReport = Any  # per-case results + fabrication/abstain summary


class GroundingDecision(Protocol):
    """enforce result (ports.md §2): a verdict plus the list of grounding violations.

    Not ``@runtime_checkable`` — it is a data shape; an ``isinstance`` check would only
    test attribute *presence*, not types, which is misleading. Use it for static typing.
    """

    verdict: Verdict
    violations: Sequence[Any]


@runtime_checkable
class GroundingEnforcementHook(Protocol):
    """Grounding single-authority gate. Implemented by U6 (GroundingGuardService);
    the sole invocation site is the U6 gateway post-handler. U2 only shapes input and
    maps the verdict — it MUST NOT re-implement ``enforce``."""

    def enforce(
        self, candidate: CandidateResponse, retrieved: RetrievedRecordSet
    ) -> GroundingDecision:
        """🔒 FROZEN — spec: ``enforce(candidate, retrieved) -> GroundingDecision``.

        FR-5/QT-1 single runtime gate: map a candidate response to real retrieved
        records, verify AI-text provenance, decide pass/block/abstain.
        Trace: FR-5, QT-1, US-D5/D6/R1.
        """
        ...

    def run_eval_set(self, eval_set: GroundingEvalSet) -> GroundingEvalReport:
        """🟡 PROVISIONAL — spec: ``runEvalSet(evalSet) -> GroundingEvalReport``.

        Run the QT-1 eval set through the *same* hook (zero-fabrication / abstain report).
        """
        ...


# --- Grounding validator registry (ports.md §2.1 — D3 domain-neutral catalog) ---
# Search grounding (``GroundingEnforcementHook.enforce(candidate, retrieved)``) and summary
# grounding (U7's deterministic ``validate(GroundingInput) -> AnchorVerdict``) are DIFFERENT
# checks with DIFFERENT signatures — search verifies a candidate against a retrieved record
# SET, U7 verifies a structured summary against ONE paper's refined source (document fidelity).
# They are deliberately parallel (ports.md §2 design note), not interchangeable. This registry
# catalogs validators by domain WITHOUT forcing a common call signature, and encodes the one
# substantive boundary U6 signs off on: *enforcement* authority belongs to the ``search``
# domain ONLY ("single grounding authority = U6 search gate"); every other domain is advisory.
GroundingDomain = Literal["search", "summary", "agent"]
GroundingAuthority = Literal["enforcement", "advisory"]


@dataclass(frozen=True)
class ValidatorRegistration:
    """One domain's grounding validator + its authority class (ports.md §2.1).

    ``validator`` is intentionally ``object``: the search slot holds a
    ``GroundingEnforcementHook`` (``enforce(candidate, retrieved)``) while the summary slot
    holds U7's anchor validator (``validate(GroundingInput) -> AnchorVerdict``) — the shapes
    genuinely differ and are NOT unified here (ports.md §2 note). A consumer fetches by domain
    and calls the concrete shape it owns; ``shared/ports`` never imports a unit's concrete type.
    """

    domain: GroundingDomain
    authority: GroundingAuthority
    owner_unit: str  # implementing unit, e.g. "U6", "U7"
    validator: object


class GroundingValidatorRegistry:
    """Domain → validator catalog (D3). An ADDITIVE seam: it does not change ``enforce`` /
    ``validate`` and does not centralize them — it only records WHICH validator owns WHICH
    domain and WHO may *enforce*. Invariant (U6 sign-off): enforcement authority is reserved
    for the ``search`` domain — the single grounding authority. ``summary``/``agent`` are
    advisory (their verdicts inform/annotate; they do not act as the system's grounding gate).
    """

    def __init__(self) -> None:
        self._by_domain: dict[GroundingDomain, ValidatorRegistration] = {}

    def register(self, registration: ValidatorRegistration) -> None:
        """Register (or replace) the validator for a domain. Rejects an enforcement-authority
        registration for any domain other than ``search`` — the boundary U6 signs off on
        ("single grounding authority = search")."""
        if registration.authority == "enforcement" and registration.domain != "search":
            raise ValueError(
                "enforcement authority is reserved for the 'search' domain "
                "(single grounding authority = U6 search gate); "
                f"got domain={registration.domain!r}"
            )
        self._by_domain[registration.domain] = registration

    def get(self, domain: GroundingDomain) -> ValidatorRegistration:
        """Return the registration for ``domain``; raises ``KeyError`` if unregistered."""
        return self._by_domain[domain]

    def domains(self) -> Sequence[GroundingDomain]:
        """Registered domains, for catalog introspection."""
        return tuple(self._by_domain)


# --- Cost guard (ports.md §3) ------------------------------------------------
class BudgetState(Protocol):
    """Cost-guard branching signal (ports.md §3): budget tier + advisory degrade mode
    + circuit state. ``degrade_mode`` tells U2 to drop embedding/LLM rerank and fall
    back to lexical-only (the embedding space itself is unchanged).
    Not ``@runtime_checkable`` (data shape — see GroundingDecision).

    Field name mapping to the spec (camelCase): ``tier`` ↔ ``tier``,
    ``degrade_mode`` ↔ ``degradeMode``, ``circuit_state`` ↔ ``circuitState``.
    """

    tier: Any
    degrade_mode: Any  # spec: degradeMode
    circuit_state: Any  # spec: circuitState


@runtime_checkable
class CostGuardCircuitBreaker(Protocol):
    """Cost-degrade state query. Implemented by U6 (CostGuardService). U2 reads the
    advisory state and branches — it MUST NOT judge cost/budget itself; accumulation /
    threshold / circuit transition (``recordSpend`` / ``evaluateCircuit``) are
    U6-internal and intentionally absent from this port."""

    def get_budget_state(self) -> BudgetState:
        """🔒 FROZEN — spec: ``getBudgetState() -> BudgetState``.

        Near-real-time threshold state + advisory degrade mode for sync fallback branching.
        """
        ...


# --- Observability (ports.md §4) ---------------------------------------------
# PROVISIONAL primitive/opaque types — refined in U6 FD (ports.md §4 type cards).
MetricName = str
MetricValue = float
TagSet = Mapping[str, str]
SpanName = str
TraceContext = Any
Span = Any
StructuredLogEntry = Any  # requestId-correlated structured fields (no PII/secrets)
AuditEvent = Any  # core change / authorization decision (append-only)


@runtime_checkable
class ObservabilityHub(Protocol):
    """Single observability collector (all units depend, NFR-O1). Implemented by U6
    (ObservabilityService). Entries carry no PII/secrets (SEC-3) and no internal
    scores/owner/debug fields (SEC-9)."""

    def emit_metric(self, name: MetricName, value: MetricValue, tags: TagSet) -> None:
        """🟡 PROVISIONAL — spec: ``emitMetric(name, value, tags) -> void``.

        Trace: NFR-O1, RES-5.
        """
        ...

    def emit_log(self, entry: StructuredLogEntry) -> None:
        """🟡 PROVISIONAL — spec: ``emitLog(entry) -> void`` (PII/secrets blocked).

        Trace: NFR-O1, SEC-3.
        """
        ...

    def start_span(self, name: SpanName, context: TraceContext) -> Span:
        """🟡 PROVISIONAL — spec: ``startSpan(name, context) -> Span``. Trace: NFR-O1."""
        ...

    def audit_append(self, event: AuditEvent) -> None:
        """🟡 PROVISIONAL — spec: ``auditAppend(event) -> void`` (append-only, 90 days+).

        Trace: SEC-13, SEC-14.
        """
        ...


# --- Evidence Formation (shared/ports §4) ------------------------------------
# 🔒 FROZEN (D5 계약 게이트 — Q1~Q3 확정 후 동결, 2026-06-29).
# Producer: U4(문헌탐색·근거형성 Agent). Consumer: U12(연구아이디어 Agent, 주입 lib).
# U12는 EvidenceFormationPort를 재구현 금지 — shared/ports 추상에만 의존.
# 데이터 스키마 SSOT: shared/dtos/evidence.schema.json (§5-B 생성).
EvidenceRequest = Any   # → evidence.schema.json#/$defs/EvidenceRequest (생성 타입으로 교체 예정)
EvidenceResult = Any    # → evidence.schema.json#/$defs/EvidenceResult | EvidenceAbstainResult


@runtime_checkable
class EvidenceFormationPort(Protocol):
    """다논문 근거형성 단일 권한 포트. U4가 구현, U12가 주입 lib으로 소비.

    U12는 Research Gap/Novelty 판단 입력으로 EvidenceResult.claims를 사용한다.
    순환 차단: U12 → shared/ports(추상) ← U4. U12가 U4 구체 모듈을 직접 import 금지.
    """

    async def form_evidence(
        self, request: EvidenceRequest, ctx: Any
    ) -> EvidenceResult:
        """🔒 FROZEN — spec:
        ``async form_evidence(request, ctx) -> EvidenceResult | EvidenceAbstainResult``.

        다논문 교차확인 → 근거 비교·정리 → 출처·기권.
        - 근거 1건 이상: EvidenceResult(state=ok, claims=[...], coverage={...})
        - 근거 없음/범위 밖: EvidenceAbstainResult(state=abstain, abstainReason=...)
        긴 다논문 분석은 비동기 잡(U7 패턴)으로 오프로드 가능 — 표면은 U4 FD 이월.
        Trace: Q1, Q3, Q4, Q9, FR-5, SEC-9, C-2, D5.
        """
        ...
