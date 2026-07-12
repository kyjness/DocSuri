"""App-shell ↔ module wiring (the coordination-zone seam).

Modules are mounted **optionally**: each integration imports its module lazily and is
skipped (logged, not fatal) when the module is not present on the branch yet. This is what
lets the app-shell land on ``develop`` *before* the track PRs and have them auto-wire as
they merge — instead of a deadlock where the shell can't merge until the modules it mounts
already exist.

Per-module integration idioms differ (see each ``_mount_*``):
  • accounts (U3) exposes a ready ``router`` + a ``get_db_session`` seam to override, and a
    Redis ``SessionRepository`` singleton to close on shutdown.
  • discovery (U2) exposes *factories* (``build_mock_orchestrator`` + ``build_router``) that
    need dependency injection — the mock orchestrator is wired with the REAL U6 grounding hook
    (docsuri-ops); only the OpenSearch/Bedrock data adapters remain mock-first.

The shell owns this file (CODEOWNERS ``/backend/``); module owners change only their lane.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

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


def mount_modules(app: FastAPI, settings: Settings, integrations=None) -> MountResult:
    """Mount every available module. Never raises — a missing or broken module degrades to
    a skip so the rest of the backend still serves.

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

    # Read path selection (U2 real adapters, critical path ⑥): when the shared OpenSearch
    # cluster + Bedrock model are configured (DOCSURI_OPENSEARCH_ENDPOINT + _BEDROCK_MODEL_ID),
    # wire the REAL OpenSearch/Bedrock read path; otherwise stay mock-first. The cluster itself
    # is provisioned by the shared infra track (U1 infra + system event bus) — U2 only reads it.
    # The process-wide U6 hub the app-shell built (CloudWatch-backed when CLOUDWATCH_NAMESPACE
    # is set, else in-memory). Injecting it here is what routes U2's app metrics to CloudWatch
    # (US-R4): the factories default to NoopObservabilityHub, so without this discovery's
    # emit_metric calls were silently dropped even though the real hub existed on app.state.
    observability = getattr(app.state, "observability", None)
    cost_guard = getattr(app.state, "cost_guard", None)

    discovery_settings = DiscoverySettings.from_env()
    if discovery_settings.search_enabled:
        from discovery.real_wiring import build_real_orchestrator

        bundle = build_real_orchestrator(
            discovery_settings,
            observability=observability,
            cost_guard=cost_guard,
        )
        read_path = "real(opensearch+bedrock)"
    else:
        from discovery.mocks.wiring import build_mock_orchestrator

        bundle = build_mock_orchestrator(observability=observability, cost_guard=cost_guard)
        read_path = "mock"

    # Wire direct history recording when EventBridge is absent but library is mounted.
    # _DirectHistoryPublisher replaces the InMemoryEventPublisher inside the orchestrator so
    # SearchExecutedEvents reach the SQL DB without requiring a live event bus.
    from discovery.mocks.port_stubs import InMemoryEventPublisher

    if isinstance(getattr(bundle, "event_publisher", None), InMemoryEventPublisher) and hasattr(
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

    # The grounding gate is the REAL U6 single authority (INV-1) in BOTH modes — replacing the
    # always-pass StubGroundingHook: enforce() blocks any exposed arXiv id/url absent from the
    # retrieved records and abstains when there is nothing to ground against. With the real
    # OpenSearch adapter the retrieved set is independent of the ranked candidates, so the hook
    # is now load-bearing (not trivially passing as it did against the mock adapter).
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

    # The paper-detail metadata endpoint (GET /api/papers/{id}) is U2-owned (corpus data); both
    # bundles expose a paper_service. getattr keeps this resilient if a bundle predates it.
    app.include_router(
        build_router(bundle.orchestrator, grounding_hook, getattr(bundle, "paper_service", None))
    )
    result.mounted.append("discovery")
    log.info("app-shell: discovery mounted (read path = %s)", read_path)


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
        result.skipped.append(("summarization", "real path not configured (no S3 bucket)"))
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
    from backend.modules.novelty import controller as novelty
    from backend.modules.novelty.adapters import (
        EvidenceFormationClient,
        NoveltyAdapters,
        U2FullSearchCorpusRetrievalClient,
        build_evidence_formation_adapter,
        build_external_adapter,
        build_llm_adapter,
        build_notion_adapter,
        build_similarity_adapter,
    )
    from backend.modules.novelty.repository import (
        InMemoryNoveltyRepository,
        SqlNoveltyRepository,
    )
    from backend.modules.user_docmodel import build_default_user_docmodel_coordinator

    if _is_postgres(settings.database_url):
        from .db import make_engine, make_session_factory

        engine = getattr(app.state, "db_engine", None) or make_engine(settings.database_url)
        app.state.db_engine = engine
        session_factory = make_session_factory(engine)

        def get_novelty_repo():
            session = session_factory()
            try:
                yield SqlNoveltyRepository(session)
                session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()
    else:
        repo = InMemoryNoveltyRepository()
        app.state.novelty_repo = repo

        def get_novelty_repo():
            return repo

    app.dependency_overrides[novelty.get_repo] = get_novelty_repo
    user_docmodel = getattr(app.state, "user_docmodel", None)
    if user_docmodel is None:
        user_docmodel = build_default_user_docmodel_coordinator()
        app.state.user_docmodel = user_docmodel
    discovery_bundle = getattr(app.state, "discovery_bundle", None)
    grounding_hook = getattr(app.state, "grounding_hook", None)
    if discovery_bundle is not None and grounding_hook is not None:
        corpus = U2FullSearchCorpusRetrievalClient(
            discovery_bundle.orchestrator,
            grounding_hook,
        )
        # US-NV1(#251) — 앱쉘이 이미 U11 오케스트레이터를 세웠으면 재사용, 아니면 env 조립.
        evidence_bundle = getattr(app.state, "evidence_bundle", None)
        if evidence_bundle is not None:
            from backend.modules.evidence.service import EvidenceFormationService

            evidence_adapter = EvidenceFormationClient(
                EvidenceFormationService(orchestrator=evidence_bundle.orchestrator)
            )
        else:
            evidence_adapter = build_evidence_formation_adapter(
                cost_guard=getattr(app.state, "cost_guard", None)
            )
        app.state.novelty_adapters = NoveltyAdapters(
            corpus=corpus,
            external=build_external_adapter(),
            similarity=build_similarity_adapter(corpus, user_docmodel=user_docmodel),
            llm=build_llm_adapter(cost_guard=getattr(app.state, "cost_guard", None)),
            evidence=evidence_adapter,
            notion=build_notion_adapter(),
        )
        log.info("app-shell: novelty wired U2 full-search corpus adapter")
    for router in novelty.routers:
        app.include_router(router)
    result.mounted.append("novelty")


def _mount_research(app: FastAPI, settings: Settings, result: MountResult) -> None:
    from backend.modules.research import controller as research
    from backend.modules.research.repository import (
        InMemoryResearchRepository,
        SqlResearchRepository,
    )

    if _is_postgres(settings.database_url):
        from .db import make_engine, make_session_factory

        engine = getattr(app.state, "db_engine", None) or make_engine(settings.database_url)
        app.state.db_engine = engine
        session_factory = make_session_factory(engine)

        def get_research_repo():
            session = session_factory()
            try:
                yield SqlResearchRepository(session)
                session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()
    else:
        repo = InMemoryResearchRepository()
        app.state.research_repo = repo

        def get_research_repo():
            return repo

    app.dependency_overrides[research.get_repo] = get_research_repo
    for router in research.routers:
        app.include_router(router)
    result.mounted.append("research")


def _mount_evidence(app: FastAPI, settings: Settings, result: MountResult) -> None:
    from backend.modules.evidence import controller as evidence
    from backend.modules.evidence.repository import (
        InMemoryEvidenceRepository,
        SqlEvidenceRepository,
    )
    from backend.modules.evidence.settings import EvidenceSettings

    ev_settings = EvidenceSettings.from_env()

    if _is_postgres(settings.database_url):
        from .db import make_engine, make_session_factory

        engine = getattr(app.state, "db_engine", None) or make_engine(settings.database_url)
        app.state.db_engine = engine
        session_factory = make_session_factory(engine)

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
    else:
        repo = InMemoryEvidenceRepository()
        app.state.evidence_repo = repo

        def get_evidence_repo():
            return repo

    if ev_settings.evidence_enabled:
        from backend.modules.evidence.real_wiring import build_evidence_orchestrator

        bundle = build_evidence_orchestrator(
            ev_settings, cost_guard=getattr(app.state, "cost_guard", None)
        )
        app.state.evidence_bundle = bundle

        def get_evidence_orchestrator():
            return bundle.orchestrator
    else:
        def get_evidence_orchestrator():
            raise RuntimeError("evidence real path not configured (no S3 DocModel bucket)")

        log.info("app-shell: evidence real path not configured — running in repo-only mode")

    # 비동기 잡 경로(BR-EV-6): sqs_enqueue 콜백을 chat service에 주입
    sqs_enqueue = None
    if ev_settings.async_enabled and ev_settings.job_queue_url:
        import json as _json

        import boto3 as _boto3

        _sqs = _boto3.client('sqs', region_name=ev_settings.region_name or 'ap-northeast-2')
        _queue_url = ev_settings.job_queue_url

        def sqs_enqueue(payload: dict) -> None:
            _sqs.send_message(QueueUrl=_queue_url, MessageBody=_json.dumps(payload))

    app.state.evidence_sqs_enqueue = sqs_enqueue

    app.dependency_overrides[evidence.get_repo] = get_evidence_repo
    app.dependency_overrides[evidence.get_orchestrator] = get_evidence_orchestrator
    for router in evidence.routers:
        app.include_router(router)
    result.mounted.append("evidence")
    log.info(
        "app-shell: evidence mounted (real_agent=%s, async=%s)",
        ev_settings.evidence_enabled,
        ev_settings.async_enabled,
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
    _mount_research,
    _mount_novelty,
    _mount_summarization,
    _mount_evidence,
)
