"""Two-level verification pipeline for generated tool wrappers."""

# Copyright 2026 Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import importlib.util
import inspect
import sys
import tempfile
from pathlib import Path
from types import ModuleType
from typing import Optional

from code_reviewer.agent.models import VerificationResult
from code_reviewer.common.models import Finding, Severity, ToolResult
from code_reviewer.common.utils import check_tool_installed


def _load_module_from_source(source: str, module_name: str = "_generated_wrapper") -> tuple[Optional[ModuleType], Optional[str]]:
    """Write source to temp file, import it, return (module, error)."""
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", prefix=f"{module_name}_", delete=False
        ) as f:
            f.write(source)
            f.flush()
            tmp_path = f.name

        spec = importlib.util.spec_from_file_location(module_name, tmp_path)
        if spec is None or spec.loader is None:
            return None, "Could not create module spec from source"
        module = importlib.util.module_from_spec(spec)
        # Add project root to sys.path so common imports work
        project_root = str(Path(__file__).resolve().parent.parent.parent)
        if project_root not in sys.path:
            sys.path.insert(0, project_root)
        spec.loader.exec_module(module)
        return module, None
    except SyntaxError as e:
        return None, f"Syntax error: {e}"
    except Exception as e:
        return None, f"Import error: {e}"


_VALID_CATEGORIES = {
    "security", "linting", "type_safety", "complexity", "duplication", "dead_code",
}


def verify_level1(source: str, expected_category: str = "") -> VerificationResult:
    """Static verification — no tool CLI required.

    Checks: syntax, importability, run() signature, SUPPORTED_LANGUAGES,
    CATEGORY validity, TOOL constant, and return type from dry run.
    """
    errors: list[str] = []
    warnings: list[str] = []

    # 1. Syntax check
    try:
        compile(source, "<generated>", "exec")
    except SyntaxError as e:
        return VerificationResult(passed=False, level=1, errors=[f"Syntax error: {e}"])

    # 2. Import check
    module, import_err = _load_module_from_source(source)
    if module is None:
        return VerificationResult(passed=False, level=1, errors=[import_err or "Unknown import error"])

    # 3. Verify run() callable with target: Path parameter
    if not hasattr(module, "run") or not callable(module.run):
        errors.append("Module must define a callable 'run' function")
    else:
        sig = inspect.signature(module.run)
        params = list(sig.parameters.keys())
        if not params or params[0] != "target":
            errors.append("run() must accept 'target' as its first parameter")

    # 4. SUPPORTED_LANGUAGES
    if not hasattr(module, "SUPPORTED_LANGUAGES"):
        errors.append("Module must define SUPPORTED_LANGUAGES list")
    elif not isinstance(module.SUPPORTED_LANGUAGES, list):
        errors.append("SUPPORTED_LANGUAGES must be a list")
    elif not all(isinstance(s, str) for s in module.SUPPORTED_LANGUAGES):
        errors.append("SUPPORTED_LANGUAGES must contain only strings")

    # 5. CATEGORY — must exist and be a valid category
    if not hasattr(module, "CATEGORY"):
        errors.append("Module must define a CATEGORY string constant")
    elif module.CATEGORY not in _VALID_CATEGORIES:
        errors.append(
            f"CATEGORY '{module.CATEGORY}' is not valid. "
            f"Must be one of: {', '.join(sorted(_VALID_CATEGORIES))}"
        )
    elif expected_category and module.CATEGORY != expected_category:
        # If the user explicitly set a category in config, warn on mismatch
        warnings.append(
            f"CATEGORY '{module.CATEGORY}' differs from config hint '{expected_category}'"
        )

    # 6. TOOL or TOOL_NAME constant
    if not (hasattr(module, "TOOL") or hasattr(module, "TOOL_NAME")):
        errors.append("Module must define a TOOL or TOOL_NAME string constant")

    if errors:
        return VerificationResult(passed=False, level=1, errors=errors, warnings=warnings)

    # 7. Dry run with nonexistent path — must return ToolResult
    try:
        result = module.run(Path(tempfile.gettempdir()) / "_nonexistent_verification_target")
        if not isinstance(result, ToolResult):
            errors.append(
                f"run() must return a ToolResult, got {type(result).__name__}"
            )
    except Exception as e:
        warnings.append(f"Dry run raised exception (acceptable): {e}")

    passed = len(errors) == 0
    return VerificationResult(passed=passed, level=1, errors=errors, warnings=warnings)


def verify_level2(
    source: str,
    tool_command: str,
    target: Path,
) -> tuple[VerificationResult, Optional[ToolResult]]:
    """Live verification — requires the tool CLI to be installed.

    Runs the wrapper against a real target and validates output.

    Returns (VerificationResult, ToolResult or None). The ToolResult is
    returned so the caller can reuse it instead of running the tool twice.
    """
    errors: list[str] = []
    warnings: list[str] = []

    # Prerequisite: tool must be installed
    if not check_tool_installed(tool_command):
        return VerificationResult(
            passed=False, level=2,
            errors=[f"Tool '{tool_command}' not installed, skipping Level 2"],
        ), None

    module, import_err = _load_module_from_source(source)
    if module is None:
        return VerificationResult(passed=False, level=2, errors=[import_err or "Import failed"]), None

    try:
        result = module.run(target)
    except Exception as e:
        return VerificationResult(
            passed=False, level=2,
            errors=[f"run() raised exception: {e}"],
        ), None

    if not isinstance(result, ToolResult):
        return VerificationResult(
            passed=False, level=2,
            errors=[f"run() returned {type(result).__name__}, expected ToolResult"],
        ), None

    if not result.success:
        errors.append(f"Tool returned success=False: {result.error}")

    for i, finding in enumerate(result.findings):
        if not isinstance(finding, Finding):
            errors.append(f"Finding {i} is {type(finding).__name__}, expected Finding")
            continue
        if not isinstance(finding.severity, Severity):
            errors.append(f"Finding {i} severity is not a valid Severity enum")

    passed = len(errors) == 0
    return VerificationResult(passed=passed, level=2, errors=errors, warnings=warnings), result
