"""MathML -> LaTeX conversion for the doc-model parser (BR-30/TD-16, deterministic).

arXiv native HTML and ar5iv are both produced by LaTeXML, which emits ``<math>``
elements carrying an ``alttext`` attribute containing the **original LaTeX** source.
That attribute is therefore the cleanest, most faithful, and fully deterministic path
(no semantic re-derivation, no LLM — D1). When ``alttext`` is absent we fall back to a
small, best-effort recursive MathML walker covering the common presentation elements.

The alttext is the *author's raw* LaTeX, so it can carry non-math layout/formatting
macros the author placed inside or around the math environment (``\\centering``, the
internal ``\\@add@centering`` LaTeXML emits, equation ``\\label{}``, or a ``[Image #n]``
placeholder LaTeXML substitutes for a graphic it could not convert). A math-only renderer
(KaTeX) shows those tokens as red error text, so ``_sanitize`` strips this small, fixed
denylist of never-math markup from the result before it is stored.

Pure: same ``<math>`` element -> same LaTeX (P7). Operates on BeautifulSoup ``Tag``s.
"""

from __future__ import annotations

import re

from bs4 import NavigableString, Tag

# Delimiters LaTeXML occasionally wraps around an alttext payload; stripped so the
# stored LaTeX is delimiter-free (the doc-model embeds its own \( \) / display markers).
_DELIMITER_PAIRS = (("$$", "$$"), ("\\[", "\\]"), ("\\(", "\\)"), ("$", "$"))

# Never-math markup that can ride along in the alttext source and that KaTeX renders as a
# red error token. Each is removed wholesale; ``_sanitize`` then re-trims surrounding space.
#   - ``\@…`` LaTeX *internal* control sequences (``\@add@centering``): ``@`` is a letter in
#     internal context, so these are single control words and never valid user math.
#   - layout/spacing macros that carry no math meaning (alignment, page/line breaks).
#   - ``\label{…}`` equation labels (the doc-model keeps the visible number as anchorLabel).
#   - ``[Image #n]`` LaTeXML placeholders for an un-convertible embedded graphic.
_INTERNAL_MACRO_RE = re.compile(r"\\@[A-Za-z@]+")
_LAYOUT_MACRO_RE = re.compile(
    r"\\(?:centering|raggedright|raggedleft|centerline|noindent|par|"
    r"hfill|vfill|hfil|vfil|medskip|smallskip|bigskip|newline|linebreak|newpage|clearpage|"
    r"protect|xspace|unskip)"
    r"(?![A-Za-z])"
)
_LABEL_RE = re.compile(r"\\label\s*\{[^{}]*\}")
_IMAGE_PLACEHOLDER_RE = re.compile(r"\[Image\s*#?\s*\d+\]", re.IGNORECASE)
_MULTI_WS_RE = re.compile(r"[ \t]{2,}")

# Security denylist (SEC-5 / BR-19): KaTeX commands that under ``trust:true`` emit links, load
# remote resources, or run TeX programming. Stored LaTeX (and macro bodies) are defence-in-depth
# stripped/rejected so safety does not rely solely on the U5 renderer keeping ``trust:false``.
DANGEROUS_LATEX_RE = re.compile(
    r"\\(?:href|url|includegraphics|html(?:Class|Id|Data|Style)?|"
    r"def|edef|gdef|xdef|let|futurelet|newcommand|renewcommand|providecommand|"
    r"input|include|catcode|expandafter|csname|endcsname|immediate|write|openout|special)"
    r"(?![A-Za-z])"
)


def mathml_to_latex(math: Tag) -> str:
    """Convert a ``<math>`` element to a LaTeX string (alttext-first, MathML fallback)."""
    alttext = math.get("alttext")
    if isinstance(alttext, str) and alttext.strip():
        return _sanitize(_strip_delimiters(alttext.strip()))
    return _sanitize(_node_to_latex(math).strip())


def _sanitize(latex: str) -> str:
    """Drop never-math layout/label/placeholder markup so KaTeX renders no red error tokens."""
    latex = DANGEROUS_LATEX_RE.sub("", latex)  # SEC-5/BR-19 KaTeX-injection strip
    latex = _INTERNAL_MACRO_RE.sub("", latex)
    latex = _LAYOUT_MACRO_RE.sub("", latex)
    latex = _LABEL_RE.sub("", latex)
    latex = _IMAGE_PLACEHOLDER_RE.sub("", latex)
    return _MULTI_WS_RE.sub(" ", latex).strip()


def _strip_delimiters(latex: str) -> str:
    for open_d, close_d in _DELIMITER_PAIRS:
        if latex.startswith(open_d) and latex.endswith(close_d) and len(latex) > len(open_d) + len(
            close_d
        ):
            return latex[len(open_d) : len(latex) - len(close_d)].strip()
    return latex


def _children(node: Tag) -> list[Tag | NavigableString]:
    return [c for c in node.children if isinstance(c, Tag) or _has_text(c)]


