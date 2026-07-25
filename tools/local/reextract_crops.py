"""Re-extract MISSING figure/table crops for the local mirror — assets only, no re-embedding.

Some papers render a `[그림]` placeholder because the crop WebP was never produced (the doc-model
has the assetRef, but no image). This fills those gaps WITHOUT re-parsing (no @10 doc-model churn)
and WITHOUT touching the search index / embeddings:

  mirror doc-model  ─→ FigureSpec(label=anchorLabel) per figure ordinal (alignment)
  arXiv PDF (re-fetch) ─→ AssetExtractor page-crops each MISSING figure/table by caption number
                       ─→ S3RdsAssetStore: WebP → s3proxy + paper_asset row (ADD only, not replace)

Why this is safe & cheap:
- The extractor (pypdfium2/pdfplumber/Pillow) needs neither GROBID nor Bedrock.
- Rebuilding FigureSpecs from the stored doc-model keeps the extractor's assetIds aligned to the
  existing doc-model blocks (caption-number match), so a recovered crop lands on the right figure.
- We store ONLY assetIds that are currently missing (referenced by the doc-model but absent on
  disk), via _put_object + _upsert_rows — never store_assets(), which would delete the version's
  existing rows first.
- boto3 ≥1.28 auto-uses AWS_ENDPOINT_URL_S3, so writes land in s3proxy (the local mirror).

Run (repo root; local stack up):
  set -a; source .env; set +a
  uv run --project ingestion python tools/local/reextract_crops.py --paper 2101.09868 --dry-run
  uv run --project ingestion python tools/local/reextract_crops.py --paper 2101.09868
  uv run --project ingestion python tools/local/reextract_crops.py --papers-file missing.txt --delay 3
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv(repo_root: Path) -> None:
    """Populate os.environ from repo-root .env (AWS_ENDPOINT_URL_S3 + creds for s3proxy, DATABASE_URL).
    boto3 reads the endpoint/creds from the environment, so they must be set before the S3 client is
    built. Does not overwrite values already exported (a sourced .env wins)."""
    path = repo_root / ".env"
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass
class PaperResult:
    paper_id: str
    targeted: int
    recovered: int
    stored_ids: list[str]
    note: str = ""


def _latest_docmodel(mirror: Path, paper_id: str) -> tuple[dict, int] | None:
    d = mirror / "doc-model" / paper_id
    versions = sorted(d.glob("v*.json"), key=lambda p: int(p.stem[1:]) if p.stem[1:].isdigit() else 0)
    if not versions:
        return None
    try:
        doc = json.loads(versions[-1].read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return doc, int(versions[-1].stem[1:])


def _walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for x in node:
            yield from _walk(x)


def _collect(doc: dict) -> tuple[dict[int, str], set[str]]:
    """Return ({figure ordinal -> anchorLabel}, {all referenced figure/table assetIds})."""
    fig_labels: dict[int, str] = {}
    referenced: set[str] = set()
    for n in _walk(doc):
        if not isinstance(n, dict):
            continue
        ref = n.get("assetRef")
        if isinstance(ref, dict) and ref.get("assetId") and n.get("type") in ("figure", "table"):
            aid = ref["assetId"]
            referenced.add(aid)
            if n["type"] == "figure":
                # Key by the ordinal embedded in the assetId tail (…:figure:<ord>), NOT ref["ordinal"]:
                # the tail is what target/present webp stems carry, and a figure whose assetRef omits a
                # numeric `ordinal` would otherwise be targeted (in `referenced`) yet get no FigureSpec,
                # so it could never be page-cropped (targeted > recovered forever).
                tail = aid.rpartition(":")[2]
                if tail.isdigit():
                    fig_labels[int(tail)] = n.get("anchorLabel") or ""
    return fig_labels, referenced


def _present_webp(mirror: Path, paper_id: str, version: int) -> set[str]:
    d = mirror / "assets" / paper_id / f"v{version}"
    if not d.is_dir():
        return set()
    return {f.stem for f in d.glob("*.webp")}


def _fetch_pdf(arxiv_id: str, timeout: float = 25.0) -> bytes | None:
    import httpx

    from docsuri_ingestion.http_limits import read_capped

    try:
        with (
            httpx.Client(timeout=timeout, follow_redirects=True) as client,
            client.stream("GET", f"https://arxiv.org/pdf/{arxiv_id}") as response,
        ):
            response.raise_for_status()
            return read_capped(response)
    except Exception as exc:  # noqa: BLE001 - missing/oversize source → no recovery this paper
        print(f"[warn] {arxiv_id}: PDF fetch failed ({type(exc).__name__})", file=sys.stderr)
        return None


def _process_paper(paper_id: str, mirror: Path, extractor, store, *, dry_run: bool) -> PaperResult:
    from docsuri_ingestion.adapters.assets import _with_object_ref
    from docsuri_ingestion.domain.assets import FigureSpec

    loaded = _latest_docmodel(mirror, paper_id)
    if loaded is None:
        return PaperResult(paper_id, 0, 0, [], note="no doc-model")
    doc, version = loaded
    fig_labels, referenced = _collect(doc)
    present = _present_webp(mirror, paper_id, version)
    target = referenced - present
    if not target:
        return PaperResult(paper_id, 0, 0, [], note="complete")

    # FigureSpecs indexed by ordinal. Only label the MISSING figures so the extractor page-crops
    # just those (existing figures stay blank → skipped); index gaps stay default (label="").
    max_ord = max(fig_labels) if fig_labels else -1
    specs = [FigureSpec() for _ in range(max_ord + 1)]
    for ordv, label in fig_labels.items():
        aid = f"{paper_id}:v{version}:figure:{ordv}"
        if aid in target:
            specs[ordv] = FigureSpec(src="", label=label)

    pdf = _fetch_pdf(paper_id)
    if pdf is None:
        return PaperResult(paper_id, len(target), 0, [], note="pdf unavailable")

    extracted = extractor.extract(
        paper_id=paper_id, version=version, pdf=pdf, eprint=None, figure_specs=specs
    )
    to_store = [a for a in extracted if a.meta.asset_id in target]
    stored_ids: list[str] = []
    if not dry_run:
        metas = []
        for asset in to_store:
            object_ref = store._put_object(asset)  # noqa: SLF001 - local tool: add-only, not store_assets()
            metas.append(_with_object_ref(asset.meta, object_ref))
        if metas:
            store._upsert_rows(metas)  # noqa: SLF001
    stored_ids = [a.meta.asset_id for a in to_store]
    return PaperResult(paper_id, len(target), len(to_store), stored_ids)


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    _load_dotenv(repo_root)

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mirror", default=str(Path.home() / "data/docsuri-data/s3"))
    parser.add_argument("--dsn", default=os.environ.get("DATABASE_URL"))
    parser.add_argument("--bucket", default=os.environ.get("DOCSURI_S3_BUCKET", "docsuri"))
    parser.add_argument("--paper", default=None, help="single bare paper id (pilot)")
    parser.add_argument("--papers-file", default=None, help="file with one bare paper id per line")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--delay", type=float, default=3.0, help="arXiv politeness delay between papers (s)")
    parser.add_argument("--dry-run", action="store_true", help="fetch+extract+report; no S3/DB writes")
    parser.add_argument("--webp-quality", type=int, default=80)
    args = parser.parse_args()

    mirror = Path(args.mirror).expanduser()
    if not (mirror / "doc-model").is_dir():
        print(f"doc-model mirror not found: {mirror}", file=sys.stderr)
        return 2
    if not args.dry_run and not args.dsn:
        print("no DSN (pass --dsn or set DATABASE_URL in .env)", file=sys.stderr)
        return 2
    if not args.dry_run and not os.environ.get("AWS_ENDPOINT_URL_S3"):
        print("AWS_ENDPOINT_URL_S3 not set — writes would target real S3, not s3proxy. Source .env.",
              file=sys.stderr)
        return 2

    papers: list[str] = []
    if args.paper:
        papers = [args.paper]
    elif args.papers_file:
        papers = [ln.strip() for ln in Path(args.papers_file).read_text().splitlines() if ln.strip()]
    else:
        print("specify --paper or --papers-file", file=sys.stderr)
        return 2
    if args.limit:
        papers = papers[: args.limit]

    from docsuri_ingestion.asset_extraction import AssetExtractor, ImageNormalizer

    extractor = AssetExtractor(normalizer=ImageNormalizer(webp_quality=args.webp_quality))
    store = None
    if not args.dry_run:
        from docsuri_ingestion.adapters.assets import S3RdsAssetStore

        store = S3RdsAssetStore(bucket=args.bucket, control_plane_dsn=args.dsn)

    print(f"[plan] {len(papers)} paper(s) | mirror={mirror} | dry_run={args.dry_run}")
    results: list[PaperResult] = []
    for i, pid in enumerate(papers):
        try:
            r = _process_paper(pid, mirror, extractor, store, dry_run=args.dry_run)
        except Exception as exc:  # noqa: BLE001 - one bad paper must not abort the run
            r = PaperResult(pid, 0, 0, [], note=f"error: {type(exc).__name__}: {exc}")
        results.append(r)
        verb = "would recover" if args.dry_run else "recovered"
        if r.targeted or r.note not in ("complete", ""):
            print(f"  {pid}: targeted={r.targeted} {verb}={r.recovered}"
                  + (f" [{r.note}]" if r.note else "") + (f" {r.stored_ids}" if r.stored_ids else ""))
        if args.delay and i < len(papers) - 1 and r.note != "complete":
            time.sleep(args.delay)

    targeted = sum(r.targeted for r in results)
    recovered = sum(r.recovered for r in results)
    papers_touched = sum(1 for r in results if r.targeted)
    print(f"\n[done] {papers_touched} paper(s) with gaps | targeted={targeted} "
          f"{'would recover' if args.dry_run else 'recovered'}={recovered} "
          f"({recovered / targeted * 100:.0f}% of gaps)" if targeted else "\n[done] no gaps found")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
