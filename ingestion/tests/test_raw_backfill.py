"""AWS-free unit tests for the pure helpers of the B3 bulk-PDF cache prime. The raw_backfill step
itself streams arXiv's requester-pays bulk tars and is exercised in the live prime, not here."""

from docsuri_ingestion.raw_backfill import _paper_id_from_member, _yymm_from_paper_id


def test_paper_id_from_member_strips_pdf_extension():
    assert _paper_id_from_member("2501.12345.pdf") == "2501.12345"


def test_paper_id_from_member_strips_version_suffix():
    assert _paper_id_from_member("2501.12345v2.pdf") == "2501.12345"


def test_paper_id_from_member_strips_directory_prefix():
    assert _paper_id_from_member("2501/2501.12345v3.pdf") == "2501.12345"


def test_paper_id_from_member_none_for_non_pdf():
    assert _paper_id_from_member("2501.12345.txt") is None


def test_paper_id_from_member_none_for_directory_entry():
    assert _paper_id_from_member("2501/") is None


def test_paper_id_from_member_none_for_unparseable_stem():
    assert _paper_id_from_member("not-an-arxiv-id.pdf") is None


def test_yymm_from_paper_id_extracts_month_shard():
    assert _yymm_from_paper_id("2501.12345") == "2501"


def test_yymm_from_paper_id_none_for_bad_input():
    assert _yymm_from_paper_id("bad") is None
    assert _yymm_from_paper_id("hep-ph/0001001") is None
