# shared/ — Language-Neutral Source of Truth (DocSuri)

> **Phase:** CONSTRUCTION → shared contracts authored first (precursor to 3 parallel tracks).
> **Repo layout:** monorepo (UQ2=A). **Ownership:** single-owner shared layer (UQ5=A).
> **Spec source of truth:** [`aidlc-docs/construction/shared/`](../aidlc-docs/construction/shared/) — see [Links](#links-to-specs).

This package is the **language-neutral source of truth** for the cross-cutting
contracts that three parallel tracks consume:

- **Track ① (U1 → U6)** — ingestion + observability/incidents.
- **Track ② (U3 → U4)** — accounts/auth + saved-searches/library/history.
- **Track ③ (U2 mock → U5)** — discovery/search + phone UI.

Each track depends on **stable contracts** and develops independently; per-language
types are **generated per-track** from these schemas later (see [Codegen](#codegen)).

---

## Purpose

The data contracts live here once, in a language-neutral format, so no track forks
its own copy and no two tracks drift. FROZEN contracts are consumed as-is;
PROVISIONAL contracts are developed under a "contract-first" agreement and
synchronized when the owning unit's FD completes.

| Status | Meaning |
|---|---|
| 🔒 **FROZEN** | Owning unit FD/NFR complete; changing it has broad impact. |
| 🟡 **PROVISIONAL** | Shape follows inception `application-design`; refined in the owning unit's FD. |

---

## Ownership

- **Single owner (UQ5=A):** `shared/` is a single-owned shared layer. **No unit forks it.**
- **Changes only via a `shared/` PR + cross-track sign-off.** A change touching a
  contract that an affected unit consumes requires that unit's sign-off (e.g. a
  Ports interface change ⇒ U2/U1/U6 sign-off; a FROZEN contract change ⇒ broad sign-off).
- **Additive evolution:** adding a field is backward-compatible; removing a field or
  changing meaning is a version bump. Consumers ignore unknown fields (forward-compat).
- **Security invariant (all contracts):** DTOs/events/observability entries expose
  **no internal fields** — no owner `userId` in external DTO bodies, no raw scores,
  no debug/trace/audit meta, no internal IndexRecord fields (e.g.
  `vector`/`lexicalTerms`/`chunkId`/`section`/`categories`, and the full `abstract`) (SEC-9);
  logs/events carry **no PII/secrets** (SEC-3); `password` is request-input-only and
  never in any response (SEC-12/SEC-3).

---

## Layout

```
shared/
├── README.md                     ← this file (package overview)
├── vector-spec/                  ← 🔒 FROZEN embedding contract + IndexRecord
│   ├── vector-spec.yaml          ← embedding config (model/dimensions/distanceMetric/normalize/inputType/specVersion)
│   └── index-record.schema.json  ← IndexRecord schema (per-chunk index document)
├── dtos/                         ← 🟡 PROVISIONAL API↔client DTOs (JSON Schema per DTO group)
│   ├── search.schema.json        ← U2 search/card DTOs (cards FROZEN-adjacent)
│   ├── accounts.schema.json      ← U3 account/auth DTOs
│   ├── library.schema.json       ← U4 saved-searches / library / history DTOs
│   ├── summarization.schema.json ← U7 summarize/translate/asset DTOs
│   └── docmodel.schema.json      ← doc-model (U1 builder → U7/U5/agent; pivot 2026-06-23)
├── events/                       ← 🟡 partially-FROZEN event-backbone contracts (JSON Schema)
│   ├── search-executed.schema.json  ← 🔒 SearchExecutedEvent (U2 → U4)
│   ├── ingestion.schema.json        ← NewArxivEvent (consume) + IngestionFailureSignal (U1 → U6)
│   ├── account-signals.schema.json  ← AccountCreated / SignupAbuseSignal / AuthFailureSignal (U3 → U6)
│   └── incidents.schema.json        ← ClassifiedIncident / OpsAlert (U6 AI incidents)
├── ports/                        ← 🟡 cross-cutting hook INTERFACES (not data schemas)
│   └── README.md                 ← interface signatures (normative SSOT for ports)
└── python/                       ← Python binding (§5-A decided: backend·ingestion·ops = Python)
    ├── src/docsuri_shared/       ← importable package `docsuri_shared`
    │   ├── _generated/           ← pydantic v2 models GENERATED from the schemas (committed, drift-checked)
    │   ├── dtos.py · events.py   ← clean re-exports of the generated DTO/event models
    │   ├── vector_spec.py        ← IndexRecord + embedding constants (mirror of vector-spec.yaml)
    │   ├── ports.py              ← `typing.Protocol` stubs (from ports/README.md)
    │   └── ids.py                ← deterministic `chunk_id(paper_id, ordinal)`
    ├── tools/generate.py         ← regenerate `_generated/`; `--check` is the CI drift guard
    └── tests/                    ← schema validity · round-trip · PBT(chunk_id) · SEC-9/8/12 invariants
```

> The four contract groups map 1:1 to the four spec files in
> `aidlc-docs/construction/shared/` (overview §2). The DTO/event file split is by
> producing unit/DTO group; the exact per-group filenames follow the
> `<group>.schema.json` convention (e.g. U4's library/saved-search/history DTOs in
> `dtos/library.schema.json`).

### Format per contract group

| Group | Format | Rationale |
|---|---|---|
| `vector-spec/index-record.schema.json` | **JSON Schema** (draft 2020-12) | IndexRecord is a data shape (writer↔reader contract). |
| `vector-spec/vector-spec.yaml` | **YAML config** | Embedding contract is config (model/dims/metric/normalize/inputType writer-vs-reader/specVersion), not a per-record shape. |
| `dtos/*.schema.json` | **JSON Schema** (draft 2020-12) | API↔client DTO shapes; shared sub-shapes via `$defs` + `$ref`. |
| `events/*.schema.json` | **JSON Schema** (draft 2020-12) | Event payload shapes; multi-event files use `$defs` + `oneOf` for the variant set. |
| `ports/README.md` | **Markdown (interface doc)** | Ports are method interfaces, not data schemas — the normative SSOT for ports. The Python `Protocol` stubs derived from it live in `python/src/docsuri_shared/ports.py` (§5-B, enabled by §5-A=Python). |

---

## Codegen

These contracts are the SSOT; typed bindings are **generated from them**, never hand-edited:

- **Python (backend U2/U3/U4/U6-middleware · ingestion U1 · ops U6)** — §5-A decided
  *all* services are Python (one modular-monolith runtime), so there is **one shared
  Python binding** in [`python/`](python/), not a per-track copy: JSON Schema →
  **pydantic v2** via `python/tools/generate.py`. The generated models are **committed**
  (so consumers need no codegen tool) and **drift-checked** in CI
  (`uv run python tools/generate.py --check`) so they can never diverge from the schemas.
- **TS frontend (U5)** — JSON Schema → **TypeScript types**, **deferred to U5** (frontend
  stack is confirmed in U5 NFR Requirements, §5-D). The same schema files here are the
  source, so the TS types will share one origin with the Python ones.

Field names/types match the specs exactly. **Do not hand-edit generated types** — change
the schema here (via the shared PR + sign-off above) and regenerate.

### Ports — Python `Protocol` (schema can't express behavior)

`ports/` are method interfaces, not data shapes, so they are **not** codegen'd from JSON
Schema. §5-B (enabled by §5-A=Python) lifts the deferral: the Python
`typing.Protocol` stubs are authored in
[`python/src/docsuri_shared/ports.py`](python/src/docsuri_shared/ports.py) directly from
[`ports/README.md`](ports/README.md) (the signatures remain the SSOT). The TS `interface`
stubs follow with U5 (§5-D). See `ports/README.md` for the dependency-inversion seam that
breaks the U2↔U6 sync cycle.

---

## Versioning

- **VectorSpec change = full corpus re-embed.** Any change to `vector-spec.yaml`
  `specVersion` / `model` / `dimensions` (and by extension the IndexRecord embedding
  shape) is a **one-way, costly, full re-embed** of the corpus. The invariant is that
  the U1 writer and U2 reader consume the **same `specVersion`**; CI/deploy SHOULD
  assert writer/reader `specVersion` equality. This makes VectorSpec effectively frozen.
- **DTO / Event** — additive evolution (add = backward-compatible; remove / meaning
  change = version bump). `SearchExecutedEvent` is FROZEN (U2 producer + U4 consumer);
  changing it needs broad sign-off.
- **Ports** — interface changes need a shared PR + U2/U1/U6 sign-off; PROVISIONAL
  items sync when U6 FD completes.

---

## Links to specs

The authoritative specifications (already merged to `develop`) live in
`aidlc-docs/construction/shared/`:

- [`00-shared-contracts-overview.md`](../aidlc-docs/construction/shared/00-shared-contracts-overview.md) — ownership (UQ5=A), status legend, per-track consumption.
- [`vector-spec.md`](../aidlc-docs/construction/shared/vector-spec.md) — 🔒 FROZEN embedding contract + IndexRecord schema.
- [`dtos.md`](../aidlc-docs/construction/shared/dtos.md) — U2 search/card, U3 account, U4 library DTOs.
- [`events.md`](../aidlc-docs/construction/shared/events.md) — SearchExecutedEvent, NewArxivEvent, U3 signals, U1 failure signal, U6 incidents.
- [`ports.md`](../aidlc-docs/construction/shared/ports.md) — GroundingEnforcementHook, CostGuardCircuitBreaker, ObservabilityHub interfaces.
- [`docmodel.md`](../aidlc-docs/construction/shared/docmodel.md) — 🟡 doc-model structured-document contract (U1 builder → U7 summary input / U5 rich view / agent; pivot 2026-06-23).

Every field/name in this package traces back to these specs (and the FR/NFR/SEC/BR
trace IDs they cite). Do not introduce fields that are not in the specs.
