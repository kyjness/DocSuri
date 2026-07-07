"""App-shell configuration — environment-driven, no external service required to boot.

Defaults are chosen so the shell starts in CI / a bare checkout with zero infrastructure
(SQLite, no Redis). Production overrides every value via env (see `.env.example` and
`docker-compose.yml` for the full-local Postgres + Redis profile).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import quote


def _resolve_database_url(default: str) -> str:
    """Resolve the DB DSN. Precedence:

    1. ``DATABASE_URL`` if set (full DSN — local/compose, tests).
    2. Assembled from ``DB_HOST``/``DB_PORT``/``DB_NAME``/``DB_USER`` + ``DB_PASSWORD`` —
       the ECS shape, where the password arrives as a Secrets Manager-injected env var and
       the rest are plain env. Keeps the password out of any single committed/visible URL.
    3. The SQLite default (bare checkout / CI).
    """
    explicit = os.getenv("DATABASE_URL")
    if explicit:
        return explicit
    host = os.getenv("DB_HOST")
    if host:
        user = quote(os.getenv("DB_USER", "docsuri_admin"), safe="")
        pw = quote(os.getenv("DB_PASSWORD", ""), safe="")
        port = os.getenv("DB_PORT", "5432")
        name = os.getenv("DB_NAME", "docsuri")
        return f"postgresql+psycopg://{user}:{pw}@{host}:{port}/{name}"
    return default

# Sensible dev defaults for the SSR phone frontend (U5) origins. CORS must be an explicit
# allow-list (not "*") because accounts/auth uses credentialed cookies (SEC-12) and the
# CORS spec forbids wildcard origin together with allow_credentials.
_DEFAULT_CORS_ORIGINS = ("http://localhost:3000", "http://localhost:5173")

# Kept at module scope (NOT referenced via ``cls.<field>``): with ``slots=True`` on the
# dataclass, ``cls.database_url`` yields the slot descriptor, not this string, which crashes
# ``_resolve_database_url`` whenever neither DATABASE_URL nor DB_HOST is set (bare local run).
_DEFAULT_DATABASE_URL = "sqlite:///./docsuri-dev.db"


@dataclass(frozen=True, slots=True)
class Settings:
    """Immutable, fully-resolved settings. Build via :meth:`from_env`."""

    env: str = "local"
    # SQLite default keeps the shell bootable with no DB server. accounts (U3) runs against
    # Postgres in prod — set DATABASE_URL to the Postgres DSN there.
    database_url: str = _DEFAULT_DATABASE_URL
    cors_origins: tuple[str, ...] = _DEFAULT_CORS_ORIGINS
    # U6 gateway rate-limit keying: trust X-Forwarded-For only behind a controlled proxy.
    # Default off → key on the direct client (request.client.host). See
    # backend/middleware/gateway.py::_rate_limit_key. Set TRUST_PROXY_HEADERS=1 in deployments
    # that sit behind a trusted reverse proxy / load balancer.
    trust_proxy_headers: bool = False
    # Number of trusted proxies in front of the app (only consulted when trust_proxy_headers).
    # The rate-limit key is the X-Forwarded-For hop this many places from the right — i.e. what
    # your outermost trusted proxy stamped — never the spoofable leftmost hop. 1 = single LB.
    trusted_proxy_count: int = 1
    gateway_rate_limit_max_requests: int = 60
    gateway_rate_limit_window_seconds: float = 60.0

    @property
    def is_local(self) -> bool:
        return self.env.lower() in {"local", "test", "dev", "development"}

    @classmethod
    def from_env(cls) -> Settings:
        raw_origins = os.getenv("CORS_ORIGINS")
        origins = (
            tuple(o.strip() for o in raw_origins.split(",") if o.strip())
            if raw_origins
            else _DEFAULT_CORS_ORIGINS
        )
        return cls(
            env=os.getenv("ENV", "local"),
            database_url=_resolve_database_url(_DEFAULT_DATABASE_URL),
            cors_origins=origins,
            trust_proxy_headers=os.getenv("TRUST_PROXY_HEADERS", "").strip().lower()
            in {"1", "true", "yes", "on"},
            trusted_proxy_count=int(os.getenv("TRUSTED_PROXY_COUNT") or "1"),
            gateway_rate_limit_max_requests=int(
                os.getenv("DOCSURI_GATEWAY_RATE_LIMIT_MAX_REQUESTS") or "60"
            ),
            gateway_rate_limit_window_seconds=float(
                os.getenv("DOCSURI_GATEWAY_RATE_LIMIT_WINDOW_SECONDS") or "60"
            ),
        )
