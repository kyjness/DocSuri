"""Shared env parsing helpers.

Replaces the per-Unit ``_env_flag`` / ``_env_int`` / ``_env_float`` copies in
module settings (U7/U11/U12). Semantics preserved from those copies:

- ``env_flag``: unset or empty → ``default`` (feature gates default OFF, so a
  misspelled value fails closed); truthy set is ``"1"/"true"/"yes"``.
- ``env_int`` / ``env_float``: unset or empty → ``default``; a malformed value
  raises ``ValueError`` loudly at the composition root instead of silently
  running with a wrong limit.
- ``env_choice``: same policy for closed vocabularies (provider switches).
"""

from __future__ import annotations

import os
from collections.abc import Collection

__all__ = ["env_choice", "env_flag", "env_float", "env_int"]

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


def env_choice(name: str, allowed: Collection[str], default: str) -> str:
    """Read a closed-vocabulary setting (case-insensitive). Unset or empty → ``default``;
    anything outside ``allowed`` raises, same policy as a malformed ``env_int``.

    Provider switches are the motivating case, and they are worse than a wrong limit because the
    wrong value LOOKS like it worked. Every Unit read its provider as ``os.environ.get(...)`` and
    then compared it (``== "openai"``, or a dict ``.get(provider, default)``), so a typo fell
    through to the other branch: ``DOCSURI_EMBEDDING_PROVIDER=bedrok`` silently selects the
    Bedrock path with no model id, U2 skips its mount, and search 404s with nothing anywhere
    naming the typo. Failing here names it once, at startup.
    """
    raw = os.environ.get(name)
    if not raw or not raw.strip():
        return default
    value = raw.strip().lower()
    if value not in allowed:
        expected = ", ".join(sorted(allowed))
        raise ValueError(f"{name}={raw.strip()!r} is not one of: {expected}")
    return value
