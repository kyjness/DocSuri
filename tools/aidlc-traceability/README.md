# aidlc-traceability (DocSuri fork)

DocSuri-local fork of [`awslabs/aidlc-workflows`](https://github.com/awslabs/aidlc-workflows)
`scripts/aidlc-traceability` **v1.0.0**, patched to parse DocSuri's Korean AI-DLC docs and
monorepo layout. Generates a requirements↔stories↔units↔components↔code traceability matrix
from `aidlc-docs/` + source. Used **rule-based** (`--no-ai`, no Amazon Bedrock).

## Run

```bash
uv run --directory tools/aidlc-traceability \
  traceability generate --input . --no-ai --format markdown -o tools/aidlc-traceability/out
```

`--format both` also emits HTML. AI mode (omit `--no-ai`) needs Amazon Bedrock — see the upstream README.

## DocSuri patches (vs upstream v1.0.0)

Upstream rule-based parsers recognised only stories on DocSuri (Korean headers, no per-item ID
prefixes, em-dash separators, code outside `src/`). All edits are marked `# DocSuri fork:`:

- `discovery.py` — scan DocSuri monorepo source roots (`backend/`, `ingestion/`, `ops/`, `shared/`, `frontend/`).
- `parsers/requirements.py` — extract inline `FR-/NFR-/SEC-/RES-/QT-N` ID tokens from Korean numbered sections.
- `parsers/units.py` — parse the `| **U1 Ingestion** | … |` unit table (IDs `U1..U8`) + story→unit map.
- `parsers/components.py` — parse `## U<n> — Name` headers + component tables; emit unit→component and component→requirement/story edges.
- `parsers/code_plans.py` — accept `### Step N —` (em-dash); namespace step IDs per unit; parse the "스토리 추적성" step→story table.
- `parsers/linker.py` / `pipeline.py` — story↔requirement via `**Traces**:` lines; rule-based code→unit and component→code linkers.

## Result (rule-based)

Empty matrix → **936 relationships / 917 edges**. Coverage: Reqs→Stories 81% · Stories→Units 100% · Units→Components 75% · Components→Code 59%.

## Known limits

- Units→Components is 6/8: `components.md` documents only U1–U6 (U7/U8 lack component tables — a DocSuri doc gap, not a parser limit).
- Components→Code is partial; full closure needs the AI stage.

Licensed under the upstream MIT license (`LICENSE`).
