# U1 Corpus Units Review Plan

**Stage**: INCEPTION -> Units Generation
**Date**: 2026-06-26
**Scope**: Minimal review of existing unit boundaries for U1 Corpus.

## Decision

- U1 Corpus does not create a new unit.
- Existing **U1 Ingestion** remains the owner because source collection, full-text extraction, DocModel production, chunking, embedding, indexing, S3 storage, scheduler/watermark, retry, and DLQ are all one write-side Corpus pipeline.
- U2/U7/U11 remain consumers of shared capabilities, not co-owners of Corpus construction.

## Reviewed Question Categories

- **Story Grouping**: No split. US-I1/US-I2/US-I3 remain U1; US-R3/US-R4 remain U6.
- **Dependencies**: No code-cycle change. U1 writes Corpus artifacts; U2/U7/U11 read capabilities.
- **Team Alignment**: No new owner/team boundary.
- **Technical Considerations**: GROBID/runtime capacity and OpenSearch/S3 wiring are Infrastructure Design details inside U1, not a new unit.
- **Business Domain**: Corpus construction is still the ingestion domain.
- **Code Organization**: Existing `ingestion/` package remains the code location.

## Checklist

- [x] Review `unit-of-work.md` U1 definition.
- [x] Review `unit-of-work-dependency.md` U1 dependency edges and data-flow text.
- [x] Review `unit-of-work-story-map.md` U1 story ownership.
- [x] Update stale arXiv-only wording to multisource Corpus wording.
- [x] Keep unit count unchanged.
- [x] Validate markdown diff with `git diff --check`.
