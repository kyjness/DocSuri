"""Mypy type checker wrapper for AIDLC Code Reviewer.

Invokes mypy as a subprocess and parses its output into standardized
Finding objects. Mypy is categorized as a type_safety tool.
"""

# Copyright 2026 Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import re
from pathlib import Path

from code_reviewer.common.models import Finding, Severity, ToolResult
from code_reviewer.common.utils import check_tool_installed, run_command

TOOL = "mypy"
CATEGORY = "type_safety"
SUPPORTED_LANGUAGES = ["python"]

# Regex to parse mypy output lines of the form:
#   path/to/file.py:10: error: Some message  [rule-id]
#   path/to/file.py:10: warning: Some message  [rule-id]
#   path/to/file.py:10: note: Some message
# The rule/error-code in brackets is optional.
_LINE_RE = re.compile(
    r"^(?P<file>.+?):(?P<line>\d+):\s*(?P<severity>error|warning|note):\s*(?P<message>.+?)(?:\s+\[(?P<rule>[^\]]+)\])?\s*$"
)


def _map_severity(mypy_severity: str) -> Severity:
    """Map mypy native severity to the framework Severity enum.

    Per the Severity Classification Policy (section 2.3):
      error   -> MEDIUM
      warning -> LOW
      note    -> INFO
    """
    severity_lower = mypy_severity.lower()
    if severity_lower == "error":
        return Severity.MEDIUM
    if severity_lower == "warning":
        return Severity.LOW
    if severity_lower == "note":
        return Severity.INFO
    # Unknown values default to INFO (non-security, safe floor)
    return Severity.INFO


def _parse_output(stdout: str, tool: str, category: str) -> list[Finding]:
    """Parse mypy stdout into a list of Finding objects."""
    findings: list[Finding] = []

    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        match = _LINE_RE.match(line)
        if not match:
            continue

        file_path = match.group("file")
        line_number = int(match.group("line"))
        mypy_severity = match.group("severity")
        message = match.group("message").strip()
        rule_code = match.group("rule") or mypy_severity  # fall back to severity word

        severity = _map_severity(mypy_severity)

        findings.append(
            Finding(
                file=file_path,
                line=line_number,
                rule_id=rule_code,
                message=message,
                severity=severity,
                tool=tool,
                category=category,
            )
        )

    return findings


def run(target: Path) -> ToolResult:
    """Run mypy against *target* and return a standardized ToolResult.

    Args:
        target: A file or directory path to analyse.

    Returns:
        ToolResult with parsed findings, or success=False on any error.
    """
    if not check_tool_installed(TOOL):
        return ToolResult(
            tool=TOOL,
            category=CATEGORY,
            success=False,
            error=f"{TOOL} is not installed or not available on PATH.",
        )

    args = [
        TOOL,
        "--show-column-numbers",  # include column numbers when available
        "--no-error-summary",     # suppress the trailing error count line
        str(target),
    ]

    returncode, stdout, stderr = run_command(args)

    # mypy exits 0 (no errors), 1 (type errors found), or 2 (fatal/config error).
    # Exit codes 0 and 1 are both "successful runs"; only 2 signals a hard failure.
    if returncode == -1:
        # Timeout or FileNotFoundError from run_command
        return ToolResult(
            tool=TOOL,
            category=CATEGORY,
            success=False,
            error=stderr or "mypy invocation failed (timeout or missing binary).",
            raw_output=stdout or None,
        )

    if returncode == 2:
        # Fatal mypy error (bad config, missing stubs package requested, etc.)
        error_detail = stderr.strip() or stdout.strip() or "mypy exited with code 2 (fatal error)."
        return ToolResult(
            tool=TOOL,
            category=CATEGORY,
            success=False,
            error=error_detail,
            raw_output=stdout or None,
        )

    # returncode 0 or 1 — parse normally
    try:
        findings = _parse_output(stdout, TOOL, CATEGORY)
    except Exception as exc:  # pylint: disable=broad-except
        return ToolResult(
            tool=TOOL,
            category=CATEGORY,
            success=False,
            error=f"Failed to parse mypy output: {exc}",
            raw_output=stdout or None,
        )

    return ToolResult(
        tool=TOOL,
        category=CATEGORY,
        success=True,
        findings=findings,
        raw_output=stdout or None,
    )