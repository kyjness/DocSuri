"""_parse_json robustness — math-heavy translations echo raw LaTeX (\\mathcal, \\rho, \\nabla)
into JSON string values; an unescaped backslash is invalid JSON and used to fail the whole batch
(generation_unavailable). The parser now escapes stray backslashes and retries."""

from __future__ import annotations

from summarization.adapters.bedrock_llm import _parse_json


def test_parse_json_recovers_raw_latex_backslashes() -> None:
    # The model returned raw LaTeX inside a JSON string (\\m, \\h are invalid JSON escapes).
    raw = '{"translations": {"0": "에너지 \\mathcal{G}=-i\\hat{H} 형태다"}}'
    val = _parse_json(raw)["translations"]["0"]
    assert "\\mathcal{G}" in val  # LaTeX survives as a literal backslash sequence
    assert "\\hat{H}" in val


def test_parse_json_recovers_latex_commands_starting_with_escape_letters() -> None:
    # The trap: \r \n \t \b \f are valid JSON escape letters, but \rho \nabla \theta \beta \frac
    # are LaTeX. A naive "valid-escape" pass would turn \rho into CR+"ho"; these must stay literal.
    raw = '{"translations": {"0": "\\rho_t, \\nabla_r, \\theta, \\beta, \\frac{a}{b}"}}'
    val = _parse_json(raw)["translations"]["0"]
    for cmd in ("\\rho_t", "\\nabla_r", "\\theta", "\\beta", "\\frac{a}{b}"):
        assert cmd in val


def test_parse_json_preserves_structural_and_unicode_escapes() -> None:
    # The guaranteed-preserved escapes: quote (\"), literal backslash (\\), and a true \uXXXX code
    # point. (Single-letter control escapes like \n are treated as LaTeX by design — translation
    # values carry no real control chars — which is the trade-off documented on the sanitizer.)
    raw = '{"translations": {"0": "\\"인용\\" 백슬래시 \\\\ 그리고 \\u00e9"}}'
    val = _parse_json(raw)["translations"]["0"]
    assert val == '"인용" 백슬래시 \\ 그리고 é'


def test_parse_json_preserves_true_unicode_escape_on_retry() -> None:
    # A broken payload (stray \m) that ALSO contains a genuine \uXXXX: the recovery must keep the
    # unicode escape while fixing the stray LaTeX backslash.
    raw = '{"translations": {"0": "\\u00e9 and \\mathcal{L}"}}'
    val = _parse_json(raw)["translations"]["0"]
    assert val.startswith("é and ")
    assert "\\mathcal{L}" in val


def test_parse_json_tolerates_surrounding_prose() -> None:
    # Leading/trailing prose around the JSON object is sliced off (existing behavior kept).
    raw = 'Here you go:\n{"translations": {"0": "값 \\nabla_r"}}\nDone.'
    assert _parse_json(raw)["translations"]["0"] == "값 \\nabla_r"
