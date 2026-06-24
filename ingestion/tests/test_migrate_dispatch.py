"""Dispatch contract for the v4 migration runner (docsuri_ingestion.migrate).

Covers only the routing logic — the step functions themselves hit AWS and are exercised in
the live migration, not here.
"""

import pytest

from docsuri_ingestion.migrate import _STEPS, run_step


def test_steps_are_exactly_the_three_migration_phases():
    assert set(_STEPS) == {"provision", "backfill", "cutover"}


def test_run_step_rejects_unknown_step_before_side_effects():
    with pytest.raises(SystemExit):
        run_step("bogus")
