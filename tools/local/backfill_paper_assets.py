"""Backfill the ``paper_asset`` manifest for the local stack (solo-local-migration).

The AWS deployment is retired. The figure/table/formula crop binaries were mirrored to
``~/data/docsuri-data/s3/assets/<paper>/v<ver>/*.webp``, but the ``paper_asset`` DB rows
that point at them (read by U7 ``RdsS3AssetReader`` to presign the /assets manifest) were
only seeded for a handful of smoke-test papers. Every other paper therefore has an empty
manifest, so the doc-model viewer renders every figure as a ``[그림]`` placeholder even
though the crop exists on disk.

This script rebuilds the rows WITHOUT re-ingestion, treating the mirrored webp objects as
the source of truth for what exists (so a row never points at a missing object — the P8
invariant the ingestion writer also holds). Captions and the structured/page-crop mode are
enriched from the parsed DocModel where available; a crop with no DocModel match still gets
a row (empty caption, page-crop) so it renders.

Row shape mirrors ingestion ``S3RdsAssetStore`` and what ``RdsS3AssetReader.list_assets``
expects:
    asset_id   = <paper>:v<ver>:<type>:<ordinal>   (the webp filename stem)
    object_ref = s3://<bucket>/assets/<paper>/v<ver>/<asset_id>.webp
    source_mode ∈ {structured, page-crop}   type ∈ {figure, table, formula}
Write is per (paper, version): DELETE then INSERT, so re-runs are idempotent.

Run (repo root; local Postgres up via backend/docker-compose.yml):

    uv run --project backend python tools/local/backfill_paper_assets.py --dry-run
    uv run --project backend python tools/local/backfill_paper_assets.py
    uv run --project backend python tools/local/backfill_paper_assets.py --paper 2101.09868
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import psycopg

_ASSET_TYPES = {"figure", "table", "formula"}


@dataclass(frozen=True)
class AssetRow:
    paper_id: str
    version: int
    asset_id: str
    type: str
    ordinal: int
    source_mode: str
    object_ref: str
    caption: str
    section_ref: str | None


def _load_dotenv(repo_root: Path) -> dict[str, str]:
    """Parse repo-root ``.env`` into a dict (does not mutate os.environ).

    ``dev.sh`` sources ``.env`` for the servers, but this tool runs standalone, so read the
    same file directly. Simple ``KEY=VALUE`` lines only — comments and blanks skipped, quotes
    stripped. Enough for ``DATABASE_URL`` / ``DOCSURI_S3_BUCKET``.
    """
    env: dict[str, str] = {}
    path = repo_root / ".env"
    if not path.exists():
        return env
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def _index_docmodel(doc: dict) -> dict[str, dict]:
    """Map assetId → {caption, section_ref} from a parsed DocModel.

    Only blocks carrying an ``assetRef`` are indexed; an assetId present here came from a
    figure/table block the parser attached a structured reference to (→ source_mode
    ``structured``). Crops with no entry fall back to ``page-crop`` at the call site.
    """
    out: dict[str, dict] = {}

    def walk(sections: list | None) -> None:
        for section in sections or []:
            sid = section.get("id")
            for block in section.get("blocks") or []:
                ref = block.get("assetRef")
                if isinstance(ref, dict) and ref.get("assetId"):
                    out[ref["assetId"]] = {
                        "caption": block.get("caption") or ref.get("caption") or "",
                        "section_ref": sid,
                    }
            walk(section.get("sections"))

    walk(doc.get("sections"))
    return out


def _docmodel_asset_ids(mirror: Path, paper_id: str, version: int) -> tuple[dict[str, dict], set[str]]:
    """Return (assetId→meta index, all referenced assetIds) for a paper's DocModel, or empty."""
    path = mirror / "doc-model" / paper_id / f"v{version}.json"
    if not path.exists():
        return {}, set()
    try:
        doc = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[warn] {paper_id}: unreadable doc-model ({exc}) — captions/mode default", file=sys.stderr)
        return {}, set()
    index = _index_docmodel(doc)
    return index, set(index)