def _has_text(node: object) -> bool:
    return isinstance(node, NavigableString) and bool(str(node).strip())


def _node_to_latex(node: Tag | NavigableString) -> str:
    if isinstance(node, NavigableString):
        return str(node).strip()
    name = (node.name or "").lower()
    if name in {"mi", "mn", "mo", "mtext", "ms"}:
        return node.get_text().strip()
    if name in {"math", "mrow", "mstyle", "mpadded", "menclose", "semantics"}:
        return "".join(_node_to_latex(c) for c in _children(node))
    if name == "msup":
        base, sup = _pair(node)
        return f"{_wrap(base)}^{_wrap(sup)}"
    if name == "msub":
        base, sub = _pair(node)
        return f"{_wrap(base)}_{_wrap(sub)}"
    if name == "msubsup":
        parts = _parts(node, 3)
        return f"{_wrap(parts[0])}_{_wrap(parts[1])}^{_wrap(parts[2])}"
    if name == "mfrac":
        num, den = _pair(node)
        return f"\\frac{{{num}}}{{{den}}}"
    if name == "msqrt":
        return f"\\sqrt{{{''.join(_node_to_latex(c) for c in _children(node))}}}"
    if name == "mroot":
        base, index = _pair(node)
        return f"\\sqrt[{index}]{{{base}}}"
    if name == "mover":
        base, over = _pair(node)
        accent = _accent_command(_children(node)[1] if len(_children(node)) > 1 else None)
        return f"{accent}{{{base}}}" if accent else f"{_wrap(base)}^{_wrap(over)}"
    if name == "munder":
        base, under = _pair(node)
        return f"{_wrap(base)}_{_wrap(under)}"
    if name == "munderover":
        parts = _parts(node, 3)
        return f"{_wrap(parts[0])}_{_wrap(parts[1])}^{_wrap(parts[2])}"
    if name in {"mtable", "mtr", "mtd"}:
        return _table_to_latex(node)
    if name == "mfenced":
        inner = "".join(_node_to_latex(c) for c in _children(node))
        open_b = node.get("open", "(")
        close_b = node.get("close", ")")
        return f"{open_b}{inner}{close_b}"
    if name in {"mspace", "none"}:
        return ""
    # Unknown / annotation: concatenate descendant text deterministically.
    return "".join(_node_to_latex(c) for c in _children(node))


# MathML accent over-scripts -> LaTeX accent commands. A bare ``mover`` carrying one of these
# (or ``accent="true"``) is an accent, not a superscript; anything else is treated as limits.
_ACCENTS = {
    "^": "\\hat", "ˆ": "\\hat", "~": "\\tilde", "˜": "\\tilde",
    "ˉ": "\\bar", "¯": "\\bar", "‾": "\\bar",
    "→": "\\vec", "⃗": "\\vec", "˙": "\\dot", ".": "\\dot", "¨": "\\ddot",
    "ˇ": "\\check", "˘": "\\breve", "´": "\\acute", "`": "\\grave",
}


def _accent_command(over: Tag | NavigableString | None) -> str | None:
    """LaTeX accent command for an ``mover`` over-script, or None if it is a true superscript."""
    if over is None:
        return None
    glyph = _node_to_latex(over).strip()
    if isinstance(over, Tag) and over.get("accent") == "true":
        return _ACCENTS.get(glyph, "\\hat")
    return _ACCENTS.get(glyph)


def _table_to_latex(node: Tag) -> str:
    """Render an ``mtable`` (or a stray ``mtr``/``mtd``) as a KaTeX ``matrix`` environment.

    Rows/cells are read non-recursively so a nested ``mtable`` (a block matrix) keeps its inner
    rows to itself instead of being flattened into the outer matrix.
    """
    is_table = (node.name or "").lower() == "mtable"
    rows = node.find_all("mtr", recursive=False) if is_table else [node]
    lines: list[str] = []
    for row in rows:
        cells = (
            row.find_all("mtd", recursive=False)
            if (row.name or "").lower() in {"mtr", "mtable"}
            else [row]
        )
        targets = cells or [row]
        lines.append(" & ".join("".join(
            _node_to_latex(c) for c in _children(cell)) for cell in targets))
    body = " \\\\ ".join(line for line in lines if line)
    if not body:
        return ""
    return f"\\begin{{matrix}} {body} \\end{{matrix}}"


def _parts(node: Tag, count: int) -> list[str]:
    rendered = [_node_to_latex(c) for c in _children(node)]
    rendered += [""] * (count - len(rendered))
    return rendered[:count]


def _pair(node: Tag) -> tuple[str, str]:
    parts = _parts(node, 2)
    return parts[0], parts[1]


def _wrap(latex: str) -> str:
    """Brace a sub/superscript argument unless it is a single token."""
    if len(latex) <= 1:
        return latex
    return f"{{{latex}}}"
