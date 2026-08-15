"""fetch_metadata backfills a missing license from OAI-PMH GetRecord.

The Atom API no longer reliably exposes <arxiv:license>, which left records with
license_url=None and broke strict-OA gating. fetch_metadata now falls back to an OAI-PMH
GetRecord to recover the license; if the Atom feed already carries one, no OAI call is made.
"""

from dataclasses import replace

from docsuri_ingestion.adapters.arxiv import ArxivHttpSource
from docsuri_ingestion.adapters.local import sample_metadata

_ATOM_NO_LICENSE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
 <entry>
  <id>http://arxiv.org/abs/2401.12345v2</id>
  <title>A Paper Without License</title>
  <summary>Abstract text.</summary>
  <author><name>Ada Lovelace</name></author>
  <category term="cs.LG"/>
  <updated>2025-12-15T10:30:00+00:00</updated>
  <published>2025-12-10T10:30:00+00:00</published>
 </entry>
</feed>"""

_ATOM_WITH_LICENSE = _ATOM_NO_LICENSE.replace(
    '  <category term="cs.LG"/>',
    '  <category term="cs.LG"/>\n'
    "  <arxiv:license>http://creativecommons.org/licenses/by-sa/4.0/</arxiv:license>",
)

_OAI_WITH_LICENSE = """<?xml version="1.0" encoding="UTF-8"?>
<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">
 <GetRecord><record><metadata>
  <arXiv xmlns="http://arxiv.org/OAI/arXiv/">
   <id>2401.12345</id>
   <license>http://creativecommons.org/licenses/by/4.0/</license>
  </arXiv>
 </metadata></record></GetRecord>
</OAI-PMH>"""


def test_fetch_metadata_backfills_license_from_oai_when_atom_missing():
    src = ArxivHttpSource()
    stages: list[str] = []

    def fake_get_text(url, *, params, stage):
        stages.append(stage)
        return _OAI_WITH_LICENSE if stage == "fetch_license" else _ATOM_NO_LICENSE

    src._get_text = fake_get_text  # type: ignore[method-assign]
    record = src.fetch_metadata("2401.12345v2")

    assert stages == ["fetch_metadata", "fetch_license"]  # OAI fallback fired
    assert record.license_url == "http://creativecommons.org/licenses/by/4.0/"


def test_fetch_metadata_skips_oai_when_atom_already_has_license():
    src = ArxivHttpSource()
    stages: list[str] = []

    def fake_get_text(url, *, params, stage):
        stages.append(stage)
        return _ATOM_WITH_LICENSE

    src._get_text = fake_get_text  # type: ignore[method-assign]
    record = src.fetch_metadata("2401.12345v2")

    assert stages == ["fetch_metadata"]  # no OAI fallback
    assert record.license_url == "http://creativecommons.org/licenses/by-sa/4.0/"


def _feed(*ids: str) -> str:
    entries = "".join(
        f"""
 <entry>
  <id>http://arxiv.org/abs/{pid}v1</id>
  <title>Paper {pid}</title>
  <summary>Abstract text.</summary>
  <author><name>Ada Lovelace</name></author>
  <category term="cs.LG"/>
  <arxiv:license>http://creativecommons.org/licenses/by/4.0/</arxiv:license>
  <updated>2025-12-15T10:30:00+00:00</updated>
  <published>2025-12-10T10:30:00+00:00</published>
 </entry>"""
        for pid in ids
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<feed xmlns="http://www.w3.org/2005/Atom" '
        'xmlns:arxiv="http://arxiv.org/schemas/atom">'
        f"{entries}\n</feed>"
    )


def test_fetch_metadata_batch_collapses_many_ids_into_one_request_per_chunk():
    """1,500 named papers must cost ~15 requests, not 1,500. arXiv rate-limits by IP and the
    per-paper burst is what trips it, so the batching is the difference between a run finishing
    and the source refusing us partway through."""
    src = ArxivHttpSource()
    id_lists: list[str] = []

    def fake_get_text(url, *, params, stage):
        id_lists.append(params["id_list"])
        return _feed(*params["id_list"].split(","))

    src._get_text = fake_get_text  # type: ignore[method-assign]
    refs = [f"2401.{i:05d}" for i in range(250)]
    records = src.fetch_metadata_batch(refs)

    assert [len(ids.split(",")) for ids in id_lists] == [100, 100, 50]
    # Keyed by BARE paper id (no version), which is the form the caller's list carries.
    assert sorted(records) == sorted(refs)


def test_fetch_metadata_batch_keeps_the_chunks_that_worked():
    """Best effort, per chunk. This is a prefetch and every caller can still fetch a paper the
    slow way, so one bad chunk must cost its own ids — raising would discard the chunks that
    already succeeded and push the whole run back onto the per-paper path it exists to avoid."""
    src = ArxivHttpSource()
    calls: list[int] = []

    def fake_get_text(url, *, params, stage):
        calls.append(len(calls))
        if len(calls) == 2:
            raise RuntimeError("arXiv blipped")
        return _feed(*params["id_list"].split(","))

    src._get_text = fake_get_text  # type: ignore[method-assign]
    records = src.fetch_metadata_batch([f"2401.{i:05d}" for i in range(250)])

    assert len(calls) == 3  # kept going past the failure
    assert len(records) == 150  # first and third chunks survived

def test_license_lookup_derives_the_bare_id_with_the_id_parser():
    """The OAI identifier is the versionless id from ``normalize_arxiv_ref``, not a hand split.

    This used to strip the version with ``ref.rsplit("v", 1)[0]``, asserting in a comment that a
    split on the last "v" was safe for legacy ids too. It is not: an old-style archive name can
    contain a v, so ``solv-int/9801001`` reduced to ``sol`` and the GetRecord asked about a paper
    that does not exist — the licence stayed None and the paper was then rejected as non-OA.

    Exercised directly on the enrichment rather than through ``fetch_metadata``, because the Atom
    feed's ``<id>`` is read with its own ``rsplit("/")`` that an old-style id does not survive
    either. That is a separate matter and, in this corpus, an empty one: the 3,500-paper
    foundational list holds no old-style id and the slice is recent-only.
    """
    src = ArxivHttpSource()
    identifiers: list[str] = []

    def fake_get_text(url, *, params, stage):
        identifiers.append(params["identifier"])
        return _OAI_WITH_LICENSE

    src._get_text = fake_get_text  # type: ignore[method-assign]
    record = replace(sample_metadata(arxiv_ref="solv-int/9801001v2"), license_url=None)

    enriched = src._enrich_license_from_oai(record)

    assert identifiers == ["oai:arXiv.org:solv-int/9801001"]
    assert enriched.license_url == "http://creativecommons.org/licenses/by/4.0/"
