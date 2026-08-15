"""The named-foundational-paper ingest path (⑧-2).

This is not a convenience script: it puts a third of the deployment corpus in, and the papers it
carries are exactly the ones a date window cannot reach. So the parts that decide whether an
interrupted or partly-failing run can be trusted — the resume ledger, failure isolation, and the
loss gate — are tested rather than eyeballed.
"""

from __future__ import annotations

import json
import pathlib
from datetime import UTC, datetime

import pytest

from docsuri_ingestion.domain.enums import DedupDecision, FailureReason
from docsuri_ingestion.domain.errors import PermanentIngestionError, RetriableIngestionError
from docsuri_ingestion.domain.models import MetadataRecord
from docsuri_ingestion.foundational import (
    CONSECUTIVE_FAILURE_LIMIT,
    MAX_FAILURE_RATIO,
    METADATA_CHUNK,
    RECENT_FAILURE_LIMIT,
    RECENT_WINDOW,
    ingest_foundational,
    load_ledger,
    pending,
    read_list,
    read_redo,
)

_HEADER = "arxiv_id\tbucket\tyear\tcitations\tsurveys\tbuckets\tscore\ttitle\n"


def _write_list(tmp_path: pathlib.Path, rows: list[tuple[str, str]]) -> pathlib.Path:
    path = tmp_path / "list.tsv"
    body = "".join(f"{aid}\t{bucket}\t2020\t100\t3\t1\t2.0\tTitle\n" for aid, bucket in rows)
    path.write_text(_HEADER + body, encoding="utf-8")
    return path


class _Pipeline:
    """Records every ingest and answers with a scripted outcome per arXiv id."""

    def __init__(self, outcomes: dict[str, object] | None = None) -> None:
        self.seen: list[str] = []
        self.metadata_seen: list[dict | None] = []
        self._outcomes = outcomes or {}

    def ingest_one(self, job):
        self.seen.append(job.arxiv_ref)
        self.metadata_seen.append(job.arxiv_metadata)
        outcome = self._outcomes.get(job.arxiv_ref, DedupDecision.NEW)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class _Arxiv:
    """Bulk-metadata double. Records the id lists it was asked for, one entry per chunk."""

    def __init__(self, *, known: set[str] | None = None, raises: Exception | None = None) -> None:
        self.calls: list[list[str]] = []
        self._known = known
        self._raises = raises

    def fetch_metadata_batch(self, refs):
        self.calls.append(list(refs))
        if self._raises is not None:
            raise self._raises
        return {aid: _metadata(aid) for aid in refs if self._known is None or aid in self._known}


def _metadata(arxiv_id: str) -> MetadataRecord:
    return MetadataRecord(
        arxiv_ref=arxiv_id,
        title=f"Title {arxiv_id}",
        authors=("A",),
        abstract="abstract",
        categories=("cs.CL",),
        updated_at=datetime(2024, 1, 1, tzinfo=UTC),
        license_url="http://creativecommons.org/licenses/by/4.0/",
    )


class _Embedding:
    """Enough of an embedding port for the pre-flight probe to succeed."""

    def embed_documents(self, texts, *, correlation_id=None):  # noqa: ARG002
        return [[0.0] for _ in texts]


class _Runtime:
    def __init__(self, pipeline: _Pipeline, arxiv: _Arxiv | None = None) -> None:
        self.pipeline = pipeline
        self.arxiv = arxiv
        self.embedding = _Embedding()


@pytest.fixture
def wired(monkeypatch):
    """Patch the runtime builder so no real adapters (or corpus) are touched."""

    def build(pipeline: _Pipeline, arxiv: _Arxiv | None = None) -> _Pipeline:
        monkeypatch.setattr(
            "docsuri_ingestion.foundational.build_production_runtime",
            lambda settings: _Runtime(pipeline, arxiv),
        )
        return pipeline

    return build


def test_read_list_selects_by_column_name_and_filters_by_bucket(tmp_path) -> None:
    # Read by NAME, not position: the TSV has already gained a column once (topics -> buckets),
    # and a positional reader would have silently shifted every id by one.
    path = _write_list(tmp_path, [("1706.03762", "canon"), ("2106.09685", "cs.CL")])
    assert read_list(path) == [("1706.03762", "canon"), ("2106.09685", "cs.CL")]
    assert read_list(path, bucket="cs.CL") == [("2106.09685", "cs.CL")]


