"""App-shell ↔ module wiring (the coordination-zone seam).

Modules are mounted **optionally**: each integration imports its module lazily and is
skipped (logged, not fatal) when the module is not present on the branch yet. This is what
lets the app-shell land on ``develop`` *before* the track PRs and have them auto-wire as
they merge — instead of a deadlock where the shell can't merge until the modules it mounts
already exist.

Per-module integration idioms differ (see each ``_mount_*``):
  • accounts (U3) exposes a ready ``router`` + a ``get_db_session`` seam to override, and a
    Redis ``SessionRepository`` singleton to close on shutdown.
  • discovery (U2) exposes *factories* (``build_real_orchestrator`` + ``build_router``) that
    need dependency injection — the orchestrator is wired with the REAL U6 grounding hook
    (docsuri-ops). Real-first like summarization: unconfigured → skipped, never a mock fallback.

The shell owns this file (CODEOWNERS ``/backend/``); module owners change only their lane.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from docsuri_shared.env import EnvConfigError, env_flag
from fastapi import FastAPI

from .config import Settings

log = logging.getLogger("docsuri.backend.wiring")


def _personalization_decision_timeout_ms() -> int:
    try:
        return max(1, int(os.getenv("PERSONALIZATION_DECISION_TIMEOUT_MS", "75")))
    except ValueError:
        return 75


class _DirectHistoryPublisher:
    """In-process SearchExecutedEvent publisher for when EventBridge is not configured.

    Mirrors EventBridgeEventPublisher semantics: recording runs on a daemon thread
    (fire-and-forget, BR-14) and each event opens its own DB session.
    """

    def __init__(self, *, session_factory, gateway, audit) -> None:
        self._session_factory = session_factory
        self._gateway = gateway
        self._audit = audit
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="history-direct"
        )

    def publish_search_executed(self, event) -> None:
        try:
            self._executor.submit(self._record, event)
        except RuntimeError:
            log.warning("wiring: history executor unavailable; dropped SearchExecuted")

    def _record(self, event) -> None:
        from backend.modules.library.history_consumer import SearchHistoryEventConsumer
        from backend.modules.library.repository.sql import SqlUserDataRepository
        from backend.modules.library.services.history import SearchHistoryService

        session = self._session_factory()
        try:
            repo = SqlUserDataRepository(session)
            consumer = SearchHistoryEventConsumer(
                SearchHistoryService(repo, self._gateway, self._audit)
            )
            consumer.consume(event)
            session.commit()
        except Exception:
            session.rollback()
            log.warning("wiring: direct history record failed", exc_info=True)
        finally:
            session.close()

    def close(self) -> None:
        self._executor.shutdown(wait=False)


# A coroutine the shell runs once on shutdown (reverse order) to release a module's resources.
Cleanup = Callable[[], Awaitable[None]]


@dataclass
class MountResult:
    mounted: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)  # (module, reason)
    cleanups: list[Cleanup] = field(default_factory=list)
    # Subset of ``skipped`` that was skipped because it was never configured, as opposed to
    # absent or broken. Readiness needs that distinction and must not re-derive it: the mount
    # gate is the only place that knows what "configured" means for a given module, and a copy
    # of the condition in health.py drifted from it (an endpoint with no embedder skipped the
    # mount while readiness still demanded the module — a permanent 503).
    unconfigured: list[str] = field(default_factory=list)

    def skip_unconfigured(self, module: str, reason: str) -> None:
        """Record a module that is legitimately absent because nobody configured it."""
        self.skipped.append((module, reason))
        self.unconfigured.append(module)


def mount_modules(app: FastAPI, settings: Settings, integrations=None) -> MountResult:
    """Mount every available module. A missing or broken module degrades to a skip so the
    rest of the backend still serves. The ONE thing that does raise is invalid configuration
    (``EnvConfigError``) — see below.

    ``integrations`` defaults to the real registry; tests inject a guaranteed-absent
    integration to exercise the skip path without depending on what's installed.
    """
    result = MountResult()
    for integration in (_INTEGRATIONS if integrations is None else integrations):
        name = integration.__name__.removeprefix("_mount_")
        try:
            integration(app, settings, result)
        except ModuleNotFoundError as exc:
            result.skipped.append((name, f"not present ({exc.name})"))
            log.info("app-shell: %s module not present yet — skipping mount", name)
        except EnvConfigError:
            # NOT contained. A misspelled provider or a malformed limit is the operator's config,
            # not a broken module. Recording it as a "mount error" boots a process that silently
            # lacks the module — or, for a required one, pins readyz at 503 with the offending
            # variable named nowhere. Fail the boot with the variable in the traceback.
            log.error("app-shell: %s has invalid configuration — refusing to start", name)
            raise
        except Exception as exc:  # defensive: one broken module must not sink the shell
            result.skipped.append((name, f"mount error: {exc!r}"))
            log.warning("app-shell: failed to mount %s: %r", name, exc)
    app.state.mounted_modules = list(result.mounted)
    return result


def _mount_accounts(app: FastAPI, settings: Settings, result: MountResult) -> None:
    # ModuleNotFoundError here (accounts not on this branch) bubbles to mount_modules → skip.
    from backend.modules.accounts import controller as accounts

    from .db import make_engine, make_session_factory

    # Fill the DI seam the module declares (its get_db_session raises by contract).
    engine = make_engine(settings.database_url)
    app.state.db_engine = engine
    session_factory = make_session_factory(engine)

    def get_db_session():
        # commit/rollback are the controller's job (verify-all-then-commit); we own open/close.
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[accounts.get_db_session] = get_db_session
    app.include_router(accounts.router)
    result.mounted.append("accounts")

    async def _close_accounts_session_store() -> None:
        # Close the Redis pool ONLY if the lru_cached singleton was actually built — calling
        # get_session_repo() unconditionally would *create* a pool just to close it.
        if accounts.get_session_repo.cache_info().currsize:
            await accounts.get_session_repo().close()

    result.cleanups.append(_close_accounts_session_store)


def _mount_discovery(app: FastAPI, settings: Settings, result: MountResult) -> None:
    # discovery is the top-level ``discovery`` package (docsuri-discovery); the real U6
    # grounding hook lives in docsuri-ops. EITHER absent → ModuleNotFoundError → skip
    # (fail-closed: serve no /api/search rather than ungrounded results). The same applies to
    # the real read path: if it is configured but its `real` extra (opensearch-py/boto3) is not
    # installed, the import raises ModuleNotFoundError → skip (no silent mock fallback).
    from discovery.adapters.settings import DiscoverySettings
    from discovery.api.router import build_router, register_search_unavailable_handler
    from docsuri_ops.grounding import GroundingEnforcementHook

    # Read path gate (U2 real adapters, critical path ⑥): the real OpenSearch/Bedrock path is
    # the ONLY path. Unconfigured → skip the mount entirely, exactly as summarization (U7) does
    # — never a mock fallback. A mock read path answers /api/search with 200 and fabricated
    # cards, and the only signal separating that from a real answer was one startup log line
    # (read_path was recorded nowhere on app.state or MountResult). Against a live corpus that
    # is indistinguishable from a search-quality bug, so a missing route is the honest outcome.
    discovery_settings = DiscoverySettings.from_env()
    if not discovery_settings.search_enabled:
        result.skip_unconfigured(
            "discovery", "real read path not configured (no OpenSearch endpoint / embedder)"
        )
        log.info("app-shell: discovery real read path not configured — skipping mount")
        return

    # Heavy wiring is imported only past the gate (the U7 idiom): an unconfigured process pays
    # neither the opensearch-py/boto3 import nor a ModuleNotFoundError it cannot act on.
    from discovery.real_wiring import build_real_orchestrator

    # The process-wide U6 hub the app-shell built (CloudWatch-backed when CLOUDWATCH_NAMESPACE
    # is set, else in-memory). Injecting it here is what routes U2's app metrics to CloudWatch
    # (US-R4): the factories default to NoopObservabilityHub, so without this discovery's
    # emit_metric calls were silently dropped even though the real hub existed on app.state.
    observability = getattr(app.state, "observability", None)
    cost_guard = getattr(app.state, "cost_guard", None)

    bundle = build_real_orchestrator(
        discovery_settings,
        observability=observability,
        cost_guard=cost_guard,
    )

    # Wire direct history recording when EventBridge is absent but library is mounted.
    # _DirectHistoryPublisher replaces the InMemoryEventPublisher inside the orchestrator so
    # SearchExecutedEvents reach the SQL DB without requiring a live event bus.
    from discovery.defaults.port_stubs import InMemoryEventPublisher

    if isinstance(bundle.event_publisher, InMemoryEventPublisher) and hasattr(
        app.state, "library_session_factory"
    ):
        direct = _DirectHistoryPublisher(
            session_factory=app.state.library_session_factory,
            gateway=app.state.library_gateway,
            audit=app.state.library_audit,
        )
        bundle.orchestrator._event_publisher = direct

        async def _close_direct_publisher() -> None:
            direct.close()

        result.cleanups.append(_close_direct_publisher)
        log.info("app-shell: discovery wired direct history publisher (no EventBridge)")

    # The grounding gate is the REAL U6 single authority (INV-1), never the always-pass
    # StubGroundingHook: enforce() blocks any exposed arXiv id/url absent from the retrieved
    # records and abstains when there is nothing to ground against. Against the real OpenSearch
    # adapter the retrieved set is independent of the ranked candidates, so the hook is
    # load-bearing rather than trivially passing.
    grounding_hook = GroundingEnforcementHook()
    app.state.discovery_bundle = bundle
    app.state.grounding_hook = grounding_hook

    # US-P4 (SHADOW): let the orchestrator ask U9 for bounded category boosts. Resolved from
    # app.state at request time so mount order is irrelevant; missing/failed → no boost (BR-P13).
    def _personalization_boosts(user_id: str) -> dict[str, float]:
        provider = getattr(app.state, "personalization_search_boosts", None)
        if provider is None:
            return {}
        try:
            return provider(user_id)
        except Exception:  # noqa: BLE001 — personalization is best-effort, never fails search
            return {}

    bundle.orchestrator._search_boosts = _personalization_boosts

    # US-P4 go-live gate (#345): apply the boost to the user-facing order only when
    # SEARCH_RERANK_LIVE is on. Default off = SHADOW (metrics emit, order unchanged), so ops can
    # review real rerank_shadow data first, then flip live by setting the env — no redeploy.
    bundle.orchestrator._rerank_live = os.getenv("SEARCH_RERANK_LIVE", "false").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    # US-D6 no-match floor on the best raw k-NN score (QA 2026-07-10 F2). Default 0.0 = off;
    # ops flips it by env after calibrating against discovery.search.best_knn_score — same
    # no-redeploy pattern as SEARCH_RERANK_LIVE. A malformed value must not sink the mount.
    try:
        bundle.orchestrator._no_match_knn_floor = float(
            os.getenv("DISCOVERY_NO_MATCH_KNN_FLOOR", "0") or "0"
        )
    except ValueError:
        log.warning("app-shell: invalid DISCOVERY_NO_MATCH_KNN_FLOOR ignored (floor off)")
        bundle.orchestrator._no_match_knn_floor = 0.0

    # Map a store outage to a fail-closed, no-leak 503 (INV-3/SEC-15). The standalone build_app
    # registers this itself; mounted via build_router here, the app-shell must do it too —
    # otherwise SearchUnavailable falls through to the generic Exception→500 handler and a
    # transient outage looks like a bug instead of a retryable 503 (the value the router/
    # paper_meta docstrings already promise). Reuse discovery's own handler so the SEC-9 message
    # stays single-sourced (no dev/app-shell drift).
    register_search_unavailable_handler(app)

    # The paper-detail metadata endpoint (GET /api/papers/{id}) is U2-owned (corpus data).
    app.include_router(build_router(bundle.orchestrator, grounding_hook, bundle.paper_service))
    result.mounted.append("discovery")
    log.info(
        "app-shell: discovery mounted (read path = real(opensearch + bedrock %s))",
        discovery_settings.bedrock_model_id,
    )


def _is_postgres(database_url: str) -> bool:
    return database_url.startswith(("postgresql://", "postgresql+psycopg://", "postgres://"))


def _mount_library(app: FastAPI, settings: Settings, result: MountResult) -> None:
    # library (U4) is `backend.modules.library`. Absent → ModuleNotFoundError → skip.
    from backend.modules.library import controller as library
    from backend.modules.library.audit import InMemoryAuditSink
    from backend.modules.library.gateway import DiscoverySearchGateway
    from backend.modules.library.history_consumer import SearchHistoryEventConsumer
    from backend.modules.library.repository.memory import InMemoryUserDataRepository
    from backend.modules.library.services.history import SearchHistoryService

    gateway = DiscoverySearchGateway(app)
    audit = InMemoryAuditSink()

    # Read/request path repo: SQL against the U3-inherited RDS when DATABASE_URL is Postgres
    # (D10 production adapter), else the in-memory default (tests / local / CI bare checkout).
    if _is_postgres(settings.database_url):
        from backend.modules.library.repository.sql import SqlUserDataRepository

        from .db import make_engine, make_session_factory

        # One engine per process — reuse the accounts-built engine (accounts mounts first).
        engine = getattr(app.state, "db_engine", None) or make_engine(settings.database_url)
        app.state.db_engine = engine
        session_factory = make_session_factory(engine)

        def get_user_data_repo():
            # FastAPI yield-dependency owns the unit of work: the library controller writes
            # against the in-memory contract (no explicit commit), so we commit here on success
            # and roll back on any error. Session is per-request (open/close around the handler).
            session = session_factory()
            try:
                yield SqlUserDataRepository(session)
                session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()

        # Store deps so _mount_discovery can wire _DirectHistoryPublisher (session-per-event).
        app.state.library_session_factory = session_factory
        app.state.library_gateway = gateway
        app.state.library_audit = audit
        # consumer_repo is kept in-memory; real recording uses _DirectHistoryPublisher.
        consumer_repo = InMemoryUserDataRepository()
        log.info("app-shell: library read path = sql(postgres)")
    else:
        repo = InMemoryUserDataRepository()

        def get_user_data_repo():
            return repo

        consumer_repo = repo
        log.info("app-shell: library read path = in-memory")

    app.dependency_overrides[library.get_user_data_repo] = get_user_data_repo
    app.dependency_overrides[library.get_search_gateway] = lambda: gateway
    app.dependency_overrides[library.get_audit_sink] = lambda: audit

    for router in library.routers:
        app.include_router(router)

    app.state.library_repo = consumer_repo
    app.state.library_history_consumer = SearchHistoryEventConsumer(
        SearchHistoryService(consumer_repo, gateway, audit)
    )

    result.mounted.append("library")


def _mount_mypage(app: FastAPI, settings: Settings, result: MountResult) -> None:
    # mypage (U10) is `backend.modules.mypage`. Absent → ModuleNotFoundError → skip. Mock
    # subscription only (Q10: "하는 척만" — no real PG/billing). The other U10 menu items
    # (관심 논문 / 로그아웃) are NOT mounted here — the frontend calls U4 GET /library and U3
    # POST /logout directly, so those two have no U10-owned backend code.
    from backend.modules.mypage import controller as mypage
    from backend.modules.mypage.repository.memory import (
        InMemoryAccountRepository,
        InMemorySubscriptionRepository,
    )

    if _is_postgres(settings.database_url):
        from backend.modules.mypage.repository.sql import (
            SqlAccountRepository,
            SqlSubscriptionRepository,
        )

        from .db import make_engine, make_session_factory

        # One engine per process — reuse the accounts-built engine (accounts mounts first).
        engine = getattr(app.state, "db_engine", None) or make_engine(settings.database_url)
        app.state.db_engine = engine
        session_factory = make_session_factory(engine)

        def get_subscription_repo():
            session = session_factory()
            try:
                yield SqlSubscriptionRepository(session)
                session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()

        # Account-backed profile/consents read straight from U3's accounts tables on the SAME
        # shared engine (SqlAccountRepository wraps CredentialRepository).
        def get_account_repo():
            session = session_factory()
            try:
                yield SqlAccountRepository(session)
                session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()

        log.info("app-shell: mypage read path = sql(postgres)")
    else:
        repo = InMemorySubscriptionRepository()
        account_repo = InMemoryAccountRepository()

        def get_subscription_repo():
            return repo

        def get_account_repo():
            return account_repo

        log.info("app-shell: mypage read path = in-memory")

    app.dependency_overrides[mypage.get_subscription_repo] = get_subscription_repo
    app.dependency_overrides[mypage.get_account_repo] = get_account_repo
    for router in mypage.routers:
        app.include_router(router)
    result.mounted.append("mypage")


def _mount_summarization(app: FastAPI, settings: Settings, result: MountResult) -> None:
    # summarization (U7) is the top-level ``summarization`` package (docsuri-summarization).
    # Real-first: unlike discovery it ships NO mock wiring, so it mounts ONLY when the real
    # read path is configured (S3 permanent store + Bedrock) — otherwise it skips (fail-closed,
    # no silent fallback). The settings probe imports nothing heavy; the real adapters
    # (boto3/redis) are imported only on the enabled path, so a bare checkout skips cleanly.
    from summarization.adapters.settings import SummarizationSettings

    sm_settings = SummarizationSettings.from_env()
    # DATABASE_URL env isn't set in prod — config._resolve_database_url assembles the DSN from
    # DB_HOST/DB_PASSWORD for the app, but SummarizationSettings.from_env reads DATABASE_URL
    # directly (→ None). The summarization glossary repo calls psycopg.connect, so feed it the
    # app's assembled DSN as a libpq URL (drop the SQLAlchemy ``+psycopg`` dialect tag). Without
    # this every summary/translate raises (DSN=None) and fail-closes to a generic "근거 없음".
    if not sm_settings.database_url and settings.database_url.startswith("postgresql"):
        from dataclasses import replace as _dc_replace

        sm_settings = _dc_replace(
            sm_settings,
            database_url=settings.database_url.replace("postgresql+psycopg://", "postgresql://"),
        )
    if not sm_settings.summarization_enabled:
        result.skip_unconfigured("summarization", "real path not configured (no S3 bucket)")
        log.info("app-shell: summarization real path not configured — skipping mount")
        return

    from summarization.api.router import build_router
    from summarization.real_wiring import build_real_orchestrator

    # Reuse the process-wide U6 single authorities the shell built (cost guard + observability).
    def abstract_lookup(paper_id: str) -> str | None:
        discovery_bundle = getattr(app.state, "discovery_bundle", None)
        if discovery_bundle is not None:
            paper_service = getattr(discovery_bundle, "paper_service", None)
            if paper_service is not None:
                try:
                    meta = paper_service.get_paper_meta(paper_id)
                    if meta is not None:
                        return meta.abstract
                except Exception:
                    pass
        return None

    bundle = build_real_orchestrator(
        sm_settings,
        cost_guard=app.state.cost_guard,
        observability=app.state.observability,
        abstract_lookup=abstract_lookup,
    )
    app.state.summarization_bundle = bundle
    # The doc-model rich view + assets are OA-license-gated; the gates are passed from settings
    # (default OFF — ``license_unavailable`` → arXiv link-out) until a license signal is wired.
    app.include_router(
        build_router(
            bundle.orchestrator,
            assets_enabled=sm_settings.assets_enabled,
            docmodel_enabled=sm_settings.docmodel_viewer_enabled,
        )
    )
    result.mounted.append("summarization")
    log.info(
        "app-shell: summarization mounted (assets=%s, docmodel=%s)",
        sm_settings.assets_enabled,
        sm_settings.docmodel_viewer_enabled,
    )


def _mount_ops(app: FastAPI, settings: Settings, result: MountResult) -> None:
    # ops (U6 dashboard/incidents) is `backend.modules.ops`. Its docsuri-ops imports are lazy
    # (inside the endpoints), so the router mounts even when docsuri-ops is absent — the
    # endpoints then return 503 via get_dashboard_service. Absent module → ModuleNotFoundError
    # → skip (handled by mount_modules), same as the other mounters.
    from backend.modules.ops import controller as ops

    app.include_router(ops.router)
    result.mounted.append("ops")


def _mount_citation_graph(app: FastAPI, settings: Settings, result: MountResult) -> None:
    from backend.modules.citation_graph import controller as citation_graph

    for router in citation_graph.routers:
        app.include_router(router)
    result.mounted.append("citation_graph")


def _mount_personalization(app: FastAPI, settings: Settings, result: MountResult) -> None:
    from backend.modules.personalization import controller as personalization
    from backend.modules.personalization.repository import (
        InMemoryPersonalizationRepository,
        SqlPersonalizationRepository,
    )

    if _is_postgres(settings.database_url):
        from .db import make_engine, make_session_factory

        engine = getattr(app.state, "db_engine", None) or make_engine(settings.database_url)
        app.state.db_engine = engine
        session_factory = make_session_factory(engine)

        def get_personalization_repo():
            session = session_factory()
            try:
                yield SqlPersonalizationRepository(session)
                session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()
    else:
        repo = InMemoryPersonalizationRepository()

        def get_personalization_repo():
            return repo

    app.dependency_overrides[personalization.get_repo] = get_personalization_repo
    for router in personalization.routers:
        app.include_router(router)
    result.mounted.append("personalization")

    # US-P4 (SHADOW): expose bounded search boosts for the discovery orchestrator. Gated by the
    # same flag as the endpoints; a fresh read-port + session per call so the singleton
    # orchestrator never holds a request-scoped DB session. Errors bubble to discovery's
    # fail-open wrapper (BR-P13).
    if os.getenv("PERSONALIZATION_ENABLED", "false").lower() in {"1", "true", "yes", "on"}:
        from backend.modules.personalization.service import PersonalizationReadPort

        observability = getattr(app.state, "observability", None)

        if _is_postgres(settings.database_url):
            from sqlalchemy import text

            timeout_ms = _personalization_decision_timeout_ms()

            def _search_boosts(user_id: str) -> dict[str, float]:
                session = session_factory()
                try:
                    session.execute(
                        text("select set_config('statement_timeout', :timeout, true)"),
                        {"timeout": f"{timeout_ms}ms"},
                    )
                    port = PersonalizationReadPort(
                        SqlPersonalizationRepository(session), observability=observability
                    )
                    return port.cached_search_boosts(user_id)
                finally:
                    session.close()
        else:

            def _search_boosts(user_id: str) -> dict[str, float]:
                port = PersonalizationReadPort(repo, observability=observability)
                return port.cached_search_boosts(user_id)

        app.state.personalization_search_boosts = _search_boosts


def _mount_novelty(app: FastAPI, settings: Settings, result: MountResult) -> None:
    """Novelty v2 — 자율 루프 API 마운트. API는 접수·조회만 하고 실행은 별도 워커
    프로세스(``python -m backend.modules.novelty.worker``)가 담당한다.

    항상 마운트한다(/readyz 필수 모듈): postgres 미구성이면 InMemory 스토어 폴백,
    큐 미구성이면 잡 접수가 503(queue_unavailable)으로 거부된다 — 제로 서비스 부팅
    유지."""
    from backend.modules.novelty import api as novelty_api
    from backend.modules.novelty.adapters.local_wiring import build_queue, build_store
    from backend.modules.novelty.settings import NoveltySettings
    from backend.modules.user_docmodel import build_default_user_docmodel_coordinator

    novelty_settings = NoveltySettings.from_env()
    app.state.novelty_settings = novelty_settings

    session_factory = None
    if _is_postgres(settings.database_url):
        from .db import make_engine, make_session_factory

        engine = getattr(app.state, "db_engine", None) or make_engine(settings.database_url)
        app.state.db_engine = engine
        session_factory = make_session_factory(engine)
    store = build_store(session_factory)
    app.state.novelty_store = store
    app.dependency_overrides[novelty_api.get_store] = lambda: store

    # 조립 불변식(코드 리뷰 반영): 큐는 내구 스토어(postgres)와만 짝지어진다 —
    # InMemory 스토어로 적재하면 별도 프로세스 워커가 잡을 못 찾고 조용히 유실된다.
    if session_factory is None:
        if novelty_settings.queue_configured:
            log.warning(
                "app-shell: novelty queue disabled — durable store (postgres) required"
            )
        app.state.novelty_queue = None
    else:
        try:
            app.state.novelty_queue = build_queue(novelty_settings)
        except Exception:  # noqa: BLE001 — 큐 조립 실패는 접수 503으로 수렴, 마운트는 유지
            log.warning("app-shell: novelty queue unavailable", exc_info=True)
            app.state.novelty_queue = None

    if getattr(app.state, "user_docmodel", None) is None:
        app.state.user_docmodel = build_default_user_docmodel_coordinator()

    for router in novelty_api.routers:
        app.include_router(router)
    result.mounted.append("novelty")


def _mount_evidence(app: FastAPI, settings: Settings, result: MountResult) -> None:
    from datetime import timedelta

    from backend.modules.evidence import controller as evidence
    from backend.modules.evidence.repository import (
        InMemoryEvidenceRepository,
        SqlEvidenceRepository,
    )
    from backend.modules.evidence.settings import EvidenceSettings

    ev_settings = EvidenceSettings.from_env()
    evidence_session_factory = None

    if _is_postgres(settings.database_url):
        from .db import make_engine, make_session_factory

        engine = getattr(app.state, "db_engine", None) or make_engine(settings.database_url)
        app.state.db_engine = engine
        session_factory = make_session_factory(engine)
        evidence_session_factory = session_factory

        def get_evidence_repo():
            session = session_factory()
            try:
                yield SqlEvidenceRepository(session)
                session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()

        def repo_factory():
            return SqlEvidenceRepository(session_factory())
    else:
        repo = InMemoryEvidenceRepository()

        def get_evidence_repo():
            return repo

        def repo_factory():
            return repo

        log.warning(
            "app-shell: evidence without Postgres — no turn checkpoints; an executor that dies "
            "leaves the turn to finish as internal_error"
        )

    # 턴 체크포인트(v3 §5). 이 프로세스가 턴을 돌리거나(러너) 다른 프로세스가 돌린 턴을
    # 읽어야 할 때(SQS dispatch — 고아 마감·세션 삭제 정리) 만든다. 둘 다 아니면 DB 연결을
    # 열 이유가 없다. 테이블은 부팅 마이그레이션과 같은 게이트 아래 saver가 만든다.
    from backend.modules.evidence.checkpoints import TurnCheckpoints

    sqs_configured = bool(ev_settings.async_enabled and ev_settings.job_queue_url)
    runner = None
    checkpoints = None
    checkpointer = None
    checkpointer_open = False
    wants_checkpoints = ev_settings.evidence_enabled or sqs_configured
    if _is_postgres(settings.database_url) and wants_checkpoints:
        from backend.modules.evidence.checkpoints import build_postgres_checkpointer

        checkpointer, close_checkpointer = build_postgres_checkpointer(
            settings.database_url,
            setup=env_flag("RUN_MIGRATIONS_ON_STARTUP", True),
        )
        checkpointer_open = True
        executor_drained = {"ok": True}

        async def _close_checkpointer() -> None:
            # 실행자가 턴을 다 못 비웠으면 풀을 닫지 않는다 — 아직 도는 스레드의 다음
            # 체크포인트 쓰기가 닫힌 풀에서 터져 INTERRUPTED 대신 internal_error가 된다.
            # 그 경우 풀은 프로세스 종료가 닫는다.
            if executor_drained["ok"]:
                close_checkpointer()

        result.cleanups.append(_close_checkpointer)
    if wants_checkpoints:
        checkpoints = TurnCheckpoints(checkpointer)
    if ev_settings.evidence_enabled:
        from backend.modules.evidence.real_wiring import build_evidence_runner

        runner = build_evidence_runner(
            ev_settings,
            cost_guard=getattr(app.state, "cost_guard", None),
            # 앱쉘이 이미 가진 세션 팩토리 재사용 — 없으면 러너가 자체 생성한다.
            session_factory=evidence_session_factory,
            checkpoints=checkpoints,
        )
    else:
        log.info("app-shell: evidence real path not configured — running in repo-only mode")

    # 실행자(v3 §5.1): SQS가 구성됐으면 enqueue, 아니면 이 프로세스의 스레드풀. 둘 다 같은
    # process_job을 돌리고 API·이벤트 계약은 같다.
    dispatch = None
    if sqs_configured:
        import json as _json

        import boto3 as _boto3

        _sqs = _boto3.client('sqs', region_name=ev_settings.region_name or 'ap-northeast-2')
        _queue_url = ev_settings.job_queue_url

        def dispatch(payload: dict) -> None:
            _sqs.send_message(QueueUrl=_queue_url, MessageBody=_json.dumps(payload))
    elif runner is not None:
        from backend.modules.evidence.executor import LocalTurnExecutor
        from backend.modules.user_docmodel import build_default_user_docmodel_coordinator

        def shared_user_docmodel():
            # 요청 경로(controller.get_user_docmodel)와 **같은 자리**에 캐시한다 — 따로 만들면
            # boto3 클라이언트와 자격증명 해석이 프로세스에 두 벌 생긴다.
            coordinator = getattr(app.state, "user_docmodel", None)
            if coordinator is None:
                coordinator = build_default_user_docmodel_coordinator()
                app.state.user_docmodel = coordinator
            return coordinator

        local = LocalTurnExecutor(
            repo_factory=repo_factory,
            runner=runner,
            user_docmodel_factory=shared_user_docmodel,
            workers=ev_settings.local_turn_workers,
            checkpoints=checkpoints,
            checkpoint_retention=timedelta(days=ev_settings.checkpoint_retention_days),
        )
        dispatch = local.submit

        async def _close_executor() -> None:
            import asyncio

            drained = await asyncio.to_thread(local.close)
            if checkpointer_open:
                executor_drained["ok"] = drained

        # lifespan이 역순으로 돌린다 — 실행자가 풀·엔진보다 먼저 닫혀야 한다.
        result.cleanups.append(_close_executor)

    app.state.evidence_dispatch = dispatch
    app.state.evidence_repo_factory = repo_factory
    app.state.evidence_execution = ev_settings.turn_execution

    app.dependency_overrides[evidence.get_repo] = get_evidence_repo
    app.dependency_overrides[evidence.get_checkpoints] = lambda: checkpoints
    for router in evidence.routers:
        app.include_router(router)
    result.mounted.append("evidence")
    log.info(
        "app-shell: evidence mounted (real_agent=%s, executor=%s, checkpoints=%s)",
        ev_settings.evidence_enabled,
        "sqs" if ev_settings.async_enabled and ev_settings.job_queue_url else
        ("local" if dispatch else "none"),
        checkpoints is not None and checkpoints.enabled,
    )


# The real registry. Each entry is a `(app, settings, result) -> None` mounter whose name
# (minus the `_mount_` prefix) labels it in MountResult / `/readyz`.
_INTEGRATIONS = (
    _mount_accounts,
    _mount_library,    # before discovery: session_factory must be on app.state first
    _mount_discovery,
    _mount_mypage,
    _mount_ops,
    _mount_citation_graph,
    _mount_personalization,
    _mount_novelty,
    _mount_summarization,
    _mount_evidence,
)
