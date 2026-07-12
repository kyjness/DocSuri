"""InputRefiner — structure-aware cleaning (BR-S3 / Q2 / Q6).

REMOVE (non-experimental noise only): references/bibliography, header/footer,
page numbers, copyright lines, author/affiliation lines.
PRESERVE (may carry experimental info): Table/Figure captions, Appendix,
Supplementary Results, LaTeX formulas. Over-removal would drop result numbers (Q2).

Section derivation (Q6): U1 does not persist section structure, so headings are
recognized here by regex → (label, char span); failure degrades to span-only.
"""

from __future__ import annotations

import re

from docsuri_shared.dtos import DocModel

from .models import RefinedSource, Section, SourceText, Table
from .token_estimate import estimate_tokens

# A references/bibliography heading ends the body (everything after is noise).
_REFERENCES_RE = re.compile(r"^\s*(references|bibliography)\s*$", re.IGNORECASE | re.MULTILINE)

# Non-experimental noise lines (conservative — only obvious boilerplate).
_PAGE_NUM_RE = re.compile(r"^\s*\d{1,4}\s*$")
_COPYRIGHT_RE = re.compile(r"(?i)\b(copyright|\(c\)|©|all rights reserved)\b")
_AUTHOR_AFFIL_RE = re.compile(r"(?i)^\s*(corresponding author|affiliation|e-?mail)\b")
_HEADER_FOOTER_RE = re.compile(r"(?i)^\s*(preprint|under review|to appear in|arxiv:)\b")

# Section / caption / formula recognition (preserve captions & formulas).
_SECTION_RE = re.compile(
    r"^\s*(?:(?:\d+(?:\.\d+)*)\s+[A-Z][^\n]{0,80}|[A-Z][A-Z \-]{3,60})\s*$", re.MULTILINE
)
_CAPTION_RE = re.compile(r"^\s*(table|figure|fig\.?)\s*\d+[:.]\s.*$", re.IGNORECASE | re.MULTILINE)
_FORMULA_RE = re.compile(
    r"\$[^$]+\$|\\\[[^\]]+\\\]|\\begin\{equation\}.*?\\end\{equation\}", re.DOTALL
)
_PRESERVED_RE = re.compile(
    r"(?i)\b(appendix|supplementary results|supplementary material|supplementary information)\b.*"
)
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

# The abstract is emitted by U1 as a dedicated doc-model section with this id (real content
# sections start at "s1"). It is summarizable content but not a citable anchor target — the reader
# hides it from the full-text body (it has its own 초록 surface), so an anchor resolving there
# could never scroll to anything. Kept out of the section index to mirror that reader-side filter.
_ABSTRACT_SECTION_ID = "s0"


def _strip_noise_lines(text: str) -> str:
    kept: list[str] = []
    for line in text.splitlines():
        if _PAGE_NUM_RE.match(line) and line.strip():
            continue
        if _COPYRIGHT_RE.search(line):
            continue
        if _AUTHOR_AFFIL_RE.match(line):
            continue
        if _HEADER_FOOTER_RE.match(line):
            continue
        kept.append(line)
    return "\n".join(kept)


def _clean(text: str) -> str:
    """Strip control characters from a doc-model text value (parity with the regex path)."""
    return _CONTROL_RE.sub("", text)


def _render_table(label: str, caption: str, rows: tuple[tuple[str, ...], ...]) -> str:
    """Render a doc-model table as readable pipe-delimited data so its numbers are visible
    to the LLM and the grounding numeric-match (D8 — not a blind cropped image)."""
    header = f"[{label}] {caption}".strip()
    lines = [header or "[Table]"]
    lines.extend(" | ".join(cell for cell in row) for row in rows)
    return "\n".join(lines)


