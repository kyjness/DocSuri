"""Data models for the wrapper generator agent."""

# Copyright 2026 Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from code_reviewer.common.models import ToolResult


class GenerationStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"


@dataclass
class VerificationResult:
    """Result of wrapper verification."""

    passed: bool
    level: int  # 1 = static, 2 = live
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class GenerationResult:
    """Result of wrapper generation."""

    status: GenerationStatus
    tool_name: str
    wrapper_path: Optional[Path] = None
    verification: Optional[VerificationResult] = None
    error: Optional[str] = None
    token_usage: Optional[dict] = None
    tool_result: Optional[ToolResult] = None  # reusable result from Level 2
