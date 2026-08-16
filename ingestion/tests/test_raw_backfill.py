"""AWS-free unit tests for the pure helpers of the B3 bulk-PDF cache prime, plus the tar walk
driven against a fake S3 client. The full step streams arXiv's requester-pays bucket and is
exercised in the live prime, not here."""

from __future__ import annotations

import io
import tarfile
from collections import Counter

from docsuri_ingestion.raw_backfill import (
    _identifier_from_member,
    _prime_from_tar,
    _yymm_from_paper_id,
)

_PDF = b"%PDF-1.7\nbody"


def test_identifier_from_member_reads_id_and_version():
    identifier = _identifier_from_member("2501.12345v2.pdf")
    assert (identifier.paper_id, identifier.version) == ("2501.12345", 2)


def test_identifier_from_member_strips_directory_prefix():
    identifier = _identifier_from_member("2501/2501.12345v3.pdf")
    assert (identifier.paper_id, identifier.version) == ("2501.12345", 3)


def test_identifier_from_member_defaults_an_unversioned_stem_to_v1():
    # arXiv's bulk tars name the version, so a bare stem is unusual. It reads as v1 and will
    # simply not match a target on a later version — the fail-closed answer, not a guess.
    identifier = _identifier_from_member("2501.12345.pdf")
    assert (identifier.paper_id, identifier.version) == ("2501.12345", 1)


def test_identifier_from_member_none_for_non_pdf():
    assert _identifier_from_member("2501.12345.txt") is None


def test_identifier_from_member_none_for_directory_entry():
    assert _identifier_from_member("2501/") is None


def test_identifier_from_member_none_for_unparseable_stem():
    assert _identifier_from_member("not-an-arxiv-id.pdf") is None


def test_yymm_from_paper_id_extracts_month_shard():
    assert _yymm_from_paper_id("2501.12345") == "2501"


def test_yymm_from_paper_id_none_for_bad_input():
    assert _yymm_from_paper_id("bad") is None
    assert _yymm_from_paper_id("hep-ph/0001001") is None


# --------------------------------------------------------------------------- the tar walk


class _FakeStore:
    def __init__(self) -> None:
        self.written: dict[tuple[str, int, str], bytes] = {}

    def put_raw(self, paper_id, version, tier, data, *, content_type=""):
        self.written[(paper_id, version, tier)] = data
        return f"s3://fake/{paper_id}/v{version}/{tier}"

    def get_raw(self, paper_id, version, tier):
        return self.written.get((paper_id, version, tier))


def _tar_client(members: dict[str, bytes]):
    """A boto3-shaped stub whose download_fileobj writes a tar holding ``members``."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    payload = buf.getvalue()

    class _Client:
        def download_fileobj(self, bucket, key, fileobj, **kwargs):
            fileobj.write(payload)

    return _Client()


def _prime(members, targets, tmp_path):
    store, skipped = _FakeStore(), Counter()
    cached = _prime_from_tar(
        _tar_client(members), "arxiv", "pdf/x.tar", targets, store, str(tmp_path), skipped
    )
    return cached, store, skipped


def test_a_matching_version_is_cached_under_that_version(tmp_path):
    cached, store, skipped = _prime({"2501.11111v2.pdf": _PDF}, {"2501.11111": 2}, tmp_path)

    assert cached == {"2501.11111"}
    assert store.written == {("2501.11111", 2, "pdf"): _PDF}
    assert not skipped


def test_a_different_version_is_refused_rather_than_filed_under_the_wanted_one(tmp_path):
    """The cache key is per version and ``reparse`` reads it exclusively (raw_cache_mode=only),
    so writing the tar's v1 bytes under the harvest's v2 would index the wrong revision's text
    and structure with nothing anywhere saying so."""
    cached, store, skipped = _prime({"2501.11111v1.pdf": _PDF}, {"2501.11111": 2}, tmp_path)

    assert cached == set()
    assert store.written == {}
    assert skipped["version_mismatch"] == 1


def test_a_non_pdf_member_is_refused(tmp_path):
    """Every READER of this cache checks the magic bytes; the one writer did not, so a landing
    page filed as a PDF read back as a miss and the paper was excluded with no trace of why."""
    landing = b"<!doctype html><title>Not found</title>"
    cached, store, skipped = _prime({"2501.11111v2.pdf": landing}, {"2501.11111": 2}, tmp_path)

    assert cached == set()
    assert store.written == {}
    assert skipped["not_pdf"] == 1


def test_a_revised_papers_other_versions_are_not_counted_once_it_is_cached(tmp_path):
    """The NORMAL shape of the bulk tars, and it used to read as a fault.

    Every harvest target is v1 (OAI ids are versionless), and arXiv's tars carry every version of
    a paper as its own member. So a revised paper's v2 and v3 members are not a snapshot lagging
    the harvest — they are what a revised paper looks like — and counting them made a healthy run
    report hundreds of mismatches, the very signal the counter was added to distinguish. Only a
    member of a paper that ends up with NOTHING cached says something went wrong.
    """
    cached, store, skipped = _prime(
        {"2501.11111v1.pdf": _PDF, "2501.11111v2.pdf": _PDF, "2501.11111v3.pdf": _PDF},
        {"2501.11111": 1},
        tmp_path,
    )

    assert cached == {"2501.11111"}
    assert store.written == {("2501.11111", 1, "pdf"): _PDF}
    assert skipped["version_mismatch"] == 0


def test_a_paper_whose_only_members_are_the_wrong_version_is_still_counted(tmp_path):
    # The signal survives for the case that matters: nothing for this paper was cached at all.
    cached, store, skipped = _prime(
        {"2501.11111v2.pdf": _PDF, "2501.11111v3.pdf": _PDF}, {"2501.11111": 1}, tmp_path
    )

    assert cached == set()
    assert skipped["version_mismatch"] == 2


def test_members_outside_the_target_set_are_ignored_without_being_counted(tmp_path):
    # Not a refusal — the tar simply holds the whole month and most of it is not wanted.
    cached, store, skipped = _prime(
        {"2501.99999v1.pdf": _PDF, "2501.11111v2.pdf": _PDF}, {"2501.11111": 2}, tmp_path
    )

    assert cached == {"2501.11111"}
    assert not skipped
