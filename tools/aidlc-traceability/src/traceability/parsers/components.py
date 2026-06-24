# SPDX-License-Identifier: MIT
# Copyright (c) 2026 AIDLC Traceability Tool Contributors
"""Parse component and design artifacts."""

from __future__ import annotations

import re
from pathlib import Path

from traceability.models import Artifact, ArtifactType, Relationship


# DocSuri fork: unit section header inside components.md, e.g.
#   ## U1 — Ingestion (이벤트 드리븐 인제스천 워커)
_DS_UNIT_HEADER = re.compile(r"^#{2,3}\s+(U\d+)\s*[—–-]\s*(.+)", re.IGNORECASE)
# DocSuri fork: a component table data row whose first cell is a bold name, e.g.
#   | **ArxivSourceClient** | 목적... | 책임... | 인터페이스 | FR-6, C-1, RES-8 |
_DS_COMP_ROW = re.compile(r"^\|\s*\*\*\s*([A-Za-z][\w./-]*)\s*\*\*[^|]*\|(.*)$")
# DocSuri fork: requirement/story IDs referenced in the Trace column.
_DS_TRACE_TOKEN = re.compile(
    r"\b((?:FR|NFR|SEC|RES|QT|PBT)-[A-Z]?\d+|(?:US|STORY)-[\w]+)\b",
    re.IGNORECASE,
)


def _parse_docsuri_components(
    file_path: Path, lines: list[str]
) -> tuple[list[Artifact], list[Relationship]]:
    """Parse DocSuri components.md (unit-grouped component tables).

    Components live in markdown tables under `## U<n> — Name` headers; the final
    table column ("Trace") lists requirement/story IDs. Emits component artifacts
    plus unit->component and component->requirement/story relationships.
    """
    artifacts: list[Artifact] = []
    relationships: list[Relationship] = []
    seen_comp: set[str] = set()
    current_unit: str | None = None

    for i, line in enumerate(lines, start=1):
        h = _DS_UNIT_HEADER.match(line)
        if h:
            current_unit = h.group(1).upper()
            continue

        row = _DS_COMP_ROW.match(line)
        if not row:
            continue
        # Skip the table header row ("| 컴포넌트 | 목적 | ... |") — it has no bold first cell,
        # so it won't match _DS_COMP_ROW. Separator rows ("|---|") also won't match.
        name = row.group(1).strip()
        rest = row.group(2)
        comp_id = f"COMP-{name}"
        if comp_id not in seen_comp:
            seen_comp.add(comp_id)
            artifacts.append(Artifact(
                id=comp_id,
                title=name,
                artifact_type=ArtifactType.COMPONENT,
                description=rest.strip()[:400],
                source_file=str(file_path),
                source_line=i,
                metadata={"unit": current_unit} if current_unit else {},
            ))
        # unit -> component
        if current_unit:
            relationships.append(Relationship(
                source_id=current_unit,
                target_id=comp_id,
                relationship_type="realized_by",
            ))
        # component -> requirement/story (from Trace tokens anywhere in the row)
        for tok in _DS_TRACE_TOKEN.findall(rest):
            relationships.append(Relationship(
                source_id=comp_id,
                target_id=tok.upper(),
                relationship_type="traces_to",
            ))

    return artifacts, relationships


def parse_components(file_path: Path) -> tuple[list[Artifact], list[Relationship]]:
    """Parse component definitions from application-design files.

    A valid component section must have a heading followed by structured fields
    like **Component Name**, **Purpose**, or **Responsibilities**. Plain section
    headers (e.g. "Architecture Overview", "Next Steps") are skipped.

    DocSuri fork: components.md uses `## U<n> — Name` unit headers + component
    tables; detect and parse those first.
    """
    content = file_path.read_text(encoding="utf-8")
    lines = content.split("\n")

    # DocSuri fork: try DocSuri component-table format first.
    ds_arts, ds_rels = _parse_docsuri_components(file_path, lines)
    if ds_arts:
        return ds_arts, ds_rels

    artifacts: list[Artifact] = []

    # Match component headers like: ## ComponentName, ### 1. ComponentName, ### Component 1.1: Name
    comp_pattern = re.compile(r"^#{2,4}\s+(?:\d+(?:\.\d+)*\.?\s+)?([A-Z][\w]+(?:\s+[\w.:()-]+)*)", re.IGNORECASE)

    # Fields that indicate a real component definition
    component_field_pattern = re.compile(
        r"^\*\*(?:Component\s+Name|Purpose|Responsibilities|Public\s+Interface|Dependencies|Technology|Type|Exception\s+Hierarchy)\*\*",
        re.IGNORECASE,
    )

    # Extract the actual component name from **Component Name**: `FooBar`
    comp_name_pattern = re.compile(r"^\*\*Component\s+Name\*\*:\s*`?([^`\n]+)`?", re.IGNORECASE)

    # Extract the **Type**: field value
    comp_type_pattern = re.compile(r"^\*\*Type\*\*:\s*(.+)", re.IGNORECASE)

    # Component types that represent design patterns/cross-cutting concerns
    # rather than standalone implementation modules
    design_pattern_types = {
        "pattern implementation", "data storage", "infrastructure component",
        "thread-local storage", "cross-cutting concern", "design pattern",
    }

    # Generic section headers that are never components
    skip_titles = {
        "overview", "summary", "dependencies", "notes", "components", "services",
        "architecture overview", "component catalog", "cross-cutting concerns",
        "component count summary", "technology stack summary", "next steps",
        "cross", "logging", "error handling", "configuration",
    }

    current_header: dict | None = None
    desc_lines: list[str] = []
    has_component_fields = False
    component_name: str | None = None
    component_type: str | None = None

    def _flush():
        """Flush the current component if it has structured fields."""
        nonlocal current_header, desc_lines, has_component_fields, component_name, component_type
        if current_header and has_component_fields:
            # Use **Component Name** field for ID/title if found
            if component_name:
                comp_id = re.sub(r"[^a-zA-Z0-9]", "-", component_name).strip("-")
                current_header["id"] = f"COMP-{comp_id}"
                current_header["title"] = component_name
            current_header["description"] = "\n".join(desc_lines).strip()
            # Mark design patterns vs implementation components
            if component_type:
                current_header.setdefault("metadata", {})["component_type"] = component_type
                if component_type.lower() in design_pattern_types:
                    current_header["metadata"]["design_pattern"] = True
            artifacts.append(Artifact(**current_header))
        current_header = None
        desc_lines = []
        has_component_fields = False
        component_name = None
        component_type = None

    for i, line in enumerate(lines, start=1):
        m = comp_pattern.match(line)
        if m:
            _flush()

            title = m.group(1).strip()
            if title.lower() in skip_titles:
                continue

            comp_id = re.sub(r"[^a-zA-Z0-9]", "-", title).strip("-")
            current_header = {
                "id": f"COMP-{comp_id}",
                "title": title,
                "artifact_type": ArtifactType.COMPONENT,
                "source_file": str(file_path),
                "source_line": i,
            }
            desc_lines = []
            has_component_fields = False
            component_name = None
            component_type = None
        elif current_header:
            desc_lines.append(line)
            stripped = line.strip()
            if component_field_pattern.match(stripped):
                has_component_fields = True
            name_match = comp_name_pattern.match(stripped)
            if name_match:
                component_name = name_match.group(1).strip()
            type_match = comp_type_pattern.match(stripped)
            if type_match:
                component_type = type_match.group(1).strip()

    _flush()

    # DocSuri fork: legacy path returns no relationships.
    return artifacts, []
