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

__all__ = ["EnvConfigError", "env_flag", "env_float", "env_int"]

_TRUTHY = ("1", "true", "yes")


class EnvConfigError(ValueError):
    """A named environment variable holds a value this process cannot run with.

    Distinct from a plain ``ValueError`` so composition roots can tell "the operator wrote the
    config wrong" apart from "a dependency failed while mounting". The former must stop the
    process — a wrong setting that gets swallowed into a "mount error" or a WARNING runs half a
    system on a config nobody meant, with the offending variable named nowhere. The latter is
    what defensive per-module error handling exists for. Catch-alls that contain mount failures
    re-raise this type.
    """


def env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if not raw:
        return default
    return raw.strip().lower() in _TRUTHY


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise EnvConfigError(f"{name}={raw!r} is not an integer") from exc


def env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise EnvConfigError(f"{name}={raw!r} is not a number") from exc
