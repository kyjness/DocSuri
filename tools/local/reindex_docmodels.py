"""Reindex the downloaded doc-model mirror into a local OpenSearch (solo-local-migration §3).

The AWS deployment is retired; the OpenSearch index was not backed up, but the parsed
DocModels were (``~/data/docsuri-data/s3/doc-model/``). This script rebuilds the search
index from them, swapping the embedding space to OpenAI (see the adapter docstrings for the
same-space invariant with the discovery reader):

    doc-model JSON → Chunker.chunk_doc_model → OpenAIEmbeddingPort → IndexRecordAssembler
                   → OpenSearchVectorIndex.bulk_upsert   (mapping: shared papers_index_body)

Authors/categories/year are not in the DocModel; they are batch-fetched from the arXiv
export API (100 ids/request, 3s politeness delay) and cached to a JSON file so re-runs are
free. Non-arXiv papers (``src-*``) fall back to DocModel meta + placeholders. Resumable:
papers already present in the index are skipped.

Run (repo root; local OpenSearch up via backend/docker-compose.yml):

    export OPENAI_API_KEY=sk-...
    uv run --project ingestion python tools/local/reindex_docmodels.py --limit 3000
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

from docsuri_ingestion.adapters.aws import OpenSearchVectorIndex, build_opensearch_client
from docsuri_ingestion.adapters.openai_embedding import OpenAIEmbeddingPort
from docsuri_ingestion.domain.models import EmbeddingBatch, ParsedPaper
from docsuri_ingestion.processors import Chunker, IndexRecordAssembler
from docsuri_shared.dtos import DocModel
from docsuri_shared.index_spec import papers_index_body
from docsuri_shared.vector_spec import DIMENSIONS

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


def _enumerate_papers(docmodel_dir: Path, limit: int | None) -> list[Path]:
    """Latest-version doc-model JSON per paper, deterministic order."""
    picked: list[Path] = []
    for paper_dir in sorted(docmodel_dir.iterdir()):
        if not paper_dir.is_dir():
            continue
        versions = sorted(
            paper_dir.glob("v*.json"), key=lambda p: int(p.stem[1:]) if p.stem[1:].isdigit() else 0
        )
        if versions:
            picked.append(versions[-1])
        if limit is not None and len(picked) >= limit:
            break
    return picked


def _ensure_index(client, index: str, alias: str, *, embedding_model: str) -> None:
    # Embedding manifest: this rebuild embeds with OpenAI; the discovery reader's space guard
    # verifies provider/model at wiring time (vector-spec §4 same-space invariant).
    embedding_meta = {
        "provider": "openai",
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


def _embed_with_retry(port: OpenAIEmbeddingPort, texts: list[str]) -> list[list[float]]:
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
    parser.add_argument("--mirror", default=str(Path.home() / "data/docsuri-data/s3"))
    parser.add_argument("--endpoint", default="http://localhost:9200")
    parser.add_argument("--index", default="docsuri-corpus-v1")
    parser.add_argument("--alias", default="docsuri-corpus")
    parser.add_argument("--limit", type=int, default=None, help="subset size (omit = full corpus)")
    parser.add_argument("--model", default="text-embedding-3-small")
    parser.add_argument("--dry-run", action="store_true", help="chunk only; no embed/index")
    args = parser.parse_args()

    mirror = Path(args.mirror)
    docmodel_dir = mirror / "doc-model"
    if not docmodel_dir.is_dir():
        print(f"doc-model mirror not found: {docmodel_dir}", file=sys.stderr)
        return 2

    files = _enumerate_papers(docmodel_dir, args.limit)
    print(f"[plan] {len(files)} papers (mirror: {mirror})")

    plain_http = args.endpoint.startswith("http://")
    client = build_opensearch_client(
        endpoint=args.endpoint, use_ssl=not plain_http, verify_certs=not plain_http
    )
    _ensure_index(client, args.index, args.alias, embedding_model=args.model)
    writer = OpenSearchVectorIndex(
        endpoint=args.endpoint, index_name=args.index,
        use_ssl=not plain_http, verify_certs=not plain_http,
    )
    embedder = OpenAIEmbeddingPort(model=args.model)
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
