"""Shared verbose output helper for AIDLC Code Reviewer."""

# Copyright 2026 Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

_verbose = False


def set_verbose(enabled: bool) -> None:
    """Enable or disable verbose terminal output."""
    global _verbose
    _verbose = enabled


def is_verbose() -> bool:
    """Return whether verbose mode is active."""
    return _verbose


def vprint(*args, **kwargs) -> None:
    """Print only when verbose mode is enabled.

    Accepts the same arguments as built-in print().
    """
    if _verbose:
        print(*args, **kwargs)
