"""``ArxivHttpSource.fetch_incremental`` — the daily tick's only source of new arXiv papers.

It had no test at all, and three independent defects were living in it together: the disjunction
was joined with a literal ``+`` (which httpx percent-encodes, so arXiv answered HTTP 200 with
totalResults=0), the update window was applied only in Python (so a sort with no date bound
returned 1993 papers that the watermark then discarded), and it read one 100-record page against a
slice measuring ~125 papers/day. Each alone made the tick queue nothing; together they made it
queue nothing *and report success*, which is indistinguishable from a quiet window.

The first of those cannot be caught by inspecting the params dict — the value looks right there
and only goes wrong when httpx encodes it. So the assertions below run over the URL as it goes on
the wire, rebuilt the way ``_get_bytes`` builds it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import unquote_plus

import httpx
import pytest

from docsuri_ingestion.adapters.arxiv import _ATOM_PAGE_SIZE, ArxivHttpSource

_SINCE = datetime(2026, 8, 10, 9, 30, tzinfo=UTC)


def _entry(index: int, updated: str) -> str:
    return f"""
 <entry>
  <id>http://arxiv.org/abs/2608.{index:05d}v1</id>
  <title>Paper {index}</title>
  <summary>Abstract {index}</summary>
  <author><name>Ada Lovelace</name></author>
  <category term="cs.CL"/>
  <updated>{updated}</updated>
  <published>{updated}</published>
  <arxiv:license>http://creativecommons.org/licenses/by/4.0/</arxiv:license>
 </entry>"""


def _feed(count: int, *, updated: str = "2026-08-15T00:00:00Z", start: int = 0) -> str:
    entries = "".join(_entry(start + i, updated) for i in range(count))
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<feed xmlns="http://www.w3.org/2005/Atom"'
        ' xmlns:arxiv="http://arxiv.org/schemas/atom">'
        f"{entries}</feed>"
    )


class _Recorder:
    """Captures each request's params and replays canned feeds, page by page."""

    def __init__(self, source: ArxivHttpSource, pages: list[str]) -> None:
        self.calls: list[dict[str, str]] = []
        self._pages = pages
        source._get_text = self._get_text  # type: ignore[method-assign]

    def _get_text(self, url: str, *, params, stage: str) -> str:
        self.calls.append(dict(params))
        return self._pages[len(self.calls) - 1]

    def url(self, index: int = 0) -> str:
        """The request as it goes ON THE WIRE — ``_get_bytes`` hands these params straight to
        httpx, and the encoding step is where the disjunction defect lived."""
        return str(
            httpx.Request(
                "GET", "https://export.arxiv.org/api/query", params=self.calls[index]
            ).url
        )

    def query(self, index: int = 0) -> str:
        """The wire URL decoded back to what arXiv's parser will see.

        Decoded rather than raw so the assertions read as the query arXiv receives — and the two
        spellings stay distinguishable, which is the whole point: the correct form decodes to
        ``cat:a OR cat:b`` (``+`` was a space) while the defect decodes to ``cat:a+OR+cat:b``
        (``+`` was a literal that survived as data).
        """
        return unquote_plus(self.url(index))


@pytest.fixture
def source() -> ArxivHttpSource:
    return ArxivHttpSource(timeout_seconds=1.0)


def test_the_category_disjunction_survives_url_encoding(source) -> None:
    """The regression that made a whole year of ticks harvest nothing.

    ``"+OR+".join(...)`` reads correctly in the source and in arXiv's own documentation, where
    ``+`` spells a space. But httpx encodes the parameter VALUE, so the literal ``+`` left as
    ``%2BOR%2B`` and arXiv returned 0 results with HTTP 200. Joining with a space lets the
    encoder produce the ``+`` arXiv is documented to want.
    """
    recorder = _Recorder(source, [_feed(1)])

    list(source.fetch_incremental(_SINCE, ("cs.CL", "cs.AI")))

    assert "cat:cs.CL OR cat:cs.AI" in recorder.query()
    # The defect's exact wire form, named so it can never come back unnoticed.
    assert "%2BOR%2B" not in recorder.url()


def test_the_window_is_a_query_bound_not_only_a_post_filter(source) -> None:
    """Without it, ``sortBy=lastUpdatedDate`` returns the corpus from 1993 and the ``> since``
    test discards every record — zero results however the disjunction is spelled.

    The range is CLOSED because an open one is not accepted: arXiv answers ``[stamp TO *]`` with
    HTTP 500 and an Atom error feed. That feed carries ``totalResults`` like a real one, so it
    reads as a successful single-result window to anything that counts entries without checking
    the status — which is how the open form got as far as a live run before being caught."""
    recorder = _Recorder(source, [_feed(1)])

    list(source.fetch_incremental(_SINCE, ("cs.CL",)))

    assert "lastUpdatedDate:[202608100930 TO 999912312359]" in recorder.query()


def test_it_reads_oldest_first(source) -> None:
    """Ascending, so a run cut short loses the NEWEST records — which the next tick re-covers —
    rather than the ones nearest the watermark, where a gap would never be revisited."""
    recorder = _Recorder(source, [_feed(1)])

    list(source.fetch_incremental(_SINCE, ("cs.CL",)))

    assert recorder.calls[0]["sortOrder"] == "ascending"
    assert recorder.calls[0]["sortBy"] == "lastUpdatedDate"


def test_it_pages_until_a_page_comes_back_short(source) -> None:
    """One page is 100 records against a slice measuring ~125/day, so a single-page read dropped
    part of even a healthy tick and most of any backlog."""
    recorder = _Recorder(
        source, [_feed(_ATOM_PAGE_SIZE), _feed(7, start=_ATOM_PAGE_SIZE)]
    )

    records = list(source.fetch_incremental(_SINCE, ("cs.CL",)))

    assert len(records) == _ATOM_PAGE_SIZE + 7
    assert [call["start"] for call in recorder.calls] == ["0", str(_ATOM_PAGE_SIZE)]


def test_a_full_final_page_still_ends_the_walk(source) -> None:
    """A page that is exactly full is followed by one more request; an empty answer stops it,
    so an exhausted window costs one extra call rather than looping."""
    recorder = _Recorder(source, [_feed(_ATOM_PAGE_SIZE), _feed(0)])

    records = list(source.fetch_incremental(_SINCE, ("cs.CL",)))

    assert len(records) == _ATOM_PAGE_SIZE
    assert len(recorder.calls) == 2


def test_the_boundary_minute_is_still_filtered_in_python(source) -> None:
    """The query stamp is minute-resolution and rounds DOWN, so the bound is inclusive and can
    re-serve a record already ingested. The ``> since`` test is what drops it."""
    at_the_bound = _SINCE.strftime("%Y-%m-%dT%H:%M:%SZ")
    _Recorder(source, [_feed(1, updated=at_the_bound)])

    assert list(source.fetch_incremental(_SINCE, ("cs.CL",))) == []