def test_limit_applies_after_the_ledger_so_chunked_runs_advance(tmp_path, wired) -> None:
    """--limit N caps THIS run's work, not the window of reachable rows.

    Sliced before the ledger filter, run 2 of `--limit 2` re-read the same first two rows,
    found them ledgered, and reported success having done nothing — rows 3+ were unreachable
    without deleting the ledger."""
    pipeline = wired(_Pipeline())
    rows = [(f"p{i}", "canon") for i in range(5)]
    path = _write_list(tmp_path, rows)
    ledger = tmp_path / "l.jsonl"

    assert ingest_foundational(list_path=str(path), ledger_path=str(ledger), limit=2) == 0
    assert pipeline.seen == ["p0", "p1"]
    assert ingest_foundational(list_path=str(path), ledger_path=str(ledger), limit=2) == 0
    assert pipeline.seen == ["p0", "p1", "p2", "p3"]


def test_limit_zero_means_do_nothing(tmp_path, monkeypatch) -> None:
    # `if limit` read 0 as "no limit" and launched the full run.
    def explode(settings):  # pragma: no cover
        raise AssertionError("limit 0 must not build a runtime")

    monkeypatch.setattr("docsuri_ingestion.foundational.build_production_runtime", explode)
    path = _write_list(tmp_path, [("a", "canon")])
    result = ingest_foundational(
        list_path=str(path), ledger_path=str(tmp_path / "l.jsonl"), limit=0
    )
    assert result == 0


def test_resume_skips_done_and_retries_failures_only_on_request() -> None:
    rows = [("a", "canon"), ("b", "canon"), ("c", "canon")]
    done = {"a": "NEW", "b": "failed:permanent:FETCH_FAILURE"}
    # Default: a recorded failure stays recorded — otherwise every re-run spends its time
    # re-attempting the same 404s.
    assert pending(rows, done, retry_failed=False) == [("c", "canon")]
    assert pending(rows, done, retry_failed=True) == [("b", "canon"), ("c", "canon")]


def test_ledger_survives_corrupt_and_wrong_shaped_lines(tmp_path) -> None:
    # The ledger is append-only and flushed per paper, so a kill mid-write can leave a partial
    # last line — and a hand-edited line can be valid JSON of the wrong shape. Either must cost
    # that line, not the whole resume record (a KeyError here re-ingests 1,500 papers).
    path = tmp_path / "ledger.jsonl"
    path.write_text(
        json.dumps({"arxiv_id": "a", "outcome": "NEW"})
        + "\n"
        + '{"arxiv_id": "b", "outc'
        + "\n"
        + json.dumps({"paper": "c"})
        + "\n"
        + json.dumps(["not", "a", "dict"]),
        encoding="utf-8",
    )
    assert load_ledger(path) == {"a": "NEW"}


def test_dry_run_never_builds_a_runtime(tmp_path, monkeypatch) -> None:
    def explode(settings):  # pragma: no cover - must not be called
        raise AssertionError("dry-run must not construct adapters")

    monkeypatch.setattr("docsuri_ingestion.foundational.build_production_runtime", explode)
    path = _write_list(tmp_path, [("a", "canon")])
    assert (
        ingest_foundational(
            list_path=str(path), ledger_path=str(tmp_path / "l.jsonl"), dry_run=True
        )
        == 0
    )


