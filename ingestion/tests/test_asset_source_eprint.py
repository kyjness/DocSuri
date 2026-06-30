"""ArxivAssetSource e-print memo: the asset and doc-model-macro paths share one fetch (BR-30)."""

from __future__ import annotations

from docsuri_ingestion.adapters.assets import ArxivAssetSource
from docsuri_ingestion.adapters.local import sample_metadata


class _CountingSource(ArxivAssetSource):
    """ArxivAssetSource with the network call stubbed so we can count actual fetches."""

    def __init__(self) -> None:
        super().__init__()
        self.gets: list[str] = []

    def _get(self, url: str) -> bytes | None:
        self.gets.append(url)
        return b"eprint-bytes"


def test_repeated_fetch_for_same_paper_hits_network_once() -> None:
    src = _CountingSource()
    meta = sample_metadata("2401.00001v1")
    first = src.fetch_eprint(meta)
    second = src.fetch_eprint(meta)  # macro path reuses what the asset path already fetched
    assert first == second == b"eprint-bytes"
    assert len(src.gets) == 1  # one network fetch shared by both consumers


def test_different_paper_refetches_and_replaces_memo() -> None:
    src = _CountingSource()
    src.fetch_eprint(sample_metadata("2401.00001v1"))
    src.fetch_eprint(sample_metadata("2402.00002v1"))
    src.fetch_eprint(sample_metadata("2401.00001v1"))  # memo holds only the most recent paper
    assert len(src.gets) == 3
