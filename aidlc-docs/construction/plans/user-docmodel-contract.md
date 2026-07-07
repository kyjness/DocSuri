# User-uploaded PDF → doc-model contract (PR0 freeze)

**Status: FROZEN** — team review 2026-07-05 (유진). This pins the cross-service contract so PR① (ingestion),
PR② (backend), PR③ (frontend) implement against one source and cannot drift. Design thread: issue #268 (cc #252).

Route user-uploaded PDFs (evidence attachments, novelty manuscripts) through the **same doc-model pipeline** the
arXiv corpus uses (Q6=A), rather than a parallel text-extraction path. The arXiv build contract is arXiv-only
(`JobKind.BUILD_DOC_MODEL` self-fetches by arXiv id; `enqueue_build(paper_id, version)` can't express "a file already
in S3"), so user uploads need a new job kind with an S3-source payload.

## 1. Identity namespaces (settled)

| Handle | Form | Notes |
|--------|------|-------|
| `paperId` | `userdoc:{uuid}` | Synthetic. Also the doc-model cache key (with `version`). **No arXiv id exists — consumers MUST NOT synthesize an `arxiv.org` URL from it (무날조).** |
| `recordRef` | `upload:{ownerId}:{jobId}:{attachmentId}` | Real internal handle (SourceRef 실재성 검증). Never display-name based. |
| `version` | `1` | User docs are single-version. |

SSOT pinned in `shared/dtos/docmodel.schema.json` (`DocModelRequest.paperId`, `DocModelMeta.paperId`, `SourceTier`)
and `shared/dtos/evidence.schema.json` (`SourceRef`). The known arXiv-URL-assembly site to branch:
`backend/modules/novelty/adapters.py:215-232` (builds `https://arxiv.org/abs/{paper_id}` — must skip for `userdoc:` ids).

The produced doc-model's `provenance.sourceTier` = `"pdf"` (extraction rung). Origin is carried by the `userdoc:`
namespace, **not** a new `SourceTier` value — decided to avoid double-encoding the same fact.

`ponytail:` origin is an implicit paperId-prefix convention, not an explicit field. Upgrade path: if telemetry needs to
count user-vs-arXiv doc-models directly, add an optional `provenance.origin` enum then — YAGNI until a second consumer needs it.

## 2. `BUILD_USER_DOC_MODEL` job payload (settled)

Sibling of the existing `BUILD_DOC_MODEL` payload (`{jobId, kind, arxivRef, ...}`), but S3-sourced — **no `arxivRef`**:

```jsonc
{
  "jobId":         "userdoc-{uuid}",              // DLQ/trace handle
  "kind":          "BUILD_USER_DOC_MODEL",
  "paperId":       "userdoc:{uuid}",              // synthetic id + doc-model cache key
  "version":       1,
  "objectKey":     "…",                            // S3 key of the uploaded file (upload bucket)
  "module":        "evidence" | "novelty",         // which consumer requested the build
  "ownerId":       "{accountId}",                  // recordRef assembly + access scoping
  "recordRef":     "upload:{ownerId}:{jobId}:{attachmentId}",
  "correlationId": null,
  "eventId":       null
}
```

- **PR② (backend, producer):** on an evidence/novelty PDF, upload to S3 → construct this payload → enqueue onto the
  existing `DOCSURI_DOCMODEL_BUILD_QUEUE_URL`. Best-effort (a failed enqueue degrades, never 500s); idempotent dedup on
  `(paperId, version)`. Manuscript upload reuses the PR #376 manuscript path; evidence attachments add the same pattern.
- **PR① (ingestion, consumer):** `job_from_payload` must accept `BUILD_USER_DOC_MODEL` **without** `arxivRef`. Worker
  branch: S3 `GetObject(objectKey)` → `pdfplumber` parse → (GROBID structure extraction **iff** `DOCSURI_GROBID_URL`
  set) → write the doc-model to `doc-model/{paperId}/v{version}.json` in `DOCSURI_DOCMODEL_BUCKET`, identical output
  format to the arXiv path. Malformed/parse-failure → isolate to DLQ via the existing poison-payload path (RES-9/BR-18);
  do not crash-loop the worker.
- **Storage note:** `paperId` contains `:`, so the artifact key is `doc-model/userdoc:{uuid}/v1.json` (S3 accepts `:`).
  Consumers must not assume `paperId` is a bare arXiv id anywhere in the path/URL logic.

## 3. Readiness = polling (settled)

Reuse the existing `building` / `retryAfterMs` model (`docmodel.schema.json` `BuildingDTO`): backend polls
`getDocModel(paperId, version)` → `building` until the artifact exists, then feeds the doc-model into the same md/txt
extraction path. **Bounded polling + timeout in the worker/orchestrator — no infinite wait.** Chosen over a completion
callback queue (smaller surface, matches the existing model).

## 4. Failure UX = partial degradation (settled)

Never fail the whole job; degrade the one attachment/input:

- **evidence:** `[첨부 안내] PDF 본문을 해석하지 못해 첨부 근거는 제외했습니다.`
- **novelty:** `degradedReason = "manuscript_pdf_parse_unavailable"` (fits the existing string idiom, cf.
  `adapters.py:538` `cost_degraded`).
- When a manuscript PDF is the **sole** input and it can't be parsed, the path must end in **분석 저하 / 근거 부족** —
  never fabricate a result.

## 5. GROBID = pdfplumber-only for the first PR (settled)

The first PR must deploy **without** GROBID (`DOCSURI_GROBID_URL` env-gated; pdfplumber-only otherwise). Infra fact:
the GROBID sidecar exists **only** on the bulk ingestion worker (`ops/cdk/stacks/ingestion_stack.py:231-259`,
`DOCSURI_GROBID_URL=http://127.0.0.1:8070`); the latency-sensitive docmodel worker deliberately omits it (`:305`
comment). So user-PDF jobs on the existing docmodel queue run **pdfplumber-only today** regardless of the env flag.
Deferred past the first PR: attach a sidecar to the docmodel worker, or split a dedicated user-PDF worker/queue.

## PR split

```
PR0 (this) — shared contract freeze: schema descriptions + regenerated DTOs + this doc.  ← DONE
  → PR① ingestion — BUILD_USER_DOC_MODEL JobKind + S3-source worker branch (pdfplumber-only).
    → PR② backend  — S3 upload + enqueue + bounded polling; evidence/novelty consume the doc-model.
      → PR③ frontend — PDF binary upload (s3:PutObject already live-verified, #252).
```
