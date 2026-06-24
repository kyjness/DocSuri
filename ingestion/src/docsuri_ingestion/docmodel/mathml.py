"""MathML -> LaTeX conversion for the doc-model parser (BR-30/TD-16, deterministic).

arXiv native HTML and ar5iv are both produced by LaTeXML, which emits ``<math>``
elements carrying an ``alttext`` attribute containing the **original LaTeX** source.
That attribute is therefore the cleanest, most faithful, and fully deterministic path
(no semantic re-derivation, no LLM — D1). When ``alttext`` is absent we fall back to a
small, best-effort recursive MathML walker covering the common presentation elements.

Pure: same ``<math>`` element -> same LaTeX (P7). Operates on BeautifulSoup ``Tag``s.
"""

from __future__ import annotations

from bs4 import NavigableString, Tag

# Delimiters LaTeXML occasionally wraps around an alttext payload; stripped so the
# stored LaTeX is delimiter-free (the doc-model embeds its own \( \) / display markers).
_DELIMITER_PAIRS = (("$$", "$$"), ("\\[", "\\]"), ("\\(", "\\)"), ("$", "$"))


def mathml_to_latex(math: Tag) -> str:
    """Convert a ``<math>`` element to a LaTeX string (alttext-first, MathML fallback)."""
    alttext = math.get("alttext")
    if isinstance(alttext, str) and alttext.strip():
        return _strip_delimiters(alttext.strip())
    return _node_to_latex(math).strip()


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
    if name in {"mover", "munder", "munderover"}:
        return "".join(_node_to_latex(c) for c in _children(node))
    if name == "mfenced":
        inner = "".join(_node_to_latex(c) for c in _children(node))
        open_b = node.get("open", "(")
        close_b = node.get("close", ")")
        return f"{open_b}{inner}{close_b}"
    if name in {"mspace", "none"}:
        return ""
    # Unknown / annotation: concatenate descendant text deterministically.
    return "".join(_node_to_latex(c) for c in _children(node))


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
