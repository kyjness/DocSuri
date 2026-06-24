"""Unified report generator for Markdown and HTML output.

Follows the AIDLC Code Reviewer rubric report structure:
  0. Executive Summary
  1. Critical Code Findings (top of report)
  2. Code Structure Critique (AI-powered)
  3. Code Quality Analysis (3.1-3.8)
  4. Appendix
"""

# Copyright 2026 Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

from __future__ import annotations

import html as html_lib
from pathlib import Path

from code_reviewer.common.models import (
    BusinessLogicCategory,
    BusinessLogicFinding,
    BusinessLogicReview,
    CodeStructureCritique,
    ConsistencyIssue,
    ConsistencyIssueType,
    CriticalCategory,
    CriticalFinding,
    DuplicationBlock,
    Finding,
    Severity,
    SkipRecord,
    StructureRating,
    ToolResult,
)

SEV_ORDER = [Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW, Severity.INFO]

CRITICAL_CATEGORY_LABELS = {
    CriticalCategory.COMPUTATION: "COMPUTATION",
    CriticalCategory.CONTROL_FLOW: "CONTROL_FLOW",
    CriticalCategory.DATA_TRANSFORM: "DATA_TRANSFORM",
}

CRITICAL_CATEGORY_ICONS = {
    CriticalCategory.COMPUTATION: "🔢",
    CriticalCategory.CONTROL_FLOW: "🔀",
    CriticalCategory.DATA_TRANSFORM: "🔄",
}

DIMENSION_ICONS = {
    "LOGGING": "📋",
    "MEASURABILITY": "📊",
    "SCALABILITY": "📈",
    "EFFICIENCY": "⚡",
    "COMPLEXITY": "🧩",
    "STRUCTURE": "🏗️",
}

RATING_LABELS = {
    StructureRating.GOOD: ("Good", "good"),
    StructureRating.NEEDS_IMPROVEMENT: ("Needs Improvement", "attention"),
    StructureRating.POOR: ("Poor", "critical"),
}

CATEGORY_LABELS = {
    "security": "Security",
    "linting": "Linting / Style Conformance",
    "type_safety": "Type Safety",
    "complexity": "Complexity",
    "duplication": "Code Duplication",
    "dead_code": "Dead Code",
}

# Which rubric section number each category maps to
CATEGORY_NUMBERS = {
    "security": "3.1",
    "linting": "3.3",
    "type_safety": "3.4",
    "complexity": "3.5",
    "duplication": "3.6",
    "dead_code": "3.7",
}

BUSINESS_LOGIC_CATEGORY_LABELS = {
    BusinessLogicCategory.FINANCIAL_FORMULA: "Financial Formula",
    BusinessLogicCategory.SCORING_AND_RANKING: "Scoring & Ranking",
    BusinessLogicCategory.PRICING_AND_DISCOUNT: "Pricing & Discount",
    BusinessLogicCategory.BUSINESS_RULE: "Business Rule",
    BusinessLogicCategory.STATE_MACHINE: "State Machine",
    BusinessLogicCategory.ROUNDING_AND_PRECISION: "Rounding & Precision",
    BusinessLogicCategory.BOUNDARY_CONDITION: "Boundary Condition",
    BusinessLogicCategory.DATA_MAPPING: "Data Mapping",
    BusinessLogicCategory.TEMPORAL_LOGIC: "Temporal Logic",
    BusinessLogicCategory.RECONCILIATION: "Reconciliation",
}

BUSINESS_LOGIC_CATEGORY_ICONS = {
    BusinessLogicCategory.FINANCIAL_FORMULA: "💰",
    BusinessLogicCategory.SCORING_AND_RANKING: "📊",
    BusinessLogicCategory.PRICING_AND_DISCOUNT: "🏷️",
    BusinessLogicCategory.BUSINESS_RULE: "📋",
    BusinessLogicCategory.STATE_MACHINE: "🔄",
    BusinessLogicCategory.ROUNDING_AND_PRECISION: "🔢",
    BusinessLogicCategory.BOUNDARY_CONDITION: "🚧",
    BusinessLogicCategory.DATA_MAPPING: "🗺️",
    BusinessLogicCategory.TEMPORAL_LOGIC: "⏰",
    BusinessLogicCategory.RECONCILIATION: "⚖️",
}

CONSISTENCY_ISSUE_LABELS = {
    ConsistencyIssueType.CONSTANT_DRIFT: "Constant Drift",
    ConsistencyIssueType.LOGIC_DIVERGENCE: "Logic Divergence",
    ConsistencyIssueType.NAMING_MISMATCH: "Naming Mismatch",
    ConsistencyIssueType.REDUNDANT_IMPLEMENTATION: "Redundant Implementation",
}

CONSISTENCY_ISSUE_ICONS = {
    ConsistencyIssueType.CONSTANT_DRIFT: "📌",
    ConsistencyIssueType.LOGIC_DIVERGENCE: "🔀",
    ConsistencyIssueType.NAMING_MISMATCH: "🏷️",
    ConsistencyIssueType.REDUNDANT_IMPLEMENTATION: "♻️",
}

# Tools that map to the secrets sub-section (3.2)
SECRETS_TOOLS = {"gitleaks"}


def _render_code_block_md(code_block: str, start_line: int, highlight_lines: list[int]) -> list[str]:
    """Render a code block in markdown with highlighted lines marked with '>>>'."""
    lines: list[str] = []
    highlight_set = set(highlight_lines)
    code_lines = code_block.split("\n")
    lines.append("```")
    for i, code_line in enumerate(code_lines):
        line_num = start_line + i
        if highlight_set and line_num in highlight_set:
            lines.append(f">>> {code_line}")
        else:
            lines.append(f"    {code_line}")
    lines.append("```")
    return lines


