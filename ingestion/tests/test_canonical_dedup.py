from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from docsuri_ingestion.adapters.local import InMemoryControlPlaneStore
from docsuri_ingestion.domain.canonical import canonical_key
from docsuri_ingestion.domain.enums import SourceName
from docsuri_ingestion.domain.models import CanonicalDedupState


def test_canonical_key_priority() -> None:
    assert (
        canonical_key(
            doi="10.1000/XYZ",
            arxiv_id="2401.00001v2",
            title="A Paper",
            first_author="Ada",
            year=2024,
        )
        == "doi:10.1000/xyz"
    )
    assert (
        canonical_key(arxiv_id="2401.00001v2", title="A Paper", first_author="Ada", year=2024)
        == "arxiv:2401.00001"
    )
    assert canonical_key(title=" A   Paper ", first_author="Ada Lovelace", year=2024).startswith(
        "title:"
    )


def test_in_memory_store_round_trips_canonical_dedup_state() -> None:
    store = InMemoryControlPlaneStore()
    state = CanonicalDedupState(
        canonical_key="doi:10.1000/x",
        paper_id="p1",
        winning_source_tier="ARXIV_HTML",
        winning_version=1,
        fingerprint="fp",
        seen_sources=(SourceName.ARXIV, SourceName.OPENALEX),
    )

    store.upsert_canonical_dedup_state(state)

    assert store.get_canonical_dedup_state("doi:10.1000/x") == state


def test_in_memory_store_deletes_canonical_state_by_paper_id() -> None:
    store = InMemoryControlPlaneStore()
    state = CanonicalDedupState(
        canonical_key="arxiv:2401.00001",
        paper_id="2401.00001",
        winning_source_tier="ARXIV_HTML",
        winning_version=1,
        fingerprint="fp",
        seen_sources=(SourceName.ARXIV,),
    )
    store.upsert_canonical_dedup_state(state)

    store.delete_canonical_dedup_state_for_paper("2401.00001")

    assert store.get_canonical_dedup_state("arxiv:2401.00001") is None


def test_in_memory_store_lists_canonical_aliases_by_paper_id() -> None:
    store = InMemoryControlPlaneStore()
    for key in ("doi:10.1000/x", "arxiv:2401.00001"):
        store.upsert_canonical_dedup_state(
            CanonicalDedupState(
                canonical_key=key,
                paper_id="p1",
                winning_source_tier="OPENALEX_GROBID",
                winning_version=1,
                fingerprint="fp",
                seen_sources=(SourceName.OPENALEX,),
            )
        )

    aliases = store.list_canonical_dedup_states_for_paper("p1")

    assert {state.canonical_key for state in aliases} == {
        "doi:10.1000/x",
        "arxiv:2401.00001",
    }


_TEXT = st.text(
    alphabet=st.characters(blacklist_categories=("Cs",)),
    min_size=1,
    max_size=80,
)


@given(title=_TEXT, author=_TEXT, year=st.integers(min_value=1900, max_value=2100))
@settings(max_examples=25, derandomize=True)
def test_canonical_key_title_fallback_is_deterministic(title, author, year) -> None:
    left = canonical_key(title=title, first_author=author, year=year)
    right = canonical_key(title=title, first_author=author, year=year)

    assert left == right
    assert left.startswith("title:")


@given(
    base=st.from_regex(r"\d{4}\.\d{4,5}", fullmatch=True),
    version=st.integers(min_value=1, max_value=99),
)
@settings(max_examples=25, derandomize=True)
def test_canonical_key_arxiv_version_suffix_is_ignored(base, version) -> None:
    arxiv_id = f"{base}v{version}"

    assert canonical_key(arxiv_id=arxiv_id, title="T", year=2024) == canonical_key(
        arxiv_id=base, title="T", year=2024
    )
