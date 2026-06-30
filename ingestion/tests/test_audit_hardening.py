"""Focused checks for the U1 audit hardening fixes (XXE, SSRF, KaTeX strip, canonical guard)."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from docsuri_ingestion.adapters.corpus_http import (
    SsrfBlockedError,
    _assert_public_host,
    _pin_url,
)
from docsuri_ingestion.adapters.local import InMemoryControlPlaneStore
from docsuri_ingestion.docmodel.macros import _parse_defs
from docsuri_ingestion.docmodel.mathml import DANGEROUS_LATEX_RE, _sanitize
from docsuri_ingestion.domain.enums import SourceName
from docsuri_ingestion.domain.models import CanonicalDedupState
from docsuri_ingestion.xmlsafe import MAX_XML_BYTES, safe_fromstring

_BILLION_LAUGHS = (
    '<?xml version="1.0"?>'
    "<!DOCTYPE lolz [<!ENTITY lol 'lol'><!ENTITY lol2 '&lol;&lol;'>]>"
    "<root>&lol2;</root>"
)


def test_safe_fromstring_rejects_entity_expansion() -> None:
    # NFR §0.5: a DTD/entity-bearing payload must be refused (as ET.ParseError so callers degrade).
    with pytest.raises(ET.ParseError):
        safe_fromstring(_BILLION_LAUGHS)


def test_safe_fromstring_rejects_oversize() -> None:
    with pytest.raises(ET.ParseError):
        safe_fromstring(b"<a/>" + b" " * (MAX_XML_BYTES + 1))


def test_safe_fromstring_parses_clean_xml() -> None:
    assert safe_fromstring("<root><a>x</a></root>").find("a").text == "x"


def test_ssrf_guard_blocks_link_local_and_loopback() -> None:
    for url in ("http://169.254.169.254/latest/meta-data", "http://127.0.0.1/x", "http://[::1]/x"):
        with pytest.raises(SsrfBlockedError):
            _assert_public_host(url)


def test_ssrf_guard_allows_public_ip_and_pins_it() -> None:
    # Returns (host, validated_ip) so the caller connects to the address it just checked — the
    # IP we validate is the IP we reach (no DNS-rebinding window).
    host, ip = _assert_public_host("https://93.184.216.34/paper.pdf")  # public literal — no raise
    assert host == "93.184.216.34"
    assert ip == "93.184.216.34"


def test_pin_url_targets_ip_and_keeps_port_path_query() -> None:
    # Host drops out of the netloc (it rides in the Host header + SNI); scheme/port/path/query stay.
    assert (
        _pin_url("https://example.test:8443/a/b?q=1", "93.184.216.34")
        == "https://93.184.216.34:8443/a/b?q=1"
    )
    # IPv6 is bracketed so the netloc stays parseable.
    assert _pin_url("https://example.test/p", "2606:2800:220:1::1").startswith(
        "https://[2606:2800:220:1::1]/p"
    )


def test_katex_sanitize_strips_dangerous_commands() -> None:
    assert "\\href" not in _sanitize(r"\href{javascript:alert(1)}{x} + y")
    assert DANGEROUS_LATEX_RE.search(r"a \includegraphics{p} b")
    assert not DANGEROUS_LATEX_RE.search(r"\frac{1}{2} + \mathbb{R}")


def test_macros_reject_dangerous_body() -> None:
    out: dict[str, str] = {}
    _parse_defs(r"\newcommand{\R}{\href{javascript:alert(1)}{x}}", out)
    assert "\\R" not in out
    safe: dict[str, str] = {}
    _parse_defs(r"\newcommand{\R}{\mathbb{R}}", safe)
    assert safe["\\R"] == r"\mathbb{R}"


def _state(key: str, tier: str, version: int, source: SourceName) -> CanonicalDedupState:
    return CanonicalDedupState(
        canonical_key=key,
        paper_id=f"p-{tier}-{version}",
        winning_source_tier=tier,
        winning_version=version,
        fingerprint="fp",
        seen_sources=(source,),
    )


def test_canonical_winner_guard_keeps_higher_priority_and_merges_seen() -> None:
    store = InMemoryControlPlaneStore()
    # arXiv (priority 0) wins; a later OpenAlex (priority 2) must NOT clobber it, but its source
    # is merged into seen_sources.
    store.upsert_canonical_dedup_state(_state("k", "ARXIV_HTML", 2, SourceName.ARXIV))
    store.upsert_canonical_dedup_state(_state("k", "OPENALEX", 5, SourceName.OPENALEX))
    winner = store.get_canonical_dedup_state("k")
    assert winner.winning_source_tier == "ARXIV_HTML"
    assert winner.winning_version == 2
    assert set(winner.seen_sources) == {SourceName.ARXIV, SourceName.OPENALEX}


def test_canonical_winner_guard_is_version_monotonic() -> None:
    store = InMemoryControlPlaneStore()
    store.upsert_canonical_dedup_state(_state("k", "ARXIV_HTML", 3, SourceName.ARXIV))
    store.upsert_canonical_dedup_state(_state("k", "ARXIV_HTML", 1, SourceName.ARXIV))  # older
    assert store.get_canonical_dedup_state("k").winning_version == 3  # no regression
