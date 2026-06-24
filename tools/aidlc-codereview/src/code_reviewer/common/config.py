"""YAML config loader and validation for AIDLC Code Reviewer."""

# Copyright 2026 Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class ToolConfig:
    """Configuration for a single review tool.

    Only 'name' is required. The rest are optional — built-in wrappers
    already define their own CATEGORY/TOOL/SUPPORTED_LANGUAGES, and the
    agent infers them for generated wrappers.
    """

    name: str
    command: str = ""        # defaults to name
    category: str = ""       # read from wrapper module at runtime
    output_format: str = ""  # hint for agent, optional
    args: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.command:
            self.command = self.name


@dataclass
class ReviewConfig:
    """Top-level review configuration."""

    tools: list[ToolConfig]


# Path to the default config that ships with the package
from code_reviewer import CONFIG_DIR
_DEFAULT_CONFIG_PATH = CONFIG_DIR / "review-config.yaml"

VALID_CATEGORIES = {
    "security", "linting", "type_safety", "complexity", "duplication", "dead_code",
}


def load_config(config_path: Path | None = None) -> ReviewConfig:
    """Load and validate a review config from YAML.

    Config entries can be:
    - A string: just the tool name (e.g. "pylint")
    - A dict with 'name' required, everything else optional

    Args:
        config_path: Path to YAML config file. If None, uses the default
                     config that ships with the package.

    Returns:
        Validated ReviewConfig instance.

    Raises:
        FileNotFoundError: If the config file does not exist.
        ValueError: If the config is invalid.
    """
    path = config_path or _DEFAULT_CONFIG_PATH
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not isinstance(raw, dict) or "tools" not in raw:
        raise ValueError("Config must contain a 'tools' key with a list of tool definitions.")

    tools: list[ToolConfig] = []
    for i, entry in enumerate(raw["tools"]):
        # Simple string entry: just the tool name
        if isinstance(entry, str):
            tools.append(ToolConfig(name=entry))
            continue

        if not isinstance(entry, dict):
            raise ValueError(f"Tool entry {i} must be a string or a mapping.")

        if "name" not in entry:
            raise ValueError(f"Tool entry {i} missing required field: 'name'")

        name = str(entry["name"])
        command = str(entry.get("command", ""))
        category = str(entry.get("category", ""))
        output_format = str(entry.get("output_format", ""))

        if category and category not in VALID_CATEGORIES:
            raise ValueError(
                f"Tool '{name}': invalid category '{category}'. "
                f"Must be one of: {', '.join(sorted(VALID_CATEGORIES))}"
            )

        tools.append(ToolConfig(
            name=name,
            command=command or name,
            category=category,
            output_format=output_format,
            args=[str(a) for a in entry.get("args", [])],
        ))

    if not tools:
        raise ValueError("Config must define at least one tool.")

    return ReviewConfig(tools=tools)
