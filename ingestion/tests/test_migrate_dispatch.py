"""Dispatch contract for the v4 migration runner (docsuri_ingestion.migrate).

Covers only the routing logic — the step functions themselves hit AWS and are exercised in
the live migration, not here.
"""

import pytest

from docsuri_ingestion.migrate import _STEPS, run_step


def test_steps_are_exactly_the_known_one_off_phases():
    assert set(_STEPS) == {
        "audit",
        "provision",
        "backfill",
        "backfill_external",
        "cutover",
        "reembed_provision",
        "reembed_copy",
        "reembed",
        "reembed_finalize",
        "reembed_verify",
        "reembed_cutover",
        "raw_backfill",
        "reparse",
    }


def test_run_step_rejects_unknown_step_before_side_effects():
    with pytest.raises(SystemExit):
        run_step("bogus")


def test_audit_refuses_to_run_without_a_control_plane_dsn() -> None:
    """An unset DSN must abort, not fall through to libpq's defaults.

    ``psycopg.connect("")`` is not an error — libpq resolves it from PGHOST/PGUSER or the local
    socket and the OS user. The audit would then print a tier distribution for an unrelated
    database with no indication that it never reached the control plane.
    """
    from docsuri_ingestion.migrate import audit
    from docsuri_ingestion.settings import IngestionSettings

    settings = IngestionSettings(DOCSURI_CONTROL_PLANE_DSN=None)
    with pytest.raises(SystemExit, match="DOCSURI_CONTROL_PLANE_DSN"):
        audit(settings)
