"""schema_is_readable — the compatible-range rule readers apply to stored doc-models."""

from __future__ import annotations

import pytest

from docsuri_shared.docmodel_contract import DOCMODEL_SCHEMA_VERSION, schema_is_readable


def test_current_and_earlier_minors_of_the_same_major_are_readable() -> None:
    assert schema_is_readable(DOCMODEL_SCHEMA_VERSION)
    assert schema_is_readable("1.1.0")  # the stored corpus, after the 1.2.0 additive bump
    assert schema_is_readable("1.0.0")


@pytest.mark.parametrize(
    "stored",
    [
        "1.99.0",  # newer minor: may carry semantics this reader predates
        "2.0.0",  # different major: breaking shape
        "0.9.0",
        "1.2",  # not major.minor.patch
        "garbage",
        None,
        120,
    ],
)
def test_everything_else_is_refused(stored: object) -> None:
    assert not schema_is_readable(stored)