def test_one_failing_paper_does_not_end_the_run(tmp_path, wired) -> None:
    pipeline = wired(
        _Pipeline(
            {
                "b": PermanentIngestionError(
                    "gone", reason=FailureReason.FETCH_FAILURE, stage="fetch_metadata"
                )
            }
        )
    )
    # Twenty papers so a single failure stays under the loss gate — this test is about the run
    # continuing, and the gate's own behaviour is covered separately below.
    rows = [(chr(ord("a") + i), "canon") for i in range(20)]
    path = _write_list(tmp_path, rows)
    ledger = tmp_path / "ledger.jsonl"

    assert ingest_foundational(list_path=str(path), ledger_path=str(ledger)) == 0
    # The run continued past the failure...
    assert pipeline.seen == [aid for aid, _ in rows]
    # ...and the ledger classifies it, so a re-run skips the successes but can target b.
    recorded = load_ledger(ledger)
    assert recorded["a"] == DedupDecision.NEW.value
    # The STAGE is part of the outcome — without it a retry run cannot tell "died on the embed
    # quota, which is back" from "died on GROBID, which is still deliberately down".
    assert recorded["b"] == "failed:permanent:FETCH_FAILURE:fetch_metadata"


def test_retriable_failure_is_classified_without_a_second_retry_layer(tmp_path, wired) -> None:
    """A RetriableIngestionError surfacing from ingest_one means the pipeline's OWN retries
    (dependency_call: up to 5 attempts behind a circuit breaker) are already exhausted. An outer
    retry here multiplied that to 15 attempts per dead dependency and re-ran the whole pipeline
    against a breaker that had just opened — so the driver classifies and moves on, and
    ``--retry-failed`` on a later run is the second chance."""
    pipeline = wired(
        _Pipeline(
            {
                "a": RetriableIngestionError(
                    "429", reason=FailureReason.RATE_LIMITED, stage="fetch_metadata"
                )
            }
        )
    )
    path = _write_list(
        tmp_path, [("a", "canon"), ("b", "canon")] + [(f"p{i}", "canon") for i in range(18)]
    )
    ledger = tmp_path / "l.jsonl"
    assert ingest_foundational(list_path=str(path), ledger_path=str(ledger)) == 0
    assert pipeline.seen.count("a") == 1
    assert load_ledger(ledger)["a"] == "failed:retriable:RATE_LIMITED:fetch_metadata"


def test_loss_over_the_gate_exits_nonzero(tmp_path, wired) -> None:
    """Unlike a date window, every id here was chosen because U12 needs it — losing many is a
    reason to stop, not a rate to average away."""
    boom = PermanentIngestionError(
        "gone", reason=FailureReason.FETCH_FAILURE, stage="fetch_metadata"
    )
    rows = [(f"p{i}", "canon") for i in range(10)]
    failures = {f"p{i}": boom for i in range(int(10 * MAX_FAILURE_RATIO) + 1)}
    wired(_Pipeline(failures))
    path = _write_list(tmp_path, rows)

    assert ingest_foundational(list_path=str(path), ledger_path=str(tmp_path / "l.jsonl")) == 1


def test_loss_at_or_below_the_gate_exits_zero(tmp_path, wired) -> None:
    boom = PermanentIngestionError(
        "gone", reason=FailureReason.FETCH_FAILURE, stage="fetch_metadata"
    )
    rows = [(f"p{i}", "canon") for i in range(20)]
    wired(_Pipeline({"p0": boom, "p1": boom}))  # 10% exactly
    path = _write_list(tmp_path, rows)

    assert ingest_foundational(list_path=str(path), ledger_path=str(tmp_path / "l.jsonl")) == 0


def test_cli_dry_run_builds_no_runtime_and_local_uses_the_local_one(tmp_path, monkeypatch) -> None:
    """The CLI dispatch order is the contract under test.

    Building the shared runtime before dispatching this subcommand silently discarded --local
    (a local runtime was constructed and thrown away while the module went on to ingest 1,500
    papers into the REAL corpus) and violated --dry-run's documented no-runtime guarantee by
    constructing production adapters it never used.
    """
    from docsuri_ingestion import cli

    path = _write_list(tmp_path, [("a", "canon")])

    def explode(*args, **kwargs):  # pragma: no cover
        raise AssertionError("this runtime must not be built on this path")

    # --dry-run: neither runtime may be constructed.
    monkeypatch.setattr(cli, "build_production_runtime", explode)
    monkeypatch.setattr(cli, "build_local_runtime", explode)
    assert (
        cli.main(
            [
                "ingest-foundational",
                "--dry-run",
                "--list",
                str(path),
                "--ledger",
                str(tmp_path / "l1.jsonl"),
            ]
        )
        == 0
    )

    # --local: the LOCAL runtime is the one the ingest actually uses.
    local = _Runtime(_Pipeline())
    monkeypatch.setattr(cli, "build_local_runtime", lambda: local)
    assert (
        cli.main(
            [
                "--local",
                "ingest-foundational",
                "--list",
                str(path),
                "--ledger",
                str(tmp_path / "l2.jsonl"),
            ]
        )
        == 0
    )
    assert local.pipeline.seen == ["a"]


