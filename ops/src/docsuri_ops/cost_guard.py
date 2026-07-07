from __future__ import annotations

from dataclasses import dataclass, field

from docsuri_ops._dedup import BoundedSeen
from docsuri_ops.domain.enums import CircuitState, DegradeMode
from docsuri_ops.domain.models import BudgetState, UsageEvent


@dataclass(slots=True)
class CostGuardCircuitBreaker:
    cap_usd: float = 1600.0
    warning_ratio: float = 0.80
    hard_degrade_ratio: float = 0.95
    spend_usd: float = 0.0
    # Bounded LRU: a long-running worker consumes a usage event per request — an unbounded set
    # would grow forever. Eviction only re-counts a long-evicted event_id (cap dwarfs the window).
    _seen_event_ids: BoundedSeen = field(default_factory=BoundedSeen)

    def record_spend(self, event: UsageEvent) -> BudgetState:
        if event.amount_usd < 0:
            raise ValueError("usage amount must be non-negative")
        if event.event_id not in self._seen_event_ids:
            self._seen_event_ids.add(event.event_id)
            self.spend_usd += event.amount_usd
        return self.get_budget_state()

    def evaluate_circuit(self) -> CircuitState:
        ratio = self._ratio()
        if ratio >= 1.0:
            return CircuitState.OPEN
        if ratio >= self.warning_ratio:
            return CircuitState.HALF_OPEN
        return CircuitState.CLOSED

    def get_budget_state(self) -> BudgetState:
        ratio = self._ratio()
        return BudgetState(
            tier=self._tier(ratio),
            degrade_mode=self._degrade_mode(ratio),
            circuit_state=self.evaluate_circuit(),
            spend_usd=round(self.spend_usd, 6),
            cap_usd=self.cap_usd,
            threshold_ratio=round(ratio, 6),
        )

    def _ratio(self) -> float:
        if self.cap_usd <= 0:
            return 1.0
        return self.spend_usd / self.cap_usd

    def _degrade_mode(self, ratio: float) -> DegradeMode:
        if ratio >= self.hard_degrade_ratio:
            return DegradeMode.LEXICAL_ONLY
        if ratio >= self.warning_ratio:
            return DegradeMode.RERANK_OFF
        return DegradeMode.NORMAL

    def _tier(self, ratio: float) -> str:
        if ratio >= 1.0:
            return "hard_cap"
        if ratio >= self.hard_degrade_ratio:
            return "critical"
        if ratio >= self.warning_ratio:
            return "warning"
        return "normal"


# --- NFR-C1 공용 헬퍼: 게이트 술어 + Bedrock 토큰→USD 추정 ---

# Bedrock Claude Sonnet 4.x 단가(USD / 1M tokens). env로 조정 가능.
_USD_PER_1M_INPUT_DEFAULT = 3.0
_USD_PER_1M_OUTPUT_DEFAULT = 15.0


def is_cost_degraded(budget: object) -> bool:
    """U7-style soft degradation predicate: warning(80%)부터 비-normal로 본다."""
    mode = str(getattr(budget, "degrade_mode", "normal") or "normal").lower().replace("_", "-")
    circuit = str(getattr(budget, "circuit_state", "closed") or "closed").lower()
    return mode not in ("normal", "none") or circuit == "open"


def is_cost_critical(budget: object) -> bool:
    """Agent Bedrock 하드 게이트: critical(95%) 이상 또는 open circuit에서만 차단한다."""
    tier = str(getattr(budget, "tier", "normal") or "normal").lower().replace("_", "-")
    mode = str(getattr(budget, "degrade_mode", "normal") or "normal").lower().replace("_", "-")
    circuit = str(getattr(budget, "circuit_state", "closed") or "closed").lower()
    return tier in {"critical", "hard-cap"} or mode == "lexical-only" or circuit == "open"


def estimate_bedrock_usd(*, input_tokens: int, output_tokens: int) -> float:
    """Bedrock 사용 토큰 → USD 추정 (DOCSURI_BEDROCK_USD_PER_1M_INPUT/OUTPUT로 단가 조정)."""
    import os

    input_rate = float(os.getenv("DOCSURI_BEDROCK_USD_PER_1M_INPUT") or _USD_PER_1M_INPUT_DEFAULT)
    output_rate = float(
        os.getenv("DOCSURI_BEDROCK_USD_PER_1M_OUTPUT") or _USD_PER_1M_OUTPUT_DEFAULT
    )
    return (
        max(input_tokens, 0) / 1_000_000 * input_rate
        + max(output_tokens, 0) / 1_000_000 * output_rate
    )
