# backend/modules/discovery — U2 Discovery (Track 3)

> **Owner:** @kyjness (Track 3) · **Deploy unit:** ① backend API (modular monolith) · **Runtime:** Python (§5-A)
> **Status:** 🟢 mock-first read path + **real OpenSearch/Bedrock adapters** (CG-2/MR-4). The
> app-shell wires the real read path when `DOCSURI_OPENSEARCH_ENDPOINT` + `DOCSURI_BEDROCK_MODEL_ID`
> are set, otherwise stays mock-first. Cloud provisioning (cluster/model/event bus) is the shared
> infra track's job — U2 only reads the configured endpoint.

This is the **U2 Discovery** module of the backend modular monolith (deploy unit ①).
It is **not a standalone app**: it is mounted into the shared app-shell owned by
@ELSAPHABA (`backend/` bootstrap·router·DI). Touch only this directory; app-shell /
middleware wiring goes through the coordination-zone owner.

## Responsibility

The synchronous search **read path**: query intake → query understanding → hybrid
search → ranking → grounding adapting → result assembly. See
`aidlc-docs/inception/application-design/` and the U2 functional design (authored
during this track's loop).

- **Stories owned:** US-D1 (NL query), US-D2 (semantic search), US-D3 (top-N ranking),
  US-D4 (phone card assembly), US-D6 (abstain).
- **Contributes to:** US-D5/D7 (grounding/state UX), US-R1/R2 (grounding/degradation),
  US-H1 (hero backing).
- **Produces:** `SearchExecutedEvent` (→ U4 history).

## Mock-first

U2 shipped a **mock** first so Track 3's U5 frontend could develop in parallel before the
real search engine existed. The mock returns responses shaped by the **frozen
`SearchResponse` contract** in `shared/dtos/search.schema.json` (union: result page /
abstain / degraded / validation error).

## Real read path (CG-2 / MR-4)

`adapters/` implements the U2 ports against the infrastructure the U1 writer already
populates — the SAME index (`docsuri-corpus-v1`) and FROZEN embedding space (vector-spec §4):

| Adapter | Port | Mirror of (U1 writer) |
|---|---|---|
| `BedrockCohereQueryEmbedder` | `EmbeddingAdapter` | `BedrockCohereEmbeddingPort` (but `input_type=search_query`) |
| `OpenSearchVectorStoreAdapter` | `VectorStoreAdapter` | `OpenSearchVectorIndex` (k-NN cosine reader) |
| `OpenSearchLexicalIndexAdapter` | `LexicalIndexAdapter` | `OpenSearchVectorIndex` (BM25 reader) |
| `EventBridgeEventPublisher` | `EventPublisher` | `SqsQueue` (non-blocking SearchExecuted → U4 history) |

Swapping mock ↔ real is a **wiring** decision (`real_wiring.build_real_orchestrator` vs
`testing.wiring.build_mock_orchestrator`), not a contract change. The grounding gate stays U6's
single authority (INV-1) in both modes. Embedding is a separable dependency (Bedrock down →
lexical-only degrade); the OpenSearch index has no fallback (down → fail-closed, INV-3).

**Local validation (no cloud):** bring up `backend/docker-compose.yml`'s `opensearch`, seed a
deterministic mini-corpus, and run the live integration suite — see *Run / test* below.

## Consumes (from `shared/`, do not fork or edit)

| Contract | Role | Notes |
|---|---|---|
| `shared/dtos/search.schema.json` | **producer** (U5 consumes) | `SearchRequest` / `SearchResponse`; card fields are FROZEN-adjacent. |
| `shared/vector-spec/` | **reader** | Query embedding shares U1 writer's space (Cohere 1024 · cosine). 🔒 FROZEN. |
| `shared/events/search-executed.schema.json` | **producer** | → U4 history. 🔒 FROZEN. |
| `shared/ports/` (Grounding · Cost hooks) | **dependant** | Depends on the interface; U6 implements (breaks U2↔U6 cycle). |

## Invariants

- **SEC-9:** DTOs expose no internal fields (owner `userId`, raw scores, debug,
  `vector`/`chunkId`/`section`). Cards carry only the 7 projected fields.
- **SEC-5 / FR-1:** validate `query` (non-empty · ≤500 chars · sanitized) before processing.
- Grounding (FR-5): every exposed card maps to a real IndexRecord (real arXiv id/link) —
  zero fabrication; enforced at the response edge by U6's `GroundingEnforcementHook`.

## Layout

```
src/discovery/
├── domain/         # framework-agnostic core: models, validator, expander, retriever
│   │               #   (RRF + PaperId dedup), ranker (baseline top-20), grounding_adapter
│   │               #   (INV-1: shape/map only), assembler (7-field cards, SEC-9)
├── ports/          # U2-owned ports: EmbeddingAdapter/VectorStoreAdapter/LexicalIndexAdapter
│                   #   + EventPublisher; dependency-isolation exceptions
├── adapters/       # REAL adapters (`real` extra): Bedrock query embedding (search_query),
│                   #   OpenSearch k-NN + BM25 reader, EventBridge publisher, settings (env)
├── cache/          # read-through embedding cache (TTL) — NFR-P1/C1
├── service/        # SearchOrchestrationService — pipeline split at the grounding seam
│                   #   (plan_and_retrieve / finalize) so the domain never calls enforce
├── api/            # gateway_seam.run_search (the single enforce invocation, INV-1) +
│                   #   router.py (thin FastAPI binding — `api` extra, app-shell-pending)
├── defaults/       # U6 port defaults taken when a hook is uninjected (PRODUCTION path)
├── testing/        # deterministic fixtures (KO↔EN cross-lingual + QT-2), mock adapters,
│                   #   build_mock_orchestrator()
├── real_wiring.py  # build_real_orchestrator() — same pipeline, real adapters injected (MR-4)
└── scripts/        # seed_local_opensearch — create index mapping + seed mini-corpus (local)
tests/              # PBT-02/03/07/09 + terminal states + degrade matrix + RES-12 fault
                    #   injection + real-adapter unit tests + live OpenSearch integration
```

## Run / test (mock-first, standalone)

```sh
cd backend/modules/discovery
uv run pytest                 # PBT + unit + fault-injection + real-adapter unit tests
                              #   (no network; live OpenSearch integration auto-skips)
uv run ruff check src tests   # lint

# Real read path against a LIVE local OpenSearch (no cloud / no Bedrock needed):
docker compose -f ../../docker-compose.yml up -d opensearch
export DOCSURI_OPENSEARCH_ENDPOINT=http://localhost:9200
export DOCSURI_OPENSEARCH_USE_SSL=0 DOCSURI_OPENSEARCH_VERIFY_CERTS=0
uv run --extra real python -m discovery.scripts.seed_local_opensearch
uv run --extra real pytest tests/test_opensearch_integration.py   # k-NN + BM25 + hybrid
```

`uv` resolves `docsuri-shared` from the in-repo path dep (`../../../shared/python`). The
backend web framework (FastAPI) and integration packaging are app-shell decisions pending
@ELSAPHABA sign-off (CG-1); the domain core runs without FastAPI. The real OpenSearch/Bedrock
adapters are implemented (`adapters/`, the `real` extra) and selected by env without any
contract change (MR-4); they run against the shared cluster once the infra track provisions it.
