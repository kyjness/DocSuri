"""Shared env parsing helpers.

Replaces the per-Unit ``_env_flag`` / ``_env_int`` / ``_env_float`` copies in
module settings (U7/U11/U12). Semantics preserved from those copies:

- ``env_flag``: unset or empty → ``default`` (feature gates default OFF, so a
  misspelled value fails closed); truthy set is ``"1"/"true"/"yes"``.
- ``env_int`` / ``env_float``: unset or empty → ``default``; a malformed value
  raises ``ValueError`` loudly at the composition root instead of silently
  running with a wrong limit.
"""

from __future__ import annotations

import os

__all__ = ["env_flag", "env_float", "env_int"]

_TRUTHY = ("1", "true", "yes")


def env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if not raw:
        return default
    return raw.strip().lower() in _TRUTHY


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw else default


def env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    return float(raw) if raw else default
