"""The two-pass TEI cache that keeps GROBID and Docling out of memory at the same time.

WHY IT EXISTS, measured on the 7.5GB dev box (2026-08-14): GROBID holds 2.9GB while working and
Docling peaks at 1.6GB, and the PDF/GROBID rung needs both — GROBID for the TEI, Docling to re-read
the tables GROBID mangles. Together with OpenSearch and the rest of the stack that overruns the
host, and the kernel OOM-kills GROBID (``Out of memory: Killed process (java)``, no cgroup limit
involved). Lowering ``-Xmx`` does not fix it: two of GROBID's models run TensorFlow off-heap, so
2.9GB is resident with ``-Xmx2g``.

So the rung runs in two passes over the same papers — ``prefer`` extracts and caches TEI with
GROBID up and Docling absent, ``only`` builds from the cache with GROBID down — and this file
pins the contract each pass depends on.
"""

from __future__ import annotations

import pytest

from docsuri_ingestion.adapters.grobid import GrobidHttpClient
from docsuri_ingestion.domain.errors import RetriableIngestionError

_TEI = "<TEI><text><body><p>hello</p></body></text></TEI>"


class _Store:
    """Raw-content store double, keyed exactly as ``S3RawContentStore`` keys it."""

    def __init__(self, seeded: dict[tuple[str, int, str], bytes] | None = None) -> None:
        self.data = dict(seeded or {})
        self.writes: list[tuple[str, int, str]] = []

    def put_raw(self, paper_id, version, tier, data, *, content_type="application/octet-stream"):
        self.data[(paper_id, version, tier)] = data
        self.writes.append((paper_id, version, tier))
        return f"s3://raw/{paper_id}/v{version}/{tier}"

    def get_raw(self, paper_id, version, tier):
        return self.data.get((paper_id, version, tier))


def _client(store, mode: str, posts: list[bytes] | None = None) -> GrobidHttpClient:
    client = GrobidHttpClient(base_url="http://grobid:8070", raw_store=store, cache_mode=mode)

    def fake_post(pdf: bytes) -> str:
        if posts is not None:
            posts.append(pdf)
        return _TEI

    client._post_tei = fake_post  # type: ignore[method-assign]
    return client


def test_prefer_calls_grobid_once_and_caches_the_result() -> None:
    """Pass 1. The TEI must land in the store, or pass 2 has nothing to read."""
    store, posts = _Store(), []
    client = _client(store, "prefer", posts)

    assert client.extract_tei(b"%PDF", paper_id="2401.00001", version=2) == _TEI
    assert store.writes == [("2401.00001", 2, "tei")]
    # Second call for the same paper is served from the cache — GROBID is not asked twice.
    assert client.extract_tei(b"%PDF", paper_id="2401.00001", version=2) == _TEI
    assert len(posts) == 1


def test_only_serves_the_cache_without_calling_grobid() -> None:
    """Pass 2, the whole point: GROBID is DOWN here, so a call would fail the paper."""
    store = _Store({("2401.00001", 2, "tei"): _TEI.encode()})
    posts: list[bytes] = []
    client = _client(store, "only", posts)

    assert client.extract_tei(b"%PDF", paper_id="2401.00001", version=2) == _TEI
    assert posts == []


def test_only_raises_on_a_miss_rather_than_returning_empty_tei() -> None:
    """A miss means pass 1 did not cover this paper — it must be loud.

    Returning "" would hand the builder an empty TEI, which reads downstream as "this paper has
    no structured form": indistinguishable from a genuinely unparseable PDF, and recorded that way
    permanently. Retriable, so the paper lands in the DLQ and can be redriven after a pass 1 that
    covers it.
    """
    client = _client(_Store(), "only")
    with pytest.raises(RetriableIngestionError) as caught:
        client.extract_tei(b"%PDF", paper_id="2401.00001", version=2)
    assert caught.value.stage == "grobid"


def test_an_unkeyed_call_bypasses_the_cache_entirely() -> None:
    """A caller that cannot name the paper cannot take part in the split. Sharing one unkeyed
    entry between papers would be far worse than not caching — it would serve one paper's TEI as
    another's."""
    store, posts = _Store(), []
    client = _client(store, "prefer", posts)

    assert client.extract_tei(b"%PDF") == _TEI
    assert store.writes == []
    assert len(posts) == 1


def test_off_is_the_plain_http_call_it_always_was() -> None:
    """Default mode: no reads, no writes, one POST — a box with room needs no split."""
    store = _Store({("2401.00001", 2, "tei"): b"<TEI>stale</TEI>"})
    posts: list[bytes] = []
    client = _client(store, "off", posts)

    assert client.extract_tei(b"%PDF", paper_id="2401.00001", version=2) == _TEI
    assert store.writes == []
    assert len(posts) == 1
