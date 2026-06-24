"""Extract Python code from LLM response (3-stage fallback)."""

# Copyright 2026 Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import re
from typing import Optional


def extract_code(response: str) -> tuple[Optional[str], Optional[str]]:
    """Extract Python wrapper code from LLM response.

    Returns (code, error). One of them is None.

    Stages:
    1. Extract from ```python ... ``` code block
    2. Heuristic: find region containing `def run(` and module-level constants
    3. Try entire response as Python via compile()
    4. Fallback: return error
    """
    # Stage 1: code block extraction
    pattern = r"```python\s*\n(.*?)```"
    matches = re.findall(pattern, response, re.DOTALL)
    if matches:
        # Pick the longest match (most likely the full wrapper)
        code = max(matches, key=len).strip()
        if "def run(" in code:
            return code, None

    # Stage 2: heuristic — find region with def run( and constants
    lines = response.split("\n")
    code_lines: list[str] = []
    in_code = False
    for line in lines:
        stripped = line.rstrip()
        # Start collecting at imports or module-level constants
        if not in_code and (
            stripped.startswith("import ")
            or stripped.startswith("from ")
            or stripped.startswith("CATEGORY")
            or stripped.startswith("TOOL")
            or stripped.startswith('"""')
        ):
            in_code = True
        if in_code:
            code_lines.append(line)

    if code_lines:
        candidate = "\n".join(code_lines).strip()
        if "def run(" in candidate:
            try:
                compile(candidate, "<heuristic>", "exec")
                return candidate, None
            except SyntaxError:
                pass

    # Stage 3: try entire response as Python
    try:
        compile(response.strip(), "<whole>", "exec")
        if "def run(" in response:
            return response.strip(), None
    except SyntaxError:
        pass

    return None, "Could not extract valid Python code from LLM response"
