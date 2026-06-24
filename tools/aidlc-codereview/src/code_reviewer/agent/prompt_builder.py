"""Builds the generation prompt by assembling context into the template."""

# Copyright 2026 Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

from pathlib import Path

from code_reviewer.common.config import ToolConfig
from code_reviewer import CONFIG_DIR

_SRC_ROOT = Path(__file__).resolve().parent.parent
_TEMPLATE_PATH = CONFIG_DIR / "prompts" / "wrapper-generator-v1.md"

# Few-shot example wrappers (JSON, XML, text output formats)
_EXAMPLE_WRAPPERS = {
    "bandit (JSON)": _SRC_ROOT / "tools" / "bandit.py",
    "checkstyle (XML)": _SRC_ROOT / "tools" / "checkstyle.py",
    "vulture (text)": _SRC_ROOT / "tools" / "vulture.py",
}


def _read_file(path: Path) -> str:
    """Read file contents, return empty string if missing."""
    try:
        return path.read_text()
    except Exception:
        return ""


def _load_template() -> str:
    return _read_file(_TEMPLATE_PATH)


def _build_examples_section() -> str:
    """Load few-shot wrapper examples."""
    parts = []
    for label, path in _EXAMPLE_WRAPPERS.items():
        source = _read_file(path)
        if source:
            parts.append(f"### Example: {label}\n```python\n{source}\n```")
    return "\n\n".join(parts)


def build_prompt(tool_config: ToolConfig, doc_text: str = "") -> str:
    """Build the full generation prompt for the LLM.

    Uses the markdown template with INSERT markers, falling back to
    inline prompt construction if the template is missing.
    """
    models_source = _read_file(_SRC_ROOT / "common" / "models.py")
    utils_source = _read_file(_SRC_ROOT / "common" / "utils.py")
    severity_mapping = _read_file(_SRC_ROOT / "common" / "SEVERITY_MAPPING.md")
    examples = _build_examples_section()

    tool_info = f"- **Name**: {tool_config.name}\n"
    if tool_config.command and tool_config.command != tool_config.name:
        tool_info += f"- **Command**: {tool_config.command}\n"
    if tool_config.category:
        tool_info += f"- **Category**: {tool_config.category}\n"
    else:
        tool_info += (
            "- **Category**: Determine the correct category from: "
            "security, linting, type_safety, complexity, duplication, dead_code\n"
        )
    if tool_config.output_format:
        tool_info += f"- **Output format**: {tool_config.output_format}\n"
    if tool_config.args:
        tool_info += f"- **Args template**: {' '.join(tool_config.args)}\n"

    template = _load_template()

    if template and "<!-- INSERT:" in template:
        # Replace markers in template
        replacements = {
            "<!-- INSERT: models.py -->": f"```python\n{models_source}\n```",
            "<!-- INSERT: utils.py -->": f"```python\n{utils_source}\n```",
            "<!-- INSERT: SEVERITY_MAPPING.md -->": severity_mapping,
            "<!-- INSERT: examples -->": examples,
            "<!-- INSERT: tool_info -->": tool_info,
            "<!-- INSERT: doc_text -->": doc_text if doc_text else "_No documentation available._",
        }
        result = template
        for marker, content in replacements.items():
            result = result.replace(marker, content)
        return result

    # Fallback: build prompt inline
    return f"""You are an expert Python developer generating a tool wrapper module for the AIDLC Code Reviewer.

## Your Task

Generate a Python module that wraps the CLI tool described below. The module must follow the exact patterns shown in the examples.

## Data Models (common/models.py)

```python
{models_source}
```

## Utility Functions (common/utils.py)

```python
{utils_source}
```

## Severity Classification Policy

{severity_mapping}

## Example Wrappers

{examples}

## Tool to Wrap

{tool_info}

## Tool Documentation

{doc_text if doc_text else "_No documentation available._"}

## Output Requirements

1. Generate a COMPLETE Python module (not a snippet)
2. Must define: CATEGORY, TOOL or TOOL_NAME, SUPPORTED_LANGUAGES
3. Must define: `def run(target: Path) -> ToolResult`
4. Import from `code_reviewer.common.models` (Finding, Severity, ToolResult) and `code_reviewer.common.utils` (run_command, check_tool_installed)
5. Follow the severity mapping policy strictly — non-security categories cap at MEDIUM
6. Handle tool not installed, parse errors, and empty output gracefully
7. Return ToolResult with success=False and descriptive error on failure
8. Parse the tool's output format ({tool_config.output_format or 'json'}) to extract findings
9. Wrap the response in ```python ... ``` code block

## CRITICAL Rules

- Never import the tool as a Python module. Always invoke via subprocess using run_command().
- Only use CLI flags you are 100% certain exist. Use the bare minimum: output format flag and target path. Do NOT guess or invent flags.
- Keep the CLI invocation simple. For example, for pylint: ["pylint", "--output-format=json", str(target)] — nothing more.
"""
