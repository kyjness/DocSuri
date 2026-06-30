import pytest
from backend.modules.accounts.controller import _ensure_orcid_configured, _InProcessOidcStateStore
from backend.modules.accounts.integrations.oidc import OrcidOidcVerifier
from fastapi import HTTPException


@pytest.mark.asyncio
async def test_oidc_state_store_consumes_once_and_binds_provider():
    store = _InProcessOidcStateStore()
    await store.put("state-1", provider="ORCID", nonce="nonce-1", code_verifier="verifier-1")

    assert await store.consume("state-1", provider="GOOGLE") is None
    assert await store.consume("state-1", provider="ORCID") is None

    await store.put("state-2", provider="ORCID", nonce="nonce-2", code_verifier="verifier-2")
    assert await store.consume("state-2", provider="ORCID") == {
        "provider": "ORCID",
        "nonce": "nonce-2",
        "code_verifier": "verifier-2",
    }
    assert await store.consume("state-2", provider="ORCID") is None


def test_orcid_start_fails_closed_when_credentials_are_missing():
    with pytest.raises(HTTPException) as exc:
        _ensure_orcid_configured(OrcidOidcVerifier(client_id="", client_secret=""))

    assert exc.value.status_code == 503
