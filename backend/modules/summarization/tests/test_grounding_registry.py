"""Contract: U7's grounding validator registers in the shared grounding catalog (D3 /
ports.md §2.1) as the ``summary`` domain with ``advisory`` authority — and the catalog
rejects any attempt to claim ``enforcement`` here (single grounding authority = search/U6).
"""

from __future__ import annotations

import pytest
from docsuri_shared.ports import GroundingValidatorRegistry, ValidatorRegistration

from summarization.domain.grounding import GroundingValidator
from summarization.real_wiring import build_grounding_registry


def test_u7_registers_as_summary_advisory() -> None:
    validator = GroundingValidator()
    registry = build_grounding_registry(validator)

    reg = registry.get("summary")
    assert reg.domain == "summary"
    assert reg.authority == "advisory"
    assert reg.owner_unit == "U7"
    assert reg.validator is validator
    # U7 only owns the summary slot; it must not register search/agent.
    assert registry.domains() == ("summary",)


def test_summary_cannot_claim_enforcement_authority() -> None:
    registry = GroundingValidatorRegistry()
    with pytest.raises(ValueError, match="enforcement authority is reserved for the 'search'"):
        registry.register(
            ValidatorRegistration(
                domain="summary",
                authority="enforcement",
                owner_unit="U7",
                validator=object(),
            )
        )
