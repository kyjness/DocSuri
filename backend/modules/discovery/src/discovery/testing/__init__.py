"""Test doubles (MR-1~4): deterministic fixtures + mock capability adapters + a wiring
helper. Real adapters (OpenSearch/Bedrock) replace these without changing the SearchResponse
contract or domain logic (MR-4).

Nothing here is on a serving path. The U6 port stubs that production DOES depend on when a
hook is left uninjected live in :mod:`discovery.defaults` instead — they were mocks only by
accident of this package's original name.
"""

from .wiring import build_mock_orchestrator

__all__ = ["build_mock_orchestrator"]
