"""Tool registry — maps tool names to their wrapper modules.

The registry provides a lookup from config tool names to the Python modules
that implement the `run(target: Path) -> ToolResult` interface.

Wrappers are discovered dynamically from tools/<name>.py files on disk.
No hardcoded imports — the agent generates wrappers as needed.
"""

# Copyright 2026 Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

from __future__ import annotations

import importlib.util
import sys
import threading
from pathlib import Path
from types import ModuleType

TOOL_REGISTRY: dict[str, ModuleType] = {}

_TOOLS_DIR = Path(__file__).resolve().parent
_registry_lock = threading.Lock()


def _try_load_from_disk(tool_name: str) -> ModuleType | None:
    """Try to load a wrapper from tools/<name>.py."""
    safe_name = tool_name.replace("-", "_").replace(" ", "_")
    wrapper_path = _TOOLS_DIR / f"{safe_name}.py"
    if not wrapper_path.exists():
        return None
    try:
        module_name = f"tools.{safe_name}"
        spec = importlib.util.spec_from_file_location(module_name, str(wrapper_path))
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        project_root = str(_TOOLS_DIR.parent.parent)
        if project_root not in sys.path:
            sys.path.insert(0, project_root)
        spec.loader.exec_module(module)
        TOOL_REGISTRY[tool_name] = module
        return module
    except Exception:
        return None


def get_wrapper(tool_name: str) -> ModuleType | None:
    """Look up a tool wrapper module by name.

    Checks the in-memory registry first, then looks for a wrapper file
    on disk (tools/<name>.py).
    """
    with _registry_lock:
        wrapper = TOOL_REGISTRY.get(tool_name)
        if wrapper is not None:
            return wrapper
        return _try_load_from_disk(tool_name)


def get_supported_languages(tool_name: str) -> list[str]:
    """Return the supported languages for a tool by reading its SUPPORTED_LANGUAGES.

    Falls back to ["*"] if the wrapper doesn't declare SUPPORTED_LANGUAGES.
    """
    with _registry_lock:
        wrapper = TOOL_REGISTRY.get(tool_name)
    if wrapper and hasattr(wrapper, "SUPPORTED_LANGUAGES"):
        return wrapper.SUPPORTED_LANGUAGES
    return ["*"]


def register_wrapper(tool_name: str, module: ModuleType) -> None:
    """Register a dynamically generated wrapper module."""
    with _registry_lock:
        TOOL_REGISTRY[tool_name] = module


def is_registered(tool_name: str) -> bool:
    """Check if a tool has a registered wrapper."""
    with _registry_lock:
        return tool_name in TOOL_REGISTRY
