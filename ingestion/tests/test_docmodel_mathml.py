"""MathML -> LaTeX (BR-30/TD-16): alttext-first, deterministic, MathML fallback."""

from __future__ import annotations

from bs4 import BeautifulSoup

from docsuri_ingestion.docmodel.mathml import mathml_to_latex


def _math(html: str):
    return BeautifulSoup(html, "lxml").find("math")


def test_alttext_is_preferred_verbatim() -> None:
    assert mathml_to_latex(_math('<math alttext="x^{2} + 1">junk</math>')) == "x^{2} + 1"


def test_alttext_delimiters_are_stripped() -> None:
    assert mathml_to_latex(_math(r'<math alttext="\(a+b\)">x</math>')) == "a+b"
    assert mathml_to_latex(_math('<math alttext="$E=mc^2$">x</math>')) == "E=mc^2"


def test_fallback_converts_presentation_mathml() -> None:
    # No alttext -> walk the MathML tree.
    latex = mathml_to_latex(
        _math("<math><msup><mi>x</mi><mn>2</mn></msup><mo>+</mo><mn>1</mn></math>")
    )
    assert latex == "x^2+1"


def test_semantics_renders_presentation_only_dropping_annotations() -> None:
    # LaTeXML wraps math in <semantics> with the presentation MathML (first child) plus
    # <annotation-xml> (content MathML) and <annotation> (TeX). With no alttext — common in
    # algorithm/pseudocode math — walking every child doubled the output and leaked
    # content-symbol names ("subscript", "italic-…") into the text. Only the presentation
    # child must render.
    html = (
        "<math><semantics>"
        "<msub><mi>ϕ</mi><mi>k</mi></msub>"
        '<annotation-xml encoding="MathML-Content">'
        "<csymbol>subscript</csymbol><ci>italic-ϕ</ci><ci>italic-k</ci>"
        "</annotation-xml>"
        '<annotation encoding="application/x-tex">\\phi_{k}</annotation>'
        "</semantics></math>"
    )
    latex = mathml_to_latex(_math(html))
    assert latex == "ϕ_k"
    assert "subscript" not in latex and "italic-" not in latex


def test_fallback_handles_fraction_and_sqrt() -> None:
    assert (
        mathml_to_latex(_math("<math><mfrac><mn>1</mn><mn>2</mn></mfrac></math>")) == "\\frac{1}{2}"
    )
    assert mathml_to_latex(_math("<math><msqrt><mi>x</mi></msqrt></math>")) == "\\sqrt{x}"


def test_superscript_wraps_multichar_argument() -> None:
    latex = mathml_to_latex(
        _math("<math><msup><mi>e</mi><mrow><mn>2</mn><mi>x</mi></mrow></msup></math>")
    )
    assert latex == "e^{2x}"


def test_conversion_is_deterministic() -> None:
    el = "<math><msub><mi>a</mi><mi>i</mi></msub></math>"
    assert mathml_to_latex(_math(el)) == mathml_to_latex(_math(el)) == "a_i"


# --- sanitization: never-math layout/label/placeholder markup is stripped (no red KaTeX) ---


def test_layout_macros_are_stripped_from_alttext() -> None:
    alt = r"\centering Attention(Q,K,V) = V \@add@centering"
    assert mathml_to_latex(_math(f'<math alttext="{alt}">x</math>')) == "Attention(Q,K,V) = V"


def test_textmode_noop_macros_are_stripped() -> None:
    # \protect / \xspace / \unskip are text-mode no-ops that ride into alttext and would
    # render as red error tokens; they carry no math meaning, so they are removed.
    alt = r"\protect x + y\xspace \unskip"
    assert mathml_to_latex(_math(f'<math alttext="{alt}">z</math>')) == "x + y"


def test_image_placeholder_is_stripped() -> None:
    assert mathml_to_latex(_math('<math alttext="a + [Image #1] b">x</math>')) == "a + b"


def test_equation_label_is_stripped() -> None:
    assert mathml_to_latex(_math(r'<math alttext="x = y \label{eq:1}">z</math>')) == "x = y"


def test_color_selection_markup_is_stripped() -> None:
    # A paper that colours its equations leaks pgf/xcolor markup into alttext: \definecolor
    # (an undefined KaTeX command) and \color[rgb]{spec} (the optional-model form KaTeX rejects
    # with a fatal "Invalid color"). Both selectors are dropped; the coloured operand survives.
    alt = r"\color[rgb]{1,0,0}x + \definecolor[named]{c}{rgb}{0,1,0}y"
    assert mathml_to_latex(_math(f'<math alttext="{alt}">z</math>')) == "x + y"


def test_color_selector_removal_does_not_fuse_control_words() -> None:
    # A selector wedged between a control word and its operand (\sim\color[...]{...}b) must not
    # fuse into a bogus \simb: it is replaced by a space, preserving the \sim token boundary.
    out = mathml_to_latex(_math(r'<math alttext="a\sim\color[rgb]{0,0,1}b">z</math>'))
    assert out == r"a\sim b"


