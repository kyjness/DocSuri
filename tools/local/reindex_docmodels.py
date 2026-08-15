"""Reindex the downloaded doc-model mirror into a local OpenSearch (solo-local-migration §3).

The AWS deployment is retired; the OpenSearch index was not backed up, but the parsed
DocModels were. This script rebuilds the search index from them:

    doc-model JSON → Chunker.chunk_doc_model → embedding port → IndexRecordAssembler
                   → OpenSearchVectorIndex.bulk_upsert   (mapping: shared papers_index_body)

THE EMBEDDING PORT COMES FROM THE ENVIRONMENT, exactly as the ingest pipeline picks it
(``DOCSURI_BEDROCK_MODEL_ID``). It used to hardcode the model, which was right for the corpus this
tool was written for and silently wrong for any other: run against the Bedrock-embedded deployment
index it would have written a few hundred papers into a DIFFERENT embedding space, and — worse —
``_ensure_index`` re-stamps the index manifest, so it would have overwritten the very manifest the
reader's space guard uses to catch that. Both sides are 1024-dimensional, so nothing would raise;
the only symptom is those papers quietly never matching a query.

Targets are given, not defaulted. The mirror/index/alias defaults were the local development
corpus, which is not where a deployment rebuild belongs.

Authors/categories/year are not in the DocModel; they are batch-fetched from the arXiv
export API (100 ids/request, 3s politeness delay) and cached to a JSON file so re-runs are
free. Non-arXiv papers (``src-*``) fall back to DocModel meta + placeholders. Resumable:
papers already present in the index are skipped.

Run (repo root; local OpenSearch up via backend/docker-compose.yml):

    set -a; . .env; set +a      # provider, region, credentials, index
    uv run --project ingestion python tools/local/reindex_docmodels.py \\
        --mirror "$DOCSURI_S3_MIRROR" --index "$DOCSURI_OPENSEARCH_INDEX" --ids ids.txt
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

from docsuri_shared.dtos import DocModel
from docsuri_shared.index_spec import papers_index_body
from docsuri_shared.vector_spec import DIMENSIONS

from docsuri_ingestion.adapters.aws import OpenSearchVectorIndex, build_opensearch_client
from docsuri_ingestion.domain.models import EmbeddingBatch, ParsedPaper
from docsuri_ingestion.ports import EmbeddingPort
from docsuri_ingestion.processors import Chunker, IndexRecordAssembler
from docsuri_ingestion.runtime import _embedding_port
from docsuri_ingestion.settings import IngestionSettings

_ARXIV_API = "http://export.arxiv.org/api/query"
_ARXIV_BATCH = 100
_ARXIV_DELAY_S = 3.0  # politeness — same budget the ingestion adapter honours
_ATOM = "{http://www.w3.org/2005/Atom}"


def _is_arxiv_id(paper_id: str) -> bool:
    return not paper_id.startswith(("src-", "userdoc:"))


def _year_from_id(paper_id: str) -> int:
    """YYMM prefix of a new-style arXiv id → year (fallback when metadata is unavailable)."""
    try:
        yy = int(paper_id[:2])
    except ValueError:
        return 2024
    return 1900 + yy if yy >= 91 else 2000 + yy


def _fetch_arxiv_batch(ids: list[str]) -> dict[str, dict]:
    query = urllib.parse.urlencode({"id_list": ",".join(ids), "max_results": len(ids)})
    with urllib.request.urlopen(f"{_ARXIV_API}?{query}", timeout=30) as response:  # noqa: S310
        tree = ET.fromstring(response.read())
    out: dict[str, dict] = {}
    for entry in tree.iter(f"{_ATOM}entry"):
        raw_id = (entry.findtext(f"{_ATOM}id") or "").rsplit("/", 1)[-1]  # 0910.0921v2
        bare = raw_id.split("v")[0]
        if not bare:
            continue
        out[bare] = {
            "authors": [
                a.findtext(f"{_ATOM}name", "").strip()
                for a in entry.iter(f"{_ATOM}author")
                if a.findtext(f"{_ATOM}name")
            ],
            "categories": [
                c.get("term", "")
                for c in entry.iter("{http://www.w3.org/2005/Atom}category")
                if c.get("term")
            ],
            "published": entry.findtext(f"{_ATOM}published", ""),
            "updated": entry.findtext(f"{_ATOM}updated", ""),
        }
    return out


def _load_meta_cache(path: Path) -> dict[str, dict]:
    if path.exists():
        return json.loads(path.read_text())
    return {}


def _resolve_metadata(paper_ids: list[str], cache_path: Path) -> dict[str, dict]:
    """arXiv metadata for every arXiv-style id, via the batch export API + on-disk cache."""
    cache = _load_meta_cache(cache_path)
    missing = [p for p in paper_ids if _is_arxiv_id(p) and p not in cache]
    if missing:
        print(f"[meta] fetching arXiv metadata for {len(missing)} papers "
              f"({(len(missing) + _ARXIV_BATCH - 1) // _ARXIV_BATCH} requests)…")
    for start in range(0, len(missing), _ARXIV_BATCH):
        batch = missing[start : start + _ARXIV_BATCH]
        try:
            cache.update(_fetch_arxiv_batch(batch))
        except Exception as exc:  # noqa: BLE001 — metadata is best-effort; placeholders cover gaps
            print(f"[meta] batch failed ({batch[0]}…): {exc} — placeholders will be used")
        cache_path.write_text(json.dumps(cache))
        time.sleep(_ARXIV_DELAY_S)
    return cache


def _parse_dt(raw: str) -> datetime:
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(UTC)


def _paper_from_doc(doc: DocModel, meta: dict | None) -> ParsedPaper:
    pid, version = doc.meta.paperId, doc.meta.version
    meta = meta or {}
    updated = _parse_dt(meta.get("updated") or meta.get("published") or "")
    published = _parse_dt(meta.get("published") or "")
    year = published.year if meta.get("published") else _year_from_id(pid)
    return ParsedPaper(
        paper_id=pid,
        version=version,
        title=doc.meta.title or pid,
        # Placeholder mirrors the source-record path's "authors or (source,)" fallback —
        # IndexRecord carries a non-empty list either way.
        authors=tuple(meta.get("authors") or ()) or ("Unknown",),
        abstract=getattr(doc.meta, "abstract", "") or doc.meta.title or pid,
        categories=tuple(meta.get("categories") or ()),
        updated_at=updated,
        year=year,
        arxiv_url=f"https://arxiv.org/abs/{pid}v{version}" if _is_arxiv_id(pid) else "",
        full_text=doc.fullText or "",
        license_url="",
        display_arxiv_id=pid if _is_arxiv_id(pid) else "",
    )


def _enumerate_papers(
    docmodel_dir: Path, limit: int | None, only: frozenset[str] = frozenset()
) -> list[Path]:
    """Latest-version doc-model JSON per paper, deterministic order.

    ``only`` restricts to named paper ids — the shape a targeted rebuild needs. Re-chunking a
    known subset (a chunker setting changed, so the stored doc-models are fine but the index rows
    are stale) is not expressible as "the first N papers", and walking the whole corpus to fix
    200 of them re-embeds everything.
    """
    picked: list[Path] = []
    for paper_dir in sorted(docmodel_dir.iterdir()):
        if not paper_dir.is_dir():
            continue
        if only and paper_dir.name not in only:
            continue
        versions = sorted(
            paper_dir.glob("v*.json"), key=lambda p: int(p.stem[1:]) if p.stem[1:].isdigit() else 0
        )
        if versions:
            picked.append(versions[-1])
        if limit is not None and len(picked) >= limit:
            break
    return picked


def _ensure_index(client, index: str, alias: str, *, provider: str, embedding_model: str) -> None:
    # Embedding manifest: stamped with the model THIS run embeds with, so the discovery
    # reader's space guard can verify it at wiring time (vector-spec §4 same-space invariant).
    # It must never be hardcoded — that defeats the guard on any index built with another model,
    # and Cohere v3/v4 are both 1024-dimensional so nothing else would catch the swap.
    embedding_meta = {
        "provider": provider,
        "model": embedding_model,
        "dimensions": DIMENSIONS,
    }
    if not client.indices.exists(index=index):
        client.indices.create(index=index, body=papers_index_body(embedding_meta=embedding_meta))
        print(f"[index] created {index}")
    else:
        # Re-stamp an existing index: a refill embeds with THIS model, so a stale manifest
        # (e.g. the fixture seeder's offline-test stamp, or a legacy stamp-less index) must not
        # make the reader-side guard mis-judge the rebuilt corpus. _meta-only put_mapping is a
        # metadata update — no reindex.
        client.indices.put_mapping(index=index, body={"_meta": {"embedding": embedding_meta}})
        print(f"[index] re-stamped embedding manifest on existing {index}")
    if alias and not client.indices.exists_alias(name=alias):
        client.indices.put_alias(index=index, name=alias)
        print(f"[index] alias {alias} → {index}")


def _already_indexed(client, index: str, paper_id: str) -> bool:
    result = client.count(index=index, body={"query": {"term": {"paperId": paper_id}}})
    return int(result.get("count", 0)) > 0


def _embed_with_retry(port: EmbeddingPort, texts: list[str]) -> list[list[float]]:
    for attempt in range(3):
        try:
            return port.embed_documents(texts)
        except Exception:  # noqa: BLE001 — transient 429/5xx: back off and retry
            if attempt == 2:
                raise
            time.sleep(2.0 * (attempt + 1) ** 2)
    raise RuntimeError("unreachable")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    # Defaults come from the environment, not from the development corpus. The old hardcoded
    # mirror/index pair meant an operator who forgot a flag rebuilt the WRONG corpus.
    settings = IngestionSettings.from_env()
    parser.add_argument("--mirror", default=os.environ.get("DOCSURI_S3_MIRROR"))
    parser.add_argument("--endpoint", default=settings.opensearch_endpoint or "http://localhost:9200")
    parser.add_argument("--index", default=settings.opensearch_index)
    parser.add_argument("--alias", default=settings.opensearch_alias)
    parser.add_argument("--limit", type=int, default=None, help="subset size (omit = full corpus)")
    parser.add_argument(
        "--ids",
        help="이 파일에 적힌 paperId만 재색인한다 (한 줄에 하나, # 뒤는 주석). "
        "청커 설정이 바뀌어 일부 논문만 낡았을 때 쓴다",
    )
    parser.add_argument("--dry-run", action="store_true", help="chunk only; no embed/index")
    args = parser.parse_args()

    if not args.mirror:
        print("--mirror 또는 DOCSURI_S3_MIRROR가 필요하다", file=sys.stderr)
        return 2
    only: frozenset[str] = frozenset()
    if args.ids:
        path = Path(args.ids)
        if not path.exists():
            print(f"--ids 파일이 없다: {path}", file=sys.stderr)
            return 2
        only = frozenset(
            candidate
            for line in path.read_text(encoding="utf-8").splitlines()
            if (candidate := line.split("#", 1)[0].strip())
        )
        if not only:
            print(f"--ids {path}: 지정된 id가 0개", file=sys.stderr)
            return 2
        print(f"[plan] --ids 지정 {len(only)}편만 재색인")

    mirror = Path(args.mirror)
    docmodel_dir = mirror / "doc-model"
    if not docmodel_dir.is_dir():
        print(f"doc-model mirror not found: {docmodel_dir}", file=sys.stderr)
        return 2

    files = _enumerate_papers(docmodel_dir, args.limit, only)
    print(f"[plan] {len(files)} papers (mirror: {mirror} · index: {args.index})")
    if only and len(files) != len(only):
        missing = sorted(only - {f.parent.name for f in files})
        print(f"[plan] doc-model이 없는 id {len(missing)}편: {', '.join(missing[:5])}…")

    # TLS follows the endpoint scheme inside the client factory now — this tool used to be the
    # only caller that got it right, and it got it right by doing exactly that here.
    client = build_opensearch_client(endpoint=args.endpoint)
    # The SAME selection the ingest pipeline makes, so a rebuild lands in the corpus's existing
    # embedding space instead of silently opening a second one.
    embedder = _embedding_port(settings)
    model = settings.bedrock_model_id
    print(f"[embed] bedrock · {model}")
    _ensure_index(
        client,
        args.index,
        args.alias,
        provider="bedrock",
        embedding_model=model or "",
    )
    writer = OpenSearchVectorIndex(endpoint=args.endpoint, index_name=args.index)
    chunker = Chunker()
    assembler = IndexRecordAssembler()

    meta_cache = _resolve_metadata(
        [f.parent.name for f in files], mirror.parent / "arxiv-meta-cache.json"
    )

    done = skipped = failed = 0
    started = time.time()
    for i, path in enumerate(files, 1):
        pid = path.parent.name
        try:
            if _already_indexed(client, args.index, pid):
                skipped += 1
                continue
            doc = DocModel.model_validate_json(path.read_text())
            chunks = chunker.chunk_doc_model(doc)
            if not chunks.chunks:
                skipped += 1
                continue
            paper = _paper_from_doc(doc, meta_cache.get(pid))
            if args.dry_run:
                done += 1
                continue
            vectors = _embed_with_retry(embedder, [c.text for c in chunks.chunks])
            embeddings = EmbeddingBatch(
                chunk_ids=tuple(c.chunk_id for c in chunks.chunks),
                vectors=tuple(tuple(v) for v in vectors),
            )
            writer.bulk_upsert(assembler.assemble(paper, chunks, embeddings))
            done += 1
        except Exception as exc:  # noqa: BLE001 — one bad paper must not kill a long run
            failed += 1
            print(f"[fail] {pid}: {type(exc).__name__}: {exc}")
        if i % 100 == 0 or i == len(files):
            rate = i / max(time.time() - started, 1e-9)
            print(f"[{i}/{len(files)}] indexed={done} skipped={skipped} failed={failed} "
                  f"({rate:.1f} papers/s)")

    print(f"[done] indexed={done} skipped={skipped} failed={failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
