"""U4 Library — ownership-authorization delegation (SEC-8, INV-L4).

U4 does NOT decide object ownership itself: it delegates to U3's ``AuthorizationGuard``, the
single authority (application-design SEC-8). The caller resolves the resource's owner via an
owner-scoped repository read (INV-L1 backstop) and then asks the Guard to authorize. Any DENY —
or a malformed owner id — is generalized to ``NotFoundError`` so existence is never disclosed
(SEC-9) and the path is fail-closed (INV-L4).
"""

from __future__ import annotations

from docsuri_shared.authz import AccountId, Action, AuthorizationGuard, Decision, Principal

from .models import NotFoundError


def authorize_owned(principal: Principal, action: Action, owner_id: str) -> None:
    """Delegate the ownership decision to U3's Guard; raise generalized NotFound on any denial."""
    try:
        resource_owner = AccountId(owner_id)
    except Exception as exc:  # malformed owner id → fail closed
        raise NotFoundError("resource not found") from exc

    if AuthorizationGuard.authorize(principal, action, resource_owner) is not Decision.ALLOW:
        raise NotFoundError("resource not found")
