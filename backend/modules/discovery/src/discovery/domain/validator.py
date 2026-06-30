"""QueryValidator — FR-1/SEC-5 validation + deterministic NFC normalization (BR-1/2).

normalize is idempotent (PBT-02): NFC + whitespace-collapse + strip. Multilingual is
required (cross-lingual KR↔EN, TD-3) — there is intentionally NO script allowlist (BR-2).
"""

from __future__ import annotations

import re
import unicodedata

from .models import NormalizedQuery, ValidationResult

MAX_QUERY_LEN = 500  # FR-1/SEC-5 (BR-1)
# Reject C0 controls + DEL; \t\n\v\f\r are whitespace (collapsed by normalize, not rejected).
_CONTROL = re.compile(r"[\x00-\x08\x0e-\x1f\x7f]")
_WHITESPACE = re.compile(r"\s+")


class QueryValidator:
    """Domain input validation/normalization. Mirrored at the U6 gateway (defense-in-depth)."""

    def validate(self, raw_query: str) -> ValidationResult:
        if not isinstance(raw_query, str):
            return ValidationResult(ok=False, reason="type", field="query")
        if _CONTROL.search(raw_query):
            return ValidationResult(ok=False, reason="control_chars", field="query")
        normalized = self.normalize(raw_query).text
        if not normalized:
            return ValidationResult(ok=False, reason="empty", field="query")
        if len(normalized) > MAX_QUERY_LEN:
            return ValidationResult(ok=False, reason="too_long", field="query")
        return ValidationResult(ok=True)

    def normalize(self, raw_query: str) -> NormalizedQuery:
        """Deterministic + idempotent (PBT-02): NFC, collapse whitespace runs, strip."""
        text = unicodedata.normalize("NFC", raw_query)
        text = _WHITESPACE.sub(" ", text).strip()
        return NormalizedQuery(text=text)
