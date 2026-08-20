"""저장된 doc-model을 현행 파서로 다시 만들고, 그림·표 자산도 다시 뽑는다.

**왜 인제스천 재실행이 아니라 별도 도구인가.** 파서가 바뀌어도 논문은 그대로다. 중복 판정은
논문 지문을 보므로 `--redo`로 되돌려도 파싱 전에 `DUPLICATE`로 끊긴다(실측: 3편 전건). 그건
중복 판정의 결함이 아니라 그 판정이 답하는 질문이 다르기 때문이다 — "이 논문이 바뀌었나"와
"우리 산출물이 낡았나"는 별개다.

임베딩은 하지 않는다. 파서 수정으로 청크 **텍스트**는 거의 바뀌지 않는다(실측 2309.12307:
청크 56→56개, 56개 중 50개가 글자까지 동일, 전체 45,983→45,977자). 바뀌는 것은 블록의
타입과 assetRef이고, 그건 화면이 읽는 doc-model 쪽이다. 그래서 쿼터를 쓰지 않는다.

    uv run python ../tools/local/rebuild_docmodels.py --ids ../reports/ids.txt
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ingestion" / "src"))

from docsuri_ingestion.domain.assets import FigureSpec  # noqa: E402
from docsuri_ingestion.runtime import build_production_runtime  # noqa: E402
from docsuri_ingestion.settings import IngestionSettings  # noqa: E402


def _read_ids(path: Path) -> list[str]:
    return [
        candidate
        for line in path.read_text(encoding="utf-8").splitlines()
        if (candidate := line.split("#", 1)[0].strip())
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ids", required=True, help="paperId 목록 파일 (한 줄에 하나, # 주석)")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true", help="빌드만; 자산 추출·저장 없음")
    args = parser.parse_args()

    ids_path = Path(args.ids)
    if not ids_path.exists():
        print(f"--ids 파일이 없다: {ids_path}", file=sys.stderr)
        return 2
    ids = _read_ids(ids_path)[: args.limit]
    if not ids:
        print(f"--ids {ids_path}: 지정된 id가 0개", file=sys.stderr)
        return 2

    settings = IngestionSettings.from_env()
    runtime = build_production_runtime(settings)
    pipeline = runtime.pipeline
    builder = pipeline._doc_model_builder  # noqa: SLF001 — 일회성 도구, 배선을 그대로 빌려 쓴다
    if builder is None:
        print("doc-model 빌더가 배선되지 않았다 (DOCSURI_S3_BUCKET 확인)", file=sys.stderr)
        return 2

    print(f"[plan] {len(ids)}편 · 파서 {builder._parser_version}")  # noqa: SLF001
    rebuilt = cached = failed = assets = 0
    started = time.time()
    for i, paper_id in enumerate(ids, 1):
        try:
            metadata = runtime.arxiv.fetch_metadata(paper_id)
            specs: list[FigureSpec] = []
            result = builder.build(metadata, figure_specs=specs)
            if getattr(result, "status", "") != "ok":
                failed += 1
                print(f"[fail] {paper_id}: {getattr(result, 'status', '?')}")
                continue
            if getattr(result, "cached", False):
                # 캐시가 신선하다 = 이 논문은 이미 현행 파서로 만들어져 있다.
                cached += 1
                continue
            rebuilt += 1
            if args.dry_run:
                continue
            # 새로 생긴 그림 블록에는 아직 크롭이 없다. 인제스천이 색인 뒤에 하는 것과 같은
            # 단계를, 같은 어댑터로 돌린다.
            paper = _PaperRef(paper_id=metadata.paper_id, version=metadata.version)
            before = len(specs)
            pipeline._store_assets_best_effort(  # noqa: SLF001
                paper, metadata, tuple(specs)
            )
            assets += before
        except Exception as exc:  # noqa: BLE001 — 한 편이 전체를 멈추지 않는다
            failed += 1
            print(f"[fail] {paper_id}: {type(exc).__name__}: {exc}")
        if i % 25 == 0 or i == len(ids):
            rate = i / max(time.time() - started, 1e-9)
            print(f"[{i}/{len(ids)}] 재빌드 {rebuilt} · 캐시신선 {cached} · 실패 {failed} "
                  f"({rate:.1f} papers/s)")

    print(f"[done] 재빌드 {rebuilt} · 캐시신선 {cached} · 실패 {failed} · 그림스펙 {assets}")
    return 0 if failed == 0 else 1


class _PaperRef:
    """``_store_assets_best_effort``가 읽는 두 필드만 갖춘 최소 객체."""

    __slots__ = ("paper_id", "version")

    def __init__(self, paper_id: str, version: int) -> None:
        self.paper_id = paper_id
        self.version = version


if __name__ == "__main__":
    raise SystemExit(main())
