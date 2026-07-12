from __future__ import annotations

import os
import re
import time
from typing import Any
from urllib.parse import quote

import httpx
from docsuri_shared.authz import Principal
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from backend.modules.library.controller import get_library_service
from backend.modules.library.schemas import LibraryItemCreateDTO
from backend.modules.library.services.library import LibraryService

MAX_DEPTH = 2
ARXIV_ID_RE = re.compile(r"^(?:[a-z-]+(?:\.[A-Z]{2})?/\d{7}|\d{4}\.\d{4,5})(?:v\d+)?$", re.I)
ARXIV_VERSION_RE = re.compile(r"v\d+$", re.I)
DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$", re.I)


def _max_visible_nodes() -> int:
    return int(os.getenv("CITATION_GRAPH_MAX_VISIBLE_NODES", "30"))


def _snapshot_ttl_seconds() -> int:
    return int(os.getenv("CITATION_GRAPH_SNAPSHOT_TTL_SECONDS", "604800"))


class CitationNode(BaseModel):
    nodeId: str
    title: str
    year: int | None = None
    citationCount: int | None = None
    depth: int = Field(ge=1, le=2)
    arxivId: str | None = None
    url: str | None = None
    inCorpus: bool = False
    saveable: bool = False
    alreadyShown: bool = False


class CitationEdge(BaseModel):
    source: str
    target: str
    depth: int


class UnresolvedCitation(BaseModel):
    title: str
    year: int | None = None
    reason: str = "unresolved"


class CitationTreeResponse(BaseModel):
    status: str
    rootPaperId: str
    nodes: list[CitationNode]
    edges: list[CitationEdge]
    unresolved: list[UnresolvedCitation] = Field(default_factory=list)
    depthReturned: int
    truncated: bool = False
    remainingEstimate: int = 0
    cacheHit: bool = False
    providerStatus: str = "not_called"


class SaveCitationNodeRequest(BaseModel):
    node: CitationNode


class InMemorySnapshotStore:
    # ponytail: process-local cache; swap for Redis when production wiring lands.
    def __init__(self) -> None:
        self._items: dict[str, tuple[float, CitationTreeResponse]] = {}

    async def get(self, key: str) -> CitationTreeResponse | None:
        item = self._items.get(key)
        if not item:
            return None
        expires_at, value = item
        if expires_at < time.time():
            self._items.pop(key, None)
            return None
        return value.model_copy(update={"cacheHit": True})

    async def set(self, key: str, value: CitationTreeResponse) -> None:
        self._items[key] = (time.time() + _snapshot_ttl_seconds(), value)


class RedisSnapshotStore:
    def __init__(self, url: str, prefix: str = "citation_graph:v1:") -> None:
        import redis.asyncio as redis

        self._redis = redis.Redis.from_url(url)
        self._prefix = prefix

    async def get(self, key: str) -> CitationTreeResponse | None:
        try:
            raw = await self._redis.get(self._prefix + key)
            if raw is None:
                return None
            return CitationTreeResponse.model_validate_json(raw).model_copy(
                update={"cacheHit": True}
            )
        except Exception:  # noqa: BLE001 - cache miss on Redis/JSON failure, provider remains source
            return None

    async def set(self, key: str, value: CitationTreeResponse) -> None:
        try:
            await self._redis.set(
                self._prefix + key,
                value.model_dump_json(),
                ex=max(1, _snapshot_ttl_seconds()),
            )
        except Exception:  # noqa: BLE001 - cache write is advisory
            pass


