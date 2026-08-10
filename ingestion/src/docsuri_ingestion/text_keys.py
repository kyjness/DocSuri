"""The comparison form of a caption, shared by the places that compare captions.

Two independent readers of the same page never agree on the incidentals. GROBID's TEI, pdfium's
text layer and a table extractor's cells render the same sentence with different spacing,
hyphenation, quoting and bracketing — ``"bounded by m " means`` against ``'bounded by m ' means``
— and none of that changes what the sentence says. So every comparison between two readers is
made on letters and digits alone, and it is made the same way wherever it happens.
"""

from __future__ import annotations

import re

_NON_ALNUM_RE = re.compile(r"[^0-9a-z]+", re.IGNORECASE)


def alnum_key(text: str) -> str:
    """``text`` reduced to its lowercase letters and digits, everything else dropped. Pure."""
    return _NON_ALNUM_RE.sub("", text).lower()
