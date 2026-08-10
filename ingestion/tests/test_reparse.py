"""reparse loss budget (⑧-2 safety net).

The reparse→finalize→cutover chain had no exclusion gate: per-paper exceptions were logged and
the run returned 0 unconditionally, finalize's document floor defaults to 1, and cutover swaps
the alias without questions. A mis-tuned quality gate or a broken GROBID sidecar could silently
exclude thousands of papers and the shrink would go live. The run itself must refuse to look
successful past a loss budget.
"""

from __future__ import annotations

from types import SimpleNamespace

from docsuri_ingestion.adapters.local import sample_metadata
from docsuri_ingestion.domain.enums import FailureReason
from docsuri_ingestion.domain.errors import PermanentIngestionError
from docsuri_ingestion.reparse import reparse
from docsuri_ingestion.settings import IngestionSettings


class _ScriptedPipeline:
    """ingest_metadata succeeds or raises per the script — one entry per harvested paper."""

    def __init__(self, script: list[str]) -> None:
        self._script = script
        self._i = 0

    def ingest_metadata(self, job, metadata):
        verdict = self._script[self._i]
        self._i += 1
        if verdict == "excluded":
            raise PermanentIngestionError(
                "excluded", reason=FailureReason.PARSE_FAILURE, stage="docmodel"
            )
        if verdict == "error":
            raise RuntimeError("transient fault")


def _run(monkeypatch, script: list[str], *, budget: float) -> int:
    class _FakeHarvest:
        def __init__(self, *a, **k) -> None:
            pass

        def harvest_seed(self, category_filter):
            for _ in script:
                yield sample_metadata()

    monkeypatch.setattr("docsuri_ingestion.adapters.arxiv.ArxivHttpSource", _FakeHarvest)
    monkeypatch.setattr(
        "docsuri_ingestion.runtime.build_production_runtime",
        lambda settings: SimpleNamespace(pipeline=_ScriptedPipeline(script)),
    )
    settings = IngestionSettings(
        DOCSURI_BEDROCK_MODEL_ID="model-x",
        DOCSURI_REPARSE_MAX_FAILURE_RATIO=budget,
    )
    return reparse(settings)


def test_reparse_within_budget_exits_zero(monkeypatch) -> None:
    # 1 exclusion / 20 papers = 5% — at the default budget, not over it.
    script = ["ok"] * 19 + ["excluded"]
    assert _run(monkeypatch, script, budget=0.05) == 0


def test_reparse_over_budget_exits_nonzero(monkeypatch) -> None:
    # A systematic fault (gate mis-tune, dead GROBID): exclusions blow the budget → the run must
    # fail so finalize/cutover cannot make the shrink permanent.
    script = ["ok"] * 6 + ["excluded"] * 3 + ["error"]
    assert _run(monkeypatch, script, budget=0.05) == 1


def test_reparse_with_zero_papers_fails(monkeypatch) -> None:
    # An empty harvest is 100% loss, not success — a window/category misconfiguration must not
    # hand finalize an empty index with exit code 0.
    assert _run(monkeypatch, [], budget=0.05) == 1
