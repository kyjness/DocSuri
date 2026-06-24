"""Core agent that generates, verifies, and registers tool wrappers."""

# Copyright 2026 Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import importlib.util
import logging
import sys
from pathlib import Path
from typing import Any

from code_reviewer.agent.base_agent import BaseAgent
from code_reviewer.agent.config import AgentConfig
from code_reviewer.common.output import vprint
from code_reviewer.agent.models import GenerationResult, GenerationStatus, VerificationResult
from code_reviewer.agent.prompt_builder import build_prompt
from code_reviewer.agent.response_parser import extract_code
from code_reviewer.agent.verification import verify_level1, verify_level2
from code_reviewer.common.config import ToolConfig
from code_reviewer.tools.registry import register_wrapper

logger = logging.getLogger("aidlc_code_reviewer.agent")

_TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"


def _write_and_register(tool_name: str, source: str) -> Path:
    """Write wrapper source to tools/<name>.py and register it."""
    # Sanitize name for filename
    safe_name = tool_name.replace("-", "_").replace(" ", "_")
    wrapper_path = _TOOLS_DIR / f"{safe_name}.py"
    wrapper_path.write_text(source)

    # Import and register
    spec = importlib.util.spec_from_file_location(f"tools.{safe_name}", str(wrapper_path))
    if spec and spec.loader:
        project_root = str(Path(__file__).resolve().parent.parent.parent)
        if project_root not in sys.path:
            sys.path.insert(0, project_root)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        register_wrapper(tool_name, module)

    return wrapper_path


class WrapperGeneratorAgent(BaseAgent):
    """Agent that auto-generates tool wrapper modules."""

    def __init__(self, config: AgentConfig | None = None) -> None:
        super().__init__(config)

    def execute(self, tool_config: ToolConfig | None = None, target: Path | None = None, **kwargs: Any) -> GenerationResult:
        """Generate a wrapper for the given tool configuration.

        Steps:
        2. Build prompt
        3. Invoke LLM, extract code
        4. Verify Level 1 (static) — retry with error feedback on failure
        5. Verify Level 2 (live) — retry with error feedback on failure
        6. Write and register wrapper
        """
        if tool_config is None:
            return GenerationResult(
                status=GenerationStatus.FAILED,
                tool_name="unknown",
                error="tool_config is required",
            )

        tool_name = tool_config.name
        max_retries = self.config.max_retries

        # 1. Build prompt
        doc_text = ""
        prompt = build_prompt(tool_config, doc_text)

        # 3-7. Generate, verify (Level 1 + Level 2), retry on failure
        last_errors: list[str] = []
        last_error_level: int = 0
        source: str | None = None
        token_usage: dict = {}
        v1: VerificationResult | None = None
        v2: VerificationResult | None = None
        live_tool_result = None

        for attempt in range(max_retries + 1):
            # Invoke LLM
            if attempt == 0:
                current_prompt = prompt
            else:
                error_feedback = "\n".join(f"- {e}" for e in last_errors)
                level_label = f"Level {last_error_level}" if last_error_level else "verification"
                current_prompt = (
                    f"{prompt}\n\n"
                    f"## IMPORTANT: Fix These Issues\n\n"
                    f"Your previous attempt failed {level_label} with these errors:\n{error_feedback}\n\n"
                    f"Please fix ALL of these issues in your new response."
                )

            try:
                response_text, usage = self._invoke_model(current_prompt)
                token_usage = usage
            except Exception as e:
                return GenerationResult(
                    status=GenerationStatus.FAILED,
                    tool_name=tool_name,
                    error=f"LLM invocation failed: {e}",
                    token_usage=token_usage,
                )

            # Extract code
            code, extract_err = extract_code(response_text)
            if code is None:
                last_errors = [extract_err or "Code extraction failed"]
                last_error_level = 0
                if attempt < max_retries:
                    logger.warning(
                        "Attempt %d: code extraction failed, retrying", attempt + 1
                    )
                    continue
                return GenerationResult(
                    status=GenerationStatus.FAILED,
                    tool_name=tool_name,
                    error=extract_err,
                    token_usage=token_usage,
                )

            source = code

            # Level 1 verification
            v1 = verify_level1(source, tool_config.category)
            if not v1.passed:
                last_errors = v1.errors
                last_error_level = 1
                if attempt < max_retries:
                    logger.warning(
                        "Attempt %d: Level 1 verification failed (%s), retrying",
                        attempt + 1,
                        "; ".join(v1.errors),
                    )
                    continue
                return GenerationResult(
                    status=GenerationStatus.VERIFICATION_FAILED,
                    tool_name=tool_name,
                    verification=v1,
                    error=f"Level 1 verification failed: {'; '.join(v1.errors)}",
                    token_usage=token_usage,
                )

            # Level 1 passed
            vprint(f"  Level 1 (static) verification passed for '{tool_name}'", flush=True)

            # Level 2 verification (if tool is installed and target provided)
            if target is not None:
                v2, live_tool_result = verify_level2(source, tool_config.command, target)
                if v2.passed:
                    logger.info("Level 2 (live) verification passed for %s", tool_name)
                    vprint(f"  Level 2 (live) verification passed for '{tool_name}'", flush=True)
                    break  # Both levels passed
                else:
                    last_errors = v2.errors
                    last_error_level = 2
                    if attempt < max_retries:
                        logger.warning(
                            "Attempt %d: Level 2 verification failed (%s), retrying",
                            attempt + 1,
                            "; ".join(v2.errors),
                        )
                        continue
                    # Final attempt failed Level 2 — report failure
                    print(
                        f"  Level 2 verification failed for '{tool_name}' "
                        f"after {max_retries + 1} attempts: {'; '.join(v2.errors)}",
                        flush=True,
                    )
                    return GenerationResult(
                        status=GenerationStatus.VERIFICATION_FAILED,
                        tool_name=tool_name,
                        verification=v2,
                        error=f"Level 2 verification failed: {'; '.join(v2.errors)}",
                        token_usage=token_usage,
                    )
            else:
                break  # No target for Level 2, accept with Level 1 only

        if source is None:
            return GenerationResult(
                status=GenerationStatus.FAILED,
                tool_name=tool_name,
                error="No source code generated",
                token_usage=token_usage,
            )

        # 8-9. Write and register
        try:
            wrapper_path = _write_and_register(tool_name, source)
        except Exception as e:
            return GenerationResult(
                status=GenerationStatus.FAILED,
                tool_name=tool_name,
                error=f"Failed to write/register wrapper: {e}",
                token_usage=token_usage,
            )

        return GenerationResult(
            status=GenerationStatus.SUCCESS,
            tool_name=tool_name,
            wrapper_path=wrapper_path,
            verification=v2 or v1,
            token_usage=token_usage,
            tool_result=live_tool_result,
        )
