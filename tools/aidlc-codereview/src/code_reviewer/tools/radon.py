"""Radon complexity wrapper for AIDLC Code Reviewer.

Invokes `radon cc` (cyclomatic complexity) as a subprocess and maps
the JSON output to the shared Finding / ToolResult data models.

Severity mapping (per policy — complexity category, capped at MEDIUM):
    Rank A (1-5)   -> INFO
    Rank B (6-10)  -> LOW
    Rank C (11-15) -> MEDIUM
    Rank D (16-20) -> MEDIUM
    Rank E (21-25) -> MEDIUM
    Rank F (26+)   -> MEDIUM
"""

# Copyright 2026 Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

from __future__ import annotations

import json
import logging
from pathlib import Path

from code_reviewer.common.models import Finding, Severity, ToolResult
from code_reviewer.common.utils import check_tool_installed, run_command

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

TOOL = "radon"
TOOL_NAME = "radon"
CATEGORY = "complexity"
SUPPORTED_LANGUAGES = ["python"]

# ---------------------------------------------------------------------------
# Severity mapping
# ---------------------------------------------------------------------------

_RANK_TO_SEVERITY: dict[str, Severity] = {
    "A": Severity.INFO,
    "B": Severity.LOW,
    "C": Severity.MEDIUM,
    "D": Severity.MEDIUM,
    "E": Severity.MEDIUM,
    "F": Severity.MEDIUM,
}


def _map_severity(rank: str) -> Severity:
    """Map a radon complexity rank to a Severity level."""
    return _RANK_TO_SEVERITY.get(rank.upper(), Severity.MEDIUM)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run(target: Path) -> ToolResult:
    """Run radon cyclomatic complexity analysis on *target* and return a ToolResult.

    Args:
        target: Path to the file or directory to analyse.

    Returns:
        A ToolResult with findings populated from radon's JSON output.
    """
    if not check_tool_installed(TOOL):
        return ToolResult(
            tool=TOOL,
            category=CATEGORY,
            success=False,
            error=f"{TOOL} is not installed or not on PATH",
        )

    args = [TOOL, "cc", "--json", str(target)]

    returncode, stdout, stderr = run_command(args)

    # radon exits 0 even when findings are present; negative returncode signals
    # an infrastructure-level failure (timeout, binary not found, etc.).
    if returncode < 0:
        return ToolResult(
            tool=TOOL,
            category=CATEGORY,
            success=False,
            error=stderr or f"{TOOL} exited with code {returncode}",
            raw_output=stdout or None,
        )

    if not stdout.strip():
        # No output means no Python files were analysed (empty directory, etc.)
        return ToolResult(
            tool=TOOL,
            category=CATEGORY,
            success=True,
            raw_output=stdout,
        )

    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        return ToolResult(
            tool=TOOL,
            category=CATEGORY,
            success=False,
            error=f"Failed to parse {TOOL} JSON output: {exc}",
            raw_output=stdout,
        )

    findings: list[Finding] = []

    # radon JSON structure:
    # {
    #   "<filepath>": [
    #     {
    #       "type": "F" | "M" | "C",
    #       "name": "<function/method name>",
    #       "lineno": <int>,
    #       "col_offset": <int>,
    #       "endline": <int>,
    #       "rank": "A" | "B" | ... | "F",
    #       "complexity": <int>,
    #       ...
    #     },
    #     ...
    #   ],
    #   ...
    # }

    for filepath, blocks in data.items():
        if not isinstance(blocks, list):
            logger.debug("Unexpected radon output structure for file %s; skipping.", filepath)
            continue

        for block in blocks:
            try:
                rank: str = block.get("rank", "A")
                complexity: int = int(block.get("complexity", 0))
                name: str = block.get("name", "<unknown>")
                lineno: int = int(block.get("lineno", 1))
                col_offset: int | None = block.get("col_offset")
                endline: int | None = block.get("endline")
                block_type: str = block.get("type", "")

                # Produce a human-readable type label
                type_label = {
                    "F": "function",
                    "M": "method",
                    "C": "class",
                }.get(block_type, "block")

                severity = _map_severity(rank)
                rule_id = f"CC{rank}"  # e.g. CCA, CCB, CCC …

                message = (
                    f"{type_label} '{name}' has cyclomatic complexity "
                    f"{complexity} (rank {rank})"
                )

                findings.append(
                    Finding(
                        file=filepath,
                        line=lineno,
                        column=col_offset,
                        end_line=endline,
                        rule_id=rule_id,
                        message=message,
                        severity=severity,
                        tool=TOOL,
                        category=CATEGORY,
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                logger.debug(
                    "Could not parse radon block entry in %s: %s — %s",
                    filepath,
                    block,
                    exc,
                )
                continue

    return ToolResult(
        tool=TOOL,
        category=CATEGORY,
        success=True,
        findings=findings,
        raw_output=stdout,
    )