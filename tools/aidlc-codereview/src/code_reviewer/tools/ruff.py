"""Ruff linting wrapper for the AIDLC Code Reviewer static analysis framework."""

# Copyright 2026 Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import json
import logging
from pathlib import Path

from code_reviewer.common.models import Finding, Severity, ToolResult
from code_reviewer.common.utils import check_tool_installed, run_command

logger = logging.getLogger(__name__)

TOOL = "ruff"
TOOL_NAME = "ruff"
CATEGORY = "linting"
SUPPORTED_LANGUAGES = ["python"]


def _map_severity(rule_id: str) -> Severity:
    """Map a Ruff rule code to a Severity level.

    Per the severity policy:
      - E (pycodestyle errors) and F (pyflakes errors) -> MEDIUM
      - W (warnings), I (import sorting), N (naming) -> LOW
      - All other prefixes -> LOW
    Non-security categories are capped at MEDIUM.
    """
    if not rule_id:
        return Severity.LOW

    prefix = rule_id[0].upper()
    if prefix in ("E", "F"):
        return Severity.MEDIUM
    return Severity.LOW


def run(target: Path) -> ToolResult:
    """Run ruff against the target path and return a ToolResult.

    Args:
        target: Path to the file or directory to analyse.

    Returns:
        ToolResult with findings parsed from ruff's JSON output.
    """
    if not check_tool_installed(TOOL):
        return ToolResult(
            tool=TOOL_NAME,
            category=CATEGORY,
            success=False,
            error=f"{TOOL_NAME} is not installed or not on PATH.",
        )

    args = [
        TOOL,
        "check",
        "--output-format=json",
        str(target),
    ]

    returncode, stdout, stderr = run_command(args)

    # ruff exits with 0 (no findings), 1 (findings found), or other non-zero
    # values for genuine errors.  We treat returncode -1 as a hard failure.
    if returncode == -1:
        return ToolResult(
            tool=TOOL_NAME,
            category=CATEGORY,
            success=False,
            error=stderr or "ruff command failed (timeout or not found).",
            raw_output=stdout or None,
        )

    raw_output = stdout or stderr

    if not stdout.strip():
        # No output — either no findings or a configuration/runtime error.
        if returncode not in (0, 1):
            return ToolResult(
                tool=TOOL_NAME,
                category=CATEGORY,
                success=False,
                error=stderr or f"ruff exited with code {returncode} and produced no output.",
                raw_output=raw_output or None,
            )
        # Clean run with no findings.
        return ToolResult(
            tool=TOOL_NAME,
            category=CATEGORY,
            success=True,
            findings=[],
            raw_output=raw_output or None,
        )

    # Parse JSON output.
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        return ToolResult(
            tool=TOOL_NAME,
            category=CATEGORY,
            success=False,
            error=f"Failed to parse ruff JSON output: {exc}",
            raw_output=raw_output,
        )

    findings: list[Finding] = []

    for item in data:
        try:
            rule_id: str = item.get("code") or item.get("rule_id") or ""
            message: str = item.get("message", "")
            filename: str = item.get("filename", "")

            location = item.get("location") or {}
            end_location = item.get("end_location") or {}

            line: int = int(location.get("row", 1))
            column: int | None = int(location.get("column", 1)) if location.get("column") is not None else None
            end_line: int | None = int(end_location.get("row")) if end_location.get("row") is not None else None
            end_column: int | None = int(end_location.get("column")) if end_location.get("column") is not None else None

            severity = _map_severity(rule_id)

            finding = Finding(
                file=filename,
                line=line,
                column=column,
                end_line=end_line,
                end_column=end_column,
                rule_id=rule_id or "ruff/unknown",
                message=message,
                severity=severity,
                tool=TOOL_NAME,
                category=CATEGORY,
            )
            findings.append(finding)

        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("Skipping ruff finding due to parse error: %s — item: %s", exc, item)
            continue

    return ToolResult(
        tool=TOOL_NAME,
        category=CATEGORY,
        success=True,
        findings=findings,
        raw_output=raw_output,
    )