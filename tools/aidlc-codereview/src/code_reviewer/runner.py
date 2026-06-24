"""Unified CLI entry point for AIDLC Code Reviewer.

Usage:
    aidlc-code-reviewer <target> [--config path] [--output-dir path] [--verbose]
    aidlc-code-reviewer <target> --technical-report   # technical report only
    aidlc-code-reviewer <target> --business-report    # business logic report only
"""

# Copyright 2026 Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import argparse
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from code_reviewer.common.config import load_config
from code_reviewer.common.language_detector import detect_languages
from code_reviewer.common.models import BusinessLogicReview, CodeStructureCritique, CriticalFinding, SkipRecord, ToolResult
from code_reviewer.common.output import set_verbose, vprint
from code_reviewer.common.report import (
    generate_business_logic_html,
    generate_business_logic_markdown,
    generate_html,
    generate_markdown,
    generate_summary_html,
)
from code_reviewer.common.spinner import Spinner
from code_reviewer.tools.registry import get_wrapper, get_supported_languages


def _run_critical_findings(target: Path, results: list[ToolResult]) -> list[CriticalFinding]:
    """Run the critical findings agent after all tools complete.

    Returns empty list on failure (non-blocking).
    """
    try:
        from code_reviewer.agent.critical_findings_agent import CriticalFindingsAgent

        vprint("\n--- Critical Code Findings Analysis ---", flush=True)
        agent = CriticalFindingsAgent()
        return agent.execute(target=target, results=results)
    except ImportError:
        print("  Agent dependencies not installed, skipping critical findings.", file=sys.stderr)
        return []
    except Exception as exc:
        print(f"  Critical findings analysis error: {exc}", file=sys.stderr)
        return []


def _run_code_structure_critique(
    target: Path,
    results: list[ToolResult],
    critical_findings: list[CriticalFinding],
) -> CodeStructureCritique | None:
    """Run the code structure critique agent.

    Returns None on failure (non-blocking).
    """
    try:
        from code_reviewer.agent.code_structure_agent import CodeStructureAgent

        vprint("\n--- Code Structure Critique ---", flush=True)
        agent = CodeStructureAgent()
        return agent.execute(target=target, results=results, critical_findings=critical_findings)
    except ImportError:
        print("  Agent dependencies not installed, skipping structure critique.", file=sys.stderr)
        return None
    except Exception as exc:
        print(f"  Structure critique error: {exc}", file=sys.stderr)
        return None


def _run_business_logic_review(target: Path) -> BusinessLogicReview | None:
    """Run the business logic review agent.

    Returns None on failure (non-blocking).
    """
    try:
        from code_reviewer.agent.business_logic_agent import BusinessLogicAgent

        vprint("\n--- Business Logic Review ---", flush=True)
        agent = BusinessLogicAgent()
        return agent.execute(target=target)
    except ImportError:
        print("  Agent dependencies not installed, skipping business logic review.", file=sys.stderr)
        return None
    except Exception as exc:
        print(f"  Business logic review error: {exc}", file=sys.stderr)
        return None


def _run_single_tool(
    tool_cfg,
    target: Path,
    detected: set[str],
    no_generate: bool,
) -> ToolResult | SkipRecord:
    """Run a single tool's full pipeline: generate wrapper if needed, check language, execute.

    Returns either a ToolResult (success or tool error) or a SkipRecord.
    """
    wrapper = get_wrapper(tool_cfg.name)
    cached_result: ToolResult | None = None

    if wrapper is None and not no_generate:
        vprint(f"  Generating wrapper for '{tool_cfg.name}'...", flush=True)
        try:
            from code_reviewer.agent.wrapper_generator import WrapperGeneratorAgent
            from code_reviewer.agent.models import GenerationStatus

            gen_agent = WrapperGeneratorAgent()
            gen_result = gen_agent.execute(tool_config=tool_cfg, target=target)
            if gen_result.status == GenerationStatus.SUCCESS:
                wrapper = get_wrapper(tool_cfg.name)
                cached_result = gen_result.tool_result
                vprint(f"  Generated wrapper for '{tool_cfg.name}'", flush=True)
            else:
                print(f"  Generation failed for '{tool_cfg.name}': {gen_result.error}", file=sys.stderr)
        except ImportError:
            print("  Agent dependencies not installed, skipping generation.", file=sys.stderr)
        except Exception as exc:
            print(f"  Generation error for '{tool_cfg.name}': {exc}", file=sys.stderr)

    category = getattr(wrapper, "CATEGORY", None) or tool_cfg.category or "unknown"

    if wrapper is None:
        return SkipRecord(
            tool=tool_cfg.name,
            category=category,
            reason=f"No wrapper for '{tool_cfg.name}'",
        )

    supported = get_supported_languages(tool_cfg.name)
    if "*" not in supported and not (set(supported) & detected):
        reason = f"No {', '.join(supported)} files detected"
        vprint(f"  Skipping {tool_cfg.name} — {reason}", flush=True)
        return SkipRecord(tool=tool_cfg.name, category=category, reason=reason)

    if cached_result is not None:
        vprint(f"  Running {tool_cfg.name}...", flush=True)
        result = cached_result
    else:
        vprint(f"  Running {tool_cfg.name}...", flush=True)
        try:
            result = wrapper.run(target)
        except Exception as exc:
            result = ToolResult(
                tool=tool_cfg.name,
                category=category,
                success=False,
                error=str(exc),
            )

    if not result.success:
        reason = result.error or "Tool returned an error"
        vprint(f"  Skipping {tool_cfg.name} — {reason}", flush=True)
        return SkipRecord(tool=tool_cfg.name, category=category, reason=reason)

    return result