def test_cli_production_path_checks_corpus_build_preconditions(tmp_path, monkeypatch) -> None:
    """ingest-foundational writes a third of the corpus, so it must refuse under the same
    preconditions trigger-full-rebuild refuses under — discovering a wrong embedding model
    after the 1.5-hour run costs the whole ledger."""
    from docsuri_ingestion import cli

    called = []
    monkeypatch.setattr(cli, "validate_corpus_build_settings", lambda settings: called.append(True))
    monkeypatch.setattr(cli, "build_production_runtime", lambda settings: _Runtime(_Pipeline()))
    # GROBID is probed before the runtime is built (so a down one costs no model loading); this
    # run is arXiv-only, so a miss is a warning rather than a stop.
    monkeypatch.setattr(cli, "probe_grobid", lambda settings, *, required: None)
    path = _write_list(tmp_path, [("a", "canon")])
    assert (
        cli.main(
            [
                "ingest-foundational",
                "--list",
                str(path),
                "--ledger",
                str(tmp_path / "l.jsonl"),
            ]
        )
        == 0
    )
    assert called == [True]


def test_metadata_is_fetched_in_bulk_and_handed_to_the_pipeline(tmp_path, wired):
    """The whole point: one metadata request per chunk, not one per paper.

    arXiv rate-limits by IP, and the per-paper burst is what trips it — a 20-paper trial walked
    one at a time put ~100 requests through and left the source refusing us for hours. If this
    regresses to per-paper fetching nothing fails; the run just gets throttled off the source
    partway through, which is why it is pinned here.
    """
    rows = [(f"24{i:02d}.0000{i % 10}", "canon") for i in range(5)]
    arxiv = _Arxiv()
    pipeline = wired(_Pipeline(), arxiv)
    rc = ingest_foundational(
        list_path=str(_write_list(tmp_path, rows)),
        ledger_path=str(tmp_path / "ledger.jsonl"),
    )
    assert rc == 0
    assert arxiv.calls == [[aid for aid, _ in rows]]
    # Every job carries its metadata, so ingest_one takes the "already fetched" branch.
    assert all(payload is not None for payload in pipeline.metadata_seen)
    assert [p["arxivRef"] for p in pipeline.metadata_seen] == [aid for aid, _ in rows]


def test_bulk_fetch_is_chunked_so_the_ledger_advances_during_a_long_run(tmp_path, wired):
    """Chunked rather than prefetched whole. Licence enrichment behind the batch is still one
    request per paper, so a single up-front fetch would spend over an hour before writing the
    first ledger line — and lose all of it on a crash."""
    rows = [(f"2400.{i:05d}", "canon") for i in range(METADATA_CHUNK + 3)]
    arxiv = _Arxiv()
    wired(_Pipeline(), arxiv)
    ingest_foundational(
        list_path=str(_write_list(tmp_path, rows)),
        ledger_path=str(tmp_path / "ledger.jsonl"),
    )
    assert [len(call) for call in arxiv.calls] == [METADATA_CHUNK, 3]


def test_a_failed_bulk_fetch_falls_back_to_per_paper_instead_of_ending_the_run(tmp_path, wired):
    """The batch is an optimisation, not a dependency — losing it must cost speed, not papers."""
    rows = [("2401.00001", "canon"), ("2401.00002", "canon")]
    arxiv = _Arxiv(raises=RuntimeError("arXiv down"))
    pipeline = wired(_Pipeline(), arxiv)
    rc = ingest_foundational(
        list_path=str(_write_list(tmp_path, rows)),
        ledger_path=str(tmp_path / "ledger.jsonl"),
    )
    assert rc == 0
    assert pipeline.seen == [aid for aid, _ in rows]
    # No metadata on the job → ingest_one fetches it itself, the pre-batch behaviour.
    assert pipeline.metadata_seen == [None, None]


