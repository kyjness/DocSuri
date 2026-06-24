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
