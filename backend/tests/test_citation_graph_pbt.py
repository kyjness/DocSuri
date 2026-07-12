"""QT-6 (US-CG6): 날조 인용 0건 · 그래프 불변식 위반 0건.

Property-style tests over citation tree assembly (US-CG3 mechanics) with seeded, randomized
reference inputs:

- every emitted node traces back to an input reference (no fabrication);
- unresolved (title-only / ambiguous-ID) references are never promoted to confirmed nodes;
- no duplicate confirmed nodes — duplicates fold to alreadyShown ("이미 표시됨");
- cycle expansion terminates (bounded client walk over a random citation graph).

``derandomize=True`` keeps the runs seeded/deterministic in CI (hypothesis is already a
backend dev dependency — accounts/library/personalization PBT suites use it).
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from backend.modules.citation_graph import controller

_ROOT = "2100.00000"
_IDS = [f"2101.{n:05d}" for n in range(1, 9)]  # small id alphabet forces duplicates + cycles


def _expected_node_id(raw: dict) -> str | None:
    """Mirror of the resolution rule: an item resolves iff it carries an identifier."""
    external = raw.get("externalIds") or {}
    node_id = external.get("ArXiv") or external.get("DOI") or raw.get("paperId") or raw.get("url")
    return str(node_id) if node_id else None


def _is_resolvable(raw: dict) -> bool:
    return bool(_expected_node_id(raw)) and bool((raw.get("title") or "").strip())


_title = st.one_of(
    st.just(""),  # missing/blank title → must stay unresolved
    st.just("   "),  # whitespace-only title → must stay unresolved
    st.text(min_size=1, max_size=40),
)

_raw_item = st.fixed_dictionaries(
    {},
    optional={
        "paperId": st.sampled_from([f"s2-{n}" for n in range(6)]),
        "title": _title,
        "year": st.one_of(st.none(), st.integers(min_value=1800, max_value=2100)),
        "citationCount": st.one_of(st.none(), st.integers(min_value=0, max_value=10**6)),
        "externalIds": st.fixed_dictionaries(
            {},
            optional={
                "ArXiv": st.sampled_from(_IDS),
                "DOI": st.sampled_from(["10.1/a", "10.1/b", "10.1/c"]),
            },
        ),
        "url": st.sampled_from(["https://x.test/1", "https://x.test/2"]),
    },
)


@settings(max_examples=150, deadline=None, derandomize=True)
@given(items=st.lists(_raw_item, max_size=40))
def test_qt6_tree_assembly_invariants(items: list[dict]) -> None:
    tree = controller._build_tree(_ROOT, _ROOT, items)

    input_ids = {_expected_node_id(raw) for raw in items if _is_resolvable(raw)}
    input_titles = {(raw.get("title") or "").strip()[:500] for raw in items}

    # 날조 인용 0건: every emitted node traces back to an input reference.
    for node in tree.nodes:
        assert node.nodeId in input_ids
        assert node.title in input_titles

    # Unresolved separation: never promoted, never silently dropped (unresolved is uncapped).
    unresolvable = [raw for raw in items if not _is_resolvable(raw)]
    assert len(tree.unresolved) == len(unresolvable)
    assert tree.status == ("Partial" if unresolvable else "Success")

    # No duplicate confirmed nodes: re-encounters fold to alreadyShown and are unsaveable.
    confirmed = [node.nodeId for node in tree.nodes if not node.alreadyShown]
    assert len(confirmed) == len(set(confirmed))
    assert _ROOT not in confirmed  # a root re-citation is never a fresh confirmed node
    first_seen: set[str] = set()
    for node in tree.nodes:
        assert node.alreadyShown is (node.nodeId in first_seen or node.nodeId == _ROOT)
        if node.alreadyShown:
            assert node.saveable is False
        first_seen.add(node.nodeId)

    # Bounded display + conservation: every input is a node, unresolved, or counted remainder.
    assert len(tree.nodes) <= controller._max_visible_nodes()
    assert len(tree.nodes) + len(tree.unresolved) + tree.remainingEstimate == len(items)
    assert tree.truncated is (tree.remainingEstimate > 0)

    # Edges bind emitted nodes to the parent only — no dangling or fabricated endpoints.
    assert [edge.target for edge in tree.edges] == [node.nodeId for node in tree.nodes]
    assert all(edge.source == _ROOT for edge in tree.edges)


def _raw_for(arxiv_id: str) -> dict:
    return {
        "paperId": f"s2-{arxiv_id}",
        "title": f"Paper {arxiv_id}",
        "externalIds": {"ArXiv": arxiv_id},
    }


@settings(max_examples=100, deadline=None, derandomize=True)
@given(
    graph=st.dictionaries(
        keys=st.sampled_from(_IDS),
        values=st.lists(st.sampled_from(_IDS), max_size=6),
        max_size=len(_IDS),
    ),
    root=st.sampled_from(_IDS),
)
def test_qt6_cycle_expansion_terminates(graph: dict[str, list[str]], root: str) -> None:
    # Simulate the client walk over a random (possibly cyclic) citation graph: expand the
    # root, then every confirmed (not alreadyShown) node exactly once. Termination holds
    # because (a) no fabricated ids can enlarge the frontier beyond the input universe and
    # (b) root/parent re-encounters fold to alreadyShown instead of re-expanding.
    universe = set(_IDS)
    expanded: set[str] = set()
    frontier = [root]
    steps = 0
    while frontier:
        current = frontier.pop()
        if current in expanded:
            continue
        expanded.add(current)
        steps += 1
        assert steps <= len(universe)  # the walk can never outgrow the input universe
        tree = controller._build_tree(
            root, current, [_raw_for(target) for target in graph.get(current, [])]
        )
        assert tree.depthReturned <= controller.MAX_DEPTH
        for node in tree.nodes:
            assert node.nodeId in universe  # 날조 0건 — a fabricated id would unbound the walk
            assert node.depth <= controller.MAX_DEPTH
            if node.nodeId in {root, current}:
                assert node.alreadyShown is True  # cycles fold ("이미 표시됨")
            if not node.alreadyShown:
                frontier.append(node.nodeId)
    assert expanded <= universe
