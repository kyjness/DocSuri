"""``key_segment`` is a contract between two services, so its edges are pinned here.

The backend builds an upload key's owner segment with it; the ingestion worker checks a queued
job's key against the owner it claims with it. Both used to carry a private copy that agreed by
inspection only. These cases are the boundary inputs the two copies were once hand-compared on;
any change to the rule that moves one of them is a change to what the worker will accept.
"""

from __future__ import annotations

import pytest

from docsuri_shared.upload_keys import key_segment


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("acct-1", "acct-1"),
        ("user@example.com", "user-example.com"),  # one run of unsafe chars → one dash
        ("a/b/c", "a-b-c"),  # a slash never survives, or a segment could carry a path
        ("  spaced id  ", "spaced-id"),
        ("한글아이디", "x"),  # nothing safe survives → fallback, not an empty segment
        ("-", "x"),  # dashes alone strip to nothing → fallback
        ("", "x"),
        (None, "x"),
        ("._-", "._"),  # only DASHES are trimmed at the edges; dot/underscore stay
    ],
)
def test_segment_grammar(value, expected) -> None:
    assert key_segment(value) == expected


def test_the_fallback_is_the_callers_word() -> None:
    """The producer names it per segment (an empty attachment id reads ``attachment``, not
    ``x``), so a bare path is still readable — and the worker sees the same word."""
    assert key_segment("", fallback="attachment") == "attachment"
    assert key_segment("acct-1", fallback="attachment") == "acct-1"


def test_length_is_capped_after_sanitising() -> None:
    assert len(key_segment("z" * 300)) == 128
    # The cap applies to the RESULT: 130 unsafe chars collapse to one dash, then trim to nothing.
    assert key_segment("/" * 130) == "x"