def test_a_paper_missing_from_the_batch_still_gets_ingested(tmp_path, wired):
    """A withdrawn or mistyped id simply has no Atom entry. It must fall through to its own
    fetch — where the real error surfaces — rather than be silently dropped from the run."""
    rows = [("2401.00001", "canon"), ("2401.99999", "canon")]
    arxiv = _Arxiv(known={"2401.00001"})
    pipeline = wired(_Pipeline(), arxiv)
    ingest_foundational(
        list_path=str(_write_list(tmp_path, rows)),
        ledger_path=str(tmp_path / "ledger.jsonl"),
    )
    assert pipeline.seen == [aid for aid, _ in rows]
    assert pipeline.metadata_seen[0] is not None
    assert pipeline.metadata_seen[1] is None


def test_a_collapsing_run_aborts_instead_of_burning_the_rest(tmp_path, wired) -> None:
    """The gate that exists because a run kept going for five and a half hours after it stopped
    producing anything.

    When Bedrock's daily token quota ran out mid-batch (2026-08-14), papers still fetched from
    arXiv and rendered their page crops, then died at the embed step: 490 papers' worth of work,
    nothing indexed, and every one of them written to the ledger as `failed` so recovering them
    costs the parse a second time. ``MAX_FAILURE_RATIO`` could not help — it only judges a run
    that has finished.
    """
    boom = RetriableIngestionError(
        "embed down", reason=FailureReason.DEPENDENCY_UNAVAILABLE, stage="embed"
    )
    rows = [(f"p{i}", "canon") for i in range(400)]
    # Fails everything after a healthy opening stretch — the shape a quota exhaustion has.
    failures = {f"p{i}": boom for i in range(20, 400)}
    pipeline = wired(_Pipeline(failures))

    rc = ingest_foundational(
        list_path=str(_write_list(tmp_path, rows)), ledger_path=str(tmp_path / "l.jsonl")
    )

    assert rc == 1
    # Aborted within roughly a window of the collapse rather than walking the remaining 380.
    assert len(pipeline.seen) < 150, f"kept going for {len(pipeline.seen)} papers"


def test_a_bad_opening_stretch_does_not_abort_a_healthy_run(tmp_path, wired) -> None:
    """A run can open badly — several dud papers early — without the batch being doomed.

    The window gate waits for a full window before it judges, so an opening cluster is diluted by
    the papers that follow rather than read as a collapse. (Failures are scattered, not
    consecutive: an unbroken run of a dozen is a dead dependency, and the other gate catches it.)
    """
    boom = PermanentIngestionError("gone", reason=FailureReason.FETCH_FAILURE, stage="fetch")
    rows = [(f"p{i}", "canon") for i in range(RECENT_WINDOW * 2)]
    # Half of the first twenty fail, alternating — a rough opening, never a dead dependency.
    failures = {f"p{i}": boom for i in range(20) if i % 2 == 0}
    pipeline = wired(_Pipeline(failures))

    ingest_foundational(
        list_path=str(_write_list(tmp_path, rows)), ledger_path=str(tmp_path / "l.jsonl")
    )

    assert len(pipeline.seen) == len(rows), "an early cluster aborted an otherwise healthy run"


def test_a_run_failing_below_the_limit_is_left_alone(tmp_path, wired) -> None:
    """Scattered failures are normal — a withdrawn paper, a 404, a bad PDF. Only a collapse is a
    reason to stop, so the limit is a majority rather than a whiff."""
    boom = PermanentIngestionError("gone", reason=FailureReason.FETCH_FAILURE, stage="fetch")
    rows = [(f"p{i}", "canon") for i in range(200)]
    # Just under the limit, spread evenly so every window sees the same rate.
    stride = int(1 / (RECENT_FAILURE_LIMIT - 0.1))
    failures = {f"p{i}": boom for i in range(200) if i % stride}
    pipeline = wired(_Pipeline(failures))

    ingest_foundational(
        list_path=str(_write_list(tmp_path, rows)), ledger_path=str(tmp_path / "l.jsonl")
    )

    assert len(pipeline.seen) == len(rows)


