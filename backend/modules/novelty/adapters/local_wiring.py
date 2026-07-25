"""로컬 1차 조립(TD-NV2-1~3) — redis 큐·postgres 저장·OpenAI tool-calling.

composition root: 프로바이더·백엔드 선택은 전부 여기서만 일어난다. 도메인·루프
코어는 어떤 구현이 조립됐는지 모른다. 설정이 없는 구성 요소는 None을 반환하거나
레지스트리에서 빠진다 — 도구 목록의 자연 축소(logical-components §4).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from ..ports.tools import ToolRegistry
from ..settings import NoveltySettings
from .corpus import CorpusSearchTool
from .evidence import FormEvidenceTool
from .external.datasets import DatasetSearchTool
from .external.github import GithubSearchTool
from .memory import InMemoryNoveltyStore
from .store_sql import SqlNoveltyStore

__all__ = [
    "build_llm",
    "build_queue",
    "build_store",
    "build_tool_registry",
]

log = logging.getLogger("docsuri.novelty.local_wiring")


def build_store(session_factory: Callable[[], Any] | None) -> Any:
    """postgres session factory가 있으면 SQL, 없으면 InMemory 폴백 —
    API는 항상 마운트된다(/readyz 필수 모듈, 제로 서비스 부팅)."""
    if session_factory is not None:
        return SqlNoveltyStore(session_factory)
    return InMemoryNoveltyStore()


def build_queue(settings: NoveltySettings) -> Any | None:
    """redis(로컬 1차) 우선, SQS(배포 기준선)는 sqs_queue_url 존재 시. 둘 다 없으면
    None — API는 뜨되 잡 접수가 503으로 거부된다(queue_unavailable)."""
    if settings.queue_url:
        import redis

        from .queue_redis import RedisJobQueue

        return RedisJobQueue(redis.Redis.from_url(settings.queue_url))
    if settings.sqs_queue_url:
        import boto3

        from .real_wiring import SqsJobQueue

        return SqsJobQueue(
            boto3.client("sqs", region_name=settings.region_name), settings.sqs_queue_url
        )
    return None


def build_llm(settings: NoveltySettings) -> Any | None:
    """프로바이더 스위치(TD-NV2-3) — openai(로컬 1차) | bedrock(배포 기준선)."""
    if settings.llm_provider == "openai" and settings.openai_api_key:
        from .llm_openai import OpenAiToolCallingLlm

        return OpenAiToolCallingLlm(
            model=settings.openai_model,
            api_key=settings.openai_api_key,
            input_usd_per_mtok=settings.openai_input_usd_per_mtok,
            output_usd_per_mtok=settings.openai_output_usd_per_mtok,
        )
    if settings.llm_provider == "bedrock":
        import boto3

        from .real_wiring import BedrockToolCallingLlm

        return BedrockToolCallingLlm(
            model_id=settings.bedrock_model_id,
            client=boto3.client("bedrock-runtime", region_name=settings.region_name),
        )
    return None


def build_tool_registry(
    settings: NoveltySettings,
    *,
    orchestrator: Any | None = None,
    grounding_hook: Any | None = None,
    evidence_port: Any | None = None,
    http_client: Any | None = None,
) -> ToolRegistry:
    """가용 의존성이 있는 도구만 등록 — view_figure는 멀티모달 단계 전 미등록,
    Notion은 레지스트리가 구조적으로 거부한다(BR-RA12)."""
    registry = ToolRegistry()
    if orchestrator is not None and grounding_hook is not None:
        registry.register(CorpusSearchTool(orchestrator, grounding_hook))
    if evidence_port is not None:
        registry.register(FormEvidenceTool(evidence_port))
    if http_client is None:
        import httpx

        http_client = httpx.Client(timeout=settings.external_timeout_seconds)
    registry.register(GithubSearchTool(http_client, token=settings.github_token))
    registry.register(DatasetSearchTool(http_client))
    log.info("novelty tool registry: %s", sorted(registry.names()))
    return registry