class SemanticScholarProvider:
    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key

    async def references(self, paper_id: str, limit: int) -> tuple[str, list[dict[str, Any]]]:
        headers = {"x-api-key": self._api_key} if self._api_key else {}
        timeout = float(os.getenv("CITATION_GRAPH_PROVIDER_TIMEOUT_SECONDS", "5"))
        retry_timeout = float(os.getenv("CITATION_GRAPH_PROVIDER_RETRY_TIMEOUT_SECONDS", "10"))
        retries = int(os.getenv("CITATION_GRAPH_PROVIDER_RETRIES", "1"))
        encoded_paper_id = quote(_semantic_scholar_paper_id(paper_id), safe="")
        url = f"https://api.semanticscholar.org/graph/v1/paper/{encoded_paper_id}/references"
        params = {
            "fields": "title,year,citationCount,externalIds,paperId,url",
            "limit": str(min(limit, 1000)),
        }
        timeouts = [timeout] + [retry_timeout] * retries
        for attempt, attempt_timeout in enumerate(timeouts):
            try:
                async with httpx.AsyncClient(timeout=attempt_timeout) as client:
                    resp = await client.get(url, params=params, headers=headers)
                if resp.status_code == 429:
                    return "rate_limited", []
                resp.raise_for_status()
                return "ok", [row.get("citedPaper") or {} for row in resp.json().get("data", [])]
            except (httpx.TimeoutException, httpx.HTTPError):
                if attempt == len(timeouts) - 1:
                    return "unavailable", []
            except Exception:  # noqa: BLE001 - non-JSON/misshapen 200 body degrades, never 500 (BR-CG12)
                # S2 often answers /references 200 with a body that isn't {"data": [...]} (HTML
                # error, JSON null, bare list). resp.json()/.get() then raises Value/Attribute/
                # TypeError — not httpx.*, so it would 500. Retry won't fix a bad body.
                return "unavailable", []
        return "unavailable", []


def _semantic_scholar_paper_id(paper_id: str) -> str:
    value = paper_id.strip()
    prefix, sep, rest = value.partition(":")
    if sep and prefix.upper() in {"ARXIV", "DOI", "PMID", "PMCID", "MAG", "ACL", "CORPUSID", "URL"}:
        normalized = ARXIV_VERSION_RE.sub("", rest) if prefix.upper() == "ARXIV" else rest
        return f"{prefix.upper()}:{normalized}"
    if ARXIV_ID_RE.match(value):
        return f"ARXIV:{ARXIV_VERSION_RE.sub('', value)}"
    if DOI_RE.match(value):
        return f"DOI:{value}"
    if value.startswith(("http://", "https://")):
        return f"URL:{value}"
    return value


def _feature_enabled() -> None:
    if os.getenv("CITATION_GRAPH_ENABLED", "false").lower() not in {"1", "true", "yes", "on"}:
        raise HTTPException(status_code=404, detail="not found")


router = APIRouter(
    prefix="/api/papers/{paper_id}/citation-tree",
    tags=["CitationGraph"],
    dependencies=[Depends(_feature_enabled)],
)
def _redis_url() -> str | None:
    if url := os.getenv("CITATION_GRAPH_REDIS_URL") or os.getenv("DOCSURI_REDIS_URL"):
        return url
    host = os.getenv("REDIS_HOST")
    if not host:
        return None
    tls = os.getenv("REDIS_TLS", "").lower() in {"1", "true", "yes", "on"}
    scheme = "rediss" if tls else "redis"
    return f"{scheme}://{host}:{os.getenv('REDIS_PORT', '6379')}/{os.getenv('REDIS_DB', '0')}"


def _build_snapshot_store() -> Any:
    if url := _redis_url():
        prefix = os.getenv("CITATION_GRAPH_CACHE_PREFIX", "citation_graph:v1:")
        return RedisSnapshotStore(url, prefix)
    return InMemorySnapshotStore()


_store: Any | None = None
_provider = SemanticScholarProvider(os.getenv("SEMANTIC_SCHOLAR_API_KEY"))


def get_principal(request: Request) -> Principal:
    principal = getattr(request.state, "principal", None)
    if principal is None:
        raise HTTPException(status_code=401, detail="authentication required")
    return principal


def get_snapshot_store() -> Any:
    global _store
    if _store is None:
        try:
            _store = _build_snapshot_store()
        except ModuleNotFoundError:
            _store = InMemorySnapshotStore()
    return _store


def get_provider() -> SemanticScholarProvider:
    return _provider