def test_redo_reingests_papers_the_ledger_calls_done(tmp_path, wired) -> None:
    """A paper that succeeded under an older parser or chunker is not "done" in any useful sense.

    When the chunk cap went 128 -> 512, the 217 papers that had been truncated were all recorded
    as NEW, so ``--retry-failed`` could not see them and they would have stayed half-indexed
    forever. The obvious workaround — deleting their lines from the ledger — is what this exists
    to avoid: the ledger is append-only so a crash cannot corrupt it, and hand-editing puts the
    whole resume record one slip away from being lost.
    """
    rows = [("p1", "canon"), ("p2", "canon"), ("p3", "canon")]
    ledger = tmp_path / "l.jsonl"
    ledger.write_text(
        "".join(
            json.dumps({"arxiv_id": aid, "bucket": "canon", "outcome": "NEW"}) + "\n"
            for aid, _ in rows
        ),
        encoding="utf-8",
    )
    redo = tmp_path / "redo.txt"
    redo.write_text("p1\np3\n", encoding="utf-8")
    pipeline = wired(_Pipeline())

    ingest_foundational(
        list_path=str(_write_list(tmp_path, rows)),
        ledger_path=str(ledger),
        redo_path=str(redo),
    )

    assert pipeline.seen == ["p1", "p3"], "redo did not override the ledger's NEW"
    # The ledger is only appended to — the original NEW lines survive.
    assert ledger.read_text(encoding="utf-8").count('"arxiv_id": "p1"') == 2


def test_redo_list_ignores_comments_and_blank_lines(tmp_path) -> None:
    """The list is produced by a query and then read by a human before it costs a batch run, so it
    has to survive being annotated."""
    path = tmp_path / "redo.txt"
    path.write_text("# 상한 128에 걸린 논문\n1706.07269  # 블록 309개\n\n2103.00020\n", "utf-8")

    assert read_redo(path) == {"1706.07269", "2103.00020"}


def test_a_dead_dependency_stops_within_a_dozen_papers(tmp_path, wired) -> None:
    """A total collapse needs no sample, and the rolling window is far too slow for one.

    When the Postgres container died mid-run (2026-08-15 — a Docker daemon restart took all six
    containers down at once) every paper failed instantly. The 50-paper window would have burned
    50 of them to learn what the first dozen already said, and each one costs an arXiv fetch and a
    parse before it dies.
    """
    boom = RetriableIngestionError(
        "db gone", reason=FailureReason.DEPENDENCY_UNAVAILABLE, stage="control_plane"
    )
    rows = [(f"p{i}", "canon") for i in range(200)]
    pipeline = wired(_Pipeline(dict.fromkeys((f"p{i}" for i in range(200)), boom)))

    rc = ingest_foundational(
        list_path=str(_write_list(tmp_path, rows)), ledger_path=str(tmp_path / "l.jsonl")
    )

    assert rc == 1
    assert len(pipeline.seen) <= CONSECUTIVE_FAILURE_LIMIT + 2, (
        f"burned {len(pipeline.seen)} papers on a dependency that was simply down"
    )


def test_scattered_failures_never_trip_the_consecutive_gate(tmp_path, wired) -> None:
    """The reasons a single paper fails — a 404, no ar5iv build, a blocked licence — are
    independent of one another, so they do not queue up. Only a shared cause does."""
    boom = PermanentIngestionError("gone", reason=FailureReason.FETCH_FAILURE, stage="fetch")
    rows = [(f"p{i}", "canon") for i in range(120)]
    # Every third paper fails: long runs of failure are impossible, and the window rate (33%)
    # stays under RECENT_FAILURE_LIMIT.
    pipeline = wired(_Pipeline({f"p{i}": boom for i in range(120) if i % 3 == 0}))

    ingest_foundational(
        list_path=str(_write_list(tmp_path, rows)), ledger_path=str(tmp_path / "l.jsonl")
    )

    assert len(pipeline.seen) == len(rows)


