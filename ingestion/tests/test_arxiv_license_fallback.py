"""fetch_metadata backfills a missing license from OAI-PMH GetRecord.

The Atom API no longer reliably exposes <arxiv:license>, which left records with
license_url=None and broke strict-OA gating. fetch_metadata now falls back to an OAI-PMH
GetRecord to recover the license; if the Atom feed already carries one, no OAI call is made.
"""

from docsuri_ingestion.adapters.arxiv import ArxivHttpSource

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
    "  <category term=\"cs.LG\"/>",
    "  <category term=\"cs.LG\"/>\n"
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