PRINCIPAL_DEP = Depends(get_principal)
STORE_DEP = Depends(get_snapshot_store)
PROVIDER_DEP = Depends(get_provider)
LIBRARY_DEP = Depends(get_library_service)


def _in_corpus(paper_service: Any, arxiv_id: str | None) -> bool:
    if not paper_service or not arxiv_id:
        return False
    try:
        return paper_service.get_paper_meta(arxiv_id) is not None
    except Exception:  # noqa: BLE001 - corpus lookup must not break citation display
        return False


def _node(
    raw: dict[str, Any],
    depth: int,
    seen: set[str],
    paper_service: Any = None,
) -> CitationNode | UnresolvedCitation:
    external = raw.get("externalIds") or {}
    node_id = external.get("ArXiv") or external.get("DOI") or raw.get("paperId") or raw.get("url")
    title = (raw.get("title") or "").strip()
    if not node_id or not title:
        return UnresolvedCitation(title=title or "(untitled)", year=raw.get("year"))
    already = node_id in seen
    seen.add(node_id)
    arxiv_id = external.get("ArXiv")
    return CitationNode(
        nodeId=str(node_id),
        title=title[:500],
        year=raw.get("year"),
        citationCount=raw.get("citationCount"),
        depth=depth,
        arxivId=arxiv_id,
        url=raw.get("url"),
        inCorpus=_in_corpus(paper_service, arxiv_id),
        saveable=bool(arxiv_id) and not already,
        alreadyShown=already,
    )


def _library_year(year: int | None) -> int | None:
    if isinstance(year, int) and not isinstance(year, bool) and 1900 <= year <= 2100:
        return year
    return None


def _build_tree(
    root: str,
    parent: str,
    raw_items: list[dict[str, Any]],
    paper_service: Any = None,
) -> CitationTreeResponse:
    target_depth = 2 if parent != root else 1
    # Root AND expanded parent seed the dedup set: a self-citation (parent in its own
    # references) must fold to alreadyShown, or the client can chase A→A→… forever (US-CG3).
    seen = {root, parent}
    nodes: list[CitationNode] = []
    edges: list[CitationEdge] = []
    unresolved: list[UnresolvedCitation] = []
    sorted_items = sorted(
        raw_items,
        key=lambda item: (
            -(item.get("citationCount") or -1),
            -(item.get("year") or 0),
            item.get("title") or "",
        ),
    )
    for raw in sorted_items:
        item = _node(raw, target_depth, seen, paper_service)
        if isinstance(item, UnresolvedCitation):
            unresolved.append(item)
            continue
        if len(nodes) < _max_visible_nodes():
            nodes.append(item)
            edges.append(CitationEdge(source=parent, target=item.nodeId, depth=target_depth))
    remaining = max(0, len(sorted_items) - len(nodes) - len(unresolved))
    return CitationTreeResponse(
        status="Partial" if unresolved else "Success",
        rootPaperId=root,
        nodes=nodes,
        edges=edges,
        unresolved=unresolved,
        depthReturned=target_depth,
        truncated=remaining > 0,
        remainingEstimate=remaining,
    )


def _metric(hub: Any, name: str, value: float, tags: dict[str, str]) -> None:
    """Advisory metric emit (US-CG6) — same fail-soft contract as discovery's _emit_guarded:
    observability MUST NOT raise into the citation path."""
    emit_metric = getattr(hub, "emit_metric", None)
    if not emit_metric:
        return
    try:
        emit_metric(name, value, tags)
    except Exception:  # noqa: BLE001 - observability is advisory
        pass


