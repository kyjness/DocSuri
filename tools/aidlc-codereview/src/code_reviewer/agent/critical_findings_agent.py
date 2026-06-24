"""Agent that analyzes tool results and source code to identify critical
sections requiring human review.

Runs after all tools complete. Three-pass analysis:
1. Reads full source code of the target codebase
2. Analyzes all tool findings
3. Cross-references flagged files/lines with actual source code
"""

# Copyright 2026 Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import json
import logging
from pathlib import Path
from typing import Any

from code_reviewer.agent.base_agent import BaseAgent
from code_reviewer.agent.config import AgentConfig
from code_reviewer.common.language_detector import EXTENSION_MAP
from code_reviewer.common.output import vprint
from code_reviewer.common.models import (
    CriticalCategory,
    CriticalFinding,
    Finding,
    Severity,
    ToolResult,
)

logger = logging.getLogger("aidlc_code_reviewer.critical_findings")

from code_reviewer import CONFIG_DIR

_TEMPLATE_PATH = CONFIG_DIR / "prompts" / "critical-findings-v1.md"

# Skip binary / non-code files and large generated files
_SKIP_DIRS = {".git", "__pycache__", ".mypy_cache", ".ruff_cache", "node_modules", ".venv", "venv"}
_MAX_FILE_SIZE = 256 * 1024  # 256 KB per file


def _collect_source_files(target: Path) -> dict[str, str]:
    """Read all source files under target into a {relative_path: content} dict."""
    sources: dict[str, str] = {}
    code_extensions = set(EXTENSION_MAP.keys())

    if target.is_file():
        if target.suffix.lower() in code_extensions:
            try:
                sources[target.name] = target.read_text(errors="replace")
            except OSError:
                pass
        return sources

    for file_path in sorted(target.rglob("*")):
        if any(part in _SKIP_DIRS for part in file_path.parts):
            continue
        if not file_path.is_file():
            continue
        if file_path.suffix.lower() not in code_extensions:
            continue
        if file_path.stat().st_size > _MAX_FILE_SIZE:
            continue
        try:
            rel = str(file_path.relative_to(target))
            sources[rel] = file_path.read_text(errors="replace")
        except OSError:
            pass

    return sources


def _format_source_block(sources: dict[str, str]) -> str:
    """Format collected sources for the prompt."""
    parts: list[str] = []
    for path, content in sources.items():
        parts.append(f"### {path}\n```\n{content}\n```")
    return "\n\n".join(parts) if parts else "(no source files found)"


def _format_tool_findings(results: list[ToolResult]) -> str:
    """Format tool findings as a compact summary for the prompt."""
    lines: list[str] = []
    for r in results:
        if not r.findings:
            continue
        lines.append(f"### {r.tool} ({r.category})")
        for f in r.findings:
            lines.append(
                f"- [{f.severity.value}] {f.rule_id} in {f.file}:{f.line} — {f.message}"
            )
    return "\n".join(lines) if lines else "(no tool findings)"


def _format_flagged_files(results: list[ToolResult], sources: dict[str, str]) -> str:
    """For files that tools flagged, include the relevant code context."""
    flagged: dict[str, set[int]] = {}
    for r in results:
        for f in r.findings:
            flagged.setdefault(f.file, set()).add(f.line)

    if not flagged:
        return "(no flagged files)"

    parts: list[str] = []
    for file_path, line_nums in sorted(flagged.items()):
        content = sources.get(file_path)
        if not content:
            parts.append(f"### {file_path}\n(source not available)")
            continue

        src_lines = content.splitlines()
        # Show context around each flagged line (5 lines before/after)
        regions: list[tuple[int, int]] = []
        for ln in sorted(line_nums):
            start = max(0, ln - 6)
            end = min(len(src_lines), ln + 5)
            regions.append((start, end))

        # Merge overlapping regions
        merged: list[tuple[int, int]] = []
        for start, end in regions:
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))

        snippet_parts: list[str] = []
        for start, end in merged:
            numbered = [
                f"{i + 1:>4} | {src_lines[i]}" for i in range(start, end)
            ]
            snippet_parts.append("\n".join(numbered))

        parts.append(f"### {file_path}\n```\n" + "\n...\n".join(snippet_parts) + "\n```")

    return "\n\n".join(parts)


def _build_prompt(
    sources: dict[str, str],
    results: list[ToolResult],
) -> str:
    """Assemble the critical findings prompt from the template."""
    try:
        template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    except OSError:
        logger.warning("Critical findings prompt template not found at %s", _TEMPLATE_PATH)
        raise
    if len(template) > 1_000_000:
        raise ValueError(f"Template file unexpectedly large: {len(template)} bytes")

    source_block = _format_source_block(sources)
    findings_block = _format_tool_findings(results)
    flagged_block = _format_flagged_files(results, sources)

    prompt = template.replace("INSERT_SOURCE_CODE", source_block)
    prompt = prompt.replace("INSERT_TOOL_FINDINGS", findings_block)
    prompt = prompt.replace("INSERT_FLAGGED_FILES", flagged_block)
    return prompt


