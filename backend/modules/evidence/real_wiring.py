"""build_evidence_runner — U11 v2 실 어댑터 조립 (real-first).

Discovery(U2) 재사용:
  SearchOrchestrationService.retrieve_ranked → CorpusSearch (하이브리드 — 리랭크 포함)
  OpenSearchLexicalIndexAdapter → LexicalIndexPort (phrase 전용)
  OpenSearchPaperLookupAdapter → PaperLookupPort

Summarization(U7) 어댑터 재사용:
  S3DocModelReader → EvidenceDocModelTool

신규:
  EvidenceExtractor/Decider → Bedrock Anthropic Sonnet 4.6.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from docsuri_shared.env import env_float

from .runner import EvidenceTurnRunner, RunnerDeps
from .settings import EvidenceSettings

log = logging.getLogger("docsuri.evidence.wiring")


def build_evidence_runner(
    settings: EvidenceSettings,
    *,
    cost_guard: Any | None = None,
    session_factory: Any | None = None,
    checkpoints: Any | None = None,
    with_answer: bool = True,
    search_orchestrator: Any | None = None,
    observability: Any | None = None,
) -> EvidenceTurnRunner:
    """실 어댑터 조립 — DOCSURI_DOCMODEL_BUCKET + OpenSearch 설정 필요.

    cost_guard(U6 단일 권위)를 주면 턴 실행의 비용 게이트에
    연결된다(NFR-C1). checkpoints를 주면 super-step마다 루프 스냅샷이
    저장된다(v3 §5). 안 주면 체크포인트 없이 돈다.

    `with_answer=False`는 판단 층(§4.2)을 붙이지 않는다 — novelty의 중첩 근거형성처럼
    `answer`를 **읽지 않는** 호출자용이다. 붙이면 턴마다 가장 큰 프롬프트를 한두 번 더
    보내고 그 비용은 바깥 잡의 상한에 잡히지 않는다.

    `search_orchestrator`(U2)를 주면 하이브리드 검색이 그것을 쓴다 — 앱쉘은 이미 세운 것을
    넘겨 임베더·임베딩 캐시·OpenSearch 서킷을 한 벌로 유지한다. 안 주면 여기서 세운다
    (워커 단독 실행). phrase 경로용 렉시컬 클라이언트는 어느 경우에도 여기서 따로 만든다 —
    오케스트레이터가 자기 어댑터를 노출하지 않으므로 커넥션 풀 한 벌은 중복된다.
    """
    # --- Discovery 어댑터 (U2 재사용) ---
    from discovery.adapters.opensearch_index import (
        OpenSearchClientFactory,
        OpenSearchLexicalIndexAdapter,
    )
    from discovery.adapters.settings import DiscoverySettings

    d_settings = DiscoverySettings.from_env()

    # 코퍼스 하이브리드 검색은 U2 오케스트레이터가 끝까지 수행한다(리랭크·랭커 포함) —
    # 임베더·동일공간 가드·벡터스토어도 그쪽이 조립하므로 여기서 다시 세우지 않는다.
    # cost_guard를 함께 넘기는 이유: U6가 rerank-off로 내려보낸 턴은 검색도 같이 내려가야
    # 한다(한쪽만 보면 예산이 닫힌 동안에도 리랭크 호출이 계속 나간다).
    if search_orchestrator is None and d_settings.search_enabled:
        from discovery.real_wiring import build_real_orchestrator

        # observability를 빼면 U2 메트릭이 `NoopObservabilityHub`로 간다 — 그중
        # `discovery.search.rerank`(status=failed/budget-off)는 **리랭크가 조용히 안 걸리는
        # 것을 보여주는 유일한 신호**다. 권한이나 ARN이 틀리면 fail-soft로 baseline RRF가
        # 나가는데, 그게 정상 동작과 구분되지 않는다.
        search_orchestrator = build_real_orchestrator(
            d_settings, observability=observability, cost_guard=cost_guard
        ).orchestrator

    from .adapters.sources import CorpusSearch, DocModelReader

    corpus_search = None
    if search_orchestrator is not None:
        # phrase(정확 문구) 검색만 렉시컬 인덱스를 직접 쓴다 — 어댑터 docstring에 이유가 있다.
        # **리전은 discovery 설정에서 읽는다.** 오케스트레이터의 클라이언트가 그렇게 서명하므로
        # (`real_wiring`의 `settings.aws_region`), 여기서 evidence의 `region_name`
        # (`AWS_REGION`/`AWS_DEFAULT_REGION`)을 쓰면 두 클라이언트가 **다른 리전으로 SigV4
        # 서명**을 하게 된다 — 하이브리드는 되는데 phrase만 403이 나는 모양이고, 두 값이
        # 같은 환경에서는 안 보인다.
        os_client = OpenSearchClientFactory.build(
            endpoint=d_settings.opensearch_endpoint,
            region_name=d_settings.aws_region or settings.region_name,
            username=d_settings.opensearch_username,
            password=d_settings.opensearch_password,
            use_ssl=d_settings.opensearch_use_ssl,
            verify_certs=d_settings.opensearch_verify_certs,
        )
        corpus_search = CorpusSearch(
            orchestrator=search_orchestrator,
            lexical_index=OpenSearchLexicalIndexAdapter(os_client, d_settings.opensearch_index),
        )
    else:
        # 도구가 등록되지 않고 목록이 자연 축소된다(러너 규약) — **왜** 빠졌는지는 말한다.
        # 코퍼스만 빠지고 실시간 조회·지정 논문 경로는 그대로 돈다.
        #
        # 여기서 예외를 던지지 않는 이유: 같은 설정으로 `_mount_discovery`가 이미
        # `skip_unconfigured`로 넘어간다(그 설정의 **소유자**가 고른 거동이다). evidence가
        # 더 엄격하면 변수 하나가 accounts·library·summarization까지 함께 떨어뜨린다.
        # 운영 신호는 기동 로그의 `mounted=[...] skipped=[...]`에 이미 있다(deploy 런북).
        log.warning(
            "evidence: U2 검색이 구성되지 않아 corpus_search 도구가 빠진다 — "
            "DOCSURI_OPENSEARCH_ENDPOINT와 DOCSURI_BEDROCK_MODEL_ID가 **함께** 있어야 한다"
            "(엔드포인트만 있으면 벡터 leg 없이 도는 것이 아니라 코퍼스 검색 자체가 없다). "
            "live_lookup과 지정 논문 경로만 쓴다"
        )

    # --- S3 DocModel 리더 (U7 재사용) ---
    from summarization.adapters.s3_docmodel import S3DocModelReader

    doc_model_reader = S3DocModelReader(
        bucket=settings.docmodel_bucket,
        region_name=settings.region_name,
    )
    doc_models = DocModelReader(doc_model_reader)

    # --- LLM (결정 + 추출) ---
    # 어댑터 조립은 여기, composition root에서만 일어난다(TD-EV2-2). 루프 코어와 프롬프트는
    # 무엇이 조립됐는지 모른다 — 포트가 같기 때문이다.
    import boto3
    from botocore.config import Config

    from backend.modules.novelty.adapters.external.base import SourceBreaker

    from .adapters.llm_bedrock import (
        MAX_EXTRACT_CONCURRENCY,
        BedrockAnswerWriter,
        BedrockDecider,
        BedrockExtractor,
    )

    rates = {
        "input_usd_per_mtok": settings.input_usd_per_mtok,
        "output_usd_per_mtok": settings.output_usd_per_mtok,
    }
    # ONE client for both adapters, with botocore's own retries turned off. The failure
    # contract belongs to SourceBreaker (retry once, then trip) — botocore's default legacy
    # mode would retry ~5x underneath it, so a sustained outage cost ~10 wire attempts per
    # turn and the breaker saw one failure per ten, never opening. Timeouts bound a hung
    # turn; the loop budget, not the transport, decides how long a job may run.
    client = boto3.client(
        "bedrock-runtime",
        region_name=settings.region_name,
        config=Config(
            connect_timeout=5,
            read_timeout=90,
            retries={"max_attempts": 1},
            # 추출이 논문별로 동시에 던진다. botocore 기본 풀이 10인데 decide·answer가 같은
            # 클라이언트를 쓰므로 실제 여유는 그보다 작고, 초과분은 매번 새 TLS 핸드셰이크다.
            # 팬아웃 상한보다 넉넉히 둔다 — 두 숫자가 따로 놀면 팬아웃 폭이 조용히 풀에 잘린다.
            max_pool_connections=MAX_EXTRACT_CONCURRENCY * 2 + 4,
        ),
    )
    # 셋이 같은 엔드포인트를 친다 — 회로차단기도 하나를 나눈다. 따로 들면 decide가 스로틀로
    # 죽은 직후 answer가 닫힌 회로에서 시작해 같은 엔드포인트를 두 번 더 친다.
    breaker = SourceBreaker()
    decider = BedrockDecider(model=settings.model_id, client=client, breaker=breaker, **rates)
    extractor = BedrockExtractor(
        model=settings.model_id, client=client, breaker=breaker, **rates
    )
    answer = (
        BedrockAnswerWriter(model=settings.model_id, client=client, breaker=breaker, **rates)
        if with_answer
        else None
    )

    # --- 선택 도구: 없으면 등록되지 않고 도구 목록이 자연 축소된다 ---
    live_lookup = None
    promotion = None
    index_queue = None
    if _live_lookup_enabled():
        live_lookup = _build_live_lookup()
        promotion = _build_promotion(doc_models)
        # 실시간 조회로 찾은 논문을 코퍼스로 되먹인다(§2.6 4단계). 실시간 조회와 한 플래그에
        # 묶는다 — 조회가 꺼져 있으면 코퍼스 밖 논문이 애초에 안 들어온다.
        index_queue = _build_index_queue()

    assets = _build_asset_reader(session_factory)

    runner = EvidenceTurnRunner(
        RunnerDeps(
            llm=decider,
            extractor=extractor,
            answer=answer,
            corpus_search=corpus_search,
            live_lookup=live_lookup,
            doc_models=doc_models,
            promotion=promotion,
            index_queue=index_queue,
            assets=assets,
            cost_guard=cost_guard,
            budget_factory=settings.build_loop_budget,
        ),
        checkpoints=checkpoints,
    )
    return runner


# --- 선택 의존성 조립 --------------------------------------------------------
#
# 각 헬퍼는 설정이 없으면 None을 돌려주고, None인 도구는 레지스트리에 등록되지
# 않는다. "기능이 조용히 죽는" 것과 다르다 — 등록되지 않은 도구는 모델에게
# 보이지도 않으므로 에이전트가 그 경로를 시도하지 않는다.


def _live_lookup_enabled() -> bool:
    from docsuri_shared.env import env_flag

    return env_flag('DOCSURI_EVIDENCE_LIVE_LOOKUP_ENABLED')


def _build_live_lookup() -> object:
    """실시간 조회 셋 — arXiv · Semantic Scholar · OpenAlex(설계 §3.2).

    초안은 u1·ingestion 어댑터 재사용을 적었지만 둘 다 성립하지 않았다: u1 `ArxivAdapter`에는
    search()가 없고(수확·전문 취득용), `docsuri_ingestion`은 backend 의존성이 아니라 import
    자체가 마운트를 죽인다. 그쪽 S2·OpenAlex 소스도 날짜 창 수확용이라 질의 검색이 없다.

    **브레이커는 소스별로 새로 만든다.** 위 Bedrock 셋이 나눠 쓰는 브레이커를 재사용하면
    arXiv 장애가 `decide`를 죽인다 — 다른 엔드포인트이므로 회로도 달라야 한다.

    자격증명 env는 **ingestion이 쓰는 이름 그대로**다. 그 이름들은 소비자가 아니라 자격증명
    자체를 가리키고, 한 배포에서 같은 키를 두 이름으로 두면 한쪽만 채워지는 날이 온다.
    """
    import httpx

    from .adapters.live_sources import LiveLookup

    return LiveLookup(
        httpx.Client(timeout=env_float('DOCSURI_EVIDENCE_LIVE_LOOKUP_TIMEOUT_MS', 15000) / 1000),
        s2_api_key=os.environ.get('DOCSURI_SEMANTIC_SCHOLAR_API_KEY'),
        mailto=os.environ.get('DOCSURI_OPENALEX_MAILTO'),
        contact=os.environ.get('DOCSURI_CONTACT_EMAIL'),
    )


def _build_index_queue() -> object | None:
    """U1 **본 큐**에 색인 잡을 넣는 어댑터. 큐 URL이 없으면 None(기능이 자연히 꺼진다).

    승격이 쓰는 우선순위 큐(`DOCSURI_DOCMODEL_BUILD_QUEUE_URL`)가 아니다 — 그쪽은 사용자가
    기다리는 본문 확보용이고, 색인 잡을 섞으면 기다리는 쪽이 밀린다.
    """
    queue_url = os.environ.get('DOCSURI_SQS_QUEUE_URL')
    if not queue_url:
        return None
    from .adapters.indexing import SqsPaperIndexQueue

    return SqsPaperIndexQueue(queue_url=queue_url)


def _build_promotion(doc_models: object) -> object | None:
    from .adapters.promotion import QueuedPaperPromotion

    queue = _build_build_queue()
    if queue is None:
        return None
    return QueuedPaperPromotion(
        build_queue=queue,
        doc_models=doc_models,
        poll_timeout_seconds=env_float('DOCSURI_EVIDENCE_PROMOTION_TIMEOUT_MS', 20000) / 1000,
    )


def _build_build_queue() -> object | None:
    """u7이 쓰는 것과 같은 BUILD_DOC_MODEL 큐 어댑터를 재사용한다(TD-EV2-5)."""
    queue_url = os.environ.get('DOCSURI_DOCMODEL_BUILD_QUEUE_URL')
    if not queue_url:
        return None
    from summarization.adapters.sqs_docmodel_build import SqsDocModelBuildQueue

    return SqsDocModelBuildQueue(queue_url=queue_url)


def _build_asset_reader(session_factory: object | None) -> object | None:
    """자산 리더 — 앱쉘이 이미 가진 세션 팩토리를 재사용한다.

    여기서 엔진을 새로 만들면 같은 프로세스에 같은 Postgres로 향하는 커넥션 풀이
    두 벌 생긴다. 팩토리가 없을 때(단독 워커)만 직접 만든다.
    """
    from backend.modules.paper_assets import SqlS3FigureReader

    if session_factory is not None:
        return SqlS3FigureReader(session_factory)
    # 단독 워커 경로 — DB 접속은 config가 소유한 해석(DATABASE_URL/DB_HOST 조합)을
    # 그대로 쓴다. 별도 env 이름을 지어내면 아무도 안 세팅해 view_figure가 워커에서만
    # 조용히 빠진다(리뷰 지적 — DOCSURI_DATABASE_URL은 저장소 어디에도 없는 이름이었다).
    from backend.config import Settings
    from backend.db import make_engine, make_session_factory

    database_url = Settings.from_env().database_url
    if not database_url.startswith(("postgresql://", "postgresql+psycopg://", "postgres://")):
        return None  # paper_asset은 Postgres에만 있다
    engine = make_engine(database_url)
    return SqlS3FigureReader(make_session_factory(engine))

