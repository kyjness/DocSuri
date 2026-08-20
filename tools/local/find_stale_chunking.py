"""색인된 청크가 현행 청커의 결과와 다른 논문을 골라 `--ids` 목록으로 낸다.

청커 설정이 바뀌면 코퍼스 일부만 낡는다. "언제 수집됐나"로 어림잡으면 경계가 흐려지고
(같은 실행 중에 코드가 바뀌었을 수도 있다) 재임베딩을 필요 이상으로 하게 된다. 그래서
논문마다 저장된 doc-model에 현행 청커를 돌려 **나올 청크 수**를 구하고, 색인에 실제로 들어
있는 수와 다른 것만 고른다. 청킹은 doc-model의 순수 함수이므로 이 대조가 곧 판정이다.

doc-model은 S3 API로 읽는다 — 미러 파일은 s3proxy가 root로 쓴다. 임베딩은 하지 않으므로
쿼터를 쓰지 않는다.

    uv run python ../tools/local/find_stale_chunking.py --out ../reports/restale.txt
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ingestion" / "src"))

from docsuri_ingestion.adapters.aws import (  # noqa: E402
    S3DocModelStore,
    build_opensearch_client,
    build_s3_client,
)
from docsuri_ingestion.processors import Chunker  # noqa: E402
from docsuri_ingestion.settings import IngestionSettings  # noqa: E402


def _indexed_chunk_counts(client, index: str) -> dict[str, int]:
    """paperId → 색인된 청크 수. composite로 걷어서 terms 크기 상한에 걸리지 않는다."""
    counts: dict[str, int] = {}
    after: dict | None = None
    while True:
        sources = [{"p": {"terms": {"field": "paperId"}}}]
        agg: dict = {"composite": {"size": 1000, "sources": sources}}
        if after:
            agg["composite"]["after"] = after
        body = {"size": 0, "aggs": {"papers": agg}}
        result = client.search(index=index, body=body)["aggregations"]["papers"]
        for bucket in result["buckets"]:
            counts[bucket["key"]["p"]] = bucket["doc_count"]
        after = result.get("after_key")
        if not after:
            return counts


def _latest_versions(s3, bucket: str, prefix: str = "doc-model") -> dict[str, int]:
    latest: dict[str, int] = {}
    root = f"{prefix.strip('/')}/"
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=root):
        for obj in page.get("Contents", ()):
            paper_id, _, name = obj["Key"][len(root) :].partition("/")
            stem = name.removesuffix(".json")
            if paper_id and stem.startswith("v") and stem[1:].isdigit():
                latest[paper_id] = max(latest.get(paper_id, 0), int(stem[1:]))
    return latest


def main() -> int:
    settings = IngestionSettings.from_env()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--endpoint", default=settings.opensearch_endpoint or "http://localhost:9200")
    parser.add_argument("--index", default=settings.opensearch_index)
    parser.add_argument("--out", required=True, help="낡은 논문 id를 적을 파일")
    args = parser.parse_args()

    client = build_opensearch_client(endpoint=args.endpoint)
    s3 = build_s3_client()
    bucket = settings.s3_bucket or ""
    store = S3DocModelStore(bucket=bucket, kms_key_id=None)
    chunker = Chunker()

    indexed = _indexed_chunk_counts(client, args.index)
    versions = _latest_versions(s3, bucket)
    print(f"[plan] 색인 {len(indexed)}편 · doc-model {len(versions)}편")

    stale: list[tuple[str, int, int]] = []
    fresh = missing = 0
    started = time.time()
    for i, (paper_id, count) in enumerate(sorted(indexed.items()), 1):
        version = versions.get(paper_id)
        if version is None:
            missing += 1
            continue
        doc = store.get(paper_id, version)
        if doc is None:
            missing += 1
            continue
        want = len(chunker.chunk_doc_model(doc).chunks)
        if want == count:
            fresh += 1
        else:
            stale.append((paper_id, count, want))
        if i % 200 == 0:
            print(f"[{i}/{len(indexed)}] 낡음 {len(stale)} · 최신 {fresh} · 없음 {missing} "
                  f"({i / max(time.time() - started, 1e-9):.0f} papers/s)")

    out = Path(args.out)
    out.write_text(
        "# 색인 청크 수가 현행 청커의 결과와 다른 논문 (재청킹·재색인 대상)\n"
        + "".join(f"{pid}  # {have} → {want}\n" for pid, have, want in stale),
        encoding="utf-8",
    )
    total = sum(want for _, _, want in stale)
    print(f"\n[done] 낡음 {len(stale)}편 · 최신 {fresh}편 · doc-model 없음 {missing}편")
    print(f"[done] 재임베딩할 청크 {total:,}개 → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