class InputRefiner:
    def refine_source(self, source: SourceText) -> RefinedSource:
        """Dispatch on the selected source (D2): a structured doc-model is taken directly;
        a legacy plain-text source (or abstract) goes through the regex path. Logic downstream
        (length route, generation, grounding, cache) is identical either way."""
        if source.doc_model is not None:
            return self.refine_doc_model(source.doc_model)
        return self.refine(source.raw)

    def refine_doc_model(self, doc: DocModel) -> RefinedSource:
        """Project a doc-model into the LLM input + structured fields (D2/D8).

        Sections/tables/formulas/captions come straight from the doc-model (reliable — no
        heading/caption regex guessing). The flattened ``body`` embeds tables as DATA and
        formulas as LaTeX, so table numbers are visible to the LLM and the grounding gate
        (D8). Section spans index into ``body`` so anchor-existence checks resolve (BR-S7)."""
        parts: list[str] = []
        sections: list[Section] = []
        tables: list[Table] = []
        captions: list[str] = []
        formulas: list[str] = []
        pos = 0

        def emit(text: str) -> None:
            # Strip control chars (parity with the legacy regex path: parsed arXiv HTML can
            # carry control bytes that must not reach the LLM prompt / summary cache). Done
            # before measuring so section spans index into the sanitized body.
            nonlocal pos
            clean = _CONTROL_RE.sub("", text)
            parts.append(clean)
            pos += len(clean)

        def walk(dsec: object) -> None:
            nonlocal pos
            title = _CONTROL_RE.sub("", (getattr(dsec, "title", "") or "").strip())
            if title:
                start = pos
                emit(title)
                # Emit the abstract's text for the prompt, but keep it out of the anchor index so
                # the grounding gate resolves no citation to a section the reader can't scroll to.
                if getattr(dsec, "id", "") != _ABSTRACT_SECTION_ID:
                    sections.append(Section(label=title, start=start, end=pos))
                emit("\n\n")
            for block in getattr(dsec, "blocks", []):
                _emit_block(block.root)
            for sub in getattr(dsec, "sections", None) or []:
                walk(sub)

        def _emit_block(b: object) -> None:
            kind = getattr(b, "type", "")
            if kind == "paragraph":
                emit(b.text.strip() + "\n\n")
            elif kind == "formula":
                # Image-only formulas (PDF/GROBID page-crop fallback) carry no LaTeX — they are
                # display-only with no text to summarize, so skip them here. Guarding avoids a
                # TypeError on the optional latex field (re.sub/str concat against None).
                if b.latex:
                    formulas.append(_clean(b.latex))
                    emit(b.latex + "\n\n")
            elif kind == "table":
                label = _clean(b.anchorLabel or "")
                caption = _clean(b.caption or "")
                rows = tuple(tuple(_clean(c.text) for c in row.cells) for row in b.rows)
                tables.append(Table(label=label, rows=rows, caption=caption, anchor=b.id))
                if caption:
                    captions.append(f"{label}: {caption}".strip(": ").strip() or caption)
                emit(_render_table(label, caption, rows) + "\n\n")
            elif kind == "figure":
                label = _clean(b.anchorLabel or "")
                caption = _clean(b.caption or "")
                line = f"{label}: {caption}".strip(": ").strip()
                if caption:
                    captions.append(line or caption)
                if line:
                    emit(line + "\n\n")
            elif kind == "list":
                for item in b.items:
                    emit(f"- {item.text}\n")
                emit("\n")
            elif kind == "code":
                emit(b.text.strip() + "\n\n")

        for top in doc.sections:
            walk(top)

        body = "".join(parts).rstrip()
        return RefinedSource(
            body=body,
            sections=tuple(sections),
            tables=tuple(tables),
            captions=tuple(captions),
            formulas=tuple(formulas),
            token_count=estimate_tokens(body),
        )

    def refine(self, raw: str) -> RefinedSource:
        # Sanitize first (control chars; injection-isolation happens in the prompt layer).
        text = _CONTROL_RE.sub("", raw)

        # Cut references/bibliography tail (pure noise — BR-S3).
        match = _REFERENCES_RE.search(text)
        if match:
            text = text[: match.start()]

        # Remove non-experimental boilerplate lines (Q2 — captions/appendix untouched).
        body = _strip_noise_lines(text).strip()

        captions = tuple(m.group(0).strip() for m in _CAPTION_RE.finditer(body))
        formulas = tuple(m.group(0).strip() for m in _FORMULA_RE.finditer(body))
        preserved = tuple(m.group(0).strip() for m in _PRESERVED_RE.finditer(body))
        sections = self._derive_sections(body)

        return RefinedSource(
            body=body,
            sections=sections,
            captions=captions,
            formulas=formulas,
            preserved=preserved,
            token_count=estimate_tokens(body),
        )

    @staticmethod
    def _derive_sections(body: str) -> tuple[Section, ...]:
        """Recognize heading lines → (label, span). Empty when none found (span-only later)."""
        out: list[Section] = []
        for m in _SECTION_RE.finditer(body):
            label = m.group(0).strip()
            out.append(Section(label=label, start=m.start(), end=m.end()))
        return tuple(out)
