"""Shared subprocess utilities for tool wrappers.

Subprocess execution is core to running static-analysis CLI tools.
Command arguments are controlled by ReviewConfig / tool wrappers, not user input.
"""

# Copyright 2026 Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import subprocess  # nosec B404
import shutil


def check_tool_installed(command: str) -> bool:
    """Check if a CLI tool is available on PATH."""
    return shutil.which(command) is not None


def run_command(
    args: list[str],
    timeout: int = 300,
    cwd: str | None = None,
) -> tuple[int, str, str]:
    """Run a subprocess command and return (returncode, stdout, stderr).

    Many static analysis tools use non-zero exit codes to indicate findings
    (not errors), so callers should interpret return codes per tool.
    """
    try:
        result = subprocess.run(  # nosec B603  # nosemgrep: dangerous-subprocess-use-audit
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            shell=False,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"Command timed out after {timeout}s: {' '.join(args)}"
    except FileNotFoundError:
        return -1, "", f"Command not found: {args[0]}"
