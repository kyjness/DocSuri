"""Bandit wrapper for AIDLC Code Reviewer.

Bandit is a security-focused static analysis tool for Python that finds
common security issues in Python code.
"""

# Copyright 2026 Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import json
import logging
from pathlib import Path

from code_reviewer.common.models import Finding, Severity, ToolResult
from code_reviewer.common.utils import check_tool_installed, run_command

logger = logging.getLogger(__name__)

TOOL = "bandit"
TOOL_NAME = "bandit"
CATEGORY = "security"
SUPPORTED_LANGUAGES = ["python"]


def _map_severity(native_severity: str) -> Severity:
    """Map Bandit native severity string to standardized Severity.

    Bandit is a security tool so HIGH is permitted.

    Mapping:
      HIGH   -> HIGH
      MEDIUM -> MEDIUM
      LOW    -> LOW
      other  -> INFO
    """
    mapping: dict[str, Severity] = {
        "HIGH": Severity.HIGH,
        "MEDIUM": Severity.MEDIUM,
        "LOW": Severity.LOW,
    }
    return mapping.get(native_severity.upper(), Severity.INFO)


def _extract_json_source(stdout: str, stderr: str) -> str:
    """Return whichever of stdout/stderr contains a parseable JSON object.

    Some versions of bandit write JSON to stdout; older versions (or certain
    invocations) may write it to stderr.  We try stdout first, then stderr.
    Returns an empty string if neither contains valid JSON.
    """
    for candidate in (stdout, stderr):
        candidate = candidate.strip()
        if candidate and candidate.startswith("{"):
            return candidate
    return ""


def _parse_findings(data: dict) -> list[Finding]:
    """Parse Bandit JSON output dict into a list of Finding objects."""
    findings: list[Finding] = []

    results = data.get("results", [])
    for item in results:
        try:
            filename: str = item.get("filename", "")
            line_number: int = int(item.get("line_number", 0))
            col_offset = item.get("col_offset")
            test_id: str = item.get("test_id", "UNKNOWN")
            test_name: str = item.get("test_name", "")
            issue_text: str = item.get("issue_text", "")
            issue_severity: str = item.get("issue_severity", "")

            # Build a descriptive message combining test name and issue text.
            if test_name and issue_text:
                message = f"{test_name}: {issue_text}"
            elif test_name:
                message = test_name
            else:
                message = issue_text or "No message provided"

            finding = Finding(
                file=filename,
                line=line_number,
                rule_id=test_id,
                message=message,
                severity=_map_severity(issue_severity),
                tool=TOOL_NAME,
                category=CATEGORY,
                column=col_offset,
            )
            findings.append(finding)
        except (KeyError, ValueError, TypeError) as exc:
            logger.debug(
                "Skipping malformed bandit result item: %s — %s", item, exc
            )
            continue

    return findings


def run(target: Path) -> ToolResult:
    """Run Bandit against the target path and return a standardized ToolResult.

    Args:
        target: Path to the Python file or directory to analyse.

    Returns:
        ToolResult with findings populated on success, or error set on failure.
    """
    if not check_tool_installed(TOOL_NAME):
        return ToolResult(
            tool=TOOL_NAME,
            category=CATEGORY,
            success=False,
            error=f"{TOOL_NAME} is not installed or not on PATH.",
        )

    if not target.exists():
        return ToolResult(
            tool=TOOL_NAME,
            category=CATEGORY,
            success=False,
            error=f"Target path does not exist: {target}",
        )

    # Build the command.  Only add -r for directories; omit it for files.
    args: list[str] = [TOOL_NAME, "-f", "json"]
    if target.is_dir():
        args.append("-r")
    args.append(str(target))

    returncode, stdout, stderr = run_command(args)

    # Bandit exit codes:
    #   0  — completed, no issues found
    #   1  — completed, issues found
    #   2  — usage / configuration error
    #  -1  — timeout or binary not found (set by run_command)
    if returncode == -1:
        return ToolResult(
            tool=TOOL_NAME,
            category=CATEGORY,
            success=False,
            error=stderr or "bandit command failed (timeout or not found).",
            raw_output=stdout or None,
        )

    if returncode == 2:
        return ToolResult(
            tool=TOOL_NAME,
            category=CATEGORY,
            success=False,
            error=(
                f"bandit exited with a configuration error (code 2): {stderr}"
            ).strip(),
            raw_output=stdout or None,
        )

    # Determine which stream holds the JSON output.
    json_source = _extract_json_source(stdout, stderr)

    # Preserve raw output for diagnostics (prefer stdout, fall back to stderr).
    raw_output = stdout if stdout.strip() else stderr

    if not json_source:
        # Bandit produced no parseable output — treat as success with no findings.
        # This can happen when the target contains no Python files.
        logger.debug(
            "bandit produced no JSON output (stdout=%r, stderr=%r).", stdout, stderr
        )
        return ToolResult(
            tool=TOOL_NAME,
            category=CATEGORY,
            success=True,
            findings=[],
            raw_output=raw_output or None,
        )

    try:
        data = json.loads(json_source)
    except json.JSONDecodeError as exc:
        return ToolResult(
            tool=TOOL_NAME,
            category=CATEGORY,
            success=False,
            error=f"Failed to parse bandit JSON output: {exc}",
            raw_output=raw_output or None,
        )

    try:
        findings = _parse_findings(data)
    except Exception as exc:  # pylint: disable=broad-except
        logger.exception("Unexpected error while parsing bandit findings.")
        return ToolResult(
            tool=TOOL_NAME,
            category=CATEGORY,
            success=False,
            error=f"Unexpected error while parsing bandit findings: {exc}",
            raw_output=raw_output or None,
        )

    return ToolResult(
        tool=TOOL_NAME,
        category=CATEGORY,
        success=True,
        findings=findings,
        raw_output=raw_output or None,
    )