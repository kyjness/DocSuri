"""Control-plane store round-trip against a real Postgres (B — real SQL, no AWS).

``PostgresControlPlaneStore`` had no test at all, so its SQL only ever ran in deployment. The
dedup decision ladder now lives in ``domain.dedup.decide_dedup`` precisely so the Postgres and
in-memory stores cannot disagree — that shared policy is worth nothing unless something checks
the two stores really do agree once real SQL supplies the state.

Gated on ``DOCSURI_TEST_PG_DSN`` (skips otherwise); point it at a throwaway Postgres with
``migrations/postgres/*.sql`` applied.
"""

from __future__ import annotations

import os

import pytest

psycopg = pytest.importorskip("psycopg")
pytest.importorskip("psycopg_pool")

DSN = os.environ.get("DOCSURI_TEST_PG_DSN")
pytestmark = pytest.mark.skipif(not DSN, reason="set DOCSURI_TEST_PG_DSN to a test Postgres")

from docsuri_ingestion.adapters.local import InMemoryControlPlaneStore  # noqa: E402
from docsuri_ingestion.adapters.postgres import PostgresControlPlaneStore  # noqa: E402
from docsuri_ingestion.domain.enums import DedupDecision, SourceName  # noqa: E402
from docsuri_ingestion.domain.models import CanonicalDedupState  # noqa: E402

_PAPER = "TEST-CONTROL-PLANE"
_FINGERPRINT = "fp-original"


@pytest.fixture
def store():
    pg = PostgresControlPlaneStore(DSN or "")
    pg.delete_canonical_dedup_state_for_paper(_PAPER)
    with pg._connect() as conn:  # noqa: SLF001 - fixture cleanup, not production access
        conn.execute("DELETE FROM dedup_state WHERE paper_id = %s", (_PAPER,))
        conn.commit()
    yield pg
    pg.delete_canonical_dedup_state_for_paper(_PAPER)
    pg.close()


def test_dedup_ladder_matches_the_in_memory_store_on_real_sql(store) -> None:
    memory = InMemoryControlPlaneStore()
    stores = (store, memory)

    def decide(version: int, fingerprint: str) -> set[DedupDecision]:
        return {s.evaluate_dedup(_PAPER, version, fingerprint).decision for s in stores}

    assert decide(1, _FINGERPRINT) == {DedupDecision.NEW}

    for s in stores:
        s.try_claim_upsert(_PAPER, 1, _FINGERPRINT)
        s.mark_ingested(_PAPER, 1, _FINGERPRINT)

    # A redelivery of the identical payload short-circuits; anything else is a real re-ingest.
    assert decide(1, _FINGERPRINT) == {DedupDecision.DUPLICATE}
    assert decide(1, "fp-changed") == {DedupDecision.CHANGED}
    assert decide(2, _FINGERPRINT) == {DedupDecision.CHANGED}
    # An older version must never overwrite a newer one.
    assert decide(0, _FINGERPRINT) == {DedupDecision.STALE}


def test_canonical_state_round_trips_through_real_sql(store) -> None:
    state = CanonicalDedupState(
        canonical_key=f"arxiv:{_PAPER}",
        paper_id=_PAPER,
        winning_source_tier="ARXIV_PDF",
        winning_version=1,
        fingerprint=_FINGERPRINT,
        seen_sources=(SourceName.ARXIV, SourceName.OPENALEX),
    )
    store.upsert_canonical_dedup_state(state)

    # Both readers share one row mapper, so both must reconstruct the model exactly — including
    # seen_sources coming back as SourceName members rather than raw strings.
    assert store.get_canonical_dedup_state(state.canonical_key) == state
    assert list(store.list_canonical_dedup_states_for_paper(_PAPER)) == [state]

    assert store.get_canonical_dedup_state("arxiv:no-such-key") is None
    assert store.list_canonical_dedup_states_for_paper("no-such-paper") == ()

    store.delete_canonical_dedup_state_for_paper(_PAPER)
    assert store.get_canonical_dedup_state(state.canonical_key) is None
