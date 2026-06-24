"""Shared data models for AIDLC Code Reviewer."""

# Copyright 2026 Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"
    INFO = "INFO"


@dataclass
class Finding:
    """A single issue found by a tool."""

    file: str
    line: int
    rule_id: str
    message: str
    severity: Severity
    tool: str
    category: str  # maps to rubric category
    column: Optional[int] = None
    end_line: Optional[int] = None
    end_column: Optional[int] = None


@dataclass
class DuplicationBlock:
    """A pair of duplicated code blocks."""

    source_file: str
    source_start_line: int
    source_end_line: int
    target_file: str
    target_start_line: int
    target_end_line: int
    lines: int
    tokens: int


@dataclass
class ToolResult:
    """Standardized output from any tool wrapper."""

    tool: str
    category: str
    success: bool
    findings: list[Finding] = field(default_factory=list)
    duplications: list[DuplicationBlock] = field(default_factory=list)
    error: Optional[str] = None
    raw_output: Optional[str] = None


@dataclass
class SkipRecord:
    """Record of a tool that was skipped (no wrapper, not installed, or errored)."""

    tool: str
    category: str
    reason: str


class CriticalCategory(str, Enum):
    """Categories of critical code that require human review (technical focus)."""

    COMPUTATION = "COMPUTATION"
    CONTROL_FLOW = "CONTROL_FLOW"
    DATA_TRANSFORM = "DATA_TRANSFORM"


@dataclass
class CriticalFinding:
    """A critical code section flagged for human review.

    Designed for scanability: category tag, location, one-line verdict,
    the actual code block, and any related tool errors.
    """

    category: CriticalCategory
    file: str
    start_line: int
    end_line: int
    verdict: str  # one-line human-readable summary
    code_block: str  # the actual source code
    why_critical: str  # brief reason this needs human eyes
    recommended_action: str = ""  # one-line actionable fix suggestion
    source: str = "agent_only"  # "agent_only" or "tool_assisted"
    related_tool_findings: list[Finding] = field(default_factory=list)
    highlight_lines: list[int] = field(default_factory=list)  # specific problematic lines (absolute)


class StructureRating(str, Enum):
    """Rating for a code structure dimension."""

    GOOD = "GOOD"
    NEEDS_IMPROVEMENT = "NEEDS_IMPROVEMENT"
    POOR = "POOR"


@dataclass
class StructureDimension:
    """Assessment of one code quality dimension (e.g. logging, scalability)."""

    dimension: str  # e.g. "logging", "scalability", "efficiency"
    rating: StructureRating
    summary: str  # one-line assessment
    findings: list["StructureIssue"] = field(default_factory=list)


@dataclass
class StructureIssue:
    """A specific actionable issue within a structure dimension."""

    file: str
    start_line: int
    end_line: int
    issue: str  # one-line description of the problem
    recommendation: str  # one-line actionable fix
    code_block: str = ""  # the relevant source code
    source: str = "agent_only"  # "agent_only" or "tool_assisted"
    related_tool_findings: list[Finding] = field(default_factory=list)
    highlight_lines: list[int] = field(default_factory=list)  # specific problematic lines (absolute)


@dataclass
class CodeStructureCritique:
    """Full AI-powered code structure critique (Section 2 of the report)."""

    overall_summary: str  # 2-3 sentence high-level assessment
    dimensions: list[StructureDimension] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Business Logic Review models
# ---------------------------------------------------------------------------


class BusinessLogicCategory(str, Enum):
    """Categories of business logic detected in code."""

    FINANCIAL_FORMULA = "FINANCIAL_FORMULA"
    SCORING_AND_RANKING = "SCORING_AND_RANKING"
    PRICING_AND_DISCOUNT = "PRICING_AND_DISCOUNT"
    BUSINESS_RULE = "BUSINESS_RULE"
    STATE_MACHINE = "STATE_MACHINE"
    ROUNDING_AND_PRECISION = "ROUNDING_AND_PRECISION"
    BOUNDARY_CONDITION = "BOUNDARY_CONDITION"
    DATA_MAPPING = "DATA_MAPPING"
    TEMPORAL_LOGIC = "TEMPORAL_LOGIC"
    RECONCILIATION = "RECONCILIATION"


class ConsistencyIssueType(str, Enum):
    """Types of self-consistency issues across business logic."""

    CONSTANT_DRIFT = "CONSTANT_DRIFT"
    LOGIC_DIVERGENCE = "LOGIC_DIVERGENCE"
    NAMING_MISMATCH = "NAMING_MISMATCH"
    REDUNDANT_IMPLEMENTATION = "REDUNDANT_IMPLEMENTATION"


@dataclass
class BusinessLogicFinding:
    """A business logic section flagged for human review."""

    category: BusinessLogicCategory
    title: str  # short, meaningful name (e.g. "Tax Rate Calculation")
    file: str
    start_line: int
    end_line: int
    what_it_does: str  # plain-English description a PM can understand
    review_guidance: str  # what specifically the human should verify
    code_block: str  # exact source lines
    risk_if_wrong: str  # business impact if this code has a bug


@dataclass
class ConsistencyIssueLocation:
    """A location involved in a consistency issue."""

    file: str
    start_line: int
    end_line: int


@dataclass
class ConsistencyIssue:
    """A self-consistency issue between business logic sections."""

    issue_type: ConsistencyIssueType
    description: str
    locations: list[ConsistencyIssueLocation] = field(default_factory=list)
    code_blocks: list[str] = field(default_factory=list)
    recommended_action: str = ""


@dataclass
class BusinessLogicReview:
    """Full business logic review result (separate report)."""

    executive_summary: str = ""  # 2-3 sentence high-level assessment
    findings: list[BusinessLogicFinding] = field(default_factory=list)
    consistency_issues: list[ConsistencyIssue] = field(default_factory=list)
