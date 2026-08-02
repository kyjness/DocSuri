"""로컬 1차 조립(TD-NV2-1~3) — redis 큐·postgres 저장·OpenAI tool-calling.

composition root: 프로바이더·백엔드 선택은 전부 여기서만 일어난다. 도메인·루프
코어는 어떤 구현이 조립됐는지 모른다. 설정이 없는 구성 요소는 None을 반환하거나
레지스트리에서 빠진다 — 도구 목록의 자연 축소(logical-components §4).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from backend.modules.paper_assets import SqlS3FigureReader

from ..ports.tools import ToolRegistry
from ..settings import NoveltySettings
from .corpus import CorpusSearchTool
from .evidence import FormEvidenceTool
from .external.datasets import DatasetSearchTool
from .external.github import GithubSearchTool
from .figures import ViewFigureTool
from .memory import InMemoryNoveltyStore
from .store_sql import SqlNoveltyStore

__all__ = [
    "build_asset_port",
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


def build_queue(settings: NoveltySettings, *, for_consumer: bool = False) -> Any | None:
    """redis(로컬 1차) 우선, SQS(배포 기준선)는 sqs_queue_url 존재 시. 둘 다 없으면
    None — API는 뜨되 잡 접수가 503으로 거부된다(queue_unavailable).

    `for_consumer`는 블록 소비를 도는 워커만 켠다. 소켓 읽기 한도를 늘리는 것은
    consume 한 곳에만 필요한데, 같은 클라이언트를 쓰는 API의 enqueue까지 길어지면
    redis가 멎었을 때 잡 접수 요청이 그만큼 더 붙들려 있다가 503을 낸다.
    """
    if settings.queue_url:
        import redis

        from .queue_redis import CONSUME_SOCKET_TIMEOUT_S, RedisJobQueue

        # 소켓 읽기 한도를 워커의 블록 시간보다 넉넉히 준다 — redis-py 8의 기본값
        # (5초)은 워커 블록 시간과 같아 유휴 폴링마다 읽기 데드라인에 걸린다.
        # 어댑터도 그 예외를 "빈 큐"로 정규화하지만, 정상 경로가 예외에 기대지
        # 않도록 여기서 한도를 맞춘다. URL이 값을 직접 지정하면 그쪽이 이긴다.
        options: dict[str, Any] = (
            {"socket_timeout": CONSUME_SOCKET_TIMEOUT_S} if for_consumer else {}
        )
        return RedisJobQueue(redis.Redis.from_url(settings.queue_url, **options))
    if settings.sqs_queue_url:
        import boto3

        from .real_wiring import SqsJobQueue

        return SqsJobQueue(
            boto3.client("sqs", region_name=settings.region_name), settings.sqs_queue_url
        )
    return None


def build_asset_port(
    settings: NoveltySettings, session_factory: Callable[[], Any] | None
) -> Any | None:
    """자산 토글 + postgres가 있을 때만 — 없으면 view_figure가 도구 목록에서 빠진다."""
    if not settings.assets_enabled or session_factory is None:
        return None
    return SqlS3FigureReader(session_factory, region_name=settings.region_name)


def build_llm(settings: NoveltySettings) -> Any | None:
    """프로바이더 스위치(TD-NV2-3) — openai(로컬 1차) | bedrock(배포 기준선)."""
    if settings.llm_provider == "openai" and settings.openai_api_key:
        from .llm_openai import OpenAiToolCallingLlm

        return OpenAiToolCallingLlm(
            model=settings.openai_model,
            api_key=settings.openai_api_key,
            input_usd_per_mtok=settings.openai_input_usd_per_mtok,
            output_usd_per_mtok=settings.openai_output_usd_per_mtok,
            image_detail=settings.figure_image_detail,
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
    asset_port: Any | None = None,
    http_client: Any | None = None,
) -> ToolRegistry:
    """가용 의존성이 있는 도구만 등록 — view_figure는 자산 스토어가 설정된 경우에만,
    Notion은 레지스트리가 구조적으로 거부한다(BR-RA12)."""
    registry = ToolRegistry()
    if orchestrator is not None and grounding_hook is not None:
        registry.register(CorpusSearchTool(orchestrator, grounding_hook))
    if evidence_port is not None:
        registry.register(FormEvidenceTool(evidence_port))
    if asset_port is not None:
        registry.register(
            ViewFigureTool(asset_port, max_image_bytes=settings.figure_max_image_bytes)
        )
    if http_client is None:
        import httpx

        http_client = httpx.Client(timeout=settings.external_timeout_seconds)
    registry.register(GithubSearchTool(http_client, token=settings.github_token))
    registry.register(DatasetSearchTool(http_client))
    log.info("novelty tool registry: %s", sorted(registry.names()))
    return registry
