# SPDX-License-Identifier: MIT
# Copyright (c) 2026 AIDLC Traceability Tool Contributors
"""Parse code-generation-plan.md files."""

from __future__ import annotations

import re
from pathlib import Path

from traceability.models import Artifact, ArtifactType, Relationship


# DocSuri fork: derive a unit prefix (U1..U8) from a code-generation-plan filename
# like "u1-ingestion-code-generation-plan.md" so step IDs are unique per plan.
_UNIT_PREFIX_PATTERN = re.compile(r"^(u\d+)", re.IGNORECASE)


def _unit_prefix(file_path: Path) -> str | None:
    m = _UNIT_PREFIX_PATTERN.match(file_path.name)
    return m.group(1).upper() if m else None


def parse_code_plans(file_path: Path) -> tuple[list[Artifact], list[Relationship]]:
    """Parse code generation plan steps as artifacts.

    Handles formats:
    - ### Step 1: Title
    - ### Step 1 — Title      (DocSuri fork: em-dash separator)
    - - [ ] Step 1: Title

    DocSuri fork: also parses the "스토리 추적성" (story traceability) table,
    emitting step -> story relationships so code-plan steps gain coverage edges.
    Step IDs are namespaced by unit prefix (e.g. STEP-U1-2) to avoid collisions
    across the per-unit plan files.
    """
    content = file_path.read_text(encoding="utf-8")
    lines = content.split("\n")
    artifacts: list[Artifact] = []
    relationships: list[Relationship] = []

    prefix = _unit_prefix(file_path)
    pfx = f"{prefix}-" if prefix else ""

    # DocSuri fork: accept both ":" and "—" (em-dash) / "-" / "–" after the step number.
    # Match header-style steps: ### Step 1: Title  OR  ### Step 1 — Title
    header_pattern = re.compile(
        r"^#{2,4}\s+Step\s+(\d+)\s*(?::|[-—–])\s*(.+)", re.IGNORECASE
    )
    # Match checkbox-style steps: - [ ] Step 1: Title  OR  - [ ] Step 1 — Title
    checkbox_pattern = re.compile(
        r"^-\s*\[[ x]\]\s*Step\s+(\d+)\s*(?::|[-—–])\s*(.+)", re.IGNORECASE
    )

    # DocSuri fork: story IDs referenced in the traceability table rows.
    story_id_pattern = re.compile(r"((?:US|STORY)-[\w]+)", re.IGNORECASE)
    # A traceability-table row mentions one or more "Step N" tokens alongside stories.
    step_ref_pattern = re.compile(r"Step\s+(\d+)", re.IGNORECASE)

    seen_step_ids: set[str] = set()

    for i, line in enumerate(lines, start=1):
        m = header_pattern.match(line) or checkbox_pattern.match(line)
        if m:
            step_num = m.group(1)
            title = m.group(2).strip()
            completed = "[x]" in line.lower()
            step_id = f"STEP-{pfx}{step_num}"
            if step_id not in seen_step_ids:
                seen_step_ids.add(step_id)
                artifacts.append(Artifact(
                    id=step_id,
                    title=title,
                    artifact_type=ArtifactType.CODE_PLAN,
                    source_file=str(file_path),
                    source_line=i,
                    metadata={"completed": completed, "unit": prefix},
                ))
            continue

        # DocSuri fork: story-traceability table rows, e.g.
        # | US-I1 arXiv 인제스천 | Step 2, Step 4, Step 7 |
        stories = story_id_pattern.findall(line)
        if stories:
            step_nums = step_ref_pattern.findall(line)
            for story_id in stories:
                for sn in step_nums:
                    relationships.append(Relationship(
                        source_id=f"STEP-{pfx}{sn}",
                        target_id=story_id.upper(),
                        relationship_type="implements",
                    ))

    return artifacts, relationships
