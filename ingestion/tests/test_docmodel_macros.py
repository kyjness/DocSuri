"""e-print preamble -> KaTeX macro map extraction (BR-30/TD-16, deterministic, best-effort)."""

from __future__ import annotations

import io
import tarfile

from docsuri_ingestion.docmodel.macros import extract_macros


def _eprint(files: dict[str, str]) -> bytes:
    """Pack ``{name: text}`` into a gzipped tar (an e-print tarball)."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, text in files.items():
            data = text.encode("utf-8")
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def test_none_and_empty_yield_empty_map() -> None:
    assert extract_macros(None) == {}
    assert extract_macros(b"") == {}


def test_non_tar_bytes_are_best_effort_empty() -> None:
    assert extract_macros(b"not a tarball") == {}


def test_newcommand_braced_and_bare() -> None:
    src = r"""
    \newcommand{\R}{\mathbb{R}}
    \newcommand\X{\mathbf{x}}
    \begin{document}\end{document}
    """
    assert extract_macros(_eprint({"main.tex": src})) == {
        "\\R": "\\mathbb{R}",
        "\\X": "\\mathbf{x}",
    }


def test_newcommand_with_arguments_keeps_hash_params() -> None:
    src = r"\newcommand{\abs}[1]{\left|#1\right|}"
    assert extract_macros(_eprint({"m.tex": src})) == {"\\abs": "\\left|#1\\right|"}


def test_newcommand_with_optional_default_is_handled() -> None:
    src = r"\newcommand{\plus}[2][0]{#2+#1}"
    assert extract_macros(_eprint({"m.tex": src})) == {"\\plus": "#2+#1"}


def test_declare_math_operator_wraps_operatorname() -> None:
    src = r"\DeclareMathOperator{\argmax}{arg\,max}" "\n" r"\DeclareMathOperator*{\E}{E}"
    assert extract_macros(_eprint({"m.tex": src})) == {
        "\\argmax": "\\operatorname{arg\\,max}",
        "\\E": "\\operatorname*{E}",
    }


def test_def_form_is_supported() -> None:
    src = r"\def\Z{\mathbb{Z}}"
    assert extract_macros(_eprint({"m.tex": src})) == {"\\Z": "\\mathbb{Z}"}


def test_comments_are_ignored() -> None:
    src = "% \\newcommand{\\R}{\\mathbb{R}}\n\\newcommand{\\N}{\\mathbb{N}}\n"
    assert extract_macros(_eprint({"m.tex": src})) == {"\\N": "\\mathbb{N}"}


def test_nested_braces_in_body_are_balanced() -> None:
    src = r"\newcommand{\norm}[1]{\left\lVert #1 \right\rVert_{2}}"
    assert extract_macros(_eprint({"m.tex": src})) == {
        "\\norm": "\\left\\lVert #1 \\right\\rVert_{2}"
    }


def test_later_definition_wins_and_is_deterministic() -> None:
    # Files are read name-sorted; within a file, later defs override earlier ones.
    a = r"\newcommand{\R}{\mathbb{R}}"
    b = r"\renewcommand{\R}{\mathcal{R}}"
    out1 = extract_macros(_eprint({"a.tex": a, "b.tex": b}))
    out2 = extract_macros(_eprint({"a.tex": a, "b.tex": b}))
    assert out1 == out2 == {"\\R": "\\mathcal{R}"}


def test_non_tex_members_are_ignored() -> None:
    files = {"img.png": "\\newcommand{\\R}{x}", "m.tex": r"\newcommand{\R}{\mathbb{R}}"}
    assert extract_macros(_eprint(files)) == {"\\R": "\\mathbb{R}"}
