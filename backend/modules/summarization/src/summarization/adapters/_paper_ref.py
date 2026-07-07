"""Shared paper-id normalization for U7 read adapters.

The app carries *versioned* paper ids (``2304.10557v1``), but U1's stores key on the *bare*
id with the version as a separate field/segment — full-text (``full-text/{bareId}/v{ver}.txt``),
doc-model (``doc-model/{bareId}/v{ver}.json``), and the ``paper_asset`` table (bare ``paper_id``
column). A U7 reader that keys on the raw versioned id never finds what U1 wrote (perpetual
miss). Normalize at every read boundary so reads line up with writes.
"""

from __future__ import annotations


def bare_paper_id(paper_id: str) -> str:
    """Strip a trailing arXiv version suffix (``v<N>``) from a paper id.

    Mirrors U1's own ``rsplit('v', 1)`` derivation. arXiv ids never contain ``v`` except the
    trailing version, so the split is safe for both new (``2304.10557v1``) and old
    (``hep-th/9901001v2``) forms; a bare id (no ``v``) is returned unchanged.
    """
    return paper_id.rsplit("v", 1)[0] if "v" in paper_id else paper_id


def paper_version(paper_id: str, default: int = 1) -> int:
    """The arXiv version ``N`` from a versioned paper id (``2304.10557v1`` → 1), else ``default``.

    Counterpart to :func:`bare_paper_id`. U1 keys doc-model / full-text on ``.../v{N}.json`` where
    ``N`` is the arXiv version the app carries in the id, so a reader must recover ``N`` rather than
    assume v1 — a revised paper (v2+) lives at ``v2.json``/``v3.json``…, and reading ``v1`` for it
    is a perpetual miss (no rich source → no grounded evidence). Mirrors U1's ``rsplit('v', 1)``:
    arXiv ids never contain ``v`` except the trailing version, so this is safe for new
    (``2304.10557v3``) and old (``hep-th/9901001v2``) forms; a bare id yields ``default``.
    """
    bare, sep, tail = paper_id.rpartition("v")
    return int(tail) if sep and bare and tail.isdigit() else default
