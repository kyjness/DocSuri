from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from docsuri_ops.domain.models import GroundingDecision, GroundingViolation

# arXiv id shapes (lowercased): new-style "YYMM.NNNNN" and old-style "archive(.sub)/NNNNNNN",
# each optionally suffixed with a version "vN". Provenance equality is version-agnostic, so the
# version is stripped — but ONLY for these shapes (a non-arXiv id ending in "...v2" is left
# intact). fullmatch keeps a non-arXiv id with a digit run (e.g. "report-2024.12345") from being
# mistaken for an arXiv id, and the old-style archive prefix is preserved so "hep-th/0601001"
# and "astro-ph/0601001" never collide.
_ARXIV_ID = re.compile(r"(?P<base>\d{4}\.\d{4,5}|[a-z][a-z.-]*/\d{7})(?:v\d+)?")
# arXiv.org URL / "arxiv:" scheme wrappers are stripped first so a card url normalizes to its id
# (keeping any old-style archive prefix, unlike a blind split on "/").
_ARXIV_URL_PREFIX = re.compile(r"^(?:https?://)?(?:www\.)?arxiv\.org/(?:abs|pdf)/")


@dataclass(slots=True)
class GroundingEnforcementHook:
    def enforce(self, candidate: Any, retrieved: Sequence[Any]) -> GroundingDecision:
        retrieved_ids = _record_ids(retrieved)
        # One entry per exposed card: its id, or None if the card exposes no arxivId/paperId/url.
        references = [_candidate_reference(item) for item in _candidate_items(candidate)]

        if not retrieved_ids:
            return GroundingDecision(
                verdict="abstain",
                violations=(GroundingViolation("no_retrieved_records", "no retrieved records"),),
            )
        if not any(references):
            return GroundingDecision(
                verdict="abstain",
                violations=(
                    GroundingViolation(
                        "no_candidate_references",
                        "candidate has no grounded references",
                    ),
                ),
            )

        violations: list[GroundingViolation] = []
        for ref in references:
            if not ref:
                # An exposed card carrying NO id, shown alongside grounded cards, can't be
                # provenance-checked — fail closed rather than let it pass unverified. (Finding 4)
                violations.append(
                    GroundingViolation(
                        "missing_reference",
                        "exposed card has no grounded reference",
                    )
                )
            elif _normalize_identifier(ref) not in retrieved_ids:
                violations.append(
                    GroundingViolation(
                        code="fabricated_reference",
                        message="candidate reference was not present in retrieved records",
                        arxiv_id=ref,
                    )
                )
        if violations:
            return GroundingDecision(verdict="block", violations=tuple(violations))
        return GroundingDecision(verdict="pass")

    def run_eval_set(self, eval_set: Any) -> dict[str, Any]:
        cases = _as_cases(eval_set)
        results: list[dict[str, Any]] = []
        for case in cases:
            decision = self.enforce(case.get("candidate"), case.get("retrieved", ()))
            expected = case.get("expected")
            results.append(
                {
                    "name": case.get("name", "case"),
                    "expected": expected,
                    "actual": decision.verdict,
                    "passed": expected is None or expected == decision.verdict,
                    "violationCount": len(decision.violations),
                }
            )
        return {
            "caseCount": len(results),
            "passed": sum(1 for result in results if result["passed"]),
            "fabricationCount": sum(
                1 for result in results if result["actual"] == "block"
            ),
            "abstainCount": sum(
                1 for result in results if result["actual"] == "abstain"
            ),
            "results": results,
        }


def _as_cases(eval_set: Any) -> list[dict[str, Any]]:
    if isinstance(eval_set, dict):
        raw_cases = eval_set.get("cases", ())
    else:
        raw_cases = eval_set
    return [dict(case) for case in raw_cases]


def _record_ids(records: Sequence[Any]) -> set[str]:
    values: set[str] = set()
    for record in records:
        for attr in ("arxivId", "paperId", "arxivUrl"):
            value = _get(record, attr)
            if value:
                values.add(_normalize_identifier(str(value)))
        url = _get(record, "arxivUrl")
        if url:
            values.add(_normalize_identifier(str(url).rstrip("/").split("/")[-1]))
    return values


def _candidate_reference(item: Any) -> str | None:
    record = _get(item, "record")
    source = record if record is not None else item
    for attr in ("arxivId", "paperId", "arxivUrl"):
        value = _get(source, attr)
        if value:
            return str(value)
    return None


def _candidate_items(candidate: Any) -> tuple[Any, ...]:
    if candidate is None:
        return ()
    if isinstance(candidate, dict):
        for key in ("cards", "results", "items", "ranked", "candidates"):
            value = candidate.get(key)
            if value is not None:
                return tuple(value)
        return ()
    for attr in ("cards", "results", "items", "ranked", "candidates"):
        value = _get(candidate, attr)
        if value is not None:
            return tuple(value)
    if isinstance(candidate, Sequence) and not isinstance(candidate, (str, bytes, bytearray)):
        return tuple(candidate)
    return ()


def _get(value: Any, field: str) -> Any:
    if isinstance(value, dict):
        return value.get(field)
    return getattr(value, field, None)


def _normalize_identifier(value: str) -> str:
    normalized = value.strip().lower()
    normalized = _ARXIV_URL_PREFIX.sub("", normalized)
    normalized = normalized.removeprefix("arxiv:").rstrip("/")
    match = _ARXIV_ID.fullmatch(normalized)
    if match:
        return match.group("base")
    return normalized