def test_cross_references_and_citations_are_stripped() -> None:
    # \eqref/\ref/\cite are undefined in KaTeX and collapse the whole formula to source text.
    # They carry no math meaning, so command + {key} are dropped.
    assert mathml_to_latex(_math(r'<math alttext="x = y \eqref{eq:1}">z</math>')) == "x = y"
    assert mathml_to_latex(_math(r'<math alttext="a~\cite{foo} + b">z</math>')) == "a~ + b"
    assert mathml_to_latex(_math(r'<math alttext="a \citep[see][]{k} b">z</math>')) == "a b"


def test_mathversion_and_leafmode_are_stripped() -> None:
    assert mathml_to_latex(_math(r'<math alttext="\mathversion{bold}x + 1">z</math>')) == "x + 1"
    assert mathml_to_latex(_math(r'<math alttext="\leafmode x">z</math>')) == "x"


def test_mbox_is_rewritten_to_text() -> None:
    # \mbox/\hbox are undefined in KaTeX; \text is supported (and accepts nested $…$ math).
    out = mathml_to_latex(_math(r'<math alttext="\mbox{a $b$ c} + \hbox{d}">z</math>'))
    assert r"\mbox" not in out and r"\hbox" not in out
    assert out == r"\text{a $b$ c} + \text{d}"


def test_big_family_braced_delimiters_are_unwrapped() -> None:
    # LaTeXML emits ``\big{(}`` (delimiter wrapped in braces); KaTeX rejects it as an "ordgroup"
    # delimiter and collapses the whole formula. The braces are unwrapped to ``\big(``.
    alt = r"2\big{(}x-y\Big{]} + \Bigl{\langle}z\bigr{|}"
    out = mathml_to_latex(_math(f'<math alttext="{alt}">z</math>'))
    # Braces unwrapped; a trailing space keeps \langle from fusing with the next letter.
    assert out == r"2\big( x-y\Big] + \Bigl\langle z\bigr|"


def test_colored_equation_renders_without_residual_color_markup() -> None:
    # Regression for arXiv:2410.10781, whose coloured objective leaked \color[rgb]/\definecolor
    # into stored LaTeX and collapsed the whole formula to red source text in KaTeX.
    alt = (
        r"{\color[rgb]{1.0,0.44,0.37}\definecolor[named]{pgfstrokecolor}{rgb}{1.0,0.44,0.37}"
        r"\min_{\theta}}\hskip 1.42271pt\mathbb{E}_{{\bm{X}\sim\color[rgb]{0.0,0.2,0.6}"
        r"\definecolor[named]{pgfstrokecolor}{rgb}{0.0,0.2,0.6}p_{\textrm{data}}}}\left[{\color"
        r"[rgb]{1,0.75,0}\definecolor[named]{pgfstrokecolor}{rgb}{1,0.75,0}\mathcal{L}}\left("
        r"{\color[rgb]{0,0.5,0.5}\definecolor[named]{pgfstrokecolor}{rgb}{0,0.5,0.5}p_{\theta}}"
        r"(\bm{X})\right)\right]\textrm{.}"
    )
    out = mathml_to_latex(_math(f'<math alttext="{alt}">z</math>'))
    assert "\\color" not in out and "\\definecolor" not in out
    # The math itself is preserved and the \sim operand did not fuse into the removed selector.
    for token in (r"\min_{\theta}", r"\mathbb{E}", r"\mathcal{L}", r"p_{\theta}", r"\sim p_"):
        assert token in out


def test_real_math_is_left_intact() -> None:
    # \frac, \sqrt, ordinary commands must survive sanitization untouched.
    alt = r"\frac{QK^{\top}}{\sqrt{d}}"
    assert mathml_to_latex(_math(f'<math alttext="{alt}">x</math>')) == alt


# --- fallback: matrices, accents, and limits (alttext absent) ---


def test_fallback_renders_matrix() -> None:
    latex = mathml_to_latex(
        _math(
            "<math><mtable>"
            "<mtr><mtd><mn>1</mn></mtd><mtd><mn>2</mn></mtd></mtr>"
            "<mtr><mtd><mn>3</mn></mtd><mtd><mn>4</mn></mtd></mtr>"
            "</mtable></math>"
        )
    )
    assert latex == r"\begin{matrix} 1 & 2 \\ 3 & 4 \end{matrix}"


def test_fallback_nested_matrix_is_not_flattened() -> None:
    # A block matrix (mtable inside an mtd) keeps its inner row to itself — the outer matrix
    # must not pull the nested rows/cells up (recursive find would flatten them).
    latex = mathml_to_latex(
        _math(
            "<math><mtable><mtr>"
            "<mtd><mn>1</mn></mtd>"
            "<mtd><mtable><mtr><mtd><mn>2</mn></mtd><mtd><mn>3</mn></mtd></mtr></mtable></mtd>"
            "</mtr></mtable></math>"
        )
    )
    assert latex == r"\begin{matrix} 1 & \begin{matrix} 2 & 3 \end{matrix} \end{matrix}"


def test_fallback_renders_accent() -> None:
    latex = mathml_to_latex(
        _math('<math><mover accent="true"><mi>x</mi><mo>^</mo></mover></math>')
    )
    assert latex == r"\hat{x}"


def test_fallback_renders_limits_when_not_accent() -> None:
    # mover without accent -> superscript/limits, not an accent command.
    latex = mathml_to_latex(
        _math("<math><munderover><mo>∑</mo><mi>i</mi><mi>n</mi></munderover></math>")
    )
    assert latex == "∑_i^n"
