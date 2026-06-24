"""Vulture dead code wrapper for AIDLC Code Reviewer."""

# Copyright 2026 Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import re
from pathlib import Path

from code_reviewer.common.models import Finding, Severity, ToolResult
from code_reviewer.common.utils import check_tool_installed, run_command

TOOL = "vulture"
CATEGORY = "dead_code"
SUPPORTED_LANGUAGES = ["python"]

# Vulture default output format:
# path/to/file.py:42: unused variable 'x' (60% confidence)
_LINE_RE = re.compile(
    r"^(?P<file>[^:]+):(?P<line>\d+):\s+(?P<message>.+?)\s+\((?P<confidence>\d+)%\s+confidence\)$"
)


def _map_severity(confidence: int) -> Severity:
    """Map vulture confidence to severity per policy.

    >= 80% confidence -> MEDIUM
    <  80% confidence -> LOW
    """
    if confidence >= 80:
        return Severity.MEDIUM
    return Severity.LOW


def _parse_rule_id(message: str) -> str:
    """Derive a stable rule_id from the message text."""
    msg_lower = message.lower()
    if "unused import" in msg_lower:
        return "VU001"
    if "unused variable" in msg_lower:
        return "VU002"
    if "unused attribute" in msg_lower:
        return "VU003"
    if "unused function" in msg_lower:
        return "VU004"
    if "unused class" in msg_lower:
        return "VU005"
    if "unused method" in msg_lower:
        return "VU006"
    if "unused property" in msg_lower:
        return "VU007"
    if "unreachable code" in msg_lower:
        return "VU008"
    return "VU000"


def run(target: Path) -> ToolResult:
    """Run vulture on *target* and return a standardised ToolResult.

    Vulture exit codes:
        0  – no dead code found
        1  – syntax error in the scanned source files
        2  – dead code found (some sources say 1; handle both 1 and 2)
        3  – dead code found AND there were some errors/warnings
        Any non-negative exit code that produces parseable stdout is treated
        as a successful run; only negative codes (timeout / not-found) or
        completely empty/unparseable output on a non-zero code are treated as
        errors.
    """
    if not check_tool_installed(TOOL):
        return ToolResult(
            tool=TOOL,
            category=CATEGORY,
            success=False,
            error="vulture is not installed or not on PATH",
        )

    args = [TOOL, str(target)]
    returncode, stdout, stderr = run_command(args)

    # Negative return codes mean the subprocess itself failed (timeout,
    # executable not found, etc.) — these are genuine infrastructure errors.
    if returncode < 0:
        error_msg = stderr.strip() or f"vulture exited with code {returncode}"
        return ToolResult(
            tool=TOOL,
            category=CATEGORY,
            success=False,
            error=error_msg,
            raw_output=stdout or None,
        )

    # For all non-negative exit codes (0, 1, 2, 3, …) attempt to parse
    # whatever vulture wrote to stdout.  Vulture uses non-zero codes to
    # signal "findings present" or minor issues, not tool failure.
    findings: list[Finding] = []
    raw_output = stdout

    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue

        match = _LINE_RE.match(line)
        if not match:
            continue

        file_path = match.group("file")
        line_no = int(match.group("line"))
        message = match.group("message")
        confidence = int(match.group("confidence"))

        severity = _map_severity(confidence)
        rule_id = _parse_rule_id(message)

        findings.append(
            Finding(
                file=file_path,
                line=line_no,
                rule_id=rule_id,
                message=f"{message} ({confidence}% confidence)",
                severity=severity,
                tool=TOOL,
                category=CATEGORY,
            )
        )

    return ToolResult(
        tool=TOOL,
        category=CATEGORY,
        success=True,
        findings=findings,
        raw_output=raw_output if raw_output.strip() else None,
    )