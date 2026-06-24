"""Agent that performs AI-powered code structure critique.

Evaluates the codebase across six dimensions: logging, measurability,
scalability, efficiency, complexity, and structure. Feeds in critical
findings from the prior agent pass plus all tool results.
"""

# Copyright 2026 Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import json
import logging
from pathlib import Path
from typing import Any

from code_reviewer.agent.base_agent import BaseAgent
from code_reviewer.agent.config import AgentConfig
from code_reviewer.agent.critical_findings_agent import _collect_source_files, _format_source_block, _format_tool_findings
from code_reviewer.common.output import vprint
from code_reviewer.common.models import (
    CodeStructureCritique,
    CriticalFinding,
    Finding,
    StructureDimension,
    StructureIssue,
    StructureRating,
    ToolResult,
)

logger = logging.getLogger("aidlc_code_reviewer.code_structure")

from code_reviewer import CONFIG_DIR

_TEMPLATE_PATH = CONFIG_DIR / "prompts" / "structure-critique-v1.md"


def _format_critical_findings(critical_findings: list[CriticalFinding]) -> str:
    """Format critical findings as context for the structure agent."""
    if not critical_findings:
        return "(no critical findings from prior analysis)"
    parts: list[str] = []
    for i, cf in enumerate(critical_findings, 1):
        parts.append(
            f"{i}. [{cf.category.value}] {cf.file}:{cf.start_line}-{cf.end_line} — {cf.verdict}"
        )
    return "\n".join(parts)


def _build_prompt(
    sources: dict[str, str],
    results: list[ToolResult],
    critical_findings: list[CriticalFinding],
) -> str:
    """Assemble the structure critique prompt from the template."""
    try:
        template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    except OSError:
        logger.warning("Structure critique prompt template not found at %s", _TEMPLATE_PATH)
        raise
    if len(template) > 1_000_000:
        raise ValueError(f"Template file unexpectedly large: {len(template)} bytes")

    source_block = _format_source_block(sources)
    findings_block = _format_tool_findings(results)
    critical_block = _format_critical_findings(critical_findings)

    prompt = template.replace("INSERT_SOURCE_CODE", source_block)
    prompt = prompt.replace("INSERT_TOOL_FINDINGS", findings_block)
    prompt = prompt.replace("INSERT_CRITICAL_FINDINGS", critical_block)
    return prompt


def _find_tool_findings_for_range(
    file_path: str,
    start: int,
    end: int,
    findings_by_file: dict[str, list[Finding]],
) -> list[Finding]:
    """Match tool findings by file path (handles absolute vs relative mismatch)."""
    matched: list[Finding] = []
    for tool_path, tool_findings in findings_by_file.items():
        if (tool_path == file_path
                or tool_path.endswith("/" + file_path)
                or file_path.endswith("/" + tool_path)
                or Path(tool_path).name == Path(file_path).name):
            for f in tool_findings:
                if start <= f.line <= end:
                    matched.append(f)
    return matched


def _parse_response(
    response_text: str,
    results: list[ToolResult],
) -> CodeStructureCritique | None:
    """Parse the LLM JSON response into a CodeStructureCritique."""
    text = response_text.strip()
    if text.startswith("```"):
        first_newline = text.index("\n") if "\n" in text else 3
        text = text[first_newline + 1:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.error("Failed to parse structure critique JSON: %s", exc)
        return None

    if not isinstance(data, dict):
        logger.error("Expected JSON object, got %s", type(data).__name__)
        return None

    # Build tool findings lookup
    findings_by_file: dict[str, list[Finding]] = {}
    for r in results:
        for f in r.findings:
            findings_by_file.setdefault(f.file, []).append(f)

    rating_map = {
        "GOOD": StructureRating.GOOD,
        "NEEDS_IMPROVEMENT": StructureRating.NEEDS_IMPROVEMENT,
        "POOR": StructureRating.POOR,
    }

    dimensions: list[StructureDimension] = []
    for dim_data in data.get("dimensions", []):
        rating = rating_map.get(dim_data.get("rating", ""), StructureRating.NEEDS_IMPROVEMENT)

        issues: list[StructureIssue] = []
        for issue_data in dim_data.get("findings", []):
            file_path = issue_data.get("file", "")
            try:
                start_line = max(0, int(issue_data.get("start_line", 0)))
                end_line = max(0, int(issue_data.get("end_line", 0)))
            except (ValueError, TypeError):
                logger.warning("Non-numeric line values in structure issue, skipping entry")
                continue

            related = _find_tool_findings_for_range(
                file_path, start_line, end_line, findings_by_file
            )

            source = "tool_assisted" if related else "agent_only"

            issues.append(StructureIssue(
                file=file_path,
                start_line=start_line,
                end_line=end_line,
                issue=issue_data.get("issue", ""),
                recommendation=issue_data.get("recommendation", ""),
                code_block=issue_data.get("code_block", ""),
                source=source,
                related_tool_findings=related,
                highlight_lines=[int(ln) for ln in issue_data.get("highlight_lines", []) if isinstance(ln, (int, float))],
            ))

        dimensions.append(StructureDimension(
            dimension=dim_data.get("dimension", "UNKNOWN"),
            rating=rating,
            summary=dim_data.get("summary", ""),
            findings=issues,
        ))

    return CodeStructureCritique(
        overall_summary=data.get("overall_summary", ""),
        dimensions=dimensions,
    )


class CodeStructureAgent(BaseAgent):
    """Agent that performs holistic code structure critique."""

    def __init__(self, config: AgentConfig | None = None) -> None:
        super().__init__(config)

    def execute(
        self,
        target: Path | None = None,
        results: list[ToolResult] | None = None,
        critical_findings: list[CriticalFinding] | None = None,
        **kwargs: Any,
    ) -> CodeStructureCritique | None:
        """Analyze codebase structure across six quality dimensions.

        Returns CodeStructureCritique or None on failure (non-blocking).
        """
        if target is None or results is None:
            logger.error("CodeStructureAgent requires target and results")
            return None

        vprint("  Collecting source files for structure critique...", flush=True)
        sources = _collect_source_files(target)
        if not sources:
            logger.warning("No source files found in %s", target)
            return None
        vprint(f"  Collected {len(sources)} source files", flush=True)

        vprint("  Building structure critique prompt...", flush=True)
        prompt = _build_prompt(sources, results, critical_findings or [])

        vprint("  Invoking agent for code structure analysis...", flush=True)
        try:
            response_text, usage = self._invoke_model(prompt)
            logger.info(
                "Structure critique agent: input=%s, output=%s tokens",
                usage.get("input_tokens", "?"),
                usage.get("output_tokens", "?"),
            )
        except Exception as e:
            logger.error("Structure critique agent invocation failed: %s", e)
            print(f"  Structure critique analysis failed: {e}", flush=True)
            return None

        vprint("  Parsing structure critique...", flush=True)
        critique = _parse_response(response_text, results)
        if critique:
            total_issues = sum(len(d.findings) for d in critique.dimensions)
            vprint(f"  Structure critique complete: {len(critique.dimensions)} dimensions, {total_issues} issues", flush=True)
        return critique