def test_skip_stage_holds_back_failures_from_a_deliberately_down_dependency(
    tmp_path, wired
) -> None:
    """Not every recorded failure is worth retrying.

    Half of the ⑧-2 retry set had died on the embed quota (back now, so worth a retry) and half on
    GROBID (still deliberately down on a box where it and Docling cannot both fit). Retrying the
    second half re-fetches and re-parses papers certain to fail again — and a long enough run of
    them trips the collapse gate for a dependency nobody expected to be up.
    """
    rows = [("quota", "canon"), ("grobid", "canon"), ("fresh", "canon")]
    ledger = tmp_path / "l.jsonl"
    ledger.write_text(
        json.dumps(
            {"arxiv_id": "quota", "outcome": "failed:retriable:DEPENDENCY_UNAVAILABLE:embed"}
        )
        + "\n"
        + json.dumps(
            {"arxiv_id": "grobid", "outcome": "failed:retriable:DEPENDENCY_UNAVAILABLE:grobid"}
        )
        + "\n",
        encoding="utf-8",
    )
    pipeline = wired(_Pipeline())

    ingest_foundational(
        list_path=str(_write_list(tmp_path, rows)),
        ledger_path=str(ledger),
        retry_failed=True,
        skip_stages=("grobid",),
    )

    assert pipeline.seen == ["quota", "fresh"], "a GROBID-stage failure was retried anyway"


def test_a_stageless_legacy_row_is_never_skipped(tmp_path, wired) -> None:
    """Rows written before the stage was recorded have no stage. An unknown stage must not be
    treated as a skippable one — that would quietly drop papers from a retry run."""
    rows = [("old", "canon")]
    ledger = tmp_path / "l.jsonl"
    ledger.write_text(
        json.dumps({"arxiv_id": "old", "outcome": "failed:retriable:DEPENDENCY_UNAVAILABLE"})
        + "\n",
        encoding="utf-8",
    )
    pipeline = wired(_Pipeline())

    ingest_foundational(
        list_path=str(_write_list(tmp_path, rows)),
        ledger_path=str(ledger),
        retry_failed=True,
        skip_stages=("grobid", "embed"),
    )

    assert pipeline.seen == ["old"]


def test_a_run_with_nothing_to_do_pays_no_probe(tmp_path, monkeypatch) -> None:
    """The pre-flight costs a billed embed call and up to a 10s GROBID timeout, so it belongs
    AFTER the ledger filter — a resumed run whose ledger is already complete should learn that for
    free."""
    from docsuri_ingestion import cli, foundational

    def explode(*args, **kwargs):  # pragma: no cover - must not be called
        raise AssertionError("a run with no papers must not probe dependencies")

    monkeypatch.setattr(foundational, "preflight_dependencies", explode)
    monkeypatch.setattr(cli, "validate_corpus_build_settings", lambda settings: None)
    monkeypatch.setattr(cli, "build_production_runtime", lambda settings: _Runtime(_Pipeline()))
    monkeypatch.setattr(cli, "probe_grobid", lambda settings, *, required: None)

    ledger = tmp_path / "l.jsonl"
    ledger.write_text(json.dumps({"arxiv_id": "a", "outcome": "NEW"}) + "\n", encoding="utf-8")
    path = _write_list(tmp_path, [("a", "canon")])

    assert cli.main(["ingest-foundational", "--list", str(path), "--ledger", str(ledger)]) == 0


def test_the_module_entry_point_delegates_to_the_cli(tmp_path, monkeypatch) -> None:
    """``python -m docsuri_ingestion.foundational`` is in this module's own docstring, and it used
    to call ``ingest_foundational`` directly — skipping the pre-flight checks and ``--local``, and
    re-declaring every flag in a second place that had already drifted."""
    from docsuri_ingestion import cli, foundational

    seen: list[list[str]] = []
    monkeypatch.setattr(cli, "main", lambda argv: seen.append(argv) or 0)

    assert foundational.main(["--dry-run", "--limit", "3"]) == 0
    assert seen == [["ingest-foundational", "--dry-run", "--limit", "3"]]
