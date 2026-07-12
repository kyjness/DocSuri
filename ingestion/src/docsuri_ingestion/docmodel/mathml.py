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
#   - ``\definecolor`` / ``\color`` colour-selection markup (pgf/xcolor) that rides in when a
#     paper *colours* its equations. KaTeX accepts only ``\color{name}``/``\color{#hex}``; the
#     ``\color[model]{spec}`` optional-model form raises a fatal *Invalid color* that collapses
#     the WHOLE expression to red source text, and ``\definecolor`` is an undefined command.
#     Colour is decorative (no math meaning), so only the *selector* is dropped — the coloured
#     content is kept and renders in the default colour. Removed markup becomes a single space
#     (not ""), so a selector wedged between a control word and its operand
#     (``\sim\color[…]{…}p``) does not fuse into a bogus ``\simp``.
#   - ``\eqref``/``\ref``/``\cite``-family cross-references and citations that ride into alttext:
#     each is an undefined KaTeX command, so (throwOnError=false) it collapses the WHOLE formula
#     to source text. They carry no math meaning and the doc-model keeps its own anchors, so the
#     command and its ``{key}`` argument are dropped.
#   - ``\mathversion{bold}`` font switch (dropped) and ``\mbox``/``\hbox`` boxes, which are
#     rewritten to KaTeX-supported ``\text`` (``\text`` accepts nested ``$…$`` math, so a
#     ``\mbox{a $b$ c}`` survives instead of erroring).
#   - ``\big{(}`` / ``\Big{]}`` sizing commands whose delimiter LaTeXML wrapped in a brace group;
#     the braces are unwrapped to ``\big(`` (KaTeX rejects the braced form as an "ordgroup"
#     delimiter and collapses the whole formula).
#   - listings noise that rides into inline-math alttext when a paper embeds ``\lstinline`` inside
#     math via a custom box macro (arXiv:2410.14706 ``\cybertron`` → ``\Colorbox{c}{\lstinline …}``)
#     LaTeXML cannot expand it, so the alttext carries the ``\Colorbox`` box + its throwaway colour
#     argument, ``\leavevmode``, ``\lstinline``, the internal ``\lst@…set`` state macros, and
#     ``\@listingGroup{ltx_lst_*}{token}`` wrappers that reduce to bare ``{ltx_lst_*}`` class tags.
#     None of it is math; dropping the box/colour, the listings machinery, and the class tags leaves
#     the surviving identifier tokens so the formula renders instead of collapsing to source text.
_INTERNAL_MACRO_RE = re.compile(r"\\@[A-Za-z@]+")
_LAYOUT_MACRO_RE = re.compile(
    r"\\(?:centering|raggedright|raggedleft|centerline|noindent|par|"
    r"hfill|vfill|hfil|vfil|medskip|smallskip|bigskip|newline|linebreak|newpage|clearpage|"
    r"protect|xspace|unskip|leafmode)"
    r"(?![A-Za-z])"
)
# Cross-references / citations (undefined in KaTeX → whole-formula collapse). Command + its flat
# ``{key}`` group dropped; citations may carry leading optional ``[...]`` args (``\citep[a][]{k}``).
_REF_RE = re.compile(
    r"\\(?:eqref|ref|cref|Cref|cpageref|autoref|pageref|nameref|vref|labelcref)"
    r"\s*\{[^{}]*\}"
)
_CITE_RE = re.compile(
    r"\\(?:cite|citep|citet|citeauthor|citeyear|citealp|citealt|citenum|"
    r"footcite|parencite|textcite)\s*(?:\[[^\]]*\])*\s*\{[^{}]*\}"
)
_MATHVERSION_RE = re.compile(r"\\mathversion\s*\{[^{}]*\}")
# Boxes → KaTeX ``\text`` (name-swap only; the following ``{…}`` group is left intact).
_MBOX_RE = re.compile(r"\\(?:mbox|hbox)(?![A-Za-z])")
_LABEL_RE = re.compile(r"\\label\s*\{[^{}]*\}")
_IMAGE_PLACEHOLDER_RE = re.compile(r"\[Image\s*#?\s*\d+\]", re.IGNORECASE)
# ``\definecolor[model]{name}{model}{spec}`` (optional bracket + three flat groups) — a colour
# *definition* that carries no math; removed wholesale. ``\color[model]{spec}`` (optional bracket
# + one flat group) — the colour *selector*; only the selector is removed, its coloured operand
# stays. Flat ``\{[^{}]*\}`` groups suffice: colour specs never nest braces.
_DEFINECOLOR_RE = re.compile(
    r"\\definecolor(?![A-Za-z])\s*(?:\[[^\]]*\])?\s*\{[^{}]*\}\s*\{[^{}]*\}\s*\{[^{}]*\}"
)
_COLOR_SELECT_RE = re.compile(r"\\color(?![A-Za-z])\s*(?:\[[^\]]*\])?\s*\{[^{}]*\}")
# ``\Colorbox[model]{colour}{content}`` — the box command plus its leading throwaway colour
# argument are dropped (mirroring \color); the ``{content}`` group is left so its math survives.
# ``\fcolorbox[model]{frame}{bg}{content}`` leaks TWO colour args, so it is stripped first (its own
# pattern) — otherwise ``_COLORBOX_RE`` (which never matches the ``\f`` prefix) would leave both.
_FCOLORBOX_RE = re.compile(
    r"\\f[Cc]olorbox(?![A-Za-z])\s*(?:\[[^\]]*\])?\s*\{[^{}]*\}\s*\{[^{}]*\}"
)
_COLORBOX_RE = re.compile(r"\\[Cc]olorbox(?![A-Za-z])\s*(?:\[[^\]]*\])?\s*\{[^{}]*\}")
# Listings machinery that leaks into inline-math alttext (see the rationale block above): the
# ``\lstinline`` command (its braced body stays), the ``\leavevmode`` guard emitted before it, the
# internal ``\lst@…`` state macros, and residual ``{ltx_lst_*}`` class tags from ``\@listingGroup``
# (the ``\@…`` macro itself is already stripped by ``_INTERNAL_MACRO_RE``).
_LISTINGS_RE = re.compile(
    r"\\lst@[A-Za-z@]+|\\lstinline(?![A-Za-z])|\\leavevmode(?![A-Za-z])|\{ltx_lst_[A-Za-z_]*\}"
)
# ``\big{(}`` / ``\Big{]}`` — LaTeXML wraps the delimiter after a \big-family sizing command in a
# brace group, which KaTeX rejects ("Invalid delimiter type 'ordgroup'") → whole-formula collapse.
# Unwrap so the delimiter follows the command directly (``\big(``). Inner is a single delimiter:
# a control word (``\langle``), an escaped brace/bar (``\{`` ``\|``), or a bare delimiter char.
_BIG_DELIM_RE = re.compile(
    r"(\\(?:bigg|Bigg|big|Big)[lrmLRM]?)\s*\{\s*(\\[a-zA-Z]+|\\[{}|]|[()\[\].|/])\s*\}"
)
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
    latex = _DEFINECOLOR_RE.sub(" ", latex)  # colour definition (no math), drop whole
    latex = _FCOLORBOX_RE.sub(" ", latex)  # \fcolorbox{frame}{bg} box, keep the boxed content
    latex = _COLORBOX_RE.sub(" ", latex)  # \Colorbox{colour} box, keep the boxed content
    latex = _COLOR_SELECT_RE.sub(" ", latex)  # colour selector, keep the coloured operand
    latex = _LISTINGS_RE.sub(" ", latex)  # \lstinline/\lst@… listings machinery + class tags
    latex = _REF_RE.sub(" ", latex)  # \eqref/\ref/… cross-reference (no math)
    latex = _CITE_RE.sub(" ", latex)  # \cite-family citation (no math)
    latex = _MATHVERSION_RE.sub(" ", latex)  # \mathversion font switch (no math)
    latex = _MBOX_RE.sub(r"\\text", latex)  # \mbox/\hbox → KaTeX-supported \text
    # \big{(} → "\big( " — trailing space so a control-word delimiter (\langle) does not fuse with
    # the following letter into a bogus \langlez; _MULTI_WS_RE collapses the extra space.
    latex = _BIG_DELIM_RE.sub(r"\1\2 ", latex)
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
    if name in {"math", "mrow", "mstyle", "mpadded", "menclose"}:
        return "".join(_node_to_latex(c) for c in _children(node))
    if name == "semantics":
        # <semantics> holds the presentation MathML (first child) plus <annotation>/
        # <annotation-xml> metadata (TeX + content MathML). Render ONLY the presentation
        # child: rendering the annotations too doubles the output and leaks content-symbol
        # names ("subscript", "italic-…") into the text — the algorithm/pseudocode garble
        # that appears when a <math> carries no alttext to short-circuit this walker.
        children = _children(node)
        return _node_to_latex(children[0]) if children else ""
    if name in {"annotation", "annotation-xml"}:
        return ""
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