def run_review(
    target: Path,
    config_path: Path | None = None,
    no_generate: bool = False,
) -> tuple[list[ToolResult], list[SkipRecord], set[str]]:
    """Run all configured tools against target in parallel, returning results and skip records."""
    config = load_config(config_path)
    detected = detect_languages(target)

    if not detected:
        print("Warning: No recognized programming languages detected in target.", file=sys.stderr)

    results: list[ToolResult] = []
    skipped: list[SkipRecord] = []

    with ThreadPoolExecutor() as executor:
        futures = {
            executor.submit(_run_single_tool, tool_cfg, target, detected, no_generate): tool_cfg
            for tool_cfg in config.tools
        }
        for future in as_completed(futures):
            outcome = future.result()
            if isinstance(outcome, SkipRecord):
                skipped.append(outcome)
            else:
                results.append(outcome)

    return results, skipped, detected


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="aidlc-code-reviewer",
        description="AIDLC Code Reviewer — automated code quality analysis.",
    )
    parser.add_argument("target", type=Path, nargs="?", default=None, help="Path to directory or file to analyze")
    parser.add_argument(
        "-c", "--config", type=Path, default=None,
        help="Path to review-config.yaml (default: built-in config)",
    )
    parser.add_argument(
        "-o", "--output-dir", type=Path, default=None,
        help="Output directory for reports (default: ./reports/)",
    )
    parser.add_argument(
        "--no-generate", action="store_true", default=False,
        help="Skip auto-generation of missing tool wrappers",
    )
    parser.add_argument(
        "--preflight", action="store_true", default=False,
        help="Run pre-flight checks for agent setup, then exit",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", default=False,
        help="Show detailed progress output for each tool and agent step",
    )
    parser.add_argument(
        "--technical-report", action="store_true", default=False,
        help="Generate only the technical report (static tools + critical findings + structure critique)",
    )
    parser.add_argument(
        "--business-report", action="store_true", default=False,
        help="Generate only the business logic review report (AI-driven, no static tools)",
    )
    args = parser.parse_args()

    # Configure verbose output and logging
    set_verbose(args.verbose)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.ERROR,
        format="%(message)s",
    )

    # Pre-flight check mode
    if args.preflight:
        try:
            from code_reviewer.agent.preflight import run_preflight
            ok = run_preflight(config_path=args.config)
            sys.exit(0 if ok else 1)
        except ImportError:
            print("Error: Agent packages not installed. Run: pip install -e .", file=sys.stderr)
            sys.exit(1)

    if args.target is None:
        parser.error("the following arguments are required: target")

    target = args.target.resolve()
    if not target.exists():
        print(f"Error: target not found: {target}", file=sys.stderr)
        sys.exit(1)

    # Determine which reports to generate.
    # Default (no flags): both. If either flag is set, only that report type.
    run_technical = not args.business_report or args.technical_report
    run_business = not args.technical_report or args.business_report
    # If both flags are explicitly set, run both (same as default).
    if args.technical_report and args.business_report:
        run_technical = True
        run_business = True

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ts_file = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    print("Activating AIDLC Code Reviewer...")
    vprint(f"  Target: {target}")

    results: list[ToolResult] = []
    skipped: list[SkipRecord] = []
    detected: set[str] = set()
    critical_findings: list[CriticalFinding] = []
    structure_critique: CodeStructureCritique | None = None
    business_logic_review: BusinessLogicReview | None = None

    # --- Technical report pipeline ---
    if run_technical:
        with Spinner("Running code review"):
            results, skipped, detected = run_review(target, args.config, no_generate=args.no_generate)

        total_findings = sum(len(r.findings) for r in results)
        print(f"  Tools run: {len(results)}, Skipped: {len(skipped)}, "
              f"Findings: {total_findings}")

        with Spinner("Analyzing critical findings"):
            critical_findings = _run_critical_findings(target, results)

        with Spinner("Generating structure critique"):
            structure_critique = _run_code_structure_critique(target, results, critical_findings)
    else:
        # Still need detected languages for the business report header
        detected = detect_languages(target)

    # --- Business logic report pipeline ---
    if run_business:
        with Spinner("Analyzing business logic"):
            business_logic_review = _run_business_logic_review(target)

    # --- Write reports ---
    output_dir = args.output_dir or Path("reports")
    output_dir.mkdir(parents=True, exist_ok=True)

    # Build filenames
    summary_html_name = f"code_review_summary_{ts_file}.html"
    tech_html_name = f"code_review_technical_{ts_file}.html"
    tech_md_name = f"code_review_technical_{ts_file}.md"
    biz_html_name = f"code_review_business_{ts_file}.html"
    biz_md_name = f"code_review_business_{ts_file}.md"

    # When both reports are generated, remove critical findings already covered
    # by the business logic report to avoid duplicate reporting.
    tech_critical_findings = critical_findings
    if business_logic_review and critical_findings:
        biz_files = {
            (Path(blf.file).name, blf.start_line)
            for blf in business_logic_review.findings
        }
        tech_critical_findings = [
            cf for cf in critical_findings
            if (Path(cf.file).name, cf.start_line) not in biz_files
        ]

    with Spinner("Writing reports"):
        if run_technical:
            md_path = output_dir / tech_md_name
            html_path = output_dir / tech_html_name

            md_content = generate_markdown(target, results, skipped, timestamp, detected, tech_critical_findings, structure_critique)
            tech_sibling = (biz_html_name, "Business Logic Report") if run_business else None
            html_content = generate_html(
                target, results, skipped, timestamp, detected,
                tech_critical_findings, structure_critique,
                summary_filename=summary_html_name,
                sibling_report=tech_sibling,
            )

            md_path.write_text(md_content)
            html_path.write_text(html_content)

        if run_business and business_logic_review:
            biz_md_path = output_dir / biz_md_name
            biz_html_path = output_dir / biz_html_name

            biz_md_content = generate_business_logic_markdown(target, timestamp, detected, business_logic_review)
            biz_sibling = (tech_html_name, "Technical Report") if run_technical else None
            biz_html_content = generate_business_logic_html(
                target, timestamp, detected, business_logic_review,
                summary_filename=summary_html_name,
                sibling_report=biz_sibling,
            )

            biz_md_path.write_text(biz_md_content)
            biz_html_path.write_text(biz_html_content)

        # Summary entry page (always generated)
        summary_path = output_dir / summary_html_name
        summary_content = generate_summary_html(
            target, timestamp, detected,
            technical_filename=tech_html_name if run_technical else None,
            business_filename=biz_html_name if (run_business and business_logic_review) else None,
            results=results if run_technical else None,
            critical_findings=critical_findings if run_technical else None,
            code_structure_critique=structure_critique if run_technical else None,
            business_logic_review=business_logic_review if run_business else None,
        )
        summary_path.write_text(summary_content)

    # --- Print summary ---
    if run_technical:
        print(f"  Critical sections: {len(critical_findings)}")
    if run_business and business_logic_review:
        print(f"  Business logic findings: {len(business_logic_review.findings)}, "
              f"Consistency issues: {len(business_logic_review.consistency_issues)}")
    print()
    print(f"  Reports:")
    print(f"    \u2192 Start here:          {summary_path}")
    if run_technical:
        print(f"    Technical (Markdown): {md_path}")
        print(f"    Technical (HTML):     {html_path}")
    if run_business and business_logic_review:
        print(f"    Business Logic (Markdown): {biz_md_path}")
        print(f"    Business Logic (HTML):     {biz_html_path}")


if __name__ == "__main__":
    main()
