"""Base agent ABC wrapping Strands SDK with BedrockModel.

Transport security: All Amazon Bedrock API calls are made via the boto3 SDK,
which enforces HTTPS with TLS 1.2+ on every request. The Bedrock service
endpoints do not accept plaintext HTTP connections. No application-level TLS
configuration is required or possible — encryption in transit is handled by
the SDK and the service.  See:
https://docs.aws.amazon.com/bedrock/latest/userguide/data-protection.html
"""

# Copyright 2026 Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import logging
import time
from abc import ABC, abstractmethod
from typing import Any, Tuple

import backoff
import boto3
from strands import Agent as StrandsAgent
from strands.models import BedrockModel

from code_reviewer.agent.config import AgentConfig, load_agent_config
from code_reviewer.agent.retry import is_retryable
from code_reviewer.common.output import is_verbose

logger = logging.getLogger("aidlc_code_reviewer.agent")


class BaseAgent(ABC):
    """Abstract base agent wrapping Strands SDK.

    Subclasses implement execute() for their specific task.
    """

    def __init__(self, config: AgentConfig | None = None) -> None:
        self.config = config or load_agent_config()

        boto_session = None
        if self.config.profile_name:
            boto_session = boto3.Session(
                profile_name=self.config.profile_name,
                region_name=self.config.region,
            )

        bedrock_kwargs: dict[str, Any] = {
            "model_id": self.config.model_id,
            "max_tokens": self.config.max_tokens,
        }
        if boto_session:
            bedrock_kwargs["boto_session"] = boto_session
        else:
            bedrock_kwargs["region_name"] = self.config.region

        bedrock_model = BedrockModel(**bedrock_kwargs)

        # Suppress Strands streaming output unless verbose mode is active
        agent_kwargs: dict[str, Any] = {"model": bedrock_model}
        if not is_verbose():
            agent_kwargs["callback_handler"] = None
        self._strands_agent = StrandsAgent(**agent_kwargs)

    @abstractmethod
    def execute(self, **kwargs: Any) -> Any:
        """Execute the agent's task."""
        ...

    @backoff.on_exception(
        backoff.expo,
        Exception,
        max_tries=4,
        base=2,
        giveup=lambda e: not is_retryable(e),
        on_backoff=lambda details: logging.getLogger("aidlc_code_reviewer.agent").warning(
            "Retry %d: %s", details["tries"], details["exception"],
        ),
    )
    def _invoke_model(self, prompt: str) -> Tuple[str, dict]:
        """Invoke model via Strands agent with backoff retry.

        Returns (response_text, usage_metadata).
        """
        start = time.perf_counter()
        try:
            response = self._strands_agent(prompt)
            elapsed = time.perf_counter() - start
            text = str(response)
            usage = self._extract_token_usage(response)
            logger.info(
                "Agent completed in %.2fs (input: %s, output: %s tokens)",
                elapsed,
                usage.get("input_tokens", "?"),
                usage.get("output_tokens", "?"),
            )
            return text, usage
        except Exception as e:
            logger.warning("Model invocation failed: %s", e)
            raise

    def _extract_token_usage(self, response: Any) -> dict:
        """Extract token counts from Strands AgentResult."""
        if hasattr(response, "metrics") and hasattr(response.metrics, "accumulated_usage"):
            usage = response.metrics.accumulated_usage
            if isinstance(usage, dict):
                return {
                    "input_tokens": usage.get("inputTokens", 0) or 0,
                    "output_tokens": usage.get("outputTokens", 0) or 0,
                }
            return {
                "input_tokens": getattr(usage, "inputTokens", 0) or 0,
                "output_tokens": getattr(usage, "outputTokens", 0) or 0,
            }

        if hasattr(response, "usage") and isinstance(response.usage, dict):
            return {
                "input_tokens": response.usage.get("inputTokens", 0),
                "output_tokens": response.usage.get("outputTokens", 0),
            }

        return {"input_tokens": 0, "output_tokens": 0}
