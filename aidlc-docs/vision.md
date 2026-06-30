# Vision Document — DocSuri

> **Artifact type**: Vision Document (AI-DLC inception input, per upstream
> `awslabs/aidlc-workflows` `docs/writing-inputs/vision-document-guide.md`).
> Business/product counterpart to `technical-environment.md`. Consolidates the
> re-inception charter, `inception/requirements/requirements.md`, and
> `inception/user-stories/personas.md` into the single project-level vision input the
> workflow (and `tools/aidlc-designreview`) expects. **Date**: 2026-06-28.

## Executive Summary

DocSuri is a **phone-first web app for AI/ML researchers to discover, understand, and
build on arXiv literature**. It combines hybrid semantic+lexical discovery over an
Open-Access AI/ML corpus with **grounded** Korean-language summaries/translation, a
citation graph, and a research-idea agent — so a Korean-speaking researcher can go from
"what's relevant?" to "what does it say, and where does my idea fit?" on a phone, with
every AI claim anchored to source text (no fabrication).

## Business Context

### Problem Statement

AI/ML output on arXiv outpaces any individual's ability to track it. Existing tools are
desktop-centric, English-centric, and either keyword-shallow or LLM-summaries that
hallucinate. Korean researchers lack a mobile, trustworthy, grounded way to discover and
digest papers.

### Business Drivers

- Volume of AI/ML preprints makes manual triage infeasible.
- Trust gap: ungrounded LLM summaries are unusable for research.
- Mobile/Korean-first is underserved.

### Target Users and Stakeholders

| Persona | Role | Priority |
|---------|------|----------|
| P1 — Active AI/ML researcher / PhD student | Primary user | PRIMARY |
| P2 — Grad student in early literature review | Secondary user | SECONDARY |
| OP — Operator / maintainer | Runs the system (not an end user) | — |

### Business Constraints

- AWS only (**C-5**); **$1600** total budget cap.
- **Strict Open Access (OA)** licensing — only OA content is ingested/served.
- Phone-only web (responsive, mobile-first).
- All-Korean team; English docs, Korean user-facing content by design.

### Success Metrics

- Grounded-answer fidelity (no fabrication; claims anchored to source).
- Discovery relevance (hybrid search quality vs. lexical baseline).
- Time-to-understanding (search → grounded summary on mobile).
- Cost within the $1600 cap.

## Full Scope Vision

### Product Vision Statement

The trusted mobile companion for AI/ML research: discover the right papers, understand
them in Korean with grounded summaries, see how work connects via citations, and surface
where a new idea is novel — all anchored to source.

### Feature Areas

| Area | Unit(s) | Description |
|------|---------|-------------|
| Corpus ingestion | U1 | OA AI/ML harvest (arXiv + Semantic Scholar/OpenAlex), DocModel build, index generations |
| Discovery | U2 | Hybrid vector (k-NN) + lexical (BM25) search with RRF, grounding-enforced results |
| Accounts | U3 | Auth (sessions, Google OIDC), lifecycle, GDPR-style deletion |
| Library | U4 | Saved papers/searches, history, rerun |
| Frontend | U5 | Phone-first web UI |
| Reliability/Ops | U6 | Gateway (security/rate/cost/grounding), observability, ops dashboard |
| Summarization/Translation | U7 | Grounded Korean summaries (document-fidelity anchoring) |
| Citation graph | U8 | Citation snapshots from external providers |
| Personalization | U9 | Bounded behavior-based search boosts |
| My Page | U10 | User settings/profile/consents |
| Research Agent | U11 | Grounded research-idea/novelty assistance |

### Integration Points

- Amazon Bedrock (Cohere embeddings, Claude summarization).
- External academic APIs (arXiv, Semantic Scholar, OpenAlex) — OA only.
- Resend (transactional email).

### User Journeys (Full Vision)

1. Search a topic → grounded, ranked results → save to library.
2. Open a paper → grounded Korean summary with source anchors.
3. Explore citations → see how a paper connects.
4. Ask the research agent → grounded novelty/idea assistance.

### Scalability and Growth

Single-writer/blue-green index generations today; read-replica/scale-out is a known
future lever. Corpus starts as an AI/ML slice and can expand by source/coverage.

## MVP Scope

### MVP Objective

Ship a live, end-to-end grounded discovery product on mobile, then layer understanding
(summary/translation), connections (citations), and ideation (agent).

### Features In Scope (MVP — live)

- Discovery (U2), Library (U4), Accounts (U3), Frontend (U5), Reliability/Ops (U6),
  Corpus ingestion (U1). **Product is E2E live** (`docsuri.org`, since 2026-06-18).

### Features Explicitly Out of Scope (this cycle)

- Research-agent Mode B (external-API coverage expansion) — domain/port seam only.
- Non-AI/ML corpus expansion.

### MVP Constraints and Assumptions

- OA-only corpus; $1600 cap; AWS; phone-only.
- Grounding is non-negotiable: abstain over fabricate.

### MVP Definition of Done

Real end-to-end chain (no stubs in production), grounded results/summaries, secure
auth, observability + alerting in place.

## Risks and Dependencies

### Key Risks

- **Grounding fidelity** drift across search/summary/agent surfaces.
- **Cost** overrun against the $1600 cap (LLM/embedding spend).
- **OA licensing** — must never ingest/serve non-OA content.
- **Single-writer index** availability during rebuilds.

### External Dependencies

- Amazon Bedrock model access; arXiv/Semantic Scholar/OpenAlex availability and quotas;
  Resend deliverability.

### Open Questions

- Final grounding-contract unification across U6/U7/U11 (intentionally parallel today).
- Read-replica/scale-out timing for the corpus index.

## How This Document Feeds Into AI-DLC

- Anchors the inception chain (requirements → user-stories → application-design →
  unit-of-work); the re-inception charter remains the detailed SSOT.
- Supplies product/business context to `tools/aidlc-designreview` (classified `VISION`),
  the counterpart to `technical-environment.md`.
