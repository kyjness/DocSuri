"""저장된 doc-model을 현행 파서로 다시 만들고, 그림·표 자산도 다시 뽑는다.

**왜 인제스천 재실행이 아니라 별도 도구인가.** 파서가 바뀌어도 논문은 그대로다. 중복 판정은
논문 지문을 보므로 `--redo`로 되돌려도 파싱 전에 `DUPLICATE`로 끊긴다(실측: 3편 전건). 그건
중복 판정의 결함이 아니라 그 판정이 답하는 질문이 다르기 때문이다 — "이 논문이 바뀌었나"와
"우리 산출물이 낡았나"는 별개다.

임베딩은 하지 않는다. 파서 수정으로 청크 **텍스트**는 거의 바뀌지 않는다(실측 2309.12307:
청크 56→56개, 56개 중 50개가 글자까지 동일, 전체 45,983→45,977자). 바뀌는 것은 블록의
타입과 assetRef이고, 그건 화면이 읽는 doc-model 쪽이다. 그래서 쿼터를 쓰지 않는다.

**두 단(rung)이 있다.** ``--rung html``(기본)은 ar5iv HTML을 다시 받아 파싱한다. ``--rung tei``는
GROBID 단으로 들어온 논문용이다 — ar5iv가 없어 HTML 단으로는 애초에 다시 만들 수 없고, 캐시된
TEI(raw 저장소 tier "tei")와 arXiv PDF로 ``build_from_tei``를 다시 돌린다. GROBID는 부르지
않는다(``DOCSURI_GROBID_CACHE_MODE=only``로 강제). 이 단이 필요한 이유: PDF 단 배치를 GROBID와
메모리를 나눌 수 없어 수식 OCR을 끈 채 돌렸고, 그 doc-model은 현행 파서 버전이면서 수식
LaTeX이 전건 0이다(⑧-2 실측 202편 중 58편). 버전 판정으로는 "같은 파서인데 리더가 꺼져
있었다"를 표현할 수 없으므로 ``force``로 신선도 검사를 건너뛴다.

    uv run python ../tools/local/rebuild_docmodels.py --ids ../reports/ids.txt
    DOCSURI_GROBID_CACHE_MODE=only uv run python ../tools/local/rebuild_docmodels.py \
        --rung tei --ids ../reports/rebuild-formula-targets.txt
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ingestion" / "src"))

from dataclasses import replace  # noqa: E402

from docsuri_shared.dtos import SourceTier  # noqa: E402

from docsuri_ingestion.domain.assets import FigureSpec  # noqa: E402
from docsuri_ingestion.runtime import build_production_runtime  # noqa: E402
from docsuri_ingestion.settings import IngestionSettings  # noqa: E402

# 어댑터의 id_list 한 번 분량과 같게 맞춘다 — 여기서 나눈 한 덩어리가 거기서 요청 하나다.
METADATA_CHUNK = 100
# doc-model 버전을 위에서부터 훑을 상한. arXiv 개정이 이보다 많은 논문은 실질적으로 없다.
_MAX_PROBED_VERSION = 12


def _read_ids(path: Path) -> list[str]:
    return [
        candidate
        for line in path.read_text(encoding="utf-8").splitlines()
        if (candidate := line.split("#", 1)[0].strip())
    ]


def _progress(i: int, total: int, rebuilt: int, cached: int, failed: int, started: float) -> None:
    """25편마다 진행을 찍는다. TEI 단이 `continue`로 빠져나가며 이 출력을 건너뛰는 바람에 58편
    실행이 통째로 무음이었다 — 진행을 보려고 저장된 doc-model의 파일 시각을 세야 했다."""
    if i % 25 and i != total:
        return
    rate = i / max(time.time() - started, 1e-9)
    print(
        f"[{i}/{total}] 재빌드 {rebuilt} · 캐시신선 {cached} · 실패 {failed} "
        f"({rate:.1f} papers/s)"
    )


def _stored_doc_model(builder, paper_id: str) -> tuple[int, str] | None:
    """저장된 doc-model의 (version, sourceTier). 없으면 None.

    버전을 모르면 읽을 수가 없으므로 최신부터 내려가며 찾는다 — arXiv 개정은 잦지 않고,
    저장소 나열은 이 도구가 쓰는 포트에 없다."""
    for version in range(_MAX_PROBED_VERSION, 0, -1):
        doc = builder._store.get(paper_id, version)  # noqa: SLF001
        if doc is not None:
            return version, doc.meta.provenance.sourceTier.value
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ids", required=True, help="paperId 목록 파일 (한 줄에 하나, # 주석)")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--rung",
        choices=("html", "tei"),
        default="html",
        help="html: ar5iv를 다시 받아 파싱 · "
        "tei: 캐시된 TEI+PDF로 GROBID 단을 다시 빌드(GROBID 호출 없음)",
    )
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
    grobid = pipeline._grobid  # noqa: SLF001
    if args.rung == "tei":
        if grobid is None:
            print("TEI 단에는 GROBID 어댑터 배선이 필요하다 (DOCSURI_GROBID_URL)", file=sys.stderr)
            return 2
        if builder._formula_reader is None:  # noqa: SLF001
            # 이 단은 수식 LaTeX을 채우려고 존재하는데, 리더가 없으면 force가 신선도 검사까지
            # 건너뛴 채 LaTeX이 0인 doc-model로 기존 것을 덮어쓴다 — 목적의 정반대다.
            print(
                "--rung tei에는 수식 리더가 필요하다. DOCSURI_FORMULA_READER를 끄지 말고,\n"
                "pix2tex 엑스트라가 설치돼 있는지 확인하라 (없으면 LaTeX 0으로 덮어쓴다).",
                file=sys.stderr,
            )
            return 2
        if settings.grobid_cache_mode != "only":
            # "prefer"면 캐시에 없는 편에서 GROBID를 실제로 부른다. 이 도구는 저장된 TEI를 다시
            # 빌드하는 것이지 파싱을 다시 하는 게 아니다 — 빠진 편은 실패로 보이는 게 맞다.
            print(
                "--rung tei는 DOCSURI_GROBID_CACHE_MODE=only로 돌려라 (GROBID를 부르지 않기 위해)",
                file=sys.stderr,
            )
            return 2

    print(f"[plan] {len(ids)}편 · 단 {args.rung} · 파서 {builder._parser_version}")  # noqa: SLF001
    rebuilt = cached = failed = assets = 0
    started = time.time()
    # 메타데이터는 100편씩 묶어서 받는다. 한 편씩 걸면 arXiv가 IP 단위로 막는다 —
    # 어댑터 주석이 "20편을 하나씩 걸었더니 요청 100건에 거절당했다"고 적어둔 그 함정이고,
    # 이 도구가 그대로 밟아 242편 중 13편이 429로 죽었다. 묶으면 논문당 요청이 사라진다.
    meta_by_id: dict = {}
    for start in range(0, len(ids), METADATA_CHUNK):
        chunk = ids[start : start + METADATA_CHUNK]
        try:
            meta_by_id.update(runtime.arxiv.fetch_metadata_batch(chunk))
        except Exception as exc:  # noqa: BLE001 — 묶음 하나가 실패해도 나머지는 간다
            print(f"[warn] 메타데이터 묶음 {start}~{start + len(chunk)} 실패: {type(exc).__name__}")
    print(f"[plan] 메타데이터 확보 {len(meta_by_id)}/{len(ids)}편")
    # 한 건도 못 받았다면 arXiv가 이미 우리를 막고 있다는 뜻이다. 여기서 개별 조회로
    # 내려가면 논문마다 요청을 하나씩 더 얹어 벌칙을 늘리기만 한다 — 오늘 실제로 그렇게
    # 17편이 죽었다. 조용히 느려지는 대신 멈춘다.
    if not meta_by_id:
        print(
            "메타데이터를 한 건도 받지 못했다 — arXiv가 막고 있을 때 개별 조회로 내려가면\n"
            "벌칙만 키운다. 잠시 뒤 다시 실행하라(같은 명령이 끝난 논문을 건너뛴다).",
            file=sys.stderr,
        )
        return 1

    for i, paper_id in enumerate(ids, 1):
        try:
            metadata = meta_by_id.get(paper_id)
            if metadata is None:
                # 묶음에 없던 편만 개별로 메운다. 전량이 아니라 빠진 것만이므로 요청이 몇 건에
                # 그치고, 그 몇 건은 묶음 응답이 실제로 누락한 논문이다.
                metadata = runtime.arxiv.fetch_metadata(paper_id)
            if args.rung == "tei":
                # 저장된 doc-model을 먼저 읽어 그 버전과 등급을 쓴다. arXiv가 주는 최신 버전을
                # 쓰면 두 가지가 어긋난다: 수집 뒤 개정된 논문은 TEI 캐시 키가 안 맞아
                # (cache_mode=only에서) 실패하고, 새 버전으로 써 넣으면 색인된 doc-model이
                # 고아가 된다.
                stored = _stored_doc_model(builder, paper_id)
                if stored is None:
                    failed += 1
                    print(f"[fail] {paper_id}: 저장된 doc-model이 없다 (이 단은 재빌드 전용이다)")
                    continue
                version, tier = stored
                if tier != SourceTier.pdf.value:
                    # 이 단은 TEI로 다시 만든다. ar5iv HTML로 만든 문서를 여기 태우면 더 나은
                    # 등급을 PDF 등급으로 갈아엎는다 — force가 신선도 검사까지 껐으므로 막을
                    # 것이 없다.
                    failed += 1
                    print(f"[fail] {paper_id}: sourceTier={tier} — PDF 단 문서가 아니다")
                    continue
                # version은 arxiv_ref에서 파생되는 속성이라 ref 자체를 저장본 버전으로 맞춘다.
                metadata = replace(metadata, arxiv_ref=f"{paper_id}v{version}")
                # 파이프라인의 GROBID 단을 그대로 부른다. 손으로 옮겨 적으면 resilience 래핑과
                # no-coords 분기가 빠진다(실제로 빠졌다).
                out = pipeline._grobid_doc_model(metadata, force=not args.dry_run)  # noqa: SLF001
                if out is None:
                    failed += 1
                    print(f"[fail] {paper_id}: GROBID 단이 doc-model을 못 냈다")
                    continue
                result, ctx = out
                if getattr(result, "cached", False):
                    # dry-run은 force를 끄므로 전건이 캐시로 돌아온다. 그것을 재빌드로 세면
                    # "실제로 무엇이 바뀌나"라는 dry-run의 유일한 질문에 항상 틀린 답을 준다.
                    cached += 1
                elif not args.dry_run:
                    rebuilt += 1
                    if ctx is not None and ctx.crops:
                        pipeline._render_and_store_crops(  # noqa: SLF001
                            metadata.paper_id, metadata.version, ctx.pdf, list(ctx.crops)
                        )
                        assets += len(ctx.crops)
                _progress(i, len(ids), rebuilt, cached, failed, started)
                continue
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
        _progress(i, len(ids), rebuilt, cached, failed, started)

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
