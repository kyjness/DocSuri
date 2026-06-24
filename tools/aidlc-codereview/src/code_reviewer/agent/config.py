"""Configuration for the agent subsystem.

Reads from agent-config.yaml or environment variables.
"""

# Copyright 2026 Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import os
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass
class AgentConfig:
    model_id: str = "us.anthropic.claude-sonnet-4-6"
    max_tokens: int = 8192
    max_retries: int = 2
    region: str = "us-east-1"
    profile_name: str | None = None


from code_reviewer import CONFIG_DIR
_CONFIG_FILE = CONFIG_DIR / "agent-config.yaml"


def load_agent_config() -> AgentConfig:
    """Load agent config from YAML file, with env var overrides."""
    config = AgentConfig()

    if _CONFIG_FILE.exists():
        with open(_CONFIG_FILE, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

        agent = raw.get("agent", {})
        config.model_id = agent.get("model_id", config.model_id)
        config.max_tokens = agent.get("max_tokens", config.max_tokens)
        config.max_retries = agent.get("max_retries", config.max_retries)

        aws = raw.get("aws", {})
        config.region = aws.get("region", config.region)
        config.profile_name = aws.get("profile_name", config.profile_name)

    # Environment variable overrides
    config.region = os.environ.get("AWS_REGION", config.region)
    config.profile_name = os.environ.get("AWS_PROFILE", config.profile_name)
    if model_env := os.environ.get("BEDROCK_MODEL_ID"):
        config.model_id = model_env

    return config