def _parse_response(response_text: str, results: list[ToolResult]) -> list[CriticalFinding]:
    """Parse the LLM JSON response into CriticalFinding objects."""
    # Strip markdown fences if the model wraps them anyway
    text = response_text.strip()
    if text.startswith("```"):
        first_newline = text.index("\n") if "\n" in text else 3
        text = text[first_newline + 1 :]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    # Sanitize control characters that the LLM may embed in JSON string values
    # (e.g. literal tabs, newlines inside code_block fields). Replace with spaces
    # except for \n \r \t which we escape properly.
    import re
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', ' ', text)

    try:
        items = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.error("Failed to parse critical findings JSON: %s", exc)
        return []

    if not isinstance(items, list):
        logger.error("Expected JSON array, got %s", type(items).__name__)
        return []

    # Build a lookup for matching related tool findings
    # Tool findings may use absolute paths while agent returns relative paths,
    # so we index by both the full path and the basename for flexible matching.
    findings_by_file: dict[str, list[Finding]] = {}
    for r in results:
        for f in r.findings:
            findings_by_file.setdefault(f.file, []).append(f)

    category_map = {
        "COMPUTATION": CriticalCategory.COMPUTATION,
        "CONTROL_FLOW": CriticalCategory.CONTROL_FLOW,
        "DATA_TRANSFORM": CriticalCategory.DATA_TRANSFORM,
    }

    _LOW_INFO_SEV = {Severity.LOW, Severity.INFO}

    def _find_tool_findings(file_path: str, start: int, end: int) -> list[Finding]:
        """Match MEDIUM+ tool findings by file path (handles absolute vs relative mismatch)."""
        matched: list[Finding] = []
        for tool_path, tool_findings in findings_by_file.items():
            if (tool_path == file_path
                    or tool_path.endswith("/" + file_path)
                    or file_path.endswith("/" + tool_path)
                    or Path(tool_path).name == Path(file_path).name):
                for f in tool_findings:
                    if start <= f.line <= end and f.severity not in _LOW_INFO_SEV:
                        matched.append(f)
        return matched

    parsed: list[CriticalFinding] = []
    for item in items:
        cat_str = item.get("category", "")
        cat = category_map.get(cat_str)
        if cat is None:
            logger.warning("Unknown critical category: %s, skipping", cat_str)
            continue

        file_path = item.get("file", "")
        try:
            start_line = max(0, int(item.get("start_line", 0)))
            end_line = max(0, int(item.get("end_line", 0)))
        except (ValueError, TypeError):
            logger.warning("Non-numeric line values in critical finding, skipping entry")
            continue

        # Match related tool findings that overlap with this code region
        related = _find_tool_findings(file_path, start_line, end_line)

        source = "tool_assisted" if related else "agent_only"

        parsed.append(CriticalFinding(
            category=cat,
            file=file_path,
            start_line=start_line,
            end_line=end_line,
            verdict=item.get("verdict", ""),
            code_block=item.get("code_block", ""),
            why_critical=item.get("why_critical", ""),
            recommended_action=item.get("recommended_action", ""),
            source=source,
            related_tool_findings=related,
            highlight_lines=[int(ln) for ln in item.get("highlight_lines", []) if isinstance(ln, (int, float))],
        ))

    return parsed


class CriticalFindingsAgent(BaseAgent):
    """Agent that identifies critical code sections for human review."""

    def __init__(self, config: AgentConfig | None = None) -> None:
        super().__init__(config)

    def execute(
        self,
        target: Path | None = None,
        results: list[ToolResult] | None = None,
        **kwargs: Any,
    ) -> list[CriticalFinding]:
        """Analyze codebase and tool results to find critical sections.

        Returns a list of CriticalFinding objects, sorted by category then location.
        Returns empty list on failure (non-blocking).
        """
        if target is None or results is None:
            logger.error("CriticalFindingsAgent requires target and results")
            return []

        vprint("  Collecting source files...", flush=True)
        sources = _collect_source_files(target)
        if not sources:
            logger.warning("No source files found in %s", target)
            return []
        vprint(f"  Collected {len(sources)} source files", flush=True)

        vprint("  Building critical findings prompt...", flush=True)
        prompt = _build_prompt(sources, results)

        vprint("  Invoking agent for critical code analysis...", flush=True)
        try:
            response_text, usage = self._invoke_model(prompt)
            logger.info(
                "Critical findings agent: input=%s, output=%s tokens",
                usage.get("input_tokens", "?"),
                usage.get("output_tokens", "?"),
            )
        except Exception as e:
            logger.error("Critical findings agent invocation failed: %s", e)
            print(f"  Critical findings analysis failed: {e}", flush=True)
            return []

        vprint("  Parsing critical findings...", flush=True)
        findings = _parse_response(response_text, results)

        # Post-parse safety net: drop findings whose only related tool results
        # are LOW or INFO.  These are nonessential and should never appear as
        # standalone critical findings.  A LOW/INFO finding should typically
        # accompany a MEDIUM-or-higher finding in the same code region.
        _LOW_INFO = {Severity.LOW, Severity.INFO}
        before = len(findings)
        findings = [
            f for f in findings
            if f.source == "agent_only"  # agent-identified → keep
            or not f.related_tool_findings  # no tool findings → keep
            or any(tf.severity not in _LOW_INFO for tf in f.related_tool_findings)
        ]
        dropped = before - len(findings)
        if dropped:
            vprint(f"  Filtered {dropped} finding(s) backed only by LOW/INFO tool results", flush=True)

        vprint(f"  Found {len(findings)} critical code sections", flush=True)
        return findings
