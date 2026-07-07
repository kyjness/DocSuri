"""U3 (accounts) re-export shim for the authorization guard.

``AuthorizationGuard`` + ``Decision`` moved to ``docsuri_shared.authz`` (#167) so cross-Unit
callers depend on the neutral shared layer, not on accounts internals. Accounts keeps
importing them from here (``from .guard import AuthorizationGuard, Decision``) — the same
classes, no behavior change. The guard is stateless (BR-A6/BR-A7), so nothing accounts-owned
is lost by hosting the policy in shared.
"""

from docsuri_shared.authz import AuthorizationGuard, Decision

__all__ = ["AuthorizationGuard", "Decision"]
