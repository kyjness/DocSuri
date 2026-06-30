"""Hardened XML parsing for untrusted external input (NFR §0.5).

arXiv Atom/OAI feeds and GROBID TEI are third-party (and, for Semantic Scholar / OpenAlex,
attacker-influenceable) XML. Stdlib ``xml.etree`` is vulnerable to entity-expansion DoS
("billion laughs" / quadratic blow-up), which NFR §0.5 requires us to block. ``safe_fromstring``
parses with DTD + entity expansion forbidden and a size cap, and normalises every rejection to
``xml.etree.ElementTree.ParseError`` so existing ``except ET.ParseError`` call sites degrade
through their normal PARSE_FAILURE / best-effort paths instead of crashing on a new exception
type.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from defusedxml import DefusedXmlException
from defusedxml.ElementTree import fromstring as _defused_fromstring

# arXiv Atom/OAI pages and GROBID TEI are well under this; the cap only stops a hostile payload
# from exhausting worker memory at parse time.
# ponytail: 32 MiB ceiling; raise only if a legitimate TEI document is ever rejected.
MAX_XML_BYTES = 32 * 1024 * 1024


def safe_fromstring(text: str | bytes, *, max_bytes: int = MAX_XML_BYTES) -> ET.Element:
    """Parse untrusted XML with DTD/entity expansion forbidden and a hard size cap.

    Raises ``ET.ParseError`` on malformed XML, a forbidden DTD/entity construct, or oversize
    input — the one exception type all call sites already handle.
    """
    raw = text.encode("utf-8", errors="replace") if isinstance(text, str) else text
    if len(raw) > max_bytes:
        raise ET.ParseError(f"XML payload {len(raw)} bytes exceeds {max_bytes} byte cap")
    try:
        return _defused_fromstring(raw)
    except DefusedXmlException as exc:  # forbidden DTD / entity expansion / external ref
        raise ET.ParseError(f"forbidden XML construct: {exc}") from exc
