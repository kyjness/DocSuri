"""Shared X-Origin-Verify secret for the social-login edge route (Option A, FR-27).

The frontend CloudFront distribution forwards `/auth/social/*` to the backend origin
(origin.docsuri.org) so the OIDC start/callback land first-party on docsuri.org (session
cookie sticks). The backend ALB authenticates the origin by an `X-Origin-Verify` header.

This secret is added as a SECOND accepted value on the backend ALB rule (ComputeStack), so the
existing backend BFF-gateway secret is untouched — a misconfig here can only break `/auth/social/*`,
never the existing paths.

Stable within one `cdk synth`. For SEPARATE per-stack deploys, pin the SAME value via env
`ORIGIN_SOCIAL_VERIFY_SECRET` on every deploy of BOTH ComputeStack and FrontendStack; otherwise
the secrets diverge and `/auth/social/*` 403s (existing paths unaffected).
"""

import os
import secrets

SOCIAL_ORIGIN_VERIFY_SECRET = os.getenv("ORIGIN_SOCIAL_VERIFY_SECRET") or secrets.token_urlsafe(32)
