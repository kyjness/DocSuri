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
