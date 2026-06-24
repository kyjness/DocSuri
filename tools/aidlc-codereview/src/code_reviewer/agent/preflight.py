"""Pre-flight verification for the agent subsystem.

Checks that all dependencies, credentials, and model access are in place
before the CLI runs. Designed to be called early so users get clear,
actionable errors instead of cryptic failures mid-run.
"""

import logging
import shutil
import sys
from pathlib import Path

from code_reviewer.common.config import load_config

logger = logging.getLogger("aidlc_code_reviewer.preflight")


def _check_python_packages() -> list[str]:
    """Check that all agent Python dependencies are importable."""
    errors = []
    required = {
        "strands": "strands-agents",
        "boto3": "boto3",
        "backoff": "backoff",
        "pydantic": "pydantic>=2.0",
        "bs4": "beautifulsoup4",
    }
    for module_name, pip_name in required.items():
        try:
            __import__(module_name)
        except ImportError:
            errors.append(f"Missing package '{pip_name}' (import {module_name} failed)")
    return errors


def _check_aws_credentials(region: str, profile_name: str | None) -> list[str]:
    """Check that AWS credentials are configured and can call STS."""
    errors = []
    logger.info(  # nosemgrep: python-logger-credential-disclosure
        "Loading AWS credentials: profile=%s, region=%s",
        profile_name or "(default)",
        region,
    )
    try:
        import boto3

        kwargs = {"region_name": region}
        if profile_name:
            kwargs["profile_name"] = profile_name

        session = boto3.Session(**kwargs)
        sts = session.client("sts")
        identity = sts.get_caller_identity()
        account = identity.get("Account", "unknown")
        arn = identity.get("Arn", "unknown")
        logger.info(  # nosemgrep: python-logger-credential-disclosure
            "AWS credentials loaded: profile=%s, region=%s, account=%s, arn=%s",
            profile_name or "(default)",
            region,
            account,
            arn,
        )
        print(f"  AWS identity: {arn} (account {account})")
    except Exception as e:
        logger.warning(  # nosemgrep: python-logger-credential-disclosure
            "AWS credentials check failed: profile=%s, region=%s, error=%s",
            profile_name or "(default)",
            region,
            e,
        )
        errors.append(f"AWS credentials check failed: {e}")
    return errors


def _check_bedrock_access(model_id: str, region: str, profile_name: str | None) -> list[str]:
    """Check that the Amazon Bedrock model is accessible with a minimal invoke."""
    errors = []
    try:
        import boto3

        kwargs = {"region_name": region}
        if profile_name:
            kwargs["profile_name"] = profile_name

        session = boto3.Session(**kwargs)
        client = session.client("bedrock-runtime", region_name=region)

        # Minimal converse call to verify model access
        response = client.converse(
            modelId=model_id,
            messages=[{
                "role": "user",
                "content": [{"text": "Say OK"}],
            }],
            inferenceConfig={"maxTokens": 10},
        )
        stop = response.get("stopReason", "unknown")
        print(f"  Amazon Bedrock model '{model_id}' is accessible (stop: {stop})")
    except Exception as e:
        error_name = type(e).__name__
        errors.append(f"Amazon Bedrock model access failed ({error_name}): {e}")
    return errors


def _check_configured_tools(config_path: Path | None) -> list[str]:
    """Check which configured CLI tools are installed on PATH."""
    warnings = []
    try:
        config = load_config(config_path)
    except Exception as e:
        return [f"Could not load config: {e}"]

    from code_reviewer.tools.registry import get_wrapper

    for tool_cfg in config.tools:
        wrapper = get_wrapper(tool_cfg.name)
        command = tool_cfg.command or tool_cfg.name
        installed = shutil.which(command) is not None

        if wrapper and installed:
            status = "wrapper + CLI"
        elif wrapper and not installed:
            status = "wrapper only (CLI not on PATH — will fail at runtime)"
            warnings.append(f"'{tool_cfg.name}': has wrapper but '{command}' not on PATH")
        elif not wrapper and installed:
            status = "CLI only (wrapper will be auto-generated)"
        else:
            status = "missing both (wrapper will be auto-generated, needs CLI installed)"
            warnings.append(f"'{tool_cfg.name}': no wrapper and '{command}' not on PATH")

        print(f"  {tool_cfg.name:<20s} {status}")

    return warnings


def run_preflight(config_path: Path | None = None) -> bool:
    """Run all pre-flight checks. Returns True if all critical checks pass."""
    all_errors: list[str] = []
    all_warnings: list[str] = []

    print("\n=== Pre-flight Check: Agent Setup ===\n")

    # 1. Python packages
    print("[1/4] Checking agent Python packages...")
    pkg_errors = _check_python_packages()
    if pkg_errors:
        all_errors.extend(pkg_errors)
        print(f"  FAIL: {len(pkg_errors)} missing package(s)")
        for e in pkg_errors:
            print(f"    - {e}")
        print(f"  Fix: pip install -e .")
    else:
        print("  OK: All agent packages installed")

    # 2. Agent config
    print("\n[2/4] Checking agent configuration...")
    try:
        from code_reviewer.agent.config import load_agent_config
        agent_cfg = load_agent_config()
        print(f"  Model:   {agent_cfg.model_id}")
        print(f"  Region:  {agent_cfg.region}")
        print(f"  Profile: {agent_cfg.profile_name or '(default)'}")
        print(f"  Retries: {agent_cfg.max_retries}")
    except Exception as e:
        all_errors.append(f"Agent config failed: {e}")
        print(f"  FAIL: {e}")
        agent_cfg = None

    # 3. AWS credentials + Amazon Bedrock access
    print("\n[3/4] Checking AWS credentials...")
    if agent_cfg and not pkg_errors:
        cred_errors = _check_aws_credentials(agent_cfg.region, agent_cfg.profile_name)
        if cred_errors:
            all_errors.extend(cred_errors)
            for e in cred_errors:
                print(f"  FAIL: {e}")
        else:
            print("\n  Checking Amazon Bedrock model access...")
            bedrock_errors = _check_bedrock_access(
                agent_cfg.model_id, agent_cfg.region, agent_cfg.profile_name
            )
            if bedrock_errors:
                all_errors.extend(bedrock_errors)
                for e in bedrock_errors:
                    print(f"  FAIL: {e}")
    else:
        print("  SKIP: Cannot check without agent packages/config")

    # 4. Configured tools
    print("\n[4/4] Checking configured tools...")
    tool_warnings = _check_configured_tools(config_path)
    all_warnings.extend(tool_warnings)

    # Summary
    print("\n=== Pre-flight Summary ===\n")
    if all_errors:
        print(f"ERRORS ({len(all_errors)}):")
        for e in all_errors:
            print(f"  ✗ {e}")
    if all_warnings:
        print(f"WARNINGS ({len(all_warnings)}):")
        for w in all_warnings:
            print(f"  ! {w}")
    if not all_errors and not all_warnings:
        print("All checks passed. Agent is ready.")
    elif not all_errors:
        print("\nNo critical errors. Agent can run (warnings above may cause skips).")
    else:
        print(f"\n{len(all_errors)} critical error(s). Fix these before using the agent.")

    return len(all_errors) == 0
