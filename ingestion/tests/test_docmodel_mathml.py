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
