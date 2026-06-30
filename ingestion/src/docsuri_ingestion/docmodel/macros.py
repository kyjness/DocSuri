"""Extract KaTeX-compatible macros from an e-print LaTeX preamble (BR-30/TD-16).

LaTeXML expands most author macros when it produces the arXiv/ar5iv HTML, but commands it
could not resolve (a ``\\newcommand`` defined in a ``.sty`` it did not bundle, etc.) survive
verbatim inside ``<math alttext>`` and then render as red *unsupported-command* errors in
KaTeX. The e-print tarball carries the author's *real* preamble, so we parse its
``\\newcommand``-family definitions into a macro map the renderer hands to KaTeX, which then
resolves the author commands per-paper.

Pure and deterministic: the same e-print bytes yield the same macro map (P7). Best-effort —
any parse/decode failure yields ``{}`` (macros are a display refinement, never blocking; the
formula still renders, just with the unresolved command shown verbatim as before).
"""

from __future__ import annotations

import io
import tarfile

from docsuri_ingestion.docmodel.mathml import DANGEROUS_LATEX_RE

# Bounds so a hostile or pathological e-print cannot bloat the doc-model: cap the macro count,
# each expansion's length, and the total bytes read from the tarball.
_MAX_MACROS = 512
_MAX_BODY_LEN = 400
_MAX_TEX_BYTES = 8_000_000
_DEF_KEYWORDS = {"newcommand", "renewcommand", "providecommand"}


def extract_macros(eprint: bytes | None) -> dict[str, str]:
    """Parse ``\\newcommand``-style defs from an e-print's ``.tex`` files into a KaTeX map.

    Keys are control sequences (``\\R``); values are expansions (``\\mathbb{R}``) and may use
    ``#1`` parameters — KaTeX infers arity from those. Returns ``{}`` on any failure.
    """
    if not eprint:
        return {}
    try:
        texts = _read_tex_sources(eprint)
    except Exception:  # noqa: BLE001 - any tar/decode failure: macros are best-effort
        return {}
    macros: dict[str, str] = {}
    for text in texts:
        _parse_defs(text, macros)
        if len(macros) >= _MAX_MACROS:
            break
    return macros


def _read_tex_sources(eprint: bytes) -> list[str]:
    """Decode the ``.tex`` members of an e-print tarball, ordered by name (deterministic)."""
    texts: list[str] = []
    budget = _MAX_TEX_BYTES
    with tarfile.open(fileobj=io.BytesIO(eprint), mode="r:*") as tar:
        members = sorted(
            (m for m in tar.getmembers() if m.isfile() and m.name.lower().endswith(".tex")),
            key=lambda m: m.name,
        )
        for member in members:
            if budget <= 0:
                break
            fh = tar.extractfile(member)
            if fh is None:
                continue
            raw = fh.read(budget)
            budget -= len(raw)
            texts.append(raw.decode("utf-8", errors="replace"))
    return texts


def _parse_defs(text: str, out: dict[str, str]) -> None:
    """Scan ``text`` for macro definitions, writing ``{name: expansion}`` into ``out``."""
    text = _strip_comments(text)
    i, n = 0, len(text)
    while i < n and len(out) < _MAX_MACROS:
        if text[i] != "\\":
            i += 1
            continue
        cs, j = _read_cs(text, i)
        if cs is None:
            i += 1
            continue
        keyword = cs[1:]
        if keyword in _DEF_KEYWORDS:
            name, body, i = _parse_newcommand(text, j)
        elif keyword == "DeclareMathOperator":
            star = j < n and text[j] == "*"
            name, body, i = _parse_declare_operator(text, j + 1 if star else j, star)
        elif keyword == "def":
            name, body, i = _parse_def(text, j)
        else:
            i = j
            continue
        # Reject a macro whose expansion carries a KaTeX-injection command (SEC-5/BR-19): a
        # hostile preamble could define \R -> \href{javascript:...}{x}. Drop it; the formula
        # still renders with the command shown verbatim, never executed.
        if (
            name
            and body is not None
            and len(body) <= _MAX_BODY_LEN
            and not DANGEROUS_LATEX_RE.search(body)
        ):
            out[name] = body
    return None


def _strip_comments(text: str) -> str:
    """Drop TeX line comments (unescaped ``%`` to end of line) so they don't swallow braces."""
    lines = []
    for line in text.splitlines():
        idx = 0
        while True:
            idx = line.find("%", idx)
            if idx == -1:
                break
            if idx == 0 or line[idx - 1] != "\\":
                line = line[:idx]
                break
            idx += 1
        lines.append(line)
    return "\n".join(lines)


def _skip_ws(text: str, i: int) -> int:
    while i < len(text) and text[i] in " \t\r\n":
        i += 1
    return i


def _read_cs(text: str, i: int) -> tuple[str | None, int]:
    """Read a control word ``\\name`` at ``text[i]``; control symbols (``\\,``) are skipped."""
    if i >= len(text) or text[i] != "\\":
        return None, i
    j = i + 1
    if j >= len(text) or not text[j].isalpha():
        return None, i
    while j < len(text) and text[j].isalpha():
        j += 1
    return text[i:j], j


def _read_group(text: str, i: int) -> tuple[str | None, int]:
    """Read a balanced ``{...}`` group at ``text[i]``; returns (content, index-after-'}')."""
    if i >= len(text) or text[i] != "{":
        return None, i
    depth = 0
    j = i
    while j < len(text):
        c = text[j]
        if c == "\\":  # escaped char (e.g. \{ \}) never changes brace depth
            j += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[i + 1 : j], j + 1
        j += 1
    return None, i  # unbalanced — abandon this definition


def _read_name(text: str, i: int) -> tuple[str | None, int]:
    """Read a macro name as either ``{\\name}`` or a bare ``\\name``."""
    if i < len(text) and text[i] == "{":
        grp, j = _read_group(text, i)
        return (grp.strip() if grp is not None else None), j
    return _read_cs(text, i)


def _parse_newcommand(text: str, i: int) -> tuple[str | None, str | None, int]:
    i = _skip_ws(text, i)
    name, i = _read_name(text, i)
    if not name or not name.startswith("\\"):
        return None, None, i
    i = _skip_ws(text, i)
    while i < len(text) and text[i] == "[":  # skip [argcount] and optional [default]
        end = text.find("]", i)
        if end == -1:
            return None, None, i
        i = _skip_ws(text, end + 1)
    body, i = _read_group(text, i)
    return (name if body is not None else None), body, i


def _parse_def(text: str, i: int) -> tuple[str | None, str | None, int]:
    i = _skip_ws(text, i)
    name, i = _read_cs(text, i)
    if not name:
        return None, None, i
    while i < len(text) and text[i] != "{":  # skip TeX param text (#1#2…); KaTeX reads #n in body
        i += 2 if text[i] == "\\" else 1
    body, i = _read_group(text, i)
    return (name if body is not None else None), body, i


def _parse_declare_operator(
    text: str, i: int, star: bool
) -> tuple[str | None, str | None, int]:
    i = _skip_ws(text, i)
    name, i = _read_name(text, i)
    if not name or not name.startswith("\\"):
        return None, None, i
    i = _skip_ws(text, i)
    body, i = _read_group(text, i)
    if body is None:
        return None, None, i
    operator = f"\\operatorname{'*' if star else ''}{{{body}}}"
    return name, operator, i
