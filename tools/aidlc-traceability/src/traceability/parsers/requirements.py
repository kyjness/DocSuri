# SPDX-License-Identifier: MIT
# Copyright (c) 2026 AIDLC Traceability Tool Contributors
"""Parse requirements.md files to extract requirement artifacts."""

from __future__ import annotations

import re
from pathlib import Path

from traceability.models import Artifact, ArtifactType


# DocSuri fork: DocSuri requirements use Korean numbered section headers
# (e.g. "## 4. 기능 요구사항") but per-item IDs are inline bold tokens at the
# start of a table row or list item:
#   | **FR-1** | ... |
#   - **NFR-P1** 검색 지연: ...
#   - **QT-1 — 엄격 근거화 인수**: ...
#   | **SEC-1** | ... |   | **RES-1** | ... |
# Mirror how stories key on US-* by extracting the leading FR/NFR/SEC/RES/QT token.
_DOCSURI_TOKEN_PATTERN = re.compile(
    r"^\s*(?:\|\s*|[-*]\s+)?\*\*\s*"
    r"((?:FR|NFR|SEC|RES|QT)-[A-Z]?\d+)"          # the ID, e.g. FR-1, NFR-P1
    r"(?:\s*\[[^\]]*\])?"                          # optional [U7]/[U8] annotation
    r"\s*(?:—|–|-|:)?\s*"                          # optional separator inside bold
    r"(.*?)\*\*"                                   # optional bolded title remainder
    r"\s*(.*)$",                                   # trailing prose after the bold
    re.IGNORECASE,
)


def _req_type_for(req_id: str) -> str:
    up = req_id.upper()
    if up.startswith("NFR"):
        return "non-functional"
    if up.startswith("SEC"):
        return "security"
    if up.startswith("RES"):
        return "resiliency"
    if up.startswith("QT"):
        return "quality"
    return "functional"


def _clean_table_cell(text: str) -> str:
    # Strip leading markdown table separators / pipes and surrounding whitespace.
    return text.strip().strip("|").strip()


def parse_requirements(file_path: Path) -> list[Artifact]:
    """Parse requirements from a markdown file.

    Handles formats like:
    - ## REQ-001: Title
    - #### FR-CAT-001: Title
    - ### NFR-001: Title
    DocSuri fork — inline bold tokens:
    - | **FR-1** | 자유 텍스트 ... |
    - **NFR-P1** 검색 지연: ...
    - **QT-1 — 엄격 근거화 인수**: ...
    """
    content = file_path.read_text(encoding="utf-8")
    lines = content.split("\n")
    artifacts: list[Artifact] = []
    seen_ids: set[str] = set()

    # Match requirement headers: ## REQ-001: Title, #### FR-CAT-001: Title, etc.
    req_pattern = re.compile(
        r"^#{2,4}\s+((?:REQ|FR|NFR|FR-[A-Z]+)-[\w-]+):\s*(.+)",
        re.IGNORECASE,
    )

    current_req: dict | None = None
    desc_lines: list[str] = []

    def _flush_header():
        nonlocal current_req
        if current_req:
            current_req["description"] = "\n".join(desc_lines).strip()
            if current_req["id"] not in seen_ids:
                seen_ids.add(current_req["id"])
                artifacts.append(Artifact(**current_req))
        current_req = None

    for i, line in enumerate(lines, start=1):
        # DocSuri fork: inline bold-token form takes priority (table rows / list items).
        tok = _DOCSURI_TOKEN_PATTERN.match(line)
        if tok:
            _flush_header()
            req_id = tok.group(1).strip().upper()
            bold_rest = (tok.group(2) or "").strip()
            trailing = _clean_table_cell(tok.group(3) or "")
            title = bold_rest or trailing
            # For table rows the title lives in the next cell (trailing); prefer it
            # when the bold only wrapped the ID.
            if not bold_rest:
                title = trailing
            title = title.strip().strip("—–-:").strip()
            if not title:
                title = req_id
            if req_id not in seen_ids:
                seen_ids.add(req_id)
                artifacts.append(Artifact(
                    id=req_id,
                    title=title[:200],
                    artifact_type=ArtifactType.REQUIREMENT,
                    description=_clean_table_cell(line),
                    source_file=str(file_path),
                    source_line=i,
                    metadata={"type": _req_type_for(req_id)},
                ))
            desc_lines = []
            continue

        m = req_pattern.match(line)
        if m:
            _flush_header()
            req_id = m.group(1).strip()
            title = m.group(2).strip()
            current_req = {
                "id": req_id,
                "title": title,
                "artifact_type": ArtifactType.REQUIREMENT,
                "source_file": str(file_path),
                "source_line": i,
                "metadata": {"type": _req_type_for(req_id)},
            }
            desc_lines = []
        elif current_req:
            # Collect description lines (stop at next header)
            if line.startswith("## ") or line.startswith("### ") or line.startswith("#### "):
                if not req_pattern.match(line):
                    desc_lines.append(line)
            else:
                desc_lines.append(line)

    _flush_header()

    return artifacts