def _emit(
    request: Request, response: CitationTreeResponse, latency_ms: int, depth_requested: int
) -> None:
    hub = getattr(request.app.state, "observability", None)
    if hub is None:
        return
    emit_log = getattr(hub, "emit_log", None)
    if emit_log:
        try:
            emit_log(
                {
                    "event": "citation_graph.lookup",
                    "paperId": response.rootPaperId,
                    "cacheHit": response.cacheHit,
                    "providerStatus": response.providerStatus,
                    "nodeCount": len(response.nodes),
                    "unresolvedCount": len(response.unresolved),
                    "depthRequested": depth_requested,
                    "depthReturned": response.depthReturned,
                    "truncated": response.truncated,
                    "latencyMs": latency_ms,
                }
            )
        except Exception:  # noqa: BLE001 - observability is advisory
            pass
    # US-CG6 metrics via the U6 hub (CloudWatch when CLOUDWATCH_NAMESPACE is set). Tags stay
    # low-cardinality — paperId lives in the log line only, never in a metric dimension.
    cache = "hit" if response.cacheHit else "miss"
    _metric(hub, "citation.graph.lookup", 1.0, {"cache": cache})
    if response.providerStatus in {"rate_limited", "unavailable"}:
        # rate_limited = upstream 429; unavailable = timeout/HTTP error/misshapen body.
        _metric(hub, "citation.graph.provider_error", 1.0, {"status": response.providerStatus})
    resolved_total = len(response.nodes) + len(response.unresolved)
    if resolved_total:
        _metric(
            hub,
            "citation.graph.unresolved_ratio",
            len(response.unresolved) / resolved_total,
            {},
        )
    _metric(hub, "citation.graph.node_count", float(len(response.nodes)), {})
    _metric(hub, "citation.graph.latency_ms", float(latency_ms), {})


@router.get("", response_model=CitationTreeResponse)
async def get_citation_tree(
    paper_id: str,
    request: Request,
    expandNodeId: str | None = None,
    refresh: bool = Query(default=False),
    _: Principal = PRINCIPAL_DEP,
    store: InMemorySnapshotStore = STORE_DEP,
    provider: SemanticScholarProvider = PROVIDER_DEP,
) -> CitationTreeResponse:
    started = time.perf_counter()
    parent = expandNodeId or paper_id
    depth_requested = 2 if expandNodeId else 1
    key = f"{paper_id}:{parent}"
    if not refresh and (cached := await store.get(key)):
        _emit(request, cached, int((time.perf_counter() - started) * 1000), depth_requested)
        return cached

    provider_status, items = await provider.references(parent, _max_visible_nodes() + 1)
    if provider_status in {"rate_limited", "unavailable"} and not items:
        degraded = CitationTreeResponse(
            status="RateLimited" if provider_status == "rate_limited" else "Unavailable",
            rootPaperId=paper_id,
            nodes=[],
            edges=[],
            depthReturned=0,
            providerStatus=provider_status,
        )
        _emit(request, degraded, int((time.perf_counter() - started) * 1000), depth_requested)
        return degraded
    paper_service = getattr(
        getattr(request.app.state, "discovery_bundle", None),
        "paper_service",
        None,
    )
    try:
        response = _build_tree(paper_id, parent, items, paper_service).model_copy(
            update={"providerStatus": provider_status}
        )
    except Exception:  # noqa: BLE001 - a misshapen provider item (e.g. string year) degrades, never 500 (BR-CG12)
        degraded = CitationTreeResponse(
            status="Unavailable",
            rootPaperId=paper_id,
            nodes=[],
            edges=[],
            depthReturned=0,
            providerStatus="unavailable",
        )
        _emit(request, degraded, int((time.perf_counter() - started) * 1000), depth_requested)
        return degraded
    await store.set(key, response)
    _emit(request, response, int((time.perf_counter() - started) * 1000), depth_requested)
    return response


@router.post("/save")
async def save_citation_node(
    dto: SaveCitationNodeRequest,
    principal: Principal = PRINCIPAL_DEP,
    library: LibraryService = LIBRARY_DEP,
):
    node = dto.node
    if not node.saveable or not node.arxivId:
        raise HTTPException(status_code=422, detail="citation node is not saveable")
    return library.add(
        principal,
        LibraryItemCreateDTO(
            arXivId=node.arxivId,
            meta={
                "title": node.title,
                "authors": [],
                "year": _library_year(node.year),
                "arxivId": node.arxivId,
                "abstractSnippet": None,
                "arxivUrl": node.url,
            },
        ),
    )


routers = (router,)
