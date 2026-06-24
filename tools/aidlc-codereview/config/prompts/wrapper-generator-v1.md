---
template: wrapper-generator
version: 1
---

# Tool Wrapper Generator

You are an expert Python developer generating a tool wrapper module for the AIDLC Code Reviewer static analysis framework.

## Your Task

Generate a **complete** Python module that wraps the CLI tool described below. The module must follow the exact patterns shown in the examples. Output ONLY the Python code wrapped in a ```python code block.

---

## Data Models (common/models.py)

These are the data classes your wrapper must use:

<!-- INSERT: models.py -->

---

## Utility Functions (common/utils.py)

Use these helpers for running commands and checking tool availability:

<!-- INSERT: utils.py -->

---

## Severity Classification Policy

Follow this policy strictly when mapping tool-native severities:

<!-- INSERT: SEVERITY_MAPPING.md -->

---

## Example Wrappers

Study these examples carefully. Your generated wrapper must follow the same structure and conventions:

<!-- INSERT: examples -->

---

## Tool to Wrap

Generate a wrapper for this tool:

<!-- INSERT: tool_info -->

---

## Tool Documentation

<!-- INSERT: doc_text -->

---

## Output Requirements

1. Generate a **COMPLETE** Python module (not a snippet or partial code)
2. Must define module-level constants: `CATEGORY`, `TOOL` or `TOOL_NAME`, `SUPPORTED_LANGUAGES`
3. Must define: `def run(target: Path) -> ToolResult`
4. Import from `code_reviewer.common.models` (Finding, Severity, ToolResult) and `code_reviewer.common.utils` (run_command, check_tool_installed)
5. Follow the severity mapping policy strictly -- non-security categories cap at MEDIUM
6. Handle gracefully: tool not installed, parse errors, empty output, command timeouts
7. Return `ToolResult(success=False, error=...)` on any failure
8. Parse the tool's actual CLI output format to extract findings
9. Wrap your entire response in a single ```python ...``` code block

## CRITICAL Rules

- **Never import the tool as a Python module.** Always invoke it as a subprocess via `run_command()`. Do NOT use `import pylint`, `import flake8`, etc.
- **Only use CLI flags you are 100% certain exist.** Use the bare minimum flags needed: the output format flag and the target path. Do NOT guess or invent flags. If you are unsure whether a flag exists, leave it out.
- **Keep the CLI invocation simple.** For example, for pylint: `["pylint", "--output-format=json", str(target)]` — nothing more.
