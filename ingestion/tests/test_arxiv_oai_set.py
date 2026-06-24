"""_oai_set maps arXiv categories to OAI-PMH setSpecs.

Regression guard for the harvest bug: a dotted ``set=cs.LG`` is rejected by arXiv OAI-PMH
(``badArgument: Set does not exist``, HTTP 200 → 0 records). Valid sets use the colon
hierarchy ``<archive>:<archive>:<CATEGORY>`` (verified against oaipmh.arxiv.org).
"""

from datetime import datetime

import pytest

from docsuri_ingestion.adapters.arxiv import ArxivHttpSource, _oai_set, parse_oai_records
from docsuri_ingestion.domain.enums import FailureReason
from docsuri_ingestion.domain.errors import RetriableIngestionError
from docsuri_ingestion.domain.models import CategoryFilter
from docsuri_ingestion.resilience import RetryPolicy


def test_dotted_category_maps_to_colon_setspec():
    assert _oai_set("cs.LG") == "cs:cs:LG"
    assert _oai_set("cs.AI") == "cs:cs:AI"
    assert _oai_set("cs.CL") == "cs:cs:CL"
    assert _oai_set("cs.CV") == "cs:cs:CV"
    assert _oai_set("stat.ML") == "stat:stat:ML"


def test_archive_only_category_passes_through():
    assert _oai_set("cs") == "cs"


# Minimal real-shape OAI-PMH ListRecords envelope: one valid record (nested <authors>) +
# one malformed record (missing <abstract>) that must be skipped, not fatal.
_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">
 <ListRecords>
  <record><metadata>
   <arXiv xmlns="http://arxiv.org/OAI/arXiv/">
    <id>2202.09848</id>
    <created>2025-12-11</created>
    <updated>2025-12-15</updated>
    <authors>
     <author><keyname>Nikoloutsopoulos</keyname><forenames>Sotirios</forenames></author>
     <author><keyname>Titsias</keyname><forenames>Michalis K.</forenames></author>
    </authors>
    <title>Personalized Federated Learning</title>
    <categories>cs.LG cs.AI</categories>
    <abstract>We propose an SGD-type algorithm.</abstract>
   </arXiv>
  </metadata></record>
  <record><metadata>
   <arXiv xmlns="http://arxiv.org/OAI/arXiv/">
    <id>9999.00000</id>
    <created>2025-12-11</created>
    <title>No abstract here</title>
    <categories>cs.LG</categories>
   </arXiv>
  </metadata></record>
 </ListRecords>
</OAI-PMH>"""


def test_parse_oai_records_nested_authors_and_skips_malformed():
    records = parse_oai_records(_SAMPLE)
    assert len(records) == 1  # malformed (missing abstract) skipped, harvest not aborted
    r = records[0]
    assert r.arxiv_ref == "2202.09848"
    assert r.authors == ("Sotirios Nikoloutsopoulos", "Michalis K. Titsias")
    assert r.categories == ("cs.LG", "cs.AI")
    # backfill now feeds the OAI record straight into fetch_full_text, which builds the URL
    # from the identifier — so the OAI record alone must resolve a usable id. The OAI id is
    # bare (no version) → normalizes to v1; fetch_full_text still gets a real arXiv version.
    assert r.identifier.paper_id == "2202.09848"
    assert r.identifier.arxiv_id  # non-empty, URL-usable


def _filter() -> CategoryFilter:
    return CategoryFilter(
        categories=("cs.LG",),
        updated_after=datetime(2025, 12, 1),
        updated_before=datetime(2025, 12, 31),
    )


def _timeout(stage: str) -> RetriableIngestionError:
    return RetriableIngestionError(
        "arXiv request timed out", reason=FailureReason.TIMEOUT, stage=stage
    )


def test_harvest_retries_transient_page_failure_then_succeeds():
    # Regression: a transient timeout mid-pagination must retry in-place, not abort the harvest
    # (it raises inside the harvest_seed generator, past backfill's per-paper try/except).
    src = ArxivHttpSource(oai_retry_policy=RetryPolicy(max_attempts=4, base_delay_seconds=0.0))
    calls = {"n": 0}

    def fake_get_text(url, *, params, stage):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise _timeout(stage)
        return _SAMPLE

    src._get_text = fake_get_text  # type: ignore[method-assign]
    records = list(src.harvest_seed(_filter()))
    assert calls["n"] == 3  # 2 transient failures + 1 success
    assert [r.arxiv_ref for r in records] == ["2202.09848"]


def test_harvest_aborts_loudly_when_retries_exhausted():
    src = ArxivHttpSource(oai_retry_policy=RetryPolicy(max_attempts=3, base_delay_seconds=0.0))

    def always_timeout(url, *, params, stage):
        raise _timeout(stage)

    src._get_text = always_timeout  # type: ignore[method-assign]
    with pytest.raises(RetriableIngestionError):
        list(src.harvest_seed(_filter()))