def _count_by_severity(findings: list[Finding]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for f in findings:
        counts[f.severity.value] = counts.get(f.severity.value, 0) + 1
    return counts


def _severity_sort_key(f: Finding) -> int:
    order = {Severity.CRITICAL: 0, Severity.HIGH: 1, Severity.MEDIUM: 2, Severity.LOW: 3, Severity.INFO: 4}
    return order.get(f.severity, 5)


def _overall_verdict(findings: list[Finding]) -> str:
    by_sev = _count_by_severity(findings)
    crit = by_sev.get("CRITICAL", 0)
    high = by_sev.get("HIGH", 0)
    med = by_sev.get("MEDIUM", 0)
    if crit > 0 or high >= 5:
        return "Critical"
    if high > 0 or med >= 10:
        return "Needs Attention"
    return "Good"


def _action_summary(
    by_sev: dict[str, int],
    verdict: str,
    critical_findings: list[CriticalFinding] | None,
    all_findings: list[Finding],
) -> str:
    """Build a short, action-oriented summary telling the reader what to do."""
    parts: list[str] = []
    crit = by_sev.get("CRITICAL", 0)
    high = by_sev.get("HIGH", 0)
    med = by_sev.get("MEDIUM", 0)
    low = by_sev.get("LOW", 0) + by_sev.get("INFO", 0)
    n_critical_sections = len(critical_findings) if critical_findings else 0

    if verdict == "Good":
        parts.append("No urgent issues found.")
        if med:
            parts.append(f"Review {med} medium-severity findings when convenient.")
        return " ".join(parts)

    # Urgent items
    urgent: list[str] = []
    if crit:
        urgent.append(f"{crit} CRITICAL")
    if high:
        urgent.append(f"{high} HIGH")
    if urgent:
        parts.append(f"{' and '.join(urgent)}-severity findings require immediate action.")

    if n_critical_sections:
        parts.append(
            f"{n_critical_sections} code section{'s' if n_critical_sections != 1 else ''}"
            f" flagged for human review — see Critical Code Findings below."
        )

    if med:
        parts.append(f"Address {med} MEDIUM findings during regular development.")

    return " ".join(parts)


def _short_path(filepath: str) -> str:
    """Return just the filename from a potentially absolute path."""
    return Path(filepath).name


def _short_rule(rule_id: str) -> str:
    """Shorten dotted rule IDs like 'java.lang.security.audit.foo.bar' → 'bar'."""
    return rule_id.rsplit(".", 1)[-1] if "." in rule_id else rule_id



def _top_findings(findings: list[Finding]) -> list[Finding]:
    """Return CRITICAL and HIGH findings for the executive summary.

    Deduplicated by ``rule_id`` so the same rule across multiple files
    appears only once (the first occurrence by severity order).
    """
    sorted_f = sorted(findings, key=_severity_sort_key)
    seen_rules: set[str] = set()
    top: list[Finding] = []
    for f in sorted_f:
        if f.severity not in (Severity.CRITICAL, Severity.HIGH):
            break
        if f.rule_id in seen_rules:
            continue
        seen_rules.add(f.rule_id)
        top.append(f)
    return top


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------

def generate_markdown(
    target: Path,
    results: list[ToolResult],
    skip_records: list[SkipRecord],
    timestamp: str,
    detected_languages: set[str],
    critical_findings: list[CriticalFinding] | None = None,
    code_structure_critique: CodeStructureCritique | None = None,
) -> str:
    all_findings = [f for r in results for f in r.findings]
    by_sev = _count_by_severity(all_findings)
    verdict = _overall_verdict(all_findings)
    top = _top_findings(all_findings)
    lang_display = ", ".join(sorted(lang.title() for lang in detected_languages)) or "Unknown"

    lines: list[str] = []

    # Header
    lines.append("# AIDLC Code Reviewer — Analysis Report")
    lines.append("")
    lines.append(f"**Generated**: {timestamp}  ")
    lines.append(f"**Target**: `{target.resolve()}`  ")
    lines.append(f"**Detected languages**: {lang_display}  ")
    lines.append(f"**Total findings**: {len(all_findings)}  ")
    lines.append(f"**Overall verdict**: **{verdict}**")
    lines.append("")

    # --- 1. Executive Summary ---
    lines.append("## 1. Executive Summary")
    lines.append("")
    sev_parts = ", ".join(f"{by_sev[s]} {s}" for s in ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"] if by_sev.get(s))
    lines.append(f"**{verdict}** — {len(all_findings)} findings ({sev_parts})")
    lines.append("")
    action = _action_summary(by_sev, verdict, critical_findings, all_findings)
    lines.append(f"> {action}")
    lines.append("")
    if top:
        for i, f in enumerate(top, 1):
            lines.append(
                f"{i}. **[{f.severity.value}]** `{_short_rule(f.rule_id)}` in `{_short_path(f.file)}`"
                f" — {f.message}"
            )
        lines.append("")

    # --- Tool Summary ---
    lines.append("### Tool Summary")
    lines.append("")
    lines.append("| Category | Tool | Status | Findings |")
    lines.append("|----------|------|--------|----------|")
    for r in results:
        cat = CATEGORY_LABELS.get(r.category, r.category)
        status = "✓ Ran" if r.success else "✗ Error"
        lines.append(f"| {cat} | {r.tool} | {status} | {len(r.findings)} |")
    for sk in skip_records:
        cat = CATEGORY_LABELS.get(sk.category, sk.category)
        lines.append(f"| {cat} | {sk.tool} | skipped | — |")
    lines.append("")

    # --- Critical Code Findings ---
    lines.append("## Critical Code Findings — Review Required")
    lines.append("")
    if critical_findings:
        lines.append(f"**{len(critical_findings)}** critical code sections identified for human review.")
        lines.append("")
        for i, cf in enumerate(critical_findings, 1):
            icon = CRITICAL_CATEGORY_ICONS.get(cf.category, "⚠️")
            label = CRITICAL_CATEGORY_LABELS.get(cf.category, cf.category.value)
            source_badge = "\U0001f916 Agent-identified" if cf.source == "agent_only" else "\U0001f527 Tool-assisted"
            lines.append(f"### {i}. {icon} [{label}] `{cf.file}`:{cf.start_line}-{cf.end_line} {source_badge}")
            lines.append("")
            lines.append(f"**Finding**: {cf.verdict}  ")
            if cf.recommended_action:
                lines.append(f"**Action**: {cf.recommended_action}  ")
            lines.append("")
            if cf.why_critical:
                lines.append("**Why it matters**:")
                lines.append("")
                lines.append(cf.why_critical)
                lines.append("")
            if cf.related_tool_findings:
                lines.append(f"**Related Tool Findings ({len(cf.related_tool_findings)})**:")
                lines.append("")
                for tf in cf.related_tool_findings:
                    lines.append(f"- **{tf.tool}** `{tf.rule_id}` [{tf.severity.value}] — {tf.message}")
                lines.append("")
            lines.append("**Code**:")
            lines.append("")
            lines.extend(_render_code_block_md(cf.code_block, cf.start_line, cf.highlight_lines))
            lines.append("")
    else:
        lines.append("No critical code sections identified.")
        lines.append("")

    # --- 2. Code Structure Critique ---
    lines.append("## 2. Code Structure Critique")
    lines.append("")
    if code_structure_critique:
        lines.append(code_structure_critique.overall_summary)
        lines.append("")
        # Dimension summary table
        lines.append("| Dimension | Rating | Summary |")
        lines.append("|-----------|--------|---------|")
        for dim in code_structure_critique.dimensions:
            icon = DIMENSION_ICONS.get(dim.dimension, "📌")
            rating_label, _ = RATING_LABELS.get(dim.rating, (dim.rating.value, ""))
            lines.append(f"| {icon} {dim.dimension} | {rating_label} | {dim.summary} |")
        lines.append("")
        # Detailed findings per dimension
        for dim in code_structure_critique.dimensions:
            if not dim.findings:
                continue
            icon = DIMENSION_ICONS.get(dim.dimension, "📌")
            rating_label, _ = RATING_LABELS.get(dim.rating, (dim.rating.value, ""))
            lines.append(f"### 2.x {icon} {dim.dimension} — {rating_label}")
            lines.append("")
            lines.append(dim.summary)
            lines.append("")
            for j, issue in enumerate(dim.findings, 1):
                source_badge = "\U0001f916 Agent" if issue.source == "agent_only" else "\U0001f527 Tool-assisted"
                lines.append(f"**{j}.** `{issue.file}`:{issue.start_line}-{issue.end_line} {source_badge}")
                lines.append(f"  - **Issue**: {issue.issue}")
                lines.append(f"  - **Fix**: {issue.recommendation}")
                if issue.related_tool_findings:
                    lines.append(f"  **Related Tool Findings ({len(issue.related_tool_findings)})**:")
                    lines.append("")
                    for tf in issue.related_tool_findings:
                        lines.append(f"  - **{tf.tool}** `{tf.rule_id}` [{tf.severity.value}] — {tf.message}")
                    lines.append("")
                if issue.code_block:
                    lines.append("  **Code**:")
                    lines.append("")
                    for cl in _render_code_block_md(issue.code_block, issue.start_line, issue.highlight_lines):
                        lines.append(f"  {cl}")
                    lines.append("")
                lines.append("")
    else:
        lines.append("*Code structure critique not available.*")
        lines.append("")

    # --- 3. Code Quality Analysis ---
    lines.append("## 3. Code Quality Analysis")
    lines.append("")

    # Only iterate over results (tools that actually ran)
    for r in results:
        if r.tool in SECRETS_TOOLS:
            section = "3.2"
            label = "Secrets and Credentials"
        else:
            section = CATEGORY_NUMBERS.get(r.category, "3.x")
            label = CATEGORY_LABELS.get(r.category, r.category)

        lines.append(f"### {section} {label} ({r.tool})")
        lines.append("")

        if not r.success:
            lines.append(f"> **Error**: {r.error}")
            lines.append("")
            continue

        if not r.findings:
            lines.append("No findings.")
            lines.append("")
            continue

        r_sev = _count_by_severity(r.findings)
        lines.append(f"**Findings**: {len(r.findings)}")
        sev_parts = [f"{s}: {r_sev[s]}" for s in ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"] if r_sev.get(s)]
        if sev_parts:
            lines.append(f"  ({', '.join(sev_parts)})")
        lines.append("")

        lines.append("| # | Severity | Rule | File | Line | Message |")
        lines.append("|---|----------|------|------|------|---------|")
        sorted_findings = sorted(r.findings, key=_severity_sort_key)
        for i, f in enumerate(sorted_findings, 1):
            loc = str(f.line)
            if f.column is not None:
                loc += f":{f.column}"
            msg = f.message.replace("|", "\\|")
            lines.append(f"| {i} | {f.severity.value} | `{f.rule_id}` | `{f.file}` | {loc} | {msg} |")
        lines.append("")

    # --- 5. Appendix ---
    lines.append("## 5. Appendix")
    lines.append("")
    lines.append(f"**Timestamp**: {timestamp}  ")
    lines.append(f"**Target path**: `{target.resolve()}`  ")
    lines.append("")

    lines.append("### Files Analyzed")
    lines.append("")
    all_files = sorted({f.file for r in results for f in r.findings})
    if all_files:
        for fp in all_files:
            lines.append(f"- `{fp}`")
    else:
        lines.append("No files with findings.")
    lines.append("")

    lines.append("### Tool Versions")
    lines.append("")
    lines.append("| Tool | Category |")
    lines.append("|------|----------|")
    for r in results:
        cat = CATEGORY_LABELS.get(r.category, r.category)
        lines.append(f"| {r.tool} | {cat} |")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# HTML report
# ---------------------------------------------------------------------------

_THIRD_PARTY_MARKERS = ("node_modules/", "vendor/", "third_party/", ".venv/", "site-packages/")


def _is_third_party(filepath: str) -> bool:
    """Return True if the file path looks like a third-party dependency."""
    return any(marker in filepath for marker in _THIRD_PARTY_MARKERS)


def _format_timestamp_human(iso_ts: str) -> str:
    """Convert '2026-03-20T16:27:54Z' → '03/20/2026, 4:27 PM UTC'."""
    from datetime import datetime, timezone
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        return dt.strftime("%m/%d/%Y, %-I:%M %p UTC")
    except (ValueError, AttributeError):
        return iso_ts


_CSS = """
:root {
    --bg: #1a1b26; --bg-surface: #24283b; --bg-card: #1f2335;
    --text: #c0caf5; --text-dim: #6b7394; --text-bright: #e0e6ff;
    --border: #3b4261; --accent: #7aa2f7;
    --sev-critical: #f7768e; --sev-high: #ff9e64; --sev-medium: #e0af68;
    --sev-low: #9ece6a; --sev-info: #7dcfff;
    --good: #9ece6a; --attention: #e0af68; --critical: #f7768e;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: 'SF Mono', 'Fira Code', 'JetBrains Mono', monospace;
    background: var(--bg); color: var(--text);
    line-height: 1.6; padding: 2rem; max-width: 1200px; margin: 0 auto;
}
h1 { color: var(--accent); font-size: 1.5rem; margin-bottom: 0.25rem; }
h2 { color: var(--text-bright); font-size: 1.2rem; margin: 2rem 0 0.75rem; border-bottom: 1px solid var(--border); padding-bottom: 0.4rem; }
h3 { color: var(--accent); font-size: 1rem; margin: 1.5rem 0 0.5rem; }
.meta { color: var(--text-dim); font-size: 0.85rem; margin-bottom: 1.5rem; }
.meta span { margin-right: 2rem; }
.verdict { display: inline-block; padding: 0.2rem 0.8rem; border-radius: 4px; font-weight: bold; font-size: 0.9rem; }
.verdict-good { background: var(--good); color: #1a1b26; }
.verdict-attention { background: var(--attention); color: #1a1b26; }
.verdict-critical { background: var(--critical); color: #1a1b26; }
.sev-badge { display: inline-block; padding: 0.1rem 0.5rem; border-radius: 3px; font-size: 0.75rem; font-weight: bold; }
.sev-CRITICAL { background: var(--sev-critical); color: #1a1b26; }
.sev-HIGH { background: var(--sev-high); color: #1a1b26; }
.sev-MEDIUM { background: var(--sev-medium); color: #1a1b26; }
.sev-LOW { background: var(--sev-low); color: #1a1b26; }
.sev-INFO { background: var(--sev-info); color: #1a1b26; }
.status-pass { background: #9ece6a; color: #1a1b26; padding: 0.1rem 0.5rem; border-radius: 3px; font-size: 0.75rem; }
.status-fail { background: #f7768e; color: #1a1b26; padding: 0.1rem 0.5rem; border-radius: 3px; font-size: 0.75rem; }
.status-skipped { background: #565f89; color: #c0caf5; padding: 0.1rem 0.5rem; border-radius: 3px; font-size: 0.75rem; }
table { width: 100%; border-collapse: collapse; margin: 0.75rem 0; font-size: 0.85rem; }
th { background: var(--bg-surface); color: var(--text-bright); text-align: left; padding: 0.5rem 0.75rem; border: 1px solid var(--border); }
td { padding: 0.4rem 0.75rem; border: 1px solid var(--border); vertical-align: top; word-break: break-word; }
td:last-child { max-width: 400px; }
tr:nth-child(even) td { background: var(--bg-card); }
tr:hover td { background: var(--bg-surface); }
.card { background: var(--bg-card); border: 1px solid var(--border); border-radius: 6px; padding: 1rem 1.25rem; margin: 0.75rem 0; }
.stats { display: flex; gap: 1.5rem; flex-wrap: wrap; margin: 0.75rem 0; }
.stat { text-align: center; }
.stat a { text-decoration: none; color: inherit; }
.stat a:hover .stat-value { text-decoration: underline; }
.stat-value { font-size: 1.5rem; font-weight: bold; color: var(--text-bright); }
.stat-label { font-size: 0.75rem; color: var(--text-dim); }
.placeholder { color: var(--text-dim); font-style: italic; padding: 1rem; border: 1px dashed var(--border); border-radius: 4px; margin: 0.5rem 0; }
code { background: var(--bg-surface); padding: 0.15rem 0.4rem; border-radius: 3px; font-size: 0.85rem; }
td code.file-ref { background: var(--bg-surface); border: 1px solid var(--accent); border-radius: 4px; padding: 0.15rem 0.5rem; color: var(--accent); font-weight: bold; }
td .line-ref { background: var(--bg-surface); border: 1px solid var(--sev-medium); border-radius: 4px; padding: 0.15rem 0.5rem; color: var(--sev-medium); font-weight: bold; font-size: 0.8rem; display: inline-block; }
.top-finding { margin: 0.4rem 0; }
.file-list { columns: 2; column-gap: 2rem; }
.file-list li { font-size: 0.8rem; color: var(--text-dim); margin: 0.15rem 0; list-style: none; }
.critical-section { background: rgba(247, 118, 142, 0.07); border-left: 4px solid var(--sev-critical); border-radius: 0 6px 6px 0; padding: 1rem 1.25rem; margin: 0.75rem 0; }
.critical-section h4 { color: var(--sev-critical); margin-bottom: 0.25rem; font-size: 0.95rem; }
.critical-file { font-size: 0.8rem; margin-bottom: 0.5rem; background: var(--bg-surface); border: 1px solid var(--accent); border-radius: 4px; padding: 0.25rem 0.6rem; display: inline-block; color: var(--accent); font-weight: bold; }
.critical-file code { background: none; padding: 0; color: var(--accent); }
.critical-meta { font-size: 0.85rem; margin: 0.25rem 0; }
.critical-meta strong { color: var(--text-bright); }
.critical-tool { font-size: 0.8rem; color: var(--text-dim); margin: 0.2rem 0 0.2rem 1rem; }
.critical-code { margin-top: 0.5rem; }
.critical-code summary { cursor: pointer; color: var(--accent); font-size: 0.85rem; }
.critical-code pre { background: var(--bg); border: 1px solid var(--border); border-radius: 4px; padding: 0.75rem; margin-top: 0.5rem; font-size: 0.8rem; overflow-x: auto; white-space: pre-wrap; }
.highlight-line { background: rgba(255, 50, 50, 0.25); display: block; margin: 0 -0.75rem; padding: 0 0.75rem; border-left: 3px solid #ff5050; }
.cat-badge { display: inline-block; padding: 0.1rem 0.5rem; border-radius: 3px; font-size: 0.7rem; font-weight: bold; margin-right: 0.5rem; }
.cat-COMPUTATION { background: #bb9af7; color: #1a1b26; }
.cat-CONTROL_FLOW { background: #7aa2f7; color: #1a1b26; }
.cat-DATA_TRANSFORM { background: #2ac3de; color: #1a1b26; }
.source-badge { display: inline-block; padding: 0.1rem 0.5rem; border-radius: 3px; font-size: 0.7rem; font-weight: bold; margin-left: 0.5rem; vertical-align: middle; }
.source-agent { background: #bb9af7; color: #1a1b26; }
.source-tool { background: #ff9e64; color: #1a1b26; }
.critical-tools { margin: 0.5rem 0; }
.critical-tools summary { cursor: pointer; color: var(--accent); font-size: 0.85rem; }
.dim-section { background: var(--bg-card); border: 1px solid var(--border); border-radius: 6px; padding: 1rem 1.25rem; margin: 0.75rem 0; }
.dim-section > details > summary { cursor: pointer; list-style: none; }
.dim-section > details > summary::-webkit-details-marker { display: none; }
.dim-header { display: flex; align-items: center; gap: 0.75rem; margin-bottom: 0; }
.dim-header h4 { color: var(--accent); font-size: 0.95rem; margin: 0; }
.dim-summary-text { font-size: 0.85rem; margin: 0.25rem 0 0; color: var(--text-dim); }
.dim-issues { margin-top: 0.75rem; }
.rating-badge { display: inline-block; padding: 0.15rem 0.6rem; border-radius: 3px; font-size: 0.7rem; font-weight: bold; }
.rating-good { background: var(--good); color: #1a1b26; }
.rating-attention { background: var(--attention); color: #1a1b26; }
.rating-critical { background: var(--critical); color: #1a1b26; }
.dim-issue { border-left: 3px solid var(--border); padding: 0.5rem 0.75rem; margin: 0.5rem 0; font-size: 0.85rem; }
.dim-issue-meta { font-size: 0.8rem; }
.dim-issue-meta code { background: var(--bg-surface); border: 1px solid var(--accent); border-radius: 4px; padding: 0.15rem 0.5rem; color: var(--accent); font-weight: bold; }
.dim-issue-fix { color: var(--good); font-size: 0.8rem; }
.back-to-top { text-align: right; margin: 0.5rem 0; }
.back-to-top a { color: var(--text-dim); font-size: 0.75rem; text-decoration: none; }
.back-to-top a:hover { color: var(--accent); }
.toc { background: var(--bg-card); border: 1px solid var(--border); border-radius: 6px; padding: 1rem 1.25rem; margin: 1rem 0; }
.toc summary { cursor: pointer; color: var(--accent); font-size: 0.95rem; font-weight: bold; }
.toc ul { list-style: none; margin: 0.5rem 0 0 0; padding: 0; }
.toc li { margin: 0.3rem 0; }
.toc a { color: var(--text); text-decoration: none; font-size: 0.85rem; }
.toc a:hover { color: var(--accent); }
.tool-findings-section summary { cursor: pointer; color: var(--accent); font-size: 0.95rem; }
.tool-findings-section { margin: 0.75rem 0; }
.third-party-badge { display: inline-block; padding: 0.1rem 0.5rem; border-radius: 3px; font-size: 0.65rem; font-weight: bold; background: #565f89; color: #c0caf5; margin-left: 0.5rem; vertical-align: middle; }
.skipped-section summary { cursor: pointer; color: var(--text-dim); font-size: 0.85rem; }
.skipped-section { margin: 0.75rem 0; }
.legend { background: var(--bg-card); border: 1px solid var(--border); border-radius: 6px; padding: 1rem 1.25rem; margin: 0.75rem 0; }
.legend summary { cursor: pointer; color: var(--accent); font-size: 0.9rem; font-weight: bold; }
.legend-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 0.75rem; margin-top: 0.75rem; }
.legend-group h4 { color: var(--text-bright); font-size: 0.8rem; margin-bottom: 0.4rem; text-transform: uppercase; letter-spacing: 0.05em; }
.legend-item { display: flex; align-items: center; gap: 0.5rem; font-size: 0.8rem; color: var(--text-dim); margin: 0.3rem 0; }
.legend-item .sev-badge, .legend-item .cat-badge, .legend-item .source-badge,
.legend-item .rating-badge, .legend-item .third-party-badge, .legend-item .verdict,
.legend-item .status-pass, .legend-item .status-fail, .legend-item .status-skipped { margin: 0; }
[title] { cursor: help; }
"""


def _esc(text: str) -> str:
    return html_lib.escape(str(text))


# Tooltip descriptions for badges
_BADGE_TIPS = {
    "source-agent": "Found by AI analysis without tool confirmation",
    "source-tool": "Confirmed or assisted by a static analysis tool",
    "cat-COMPUTATION": "Cryptographic, precision, or concurrency-sensitive computation",
    "cat-CONTROL_FLOW": "Auth gates, error handling, or security-sensitive control flow",
    "cat-DATA_TRANSFORM": "Data conversion or mapping requiring human verification",
    "rating-good": "Meets quality standards",
    "rating-attention": "Has addressable issues",
    "rating-critical": "Requires significant rework",
    "third-party": "File from an external dependency (node_modules, vendor, etc.)",
}


def _verdict_class(verdict: str) -> str:
    return {"Good": "verdict-good", "Needs Attention": "verdict-attention", "Critical": "verdict-critical"}.get(verdict, "")


def _render_code_block_html(code_block: str, start_line: int, highlight_lines: list[int]) -> str:
    """Render a code block as HTML <pre> with highlighted lines in red."""
    highlight_set = set(highlight_lines)
    if not highlight_set:
        return f"<pre>{_esc(code_block)}</pre>"
    code_lines = code_block.split("\n")
    parts: list[str] = []
    parts.append("<pre>")
    for i, code_line in enumerate(code_lines):
        line_num = start_line + i
        escaped = _esc(code_line)
        if line_num in highlight_set:
            parts.append(f'<span class="highlight-line">{escaped}</span>')
        else:
            parts.append(escaped)
    parts.append("</pre>")
    return "\n".join(parts)



def generate_html(
    target: Path,
    results: list[ToolResult],
    skip_records: list[SkipRecord],
    timestamp: str,
    detected_languages: set[str],
    critical_findings: list[CriticalFinding] | None = None,
    code_structure_critique: CodeStructureCritique | None = None,
    summary_filename: str | None = None,
    sibling_report: tuple[str, str] | None = None,
) -> str:
    all_findings = [f for r in results for f in r.findings]
    by_sev = _count_by_severity(all_findings)
    verdict = _overall_verdict(all_findings)
    top = _top_findings(all_findings)
    lang_display = ", ".join(sorted(lang.title() for lang in detected_languages)) or "Unknown"
    human_ts = _format_timestamp_human(timestamp)

    h: list[str] = []
    h.append("<!DOCTYPE html>")
    h.append('<html lang="en"><head><meta charset="utf-8">')
    h.append('<meta name="viewport" content="width=device-width, initial-scale=1">')
    h.append(f"<title>AIDLC Code Review \u2014 {_esc(human_ts)}</title>")
    h.append(f"<style>{_CSS}</style>")
    h.append("</head><body>")

    # Header
    h.append('<div id="top"></div>')
    h.append("<h1>AIDLC Code Reviewer \u2014 Analysis Report</h1>")
    h.append('<div class="meta">')
    h.append(f"<span>Generated: {_esc(human_ts)}</span>")
    h.append(f"<span>Target: <code>{_esc(str(target.resolve()))}</code></span>")
    h.append(f"<span>Detected languages: {_esc(lang_display)}</span>")
    h.append("</div>")

    if summary_filename:
        h.append(f'<div style="margin-bottom: 1rem;"><a href="{_esc(summary_filename)}" '
                 'style="color: var(--accent); font-size: 0.85rem; text-decoration: none;">'
                 '\u2190 Back to Overview</a></div>')

    # --- Table of Contents ---
    h.append('<details class="toc" open>')
    h.append("<summary>Table of Contents</summary>")
    h.append("<ul>")
    h.append('<li><a href="#executive-summary">1. Executive Summary</a></li>')
    h.append('<li><a href="#critical-findings">\u26a0 Critical Code Findings</a></li>')
    h.append('<li><a href="#structure-critique">2. Code Structure Critique</a></li>')
    h.append('<li><a href="#code-quality">3. Code Quality Analysis</a></li>')
    h.append('<li><a href="#appendix">5. Appendix</a></li>')
    h.append("</ul>")
    h.append("</details>")

    # --- Badge Legend ---
    h.append('<details class="legend">')
    h.append("<summary>\U0001f3f7\ufe0f Badge Legend</summary>")
    h.append('<div class="legend-grid">')
    # Severity
    h.append('<div class="legend-group"><h4>Severity</h4>')
    h.append('<div class="legend-item"><span class="sev-badge sev-CRITICAL">CRITICAL</span> Immediate fix required</div>')
    h.append('<div class="legend-item"><span class="sev-badge sev-HIGH">HIGH</span> Significant issue, fix soon</div>')
    h.append('<div class="legend-item"><span class="sev-badge sev-MEDIUM">MEDIUM</span> Moderate concern</div>')
    h.append('<div class="legend-item"><span class="sev-badge sev-LOW">LOW</span> Minor improvement</div>')
    h.append('<div class="legend-item"><span class="sev-badge sev-INFO">INFO</span> Informational note</div>')
    h.append("</div>")
    # Critical categories
    h.append('<div class="legend-group"><h4>Critical Categories</h4>')
    h.append('<div class="legend-item"><span class="cat-badge cat-COMPUTATION">\U0001f522 COMPUTATION</span> Crypto / precision / concurrency</div>')
    h.append('<div class="legend-item"><span class="cat-badge cat-CONTROL_FLOW">\U0001f500 CONTROL_FLOW</span> Auth / error handling / security flow</div>')
    h.append('<div class="legend-item"><span class="cat-badge cat-DATA_TRANSFORM">\U0001f504 DATA_TRANSFORM</span> Data conversion / mapping</div>')
    h.append("</div>")
    # Source
    h.append('<div class="legend-group"><h4>Finding Source</h4>')
    h.append('<div class="legend-item"><span class="source-badge source-agent">\U0001f916 Agent-identified</span> Found by AI analysis</div>')
    h.append('<div class="legend-item"><span class="source-badge source-tool">\U0001f527 Tool-assisted</span> Confirmed by static analysis tool</div>')
    h.append("</div>")
    # Ratings
    h.append('<div class="legend-group"><h4>Structure Ratings</h4>')
    h.append('<div class="legend-item"><span class="rating-badge rating-good">Good</span> Meets quality standards</div>')
    h.append('<div class="legend-item"><span class="rating-badge rating-attention">Needs Improvement</span> Has addressable issues</div>')
    h.append('<div class="legend-item"><span class="rating-badge rating-critical">Poor</span> Requires significant rework</div>')
    h.append("</div>")
    # Status & other
    h.append('<div class="legend-group"><h4>Tool Status</h4>')
    h.append('<div class="legend-item"><span class="status-pass">\u2713 Ran</span> Tool executed successfully</div>')
    h.append('<div class="legend-item"><span class="status-fail">\u2717 Error</span> Tool encountered an error</div>')
    h.append('<div class="legend-item"><span class="third-party-badge">3rd party</span> File from external dependency</div>')
    h.append("</div>")
    h.append("</div>")  # legend-grid
    h.append("</details>")

    # --- 1. Executive Summary ---
    h.append('<h2 id="executive-summary">1. Executive Summary</h2>')
    h.append(f'<p><span class="verdict {_verdict_class(verdict)}">{_esc(verdict)}</span></p>')
    action = _action_summary(by_sev, verdict, critical_findings, all_findings)
    h.append(f'<p style="margin: 0.5rem 0; font-size: 0.9rem;">{_esc(action)}</p>')

    # Stats row - linked to sections
    h.append('<div class="stats">')
    h.append(
        f'<div class="stat"><a href="#code-quality"><div class="stat-value">{len(all_findings)}</div>'
        '<div class="stat-label">Total Findings</div></a></div>'
    )
    for sev in SEV_ORDER:
        count = by_sev.get(sev.value, 0)
        if count:
            h.append(
                f'<div class="stat"><a href="#code-quality"><div class="stat-value">{count}</div>'
                f'<div class="stat-label"><span class="sev-badge sev-{sev.value}">{sev.value}</span></div></a></div>'
            )
    h.append("</div>")

    # Top findings (CRITICAL + HIGH only)
    if top:
        for i, f in enumerate(top, 1):
            third_party = ' <span class="third-party-badge" title="File from an external dependency (node_modules, vendor, etc.)">3rd party</span>' if _is_third_party(f.file) else ""
            h.append(
                f'<div class="top-finding">{i}. <span class="sev-badge sev-{f.severity.value}">{f.severity.value}</span> '
                f"<code>{_esc(_short_rule(f.rule_id))}</code> in <code>{_esc(_short_path(f.file))}</code>"
                f" \u2014 {_esc(f.message)}{third_party}</div>"
            )

    # Tool summary table - active tools only
    h.append("<h3>Tool Summary</h3>")
    h.append("<table><thead><tr><th>Category</th><th>Tool</th><th>Status</th><th>Findings</th></tr></thead><tbody>")
    for r in results:
        cat = _esc(CATEGORY_LABELS.get(r.category, r.category))
        status_text = "\u2713 Ran" if r.success else "\u2717 Error"
        status_cls = "status-pass" if r.success else "status-fail"
        status_tip = "Tool executed successfully" if r.success else "Tool encountered an error"
        h.append(
            f'<tr><td>{cat}</td><td>{_esc(r.tool)}</td><td><span class="{status_cls}" title="{status_tip}">{status_text}</span></td>'
            f"<td>{len(r.findings)}</td></tr>"
        )
    h.append("</tbody></table>")

    # Skipped tools - collapsible
    if skip_records:
        h.append('<details class="skipped-section">')
        h.append(f"<summary>Skipped tools ({len(skip_records)})</summary>")
        h.append("<table><thead><tr><th>Category</th><th>Tool</th><th>Reason</th></tr></thead><tbody>")
        for sk in skip_records:
            cat = _esc(CATEGORY_LABELS.get(sk.category, sk.category))
            h.append(f"<tr><td>{cat}</td><td>{_esc(sk.tool)}</td><td>{_esc(sk.reason)}</td></tr>")
        h.append("</tbody></table>")
        h.append("</details>")

    h.append('<div class="back-to-top"><a href="#top">\u2191 Back to top</a></div>')

    # --- Critical Code Findings ---
    h.append('<h2 id="critical-findings">\u26a0 Critical Code Findings \u2014 Review Required</h2>')
    if critical_findings:
        h.append(f'<p><strong>{len(critical_findings)}</strong> critical code sections identified for human review.</p>')
        for i, cf in enumerate(critical_findings, 1):
            label = CRITICAL_CATEGORY_LABELS.get(cf.category, cf.category.value)
            source_icon = "\U0001f916" if cf.source == "agent_only" else "\U0001f527"
            source_label = "Agent-identified" if cf.source == "agent_only" else "Tool-assisted"
            source_cls = "source-agent" if cf.source == "agent_only" else "source-tool"
            cat_tip = _esc(_BADGE_TIPS.get(f"cat-{label}", label))
            src_tip = _esc(_BADGE_TIPS.get(source_cls, source_label))
            h.append('<div class="critical-section">')
            h.append(
                f'<h4>{i}. <span class="cat-badge cat-{label}" title="{cat_tip}">{label}</span> '
                f'<span class="source-badge {source_cls}" title="{src_tip}">{source_icon} {source_label}</span></h4>'
            )
            h.append(f'<div class="critical-file"><code>{_esc(cf.file)}</code>:{cf.start_line}-{cf.end_line}</div>')
            h.append(f'<div class="critical-meta"><strong>Finding:</strong> {_esc(cf.verdict)}</div>')
            if cf.recommended_action:
                h.append(f'<div class="critical-meta" style="color: var(--good);"><strong>Action:</strong> {_esc(cf.recommended_action)}</div>')
            h.append(f'<details style="margin: 0.25rem 0; font-size: 0.85rem;"><summary style="cursor: pointer; color: var(--text-dim);">Why it matters</summary>')
            h.append(f'<div class="critical-meta">{_esc(cf.why_critical)}</div>')
            h.append("</details>")
            if cf.related_tool_findings:
                h.append(f'<details class="critical-tools"><summary>Related Tool Findings ({len(cf.related_tool_findings)})</summary>')
                for tf in cf.related_tool_findings:
                    h.append(
                        f'<div class="critical-tool">\U0001f527 {_esc(tf.tool)} <code>{_esc(tf.rule_id)}</code> '
                        f'<span class="sev-badge sev-{tf.severity.value}">{tf.severity.value}</span> \u2014 {_esc(tf.message)}</div>'
                    )
                h.append("</details>")
            h.append('<details class="critical-code"><summary>View Code</summary>')
            h.append(_render_code_block_html(cf.code_block, cf.start_line, cf.highlight_lines))
            h.append("</details>")
            h.append("</div>")
    else:
        h.append('<div class="card">No critical code sections identified.</div>')
    h.append('<div class="back-to-top"><a href="#top">\u2191 Back to top</a></div>')

    # --- 2. Code Structure Critique ---
    h.append('<h2 id="structure-critique">2. Code Structure Critique</h2>')
    if code_structure_critique:
        h.append(f"<p>{_esc(code_structure_critique.overall_summary)}</p>")
        # Dimension summary table
        h.append("<table><thead><tr><th>Dimension</th><th>Rating</th><th>Summary</th></tr></thead><tbody>")
        for dim in code_structure_critique.dimensions:
            icon = DIMENSION_ICONS.get(dim.dimension, "\U0001f4cc")
            rating_label, rating_cls = RATING_LABELS.get(dim.rating, (dim.rating.value, ""))
            r_tip = _esc(_BADGE_TIPS.get(f"rating-{rating_cls}", rating_label))
            h.append(
                f"<tr><td>{icon} {_esc(dim.dimension)}</td>"
                f'<td><span class="rating-badge rating-{rating_cls}" title="{r_tip}">{_esc(rating_label)}</span></td>'
                f"<td>{_esc(dim.summary)}</td></tr>"
            )
        h.append("</tbody></table>")
        # Detailed findings per dimension - collapsible
        for dim in code_structure_critique.dimensions:
            if not dim.findings:
                continue
            icon = DIMENSION_ICONS.get(dim.dimension, "\U0001f4cc")
            rating_label, rating_cls = RATING_LABELS.get(dim.rating, (dim.rating.value, ""))
            h.append('<div class="dim-section">')
            h.append("<details>")
            h.append("<summary>")
            r_tip = _esc(_BADGE_TIPS.get(f"rating-{rating_cls}", rating_label))
            h.append(
                f'<div class="dim-header"><h4>{icon} {_esc(dim.dimension)}</h4>'
                f'<span class="rating-badge rating-{rating_cls}" title="{r_tip}">{_esc(rating_label)}</span>'
                f'<span style="color: var(--text-dim); font-size: 0.8rem; margin-left: auto;">'
                f"{len(dim.findings)} issues</span></div>"
            )
            h.append(f'<p class="dim-summary-text">{_esc(dim.summary)}</p>')
            h.append("</summary>")
            h.append('<div class="dim-issues">')
            for j, issue in enumerate(dim.findings, 1):
                h.append('<div class="dim-issue">')
                source_icon = "\U0001f916" if issue.source == "agent_only" else "\U0001f527"
                source_label = "Agent" if issue.source == "agent_only" else "Tool-assisted"
                source_cls = "source-agent" if issue.source == "agent_only" else "source-tool"
                src_tip = _esc(_BADGE_TIPS.get(source_cls, source_label))
                h.append(
                    f'<div class="dim-issue-meta"><strong>{j}.</strong> '
                    f"<code>{_esc(issue.file)}</code>:{issue.start_line}-{issue.end_line} "
                    f'<span class="source-badge {source_cls}" title="{src_tip}">{source_icon} {source_label}</span></div>'
                )
                h.append(f"<div><strong>Issue:</strong> {_esc(issue.issue)}</div>")
                h.append(f'<div class="dim-issue-fix"><strong>Fix:</strong> {_esc(issue.recommendation)}</div>')
                if issue.related_tool_findings:
                    h.append(f'<details class="critical-tools"><summary>Related Tool Findings ({len(issue.related_tool_findings)})</summary>')
                    for tf in issue.related_tool_findings:
                        h.append(
                            f'<div class="critical-tool">\U0001f527 {_esc(tf.tool)} <code>{_esc(tf.rule_id)}</code> '
                            f'<span class="sev-badge sev-{tf.severity.value}">{tf.severity.value}</span> \u2014 {_esc(tf.message)}</div>'
                        )
                    h.append("</details>")
                if issue.code_block:
                    h.append('<details class="critical-code"><summary>View Code</summary>')
                    h.append(_render_code_block_html(issue.code_block, issue.start_line, issue.highlight_lines))
                    h.append("</details>")
                h.append("</div>")
            h.append("</div>")
            h.append("</details>")
            h.append("</div>")
    else:
        h.append('<div class="card">Code structure critique not available.</div>')
    h.append('<div class="back-to-top"><a href="#top">\u2191 Back to top</a></div>')

    # --- 3. Code Quality Analysis (only tools that ran) ---
    h.append('<h2 id="code-quality">3. Code Quality Analysis</h2>')

    for r in results:
        if r.tool in SECRETS_TOOLS:
            section = "3.2"
            label = "Secrets and Credentials"
        else:
            section = CATEGORY_NUMBERS.get(r.category, "3.x")
            label = CATEGORY_LABELS.get(r.category, r.category)

        if not r.success:
            h.append(f"<h3>{section} {_esc(label)} ({_esc(r.tool)})</h3>")
            h.append(f'<div class="card">Error: {_esc(r.error or "unknown")}</div>')
            continue

        if not r.findings:
            h.append(f"<h3>{section} {_esc(label)} ({_esc(r.tool)})</h3>")
            h.append('<div class="card">No findings.</div>')
            continue

        # Determine if this should be expanded by default
        r_sev = _count_by_severity(r.findings)
        has_important = any(r_sev.get(s, 0) > 0 for s in ["CRITICAL", "HIGH", "MEDIUM"])
        sev_parts = " ".join(
            f'<span class="sev-badge sev-{s}">{s}: {r_sev[s]}</span>'
            for s in ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]
            if r_sev.get(s)
        )
        open_attr = " open" if has_important else ""

        # Check for third-party findings
        third_party_count = sum(1 for f in r.findings if _is_third_party(f.file))
        tp_note = ""
        if third_party_count:
            tp_note = f' <span class="third-party-badge" title="File from an external dependency">{third_party_count} from 3rd party</span>'

        h.append(f'<details class="tool-findings-section"{open_attr}>')
        h.append(
            f"<summary>{section} {_esc(label)} ({_esc(r.tool)}) \u2014 "
            f"{len(r.findings)} findings {sev_parts}{tp_note}</summary>"
        )

        h.append(
            "<table><thead><tr><th>#</th><th>Severity</th><th>Rule</th>"
            "<th>File</th><th>Line</th><th>Message</th></tr></thead><tbody>"
        )
        sorted_findings = sorted(r.findings, key=_severity_sort_key)
        for i, f in enumerate(sorted_findings, 1):
            loc = str(f.line)
            if f.column is not None:
                loc += f":{f.column}"
            msg = _esc(f.message)
            tp_badge = ""
            if _is_third_party(f.file):
                tp_badge = ' <span class="third-party-badge" title="File from an external dependency">3rd party</span>'
            h.append(
                f"<tr><td>{i}</td>"
                f'<td><span class="sev-badge sev-{f.severity.value}">{f.severity.value}</span></td>'
                f"<td><code>{_esc(f.rule_id)}</code></td>"
                f'<td><code class="file-ref">{_esc(f.file)}</code>{tp_badge}</td>'
                f'<td><span class="line-ref">{loc}</span></td><td>{msg}</td></tr>'
            )
        h.append("</tbody></table>")
        h.append("</details>")

    h.append('<div class="back-to-top"><a href="#top">\u2191 Back to top</a></div>')

    # --- 5. Appendix ---
    h.append('<h2 id="appendix">5. Appendix</h2>')
    h.append(f"<p>Timestamp: {_esc(human_ts)}<br>Target: <code>{_esc(str(target.resolve()))}</code></p>")

    h.append("<h3>Files Analyzed</h3>")
    all_files = sorted({f.file for r in results for f in r.findings})
    if all_files:
        h.append('<ul class="file-list">')
        for fp in all_files:
            tp_badge = ""
            if _is_third_party(fp):
                tp_badge = ' <span class="third-party-badge" title="File from an external dependency">3rd party</span>'
            h.append(f"<li>{_esc(fp)}{tp_badge}</li>")
        h.append("</ul>")
    else:
        h.append("<p>No files with findings.</p>")

    h.append("<h3>Tool Configuration</h3>")
    h.append("<table><thead><tr><th>Tool</th><th>Category</th></tr></thead><tbody>")
    for r in results:
        cat = _esc(CATEGORY_LABELS.get(r.category, r.category))
        h.append(f"<tr><td>{_esc(r.tool)}</td><td>{cat}</td></tr>")
    h.append("</tbody></table>")

    # Bottom navigation
    nav_parts: list[str] = []
    if summary_filename:
        nav_parts.append(f'<a href="{_esc(summary_filename)}" style="color: var(--accent); text-decoration: none;">\u2190 Back to Summary</a>')
    if sibling_report:
        sib_file, sib_label = sibling_report
        nav_parts.append(f'<a href="{_esc(sib_file)}" style="color: var(--accent); text-decoration: none;">{_esc(sib_label)} \u2192</a>')
    if nav_parts:
        h.append(f'<div style="margin-top: 2rem; padding-top: 1rem; border-top: 1px solid var(--border); display: flex; justify-content: space-between; font-size: 0.85rem;">{"".join(nav_parts)}</div>')

    h.append("</body></html>")
    return "\n".join(h)


# ---------------------------------------------------------------------------
# Business Logic Review — Separate Report (Markdown)
# ---------------------------------------------------------------------------


def generate_business_logic_markdown(
    target: Path,
    timestamp: str,
    detected_languages: set[str],
    review: BusinessLogicReview,
) -> str:
    """Generate a standalone markdown report for business logic review."""
    lang_display = ", ".join(sorted(lang.title() for lang in detected_languages)) or "Unknown"

    lines: list[str] = []

    # Header
    lines.append("# Business Logic Review — Human Review Checkpoint")
    lines.append("")
    lines.append(f"**Generated**: {timestamp}  ")
    lines.append(f"**Target**: `{target.resolve()}`  ")
    lines.append(f"**Detected languages**: {lang_display}  ")
    lines.append(f"**Business logic findings**: {len(review.findings)}  ")
    lines.append(f"**Consistency issues**: {len(review.consistency_issues)}")
    lines.append("")

    # --- Executive Summary ---
    lines.append("## Executive Summary")
    lines.append("")
    if review.executive_summary:
        lines.append(review.executive_summary)
    else:
        lines.append("This report identifies code sections that encode core business rules,")
        lines.append("formulas, and domain logic. Every finding is flagged for human review")
        lines.append("regardless of whether static analysis tools reported issues.")
    lines.append("")

    # --- Summary by category ---
    lines.append("## Summary by Category")
    lines.append("")
    cat_counts: dict[BusinessLogicCategory, int] = {}
    for f in review.findings:
        cat_counts[f.category] = cat_counts.get(f.category, 0) + 1
    if cat_counts:
        lines.append("| Category | Findings |")
        lines.append("|----------|----------|")
        for cat in BusinessLogicCategory:
            count = cat_counts.get(cat, 0)
            if count:
                icon = BUSINESS_LOGIC_CATEGORY_ICONS.get(cat, "📌")
                label = BUSINESS_LOGIC_CATEGORY_LABELS.get(cat, cat.value)
                lines.append(f"| {icon} {label} | {count} |")
        lines.append("")
    else:
        lines.append("No business logic findings identified.")
        lines.append("")

    # --- Findings ---
    lines.append("## Business Logic Findings")
    lines.append("")
    if review.findings:
        # Group by category
        current_cat: str | None = None
        finding_num = 0
        for f in review.findings:
            cat_label = BUSINESS_LOGIC_CATEGORY_LABELS.get(f.category, f.category.value)
            cat_icon = BUSINESS_LOGIC_CATEGORY_ICONS.get(f.category, "📌")
            if f.category.value != current_cat:
                current_cat = f.category.value
                lines.append(f"### {cat_icon} {cat_label}")
                lines.append("")

            finding_num += 1
            lines.append(f"#### {finding_num}. {f.title}")
            lines.append("")
            lines.append(f"`{f.file}`:{f.start_line}-{f.end_line}")
            lines.append("")
            lines.append(f"**What it does**: {f.what_it_does}  ")
            lines.append(f"**Review guidance**: {f.review_guidance}  ")
            lines.append(f"**Risk if wrong**: {f.risk_if_wrong}")
            lines.append("")
            lines.append("**Code**:")
            lines.append("")
            lines.append("```")
            lines.append(f"{f.code_block}")
            lines.append("```")
            lines.append("")
    else:
        lines.append("No business logic findings identified. However, a human reviewer should")
        lines.append("still verify the core functional areas of this codebase.")
        lines.append("")

    # --- Consistency Issues ---
    lines.append("## Self-Consistency Issues")
    lines.append("")
    if review.consistency_issues:
        lines.append(f"**{len(review.consistency_issues)}** consistency issues detected across business logic sections.")
        lines.append("")
        for i, ci in enumerate(review.consistency_issues, 1):
            icon = CONSISTENCY_ISSUE_ICONS.get(ci.issue_type, "⚠️")
            label = CONSISTENCY_ISSUE_LABELS.get(ci.issue_type, ci.issue_type.value)
            lines.append(f"### {i}. {icon} {label}")
            lines.append("")
            lines.append(f"**Issue**: {ci.description}  ")
            if ci.recommended_action:
                lines.append(f"**Recommended action**: {ci.recommended_action}")
            lines.append("")
            lines.append("**Locations**:")
            lines.append("")
            for loc in ci.locations:
                lines.append(f"- `{loc.file}`:{loc.start_line}-{loc.end_line}")
            lines.append("")
            if ci.code_blocks:
                for j, cb in enumerate(ci.code_blocks):
                    loc_label = f"`{ci.locations[j].file}`" if j < len(ci.locations) else f"Location {j + 1}"
                    lines.append(f"**{loc_label}**:")
                    lines.append("")
                    lines.append("```")
                    lines.append(cb)
                    lines.append("```")
                    lines.append("")
    else:
        lines.append("No self-consistency issues detected.")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Business Logic Review — Separate Report (HTML)
# ---------------------------------------------------------------------------

_BUSINESS_CSS = """
:root {
    --bg: #1a1b26; --bg-surface: #24283b; --bg-card: #1f2335;
    --text: #c0caf5; --text-dim: #6b7394; --text-bright: #e0e6ff;
    --border: #3b4261; --accent: #7aa2f7;
    --good: #9ece6a; --attention: #e0af68; --critical: #f7768e;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: 'SF Mono', 'Fira Code', 'JetBrains Mono', monospace;
    background: var(--bg); color: var(--text);
    line-height: 1.6; padding: 2rem; max-width: 1200px; margin: 0 auto;
}
h1 { color: var(--accent); font-size: 1.5rem; margin-bottom: 0.25rem; }
h2 { color: var(--text-bright); font-size: 1.2rem; margin: 2rem 0 0.75rem; border-bottom: 1px solid var(--border); padding-bottom: 0.4rem; }
h3 { color: var(--accent); font-size: 1rem; margin: 1.5rem 0 0.5rem; }
.meta { color: var(--text-dim); font-size: 0.85rem; margin-bottom: 1.5rem; }
.meta span { margin-right: 2rem; }
.intro { color: var(--text-dim); font-size: 0.85rem; font-style: italic; margin-bottom: 1.5rem; border-left: 3px solid var(--accent); padding-left: 0.75rem; }
table { width: 100%; border-collapse: collapse; margin: 0.75rem 0; font-size: 0.85rem; }
th { background: var(--bg-surface); color: var(--text-bright); text-align: left; padding: 0.5rem 0.75rem; border: 1px solid var(--border); }
td { padding: 0.4rem 0.75rem; border: 1px solid var(--border); vertical-align: top; }
tr:nth-child(even) td { background: var(--bg-card); }
tr:hover td { background: var(--bg-surface); }
code { background: var(--bg-surface); padding: 0.15rem 0.4rem; border-radius: 3px; font-size: 0.85rem; }
pre { background: var(--bg); border: 1px solid var(--border); border-radius: 4px; padding: 0.75rem; font-size: 0.8rem; overflow-x: auto; white-space: pre-wrap; margin: 0.5rem 0; }
.card { background: var(--bg-card); border: 1px solid var(--border); border-radius: 6px; padding: 1rem 1.25rem; margin: 0.75rem 0; }
.stats { display: flex; gap: 1.5rem; flex-wrap: wrap; margin: 0.75rem 0; }
.stat { text-align: center; }
.stat-value { font-size: 1.5rem; font-weight: bold; color: var(--text-bright); }
.stat-label { font-size: 0.75rem; color: var(--text-dim); }
.cat-badge { display: inline-block; padding: 0.1rem 0.5rem; border-radius: 3px; font-size: 0.7rem; font-weight: bold; margin-right: 0.5rem; }
.cat-FINANCIAL_FORMULA { background: #bb9af7; color: #1a1b26; }
.cat-SCORING_AND_RANKING { background: #7aa2f7; color: #1a1b26; }
.cat-PRICING_AND_DISCOUNT { background: #e0af68; color: #1a1b26; }
.cat-BUSINESS_RULE { background: #2ac3de; color: #1a1b26; }
.cat-STATE_MACHINE { background: #ff9e64; color: #1a1b26; }
.cat-ROUNDING_AND_PRECISION { background: #9ece6a; color: #1a1b26; }
.cat-BOUNDARY_CONDITION { background: #f7768e; color: #1a1b26; }
.cat-DATA_MAPPING { background: #73daca; color: #1a1b26; }
.cat-TEMPORAL_LOGIC { background: #b4f9f8; color: #1a1b26; }
.cat-RECONCILIATION { background: #c0caf5; color: #1a1b26; }
.issue-badge { display: inline-block; padding: 0.1rem 0.5rem; border-radius: 3px; font-size: 0.7rem; font-weight: bold; background: var(--attention); color: #1a1b26; }
.finding-section { background: var(--bg-card); border-left: 4px solid var(--accent); border-radius: 0 6px 6px 0; padding: 1rem 1.25rem; margin: 0.75rem 0; }
.finding-section h4 { color: var(--accent); margin-bottom: 0.25rem; font-size: 0.95rem; }
.finding-file { font-size: 0.8rem; margin-bottom: 0.5rem; background: var(--bg-surface); border: 1px solid var(--accent); border-radius: 4px; padding: 0.25rem 0.6rem; display: inline-block; color: var(--accent); font-weight: bold; }
.finding-meta { font-size: 0.85rem; margin: 0.25rem 0; }
.finding-meta strong { color: var(--text-bright); }
.finding-risk { color: var(--critical); font-size: 0.85rem; margin: 0.25rem 0; }
.finding-code { margin-top: 0.5rem; }
.finding-code summary { cursor: pointer; color: var(--accent); font-size: 0.85rem; }
.consistency-section { background: var(--bg-card); border-left: 4px solid var(--attention); border-radius: 0 6px 6px 0; padding: 1rem 1.25rem; margin: 0.75rem 0; }
.consistency-section h4 { color: var(--attention); margin-bottom: 0.25rem; font-size: 0.95rem; }
.back-to-top { text-align: right; margin: 0.5rem 0; }
.back-to-top a { color: var(--text-dim); font-size: 0.75rem; text-decoration: none; }
.back-to-top a:hover { color: var(--accent); }
.toc { background: var(--bg-card); border: 1px solid var(--border); border-radius: 6px; padding: 1rem 1.25rem; margin: 1rem 0; }
.toc summary { cursor: pointer; color: var(--accent); font-size: 0.95rem; font-weight: bold; }
.toc ul { list-style: none; margin: 0.5rem 0 0 0; padding: 0; }
.toc li { margin: 0.3rem 0; }
.toc a { color: var(--text); text-decoration: none; font-size: 0.85rem; }
.toc a:hover { color: var(--accent); }
.cat-group { margin: 1rem 0; }
.cat-group > details > summary { cursor: pointer; list-style: none; }
.cat-group > details > summary::-webkit-details-marker { display: none; }
.cat-header { display: flex; align-items: center; gap: 0.75rem; }
.cat-header h4 { color: var(--accent); font-size: 0.95rem; margin: 0; }
.legend { background: var(--bg-card); border: 1px solid var(--border); border-radius: 6px; padding: 1rem 1.25rem; margin: 1rem 0; }
.legend summary { cursor: pointer; color: var(--accent); font-size: 0.95rem; font-weight: bold; }
.legend-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 1rem; margin-top: 0.75rem; }
.legend-group h4 { color: var(--text-bright); font-size: 0.85rem; margin-bottom: 0.4rem; border-bottom: 1px solid var(--border); padding-bottom: 0.25rem; }
.legend-item { font-size: 0.8rem; margin: 0.3rem 0; display: flex; align-items: center; gap: 0.5rem; }
"""


def generate_business_logic_html(
    target: Path,
    timestamp: str,
    detected_languages: set[str],
    review: BusinessLogicReview,
    summary_filename: str | None = None,
    sibling_report: tuple[str, str] | None = None,
) -> str:
    """Generate a standalone HTML report for business logic review."""
    lang_display = ", ".join(sorted(lang.title() for lang in detected_languages)) or "Unknown"
    human_ts = _format_timestamp_human(timestamp)

    h: list[str] = []
    h.append("<!DOCTYPE html>")
    h.append('<html lang="en"><head><meta charset="utf-8">')
    h.append('<meta name="viewport" content="width=device-width, initial-scale=1">')
    h.append(f"<title>Business Logic Review \u2014 {_esc(human_ts)}</title>")
    h.append(f"<style>{_BUSINESS_CSS}</style>")
    h.append("</head><body>")

    # Header
    h.append('<div id="top"></div>')
    h.append("<h1>Business Logic Review \u2014 Human Review Checkpoint</h1>")
    h.append('<div class="meta">')
    h.append(f"<span>Generated: {_esc(human_ts)}</span>")
    h.append(f"<span>Target: <code>{_esc(str(target.resolve()))}</code></span>")
    h.append(f"<span>Languages: {_esc(lang_display)}</span>")
    h.append("</div>")

    if summary_filename:
        h.append(f'<div style="margin-bottom: 1rem;"><a href="{_esc(summary_filename)}" '
                 'style="color: var(--accent); font-size: 0.85rem; text-decoration: none;">'
                 '\u2190 Back to Overview</a></div>')

    # Badge Legend
    h.append('<details class="legend">')
    h.append("<summary>\U0001f3f7\ufe0f Badge Legend</summary>")
    h.append('<div class="legend-grid">')
    h.append('<div class="legend-group"><h4>Business Logic Categories</h4>')
    _BIZ_CAT_DESCRIPTIONS = {
        BusinessLogicCategory.FINANCIAL_FORMULA: "Monetary calculations, interest rates, tax logic",
        BusinessLogicCategory.SCORING_AND_RANKING: "Score computations, ranking algorithms, weighted evaluations",
        BusinessLogicCategory.PRICING_AND_DISCOUNT: "Price derivation, discount tiers, promotional rules",
        BusinessLogicCategory.BUSINESS_RULE: "Domain-specific if/then rules, eligibility checks",
        BusinessLogicCategory.STATE_MACHINE: "Workflow transitions, status progressions, approval gates",
        BusinessLogicCategory.ROUNDING_AND_PRECISION: "Decimal handling, truncation, precision-sensitive math",
        BusinessLogicCategory.BOUNDARY_CONDITION: "Edge cases, off-by-one, min/max threshold logic",
        BusinessLogicCategory.DATA_MAPPING: "Field mapping, schema translation, key transformations",
        BusinessLogicCategory.TEMPORAL_LOGIC: "Date/time calculations, scheduling, expiration rules",
        BusinessLogicCategory.RECONCILIATION: "Cross-system consistency checks, balance verification",
    }
    for cat in BusinessLogicCategory:
        icon = BUSINESS_LOGIC_CATEGORY_ICONS.get(cat, "\U0001f4cc")
        label = BUSINESS_LOGIC_CATEGORY_LABELS.get(cat, cat.value)
        desc = _BIZ_CAT_DESCRIPTIONS.get(cat, "")
        h.append(f'<div class="legend-item"><span class="cat-badge cat-{cat.value}">{icon} {_esc(label)}</span> {_esc(desc)}</div>')
    h.append("</div>")
    h.append('<div class="legend-group"><h4>Consistency Issue Types</h4>')
    _CONSISTENCY_DESCRIPTIONS = {
        ConsistencyIssueType.CONSTANT_DRIFT: "Same constant defined with different values across files",
        ConsistencyIssueType.LOGIC_DIVERGENCE: "Similar logic implemented differently in separate locations",
        ConsistencyIssueType.NAMING_MISMATCH: "Inconsistent naming for the same concept across the codebase",
        ConsistencyIssueType.REDUNDANT_IMPLEMENTATION: "Duplicate functionality that should be consolidated",
    }
    for issue_type in ConsistencyIssueType:
        icon = CONSISTENCY_ISSUE_ICONS.get(issue_type, "\u26a0\ufe0f")
        label = CONSISTENCY_ISSUE_LABELS.get(issue_type, issue_type.value)
        desc = _CONSISTENCY_DESCRIPTIONS.get(issue_type, "")
        h.append(f'<div class="legend-item"><span class="issue-badge">{icon} {_esc(label)}</span> {_esc(desc)}</div>')
    h.append("</div>")
    h.append("</div>")
    h.append("</details>")
    # Table of Contents
    h.append('<details class="toc" open>')
    h.append("<summary>Table of Contents</summary>")
    h.append("<ul>")
    h.append('<li><a href="#executive-summary">Executive Summary</a></li>')
    h.append('<li><a href="#summary">Summary by Category</a></li>')
    h.append('<li><a href="#findings">Business Logic Findings</a></li>')
    h.append('<li><a href="#consistency">Self-Consistency Issues</a></li>')
    h.append("</ul>")
    h.append("</details>")

    # --- Executive Summary ---
    h.append('<h2 id="executive-summary">Executive Summary</h2>')
    h.append('<div class="card">')
    if review.executive_summary:
        h.append(f"<p>{_esc(review.executive_summary)}</p>")
    else:
        h.append("<p>This report identifies code sections that encode core business rules, ")
        h.append("formulas, and domain logic. Every finding is flagged for human review regardless of ")
        h.append("whether static analysis tools reported issues.</p>")
    h.append("</div>")

    # Stats
    h.append('<div class="stats">')
    h.append(f'<div class="stat"><a href="#findings"><div class="stat-value">{len(review.findings)}</div><div class="stat-label">Findings</div></a></div>')
    h.append(f'<div class="stat"><a href="#consistency"><div class="stat-value">{len(review.consistency_issues)}</div><div class="stat-label">Consistency Issues</div></a></div>')
    # Count by category for stats
    cat_counts: dict[BusinessLogicCategory, int] = {}
    for f in review.findings:
        cat_counts[f.category] = cat_counts.get(f.category, 0) + 1
    h.append(f'<div class="stat"><div class="stat-value">{len(cat_counts)}</div><div class="stat-label">Categories</div></div>')
    h.append("</div>")

    h.append('<div class="back-to-top"><a href="#top">\u2191 Back to top</a></div>')

    # --- Summary by category ---
    h.append(f'<h2 id="summary">Summary by Category</h2>')
    if cat_counts:
        h.append("<table><thead><tr><th>Category</th><th>Findings</th></tr></thead><tbody>")
        for cat in BusinessLogicCategory:
            count = cat_counts.get(cat, 0)
            if count:
                icon = BUSINESS_LOGIC_CATEGORY_ICONS.get(cat, "\U0001f4cc")
                label = BUSINESS_LOGIC_CATEGORY_LABELS.get(cat, cat.value)
                h.append(f'<tr><td><span class="cat-badge cat-{cat.value}">{icon} {_esc(label)}</span></td><td>{count}</td></tr>')
        h.append("</tbody></table>")
    else:
        h.append('<div class="card">No business logic findings identified.</div>')

    h.append('<div class="back-to-top"><a href="#top">\u2191 Back to top</a></div>')

    # --- Findings ---
    h.append(f'<h2 id="findings">Business Logic Findings</h2>')
    if review.findings:
        h.append(f"<p><strong>{len(review.findings)}</strong> business logic sections identified for human review.</p>")
        current_cat: str | None = None
        finding_num = 0
        for f in review.findings:
            cat_label = BUSINESS_LOGIC_CATEGORY_LABELS.get(f.category, f.category.value)
            cat_icon = BUSINESS_LOGIC_CATEGORY_ICONS.get(f.category, "\U0001f4cc")

            if f.category.value != current_cat:
                # Close previous group
                if current_cat is not None:
                    h.append("</div></details></div>")
                current_cat = f.category.value
                cat_count = cat_counts.get(f.category, 0)
                h.append('<div class="cat-group"><details>')
                h.append("<summary>")
                h.append(f'<div class="cat-header"><h4><span class="cat-badge cat-{f.category.value}">{cat_icon} {_esc(cat_label)}</span></h4>')
                h.append(f'<span style="color: var(--text-dim); font-size: 0.8rem;">{cat_count} findings</span></div>')
                h.append("</summary>")
                h.append("<div>")

            finding_num += 1
            h.append('<div class="finding-section">')
            h.append(f'<h4>{finding_num}. {_esc(f.title)}</h4>')
            h.append(f'<div class="finding-file"><code>{_esc(f.file)}</code>:{f.start_line}-{f.end_line}</div>')
            h.append(f'<div class="finding-meta"><strong>What it does:</strong> {_esc(f.what_it_does)}</div>')
            h.append(f'<div class="finding-meta" style="color: var(--good);"><strong>Review guidance:</strong> {_esc(f.review_guidance)}</div>')
            h.append(f'<div class="finding-risk"><strong>Risk if wrong:</strong> {_esc(f.risk_if_wrong)}</div>')
            h.append(f'<details class="finding-code"><summary>View Code</summary>')
            h.append(f"<pre>{_esc(f.code_block)}</pre>")
            h.append("</details>")
            h.append("</div>")

        # Close last group
        if current_cat is not None:
            h.append("</div></details></div>")
    else:
        h.append('<div class="card">No business logic findings identified. However, a human reviewer ')
        h.append("should still verify the core functional areas of this codebase.</div>")

    h.append('<div class="back-to-top"><a href="#top">\u2191 Back to top</a></div>')

    # --- Consistency Issues ---
    h.append(f'<h2 id="consistency">Self-Consistency Issues</h2>')
    if review.consistency_issues:
        h.append(f"<p><strong>{len(review.consistency_issues)}</strong> consistency issues detected across business logic sections.</p>")
        for i, ci in enumerate(review.consistency_issues, 1):
            icon = CONSISTENCY_ISSUE_ICONS.get(ci.issue_type, "\u26a0\ufe0f")
            label = CONSISTENCY_ISSUE_LABELS.get(ci.issue_type, ci.issue_type.value)
            h.append('<div class="consistency-section">')
            h.append(f'<h4>{i}. <span class="issue-badge">{icon} {_esc(label)}</span></h4>')
            h.append(f'<div class="finding-meta"><strong>Issue:</strong> {_esc(ci.description)}</div>')
            if ci.recommended_action:
                h.append(f'<div class="finding-meta" style="color: var(--good);"><strong>Recommended action:</strong> {_esc(ci.recommended_action)}</div>')
            # Locations
            h.append('<div class="finding-meta"><strong>Locations:</strong></div>')
            for loc in ci.locations:
                h.append(f'<div class="finding-file" style="margin: 0.25rem 0.5rem;"><code>{_esc(loc.file)}</code>:{loc.start_line}-{loc.end_line}</div>')
            # Code blocks — collapsible
            if ci.code_blocks:
                h.append('<details class="finding-code"><summary>View Code</summary>')
                for j, cb in enumerate(ci.code_blocks):
                    loc_label = f"{_esc(ci.locations[j].file)}" if j < len(ci.locations) else f"Location {j + 1}"
                    h.append(f'<div class="finding-meta" style="margin-top: 0.5rem;"><strong>{loc_label}:</strong></div>')
                    h.append(f"<pre>{_esc(cb)}</pre>")
                h.append("</details>")
            h.append("</div>")
    else:
        h.append('<div class="card">No self-consistency issues detected.</div>')

    h.append('<div class="back-to-top"><a href="#top">\u2191 Back to top</a></div>')

    # Bottom navigation
    nav_parts: list[str] = []
    if summary_filename:
        nav_parts.append(f'<a href="{_esc(summary_filename)}" style="color: var(--accent); text-decoration: none;">\u2190 Back to Summary</a>')
    if sibling_report:
        sib_file, sib_label = sibling_report
        nav_parts.append(f'<a href="{_esc(sib_file)}" style="color: var(--accent); text-decoration: none;">{_esc(sib_label)} \u2192</a>')
    if nav_parts:
        h.append(f'<div style="margin-top: 2rem; padding-top: 1rem; border-top: 1px solid var(--border); display: flex; justify-content: space-between; font-size: 0.85rem;">{"".join(nav_parts)}</div>')

    h.append("</body></html>")
    return "\n".join(h)


# ---------------------------------------------------------------------------
# Summary / Entry Page (HTML only)
# ---------------------------------------------------------------------------

_SUMMARY_CSS = """
:root {
    --bg: #1a1b26; --bg-surface: #24283b; --bg-card: #1f2335;
    --text: #c0caf5; --text-dim: #6b7394; --text-bright: #e0e6ff;
    --border: #3b4261; --accent: #7aa2f7;
    --sev-critical: #f7768e; --sev-high: #ff9e64; --sev-medium: #e0af68;
    --sev-low: #9ece6a; --sev-info: #7dcfff;
    --good: #9ece6a; --attention: #e0af68; --critical: #f7768e;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: 'SF Mono', 'Fira Code', 'JetBrains Mono', monospace;
    background: var(--bg); color: var(--text);
    line-height: 1.6; padding: 2rem; max-width: 1200px; margin: 0 auto;
}
h1 { color: var(--accent); font-size: 1.5rem; margin-bottom: 0.25rem; }
h2 { color: var(--text-bright); font-size: 1.2rem; margin: 2rem 0 0.75rem; border-bottom: 1px solid var(--border); padding-bottom: 0.4rem; }
.meta { color: var(--text-dim); font-size: 0.85rem; margin-bottom: 1.5rem; }
.meta span { margin-right: 2rem; }
.action-text { color: var(--text); font-size: 0.85rem; margin-bottom: 1rem; border-left: 3px solid var(--accent); padding-left: 0.75rem; }
.report-card {
    background: var(--bg-card); border: 1px solid var(--border); border-radius: 8px;
    padding: 1.5rem; margin: 1rem 0; transition: border-color 0.2s;
}
.report-card:hover { border-color: var(--accent); }
.report-card h3 { color: var(--accent); font-size: 1.1rem; margin-bottom: 0.5rem; }
.report-card .description { color: var(--text-dim); font-size: 0.85rem; margin-bottom: 1rem; }
.report-card .stats { display: flex; gap: 1.5rem; flex-wrap: wrap; margin: 0.75rem 0; }
.report-card .stat { text-align: center; }
.report-card .stat-value { font-size: 1.3rem; font-weight: bold; color: var(--text-bright); }
.report-card .stat-label { font-size: 0.7rem; color: var(--text-dim); }
.report-link {
    display: inline-block; margin-top: 0.75rem; padding: 0.5rem 1.25rem;
    background: var(--accent); color: #1a1b26; border-radius: 4px;
    text-decoration: none; font-weight: bold; font-size: 0.85rem;
    transition: opacity 0.2s;
}
.report-link:hover { opacity: 0.85; }
.not-generated {
    background: var(--bg-card); border: 1px dashed var(--border); border-radius: 8px;
    padding: 1.25rem; margin: 1rem 0; color: var(--text-dim); font-size: 0.85rem;
}
.not-generated h3 { color: var(--text-dim); font-size: 1rem; margin-bottom: 0.4rem; }
.verdict { display: inline-block; padding: 0.2rem 0.8rem; border-radius: 4px; font-weight: bold; font-size: 0.85rem; }
.verdict-good { background: var(--good); color: #1a1b26; }
.verdict-attention { background: var(--attention); color: #1a1b26; }
.verdict-critical { background: var(--critical); color: #1a1b26; }
.sev-badge { display: inline-block; padding: 0.1rem 0.5rem; border-radius: 3px; font-size: 0.7rem; font-weight: bold; }
.sev-CRITICAL { background: var(--sev-critical); color: #1a1b26; }
.sev-HIGH { background: var(--sev-high); color: #1a1b26; }
.sev-MEDIUM { background: var(--sev-medium); color: #1a1b26; }
.sev-LOW { background: var(--sev-low); color: #1a1b26; }
.sev-INFO { background: var(--sev-info); color: #1a1b26; }
.footer { margin-top: 2rem; padding-top: 1rem; border-top: 1px solid var(--border); color: var(--text-dim); font-size: 0.75rem; }
"""


def generate_summary_html(
    target: Path,
    timestamp: str,
    detected_languages: set[str],
    *,
    technical_filename: str | None = None,
    business_filename: str | None = None,
    results: list[ToolResult] | None = None,
    critical_findings: list[CriticalFinding] | None = None,
    code_structure_critique: CodeStructureCritique | None = None,
    business_logic_review: BusinessLogicReview | None = None,
) -> str:
    lang_display = ", ".join(sorted(lang.title() for lang in detected_languages)) or "Unknown"
    human_ts = _format_timestamp_human(timestamp)

    h: list[str] = []
    h.append("<!DOCTYPE html>")
    h.append('<html lang="en"><head><meta charset="utf-8">')
    h.append('<meta name="viewport" content="width=device-width, initial-scale=1">')
    h.append(f"<title>Code Review Summary \u2014 {_esc(human_ts)}</title>")
    h.append(f"<style>{_SUMMARY_CSS}</style>")
    h.append("</head><body>")

    h.append("<h1>AIDLC Code Review</h1>")
    h.append('<div class="meta">')
    h.append(f"<span>Generated: {_esc(human_ts)}</span>")
    h.append(f"<span>Target: <code>{_esc(str(target.resolve()))}</code></span>")
    h.append(f"<span>Languages: {_esc(lang_display)}</span>")
    h.append("</div>")

    # One-line action summary
    all_findings = [f for r in (results or []) for f in r.findings]
    by_sev = _count_by_severity(all_findings)
    verdict = _overall_verdict(all_findings)
    n_biz = len(business_logic_review.findings) if business_logic_review else 0

    parts: list[str] = []
    action_text = _action_summary(by_sev, verdict, critical_findings or [], all_findings)
    if action_text:
        parts.append(action_text)
    if n_biz:
        parts.append(f"{n_biz} business logic section{'s' if n_biz != 1 else ''} flagged for human review.")
    if parts:
        h.append(f'<div class="action-text">{_esc(" ".join(parts))}</div>')

    h.append("<h2>Reports</h2>")

    # --- Business Logic Report Card (shown FIRST — primary human concern) ---
    if business_filename and business_logic_review is not None:
        n_consistency = len(business_logic_review.consistency_issues)
        cat_counts: dict[BusinessLogicCategory, int] = {}
        for f in business_logic_review.findings:
            cat_counts[f.category] = cat_counts.get(f.category, 0) + 1

        h.append('<div class="report-card">')
        h.append("<h3>\U0001f4cb Business Logic Report</h3>")
        h.append('<div class="description">AI-driven analysis of business rules, formulas, and domain logic. '
                 "Every finding is flagged for human review regardless of static tool results.</div>")
        if n_biz:
            h.append('<p><span class="verdict verdict-attention">Needs Review</span></p>')
        h.append('<div class="stats">')
        h.append(f'<div class="stat"><div class="stat-value">{n_biz}</div>'
                 '<div class="stat-label">Findings</div></div>')
        h.append(f'<div class="stat"><div class="stat-value">{n_consistency}</div>'
                 '<div class="stat-label">Consistency Issues</div></div>')
        h.append(f'<div class="stat"><div class="stat-value">{len(cat_counts)}</div>'
                 '<div class="stat-label">Categories</div></div>')
        h.append("</div>")
        h.append(f'<a class="report-link" href="{_esc(business_filename)}">Open Business Logic Report \u2192</a>')
        h.append("</div>")
    else:
        h.append('<div class="not-generated">')
        h.append("<h3>\U0001f4cb Business Logic Report</h3>")
        h.append("<p>Not generated. Run with default mode or <code>--business-report</code> to include it.</p>")
        h.append("</div>")

    # --- Technical Report Card ---
    if technical_filename and results is not None:
        n_critical = len(critical_findings) if critical_findings else 0
        n_dimensions = len(code_structure_critique.dimensions) if code_structure_critique else 0

        h.append('<div class="report-card">')
        h.append("<h3>\U0001f527 Technical Report</h3>")
        h.append('<div class="description">Static analysis findings, critical code sections flagged for human review, '
                 "and AI-powered code structure critique.</div>")
        h.append(f'<p><span class="verdict {_verdict_class(verdict)}">{_esc(verdict)}</span></p>')
        h.append('<div class="stats">')
        h.append(f'<div class="stat"><div class="stat-value">{len(all_findings)}</div>'
                 '<div class="stat-label">Findings</div></div>')
        for sev in SEV_ORDER:
            count = by_sev.get(sev.value, 0)
            if count:
                h.append(f'<div class="stat"><div class="stat-value">{count}</div>'
                         f'<div class="stat-label"><span class="sev-badge sev-{sev.value}">{sev.value}</span></div></div>')
        if n_critical:
            h.append(f'<div class="stat"><div class="stat-value">{n_critical}</div>'
                     '<div class="stat-label">Critical Sections</div></div>')
        if n_dimensions:
            h.append(f'<div class="stat"><div class="stat-value">{n_dimensions}</div>'
                     '<div class="stat-label">Structure Dimensions</div></div>')
        h.append("</div>")
        h.append(f'<a class="report-link" href="{_esc(technical_filename)}">Open Technical Report \u2192</a>')
        h.append("</div>")
    else:
        h.append('<div class="not-generated">')
        h.append("<h3>\U0001f527 Technical Report</h3>")
        h.append("<p>Not generated. Run with default mode or <code>--technical-report</code> to include it.</p>")
        h.append("</div>")

    h.append('<div class="footer">')
    h.append(f"Generated by AIDLC Code Reviewer \u2014 {_esc(human_ts)}")
    h.append("</div>")

    h.append("</body></html>")
    return "\n".join(h)


# ---------------------------------------------------------------------------
# Summary / Entry Page (HTML only)
# ---------------------------------------------------------------------------

_SUMMARY_CSS = """
:root {
    --bg: #1a1b26; --bg-surface: #24283b; --bg-card: #1f2335;
    --text: #c0caf5; --text-dim: #565f89; --text-bright: #e0e6ff;
    --border: #3b4261; --accent: #7aa2f7;
    --sev-critical: #f7768e; --sev-high: #ff9e64; --sev-medium: #e0af68;
    --sev-low: #9ece6a; --sev-info: #7dcfff;
    --good: #9ece6a; --attention: #e0af68; --critical: #f7768e;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: 'SF Mono', 'Fira Code', 'JetBrains Mono', monospace;
    background: var(--bg); color: var(--text);
    line-height: 1.6; padding: 2rem; max-width: 1200px; margin: 0 auto;
}
h1 { color: var(--accent); font-size: 1.5rem; margin-bottom: 0.25rem; }
h2 { color: var(--text-bright); font-size: 1.2rem; margin: 2rem 0 0.75rem; border-bottom: 1px solid var(--border); padding-bottom: 0.4rem; }
.meta { color: var(--text-dim); font-size: 0.85rem; margin-bottom: 1.5rem; }
.meta span { margin-right: 2rem; }
.report-card {
    background: var(--bg-card); border: 1px solid var(--border); border-radius: 8px;
    padding: 1.5rem; margin: 1rem 0; transition: border-color 0.2s;
}
.report-card:hover { border-color: var(--accent); }
.report-card h3 { color: var(--accent); font-size: 1.1rem; margin-bottom: 0.5rem; }
.report-card .description { color: var(--text-dim); font-size: 0.85rem; margin-bottom: 1rem; }
.report-card .stats { display: flex; gap: 1.5rem; flex-wrap: wrap; margin: 0.75rem 0; }
.report-card .stat { text-align: center; }
.report-card .stat-value { font-size: 1.3rem; font-weight: bold; color: var(--text-bright); }
.report-card .stat-label { font-size: 0.7rem; color: var(--text-dim); }
.report-link {
    display: inline-block; margin-top: 0.75rem; padding: 0.5rem 1.25rem;
    background: var(--accent); color: #1a1b26; border-radius: 4px;
    text-decoration: none; font-weight: bold; font-size: 0.85rem;
    transition: opacity 0.2s;
}
.report-link:hover { opacity: 0.85; }
.not-generated {
    background: var(--bg-card); border: 1px dashed var(--border); border-radius: 8px;
    padding: 1.25rem; margin: 1rem 0; color: var(--text-dim); font-size: 0.85rem;
}
.not-generated h3 { color: var(--text-dim); font-size: 1rem; margin-bottom: 0.4rem; }
.verdict { display: inline-block; padding: 0.2rem 0.8rem; border-radius: 4px; font-weight: bold; font-size: 0.85rem; }
.verdict-good { background: var(--good); color: #1a1b26; }
.verdict-attention { background: var(--attention); color: #1a1b26; }
.verdict-critical { background: var(--critical); color: #1a1b26; }
.sev-badge { display: inline-block; padding: 0.1rem 0.5rem; border-radius: 3px; font-size: 0.7rem; font-weight: bold; }
.sev-CRITICAL { background: var(--sev-critical); color: #1a1b26; }
.sev-HIGH { background: var(--sev-high); color: #1a1b26; }
.sev-MEDIUM { background: var(--sev-medium); color: #1a1b26; }
.sev-LOW { background: var(--sev-low); color: #1a1b26; }
.sev-INFO { background: var(--sev-info); color: #1a1b26; }
.footer { margin-top: 2rem; padding-top: 1rem; border-top: 1px solid var(--border); color: var(--text-dim); font-size: 0.75rem; }
"""


def generate_summary_html(
    target: Path,
    timestamp: str,
    detected_languages: set[str],
    *,
    technical_filename: str | None = None,
    business_filename: str | None = None,
    results: list[ToolResult] | None = None,
    critical_findings: list[CriticalFinding] | None = None,
    code_structure_critique: CodeStructureCritique | None = None,
    business_logic_review: BusinessLogicReview | None = None,
) -> str:
    """Generate a lightweight HTML entry page linking to the individual reports."""
    lang_display = ", ".join(sorted(lang.title() for lang in detected_languages)) or "Unknown"
    human_ts = _format_timestamp_human(timestamp)

    h: list[str] = []
    h.append("<!DOCTYPE html>")
    h.append('<html lang="en"><head><meta charset="utf-8">')
    h.append('<meta name="viewport" content="width=device-width, initial-scale=1">')
    h.append(f"<title>Code Review Summary \u2014 {_esc(human_ts)}</title>")
    h.append(f"<style>{_SUMMARY_CSS}</style>")
    h.append("</head><body>")

    # Header
    h.append("<h1>AIDLC Code Review</h1>")
    h.append('<div class="meta">')
    h.append(f"<span>Generated: {_esc(human_ts)}</span>")
    h.append(f"<span>Target: <code>{_esc(str(target.resolve()))}</code></span>")
    h.append(f"<span>Languages: {_esc(lang_display)}</span>")
    h.append("</div>")

    h.append("<h2>Reports</h2>")

    # --- Technical Report Card ---
    if technical_filename and results is not None:
        all_findings = [f for r in results for f in r.findings]
        by_sev = _count_by_severity(all_findings)
        verdict = _overall_verdict(all_findings)
        n_critical = len(critical_findings) if critical_findings else 0
        n_dimensions = len(code_structure_critique.dimensions) if code_structure_critique else 0

        h.append('<div class="report-card">')
        h.append("<h3>\U0001f527 Technical Report</h3>")
        h.append('<div class="description">Static analysis findings, critical code sections flagged for human review, '
                 "and AI-powered code structure critique.</div>")

        # Verdict
        h.append(f'<p><span class="verdict {_verdict_class(verdict)}">{_esc(verdict)}</span></p>')

        # Stats
        h.append('<div class="stats">')
        h.append(f'<div class="stat"><div class="stat-value">{len(all_findings)}</div>'
                 '<div class="stat-label">Findings</div></div>')
        for sev in SEV_ORDER:
            count = by_sev.get(sev.value, 0)
            if count:
                h.append(f'<div class="stat"><div class="stat-value">{count}</div>'
                         f'<div class="stat-label"><span class="sev-badge sev-{sev.value}">{sev.value}</span></div></div>')
        if n_critical:
            h.append(f'<div class="stat"><div class="stat-value">{n_critical}</div>'
                     '<div class="stat-label">Critical Sections</div></div>')
        if n_dimensions:
            h.append(f'<div class="stat"><div class="stat-value">{n_dimensions}</div>'
                     '<div class="stat-label">Structure Dimensions</div></div>')
        h.append("</div>")

        h.append(f'<a class="report-link" href="{_esc(technical_filename)}">Open Technical Report \u2192</a>')
        h.append("</div>")
    else:
        h.append('<div class="not-generated">')
        h.append("<h3>\U0001f527 Technical Report</h3>")
        h.append("<p>Not generated. Run with default mode or <code>--technical-report</code> to include it.</p>")
        h.append("</div>")

    # --- Business Logic Report Card ---
    if business_filename and business_logic_review is not None:
        n_findings = len(business_logic_review.findings)
        n_consistency = len(business_logic_review.consistency_issues)
        cat_counts: dict[BusinessLogicCategory, int] = {}
        for f in business_logic_review.findings:
            cat_counts[f.category] = cat_counts.get(f.category, 0) + 1

        h.append('<div class="report-card">')
        h.append("<h3>\U0001f4cb Business Logic Report</h3>")
        h.append('<div class="description">AI-driven analysis of business rules, formulas, and domain logic. '
                 "Every finding is flagged for human review regardless of static tool results.</div>")

        # Stats
        h.append('<div class="stats">')
        h.append(f'<div class="stat"><div class="stat-value">{n_findings}</div>'
                 '<div class="stat-label">Findings</div></div>')
        h.append(f'<div class="stat"><div class="stat-value">{n_consistency}</div>'
                 '<div class="stat-label">Consistency Issues</div></div>')
        h.append(f'<div class="stat"><div class="stat-value">{len(cat_counts)}</div>'
                 '<div class="stat-label">Categories</div></div>')
        h.append("</div>")

        h.append(f'<a class="report-link" href="{_esc(business_filename)}">Open Business Logic Report \u2192</a>')
        h.append("</div>")
    else:
        h.append('<div class="not-generated">')
        h.append("<h3>\U0001f4cb Business Logic Report</h3>")
        h.append("<p>Not generated. Run with default mode or <code>--business-report</code> to include it.</p>")
        h.append("</div>")

    # Footer
    h.append('<div class="footer">')
    h.append(f"Generated by AIDLC Code Reviewer \u2014 {_esc(human_ts)}")
    h.append("</div>")

    h.append("</body></html>")
    return "\n".join(h)