def _rows_for_paper(
    mirror: Path, paper_dir: Path, bucket: str
) -> tuple[list[AssetRow], list[str]]:
    """Build manifest rows from the webp crops under a paper dir. Returns (rows, warnings)."""
    rows: list[AssetRow] = []
    warnings: list[str] = []
    paper_id = paper_dir.name
    for ver_dir in sorted(paper_dir.iterdir()):
        if not ver_dir.is_dir() or not ver_dir.name.startswith("v"):
            continue
        try:
            version = int(ver_dir.name[1:])
        except ValueError:
            warnings.append(f"{paper_id}: skipped non-versioned dir {ver_dir.name!r}")
            continue
        index, referenced = _docmodel_asset_ids(mirror, paper_id, version)
        present: set[str] = set()
        for webp in sorted(ver_dir.glob("*.webp")):
            asset_id = webp.stem
            prefix, _, tail = asset_id.rpartition(":")
            head, _, type_ = prefix.rpartition(":")
            if not tail.isdigit() or type_ not in _ASSET_TYPES:
                warnings.append(f"{paper_id}: unparseable asset filename {webp.name!r} — skipped")
                continue
            present.add(asset_id)
            # object_ref must be the exact stored object key so the presign resolves it.
            key = webp.relative_to(mirror).as_posix()
            meta = index.get(asset_id)
            rows.append(
                AssetRow(
                    paper_id=paper_id,
                    version=version,
                    asset_id=asset_id,
                    type=type_,
                    ordinal=int(tail),
                    source_mode="structured" if meta is not None else "page-crop",
                    object_ref=f"s3://{bucket}/{key}",
                    caption=(meta or {}).get("caption", ""),
                    section_ref=(meta or {}).get("section_ref"),
                )
            )
        # DocModel references a crop we have no object for (e.g. figure:3/6): can't backfill —
        # a manifest row must never point at a missing object. Surface it; needs re-ingestion.
        missing = referenced - present
        if missing:
            warnings.append(
                f"{paper_id} v{version}: {len(missing)} referenced crop(s) missing on disk "
                f"(needs re-ingestion): {', '.join(sorted(missing))}"
            )
    return rows, warnings


_INSERT = (
    "INSERT INTO paper_asset "
    "(paper_id, version, asset_id, type, ordinal, source_mode, object_ref, caption, section_ref, bbox) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NULL)"
)


def _write_paper(conn: psycopg.Connection, paper_id: str, rows: list[AssetRow]) -> None:
    """Idempotent (paper, version) replace: delete existing rows, insert rebuilt ones."""
    versions = {r.version for r in rows}
    with conn.cursor() as cur:
        for version in versions:
            cur.execute(
                "DELETE FROM paper_asset WHERE paper_id = %s AND version = %s",
                (paper_id, version),
            )
        cur.executemany(
            _INSERT,
            [
                (
                    r.paper_id,
                    r.version,
                    r.asset_id,
                    r.type,
                    r.ordinal,
                    r.source_mode,
                    r.object_ref,
                    r.caption,
                    r.section_ref,
                )
                for r in rows
            ],
        )


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    dotenv = _load_dotenv(repo_root)

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mirror", default=str(Path.home() / "data/docsuri-data/s3"))
    parser.add_argument("--dsn", default=dotenv.get("DATABASE_URL"), help="Postgres DSN (default: .env DATABASE_URL)")
    parser.add_argument("--bucket", default=dotenv.get("DOCSURI_S3_BUCKET", "docsuri"))
    parser.add_argument("--paper", default=None, help="backfill only this bare paper id")
    parser.add_argument("--dry-run", action="store_true", help="report the plan; write nothing")
    args = parser.parse_args()

    mirror = Path(args.mirror).expanduser()
    assets_dir = mirror / "assets"
    if not assets_dir.is_dir():
        print(f"assets mirror not found: {assets_dir}", file=sys.stderr)
        return 2
    if not args.dry_run and not args.dsn:
        print("no DSN (pass --dsn or set DATABASE_URL in .env)", file=sys.stderr)
        return 2

    paper_dirs = [
        d
        for d in sorted(assets_dir.iterdir())
        if d.is_dir() and (args.paper is None or d.name == args.paper)
    ]
    if not paper_dirs:
        print(f"no papers matched under {assets_dir}" + (f" (--paper {args.paper})" if args.paper else ""))
        return 0
    print(f"[plan] {len(paper_dirs)} paper(s) (mirror: {mirror}, bucket: {args.bucket})")

    conn = None if args.dry_run else psycopg.connect(args.dsn)
    total_rows = papers_written = 0
    all_warnings: list[str] = []
    try:
        for paper_dir in paper_dirs:
            rows, warnings = _rows_for_paper(mirror, paper_dir, args.bucket)
            all_warnings.extend(warnings)
            if not rows:
                continue
            by_type: dict[str, int] = {}
            for r in rows:
                by_type[r.type] = by_type.get(r.type, 0) + 1
            summary = " ".join(f"{k}={v}" for k, v in sorted(by_type.items()))
            if args.dry_run:
                print(f"[dry-run] {paper_dir.name}: {len(rows)} rows ({summary})")
            else:
                _write_paper(conn, paper_dir.name, rows)
                conn.commit()
                print(f"[write] {paper_dir.name}: {len(rows)} rows ({summary})")
            total_rows += len(rows)
            papers_written += 1
    finally:
        if conn is not None:
            conn.close()

    for w in all_warnings:
        print(f"[warn] {w}", file=sys.stderr)
    verb = "planned" if args.dry_run else "written"
    print(f"[done] {papers_written} paper(s), {total_rows} rows {verb}; {len(all_warnings)} warning(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
