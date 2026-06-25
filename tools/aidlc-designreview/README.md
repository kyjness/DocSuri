# aidlc-designreview

Automated design-review tool for DocSuri's AI-DLC artifacts. Parses the
`aidlc-docs/` design documents (requirements, user stories, application/unit
design, per-unit functional/NFR/infrastructure design) and produces a
severity-ranked review report (Markdown + HTML).

## Install

```bash
uv sync            # or: pip install -e .
```

## Usage

```bash
design-reviewer --aidlc-docs ../../aidlc-docs --output ./review
```

Options:
- `--aidlc-docs PATH` — path to the `aidlc-docs/` folder (required).
- `--output BASE` — output base path; writes `BASE.md` and `BASE.html` (default `./review`).
- `--config PATH` — path to `config.yaml` (default `./config.yaml`).

The reviewer uses `strands-agents` over Amazon Bedrock, so a run requires AWS
credentials and Bedrock model access in the configured account/region.
