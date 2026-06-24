"""Agent that performs AI-powered business logic review.

Identifies core business rules, formulas, and domain logic in the codebase
so a human reviewer knows exactly what to inspect — even when every static
analysis tool reports zero findings.  Produces a separate report.
"""

# Copyright 2026 Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import json
import logging
from pathlib import Path
from typing import Any

from code_reviewer.agent.base_agent import BaseAgent
from code_reviewer.agent.config import AgentConfig
from code_reviewer.agent.critical_findings_agent import _collect_source_files, _format_source_block
from code_reviewer.common.output import vprint
from code_reviewer.common.models import (
    BusinessLogicCategory,
    BusinessLogicFinding,
    BusinessLogicReview,
    ConsistencyIssue,
    ConsistencyIssueLocation,
    ConsistencyIssueType,
)

logger = logging.getLogger("aidlc_code_reviewer.business_logic")

from code_reviewer import CONFIG_DIR

_TEMPLATE_PATH = CONFIG_DIR / "prompts" / "business-logic-review.md"

# Valid enum values for safe parsing
_VALID_CATEGORIES = {c.value for c in BusinessLogicCategory}
_VALID_ISSUE_TYPES = {t.value for t in ConsistencyIssueType}


def _build_prompt(sources: dict[str, str]) -> str:
    """Assemble the business logic review prompt from the template."""
    try:
        template = _TEMPLATE_PATH.read_text()
    except OSError:
        logger.warning("Business logic review prompt template not found at %s", _TEMPLATE_PATH)
        raise

    source_block = _format_source_block(sources)
    return template.replace("INSERT_SOURCE_CODE", source_block)


def _parse_response(response_text: str) -> BusinessLogicReview | None:
    """Parse the LLM JSON response into a BusinessLogicReview."""
    text = response_text.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        first_newline = text.index("\n") if "\n" in text else 3
        text = text[first_newline + 1:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.error("Failed to parse business logic review JSON: %s", exc)
        return None

    if not isinstance(data, dict):
        logger.error("Expected JSON object, got %s", type(data).__name__)
        return None

    # Parse findings
    findings: list[BusinessLogicFinding] = []
    for item in data.get("findings", []):
        raw_cat = item.get("category", "")
        if raw_cat not in _VALID_CATEGORIES:
            logger.warning("Skipping finding with unknown category: %s", raw_cat)
            continue

        findings.append(BusinessLogicFinding(
            category=BusinessLogicCategory(raw_cat),
            title=item.get("title", ""),
            file=item.get("file", ""),
            start_line=int(item.get("start_line", 0)),
            end_line=int(item.get("end_line", 0)),
            what_it_does=item.get("what_it_does", ""),
            review_guidance=item.get("review_guidance", ""),
            code_block=item.get("code_block", ""),
            risk_if_wrong=item.get("risk_if_wrong", ""),
        ))

    # Parse consistency issues
    consistency_issues: list[ConsistencyIssue] = []
    for item in data.get("consistency_issues", []):
        raw_type = item.get("issue_type", "")
        if raw_type not in _VALID_ISSUE_TYPES:
            logger.warning("Skipping consistency issue with unknown type: %s", raw_type)
            continue

        locations: list[ConsistencyIssueLocation] = []
        for loc in item.get("locations", []):
            locations.append(ConsistencyIssueLocation(
                file=loc.get("file", ""),
                start_line=int(loc.get("start_line", 0)),
                end_line=int(loc.get("end_line", 0)),
            ))

        consistency_issues.append(ConsistencyIssue(
            issue_type=ConsistencyIssueType(raw_type),
            description=item.get("description", ""),
            locations=locations,
            code_blocks=list(item.get("code_blocks", [])),
            recommended_action=item.get("recommended_action", ""),
        ))

    # Enforce sort order: category (taxonomy order), then file path, then start_line.
    # The LLM doesn't always respect the requested sort, so we do it here.
    _CAT_ORDER = {cat: i for i, cat in enumerate(BusinessLogicCategory)}
    findings.sort(key=lambda f: (_CAT_ORDER.get(f.category, 99), f.file, f.start_line))

    return BusinessLogicReview(
        executive_summary=data.get("executive_summary", ""),
        findings=findings,
        consistency_issues=consistency_issues,
    )


class BusinessLogicAgent(BaseAgent):
    """Agent that identifies core business logic for human review."""

    def __init__(self, config: AgentConfig | None = None) -> None:
        super().__init__(config)

    def execute(
        self,
        target: Path | None = None,
        **kwargs: Any,
    ) -> BusinessLogicReview | None:
        """Analyze codebase for business logic requiring human review.

        Returns BusinessLogicReview or None on failure (non-blocking).
        """
        if target is None:
            logger.error("BusinessLogicAgent requires target")
            return None

        vprint("  Collecting source files for business logic review...", flush=True)
        sources = _collect_source_files(target)
        if not sources:
            logger.warning("No source files found in %s", target)
            return None
        vprint(f"  Collected {len(sources)} source files", flush=True)

        vprint("  Building business logic review prompt...", flush=True)
        prompt = _build_prompt(sources)

        vprint("  Invoking agent for business logic analysis...", flush=True)
        try:
            response_text, usage = self._invoke_model(prompt)
            logger.info(
                "Business logic agent: input=%s, output=%s tokens",
                usage.get("input_tokens", "?"),
                usage.get("output_tokens", "?"),
            )
        except Exception as e:
            logger.error("Business logic agent invocation failed: %s", e)
            print(f"  Business logic review failed: {e}", flush=True)
            return None

        vprint("  Parsing business logic review...", flush=True)
        review = _parse_response(response_text)
        if review:
            vprint(
                f"  Business logic review complete: {len(review.findings)} findings, "
                f"{len(review.consistency_issues)} consistency issues",
                flush=True,
            )
        return review
