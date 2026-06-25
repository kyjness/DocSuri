from __future__ import annotations

from collections import OrderedDict


class BoundedSeen:
    """LRU membership set that bounds dedup memory in long-running workers.

    Same idea as InMemoryEventStore._seen (adapters/local.py): O(1) add/lookup, evict the
    oldest key once past ``max_size``. A key re-seen after eviction is reprocessed — acceptable
    for at-least-once dedup, where the cap dwarfs any realistic in-flight redelivery window.
    Exposes the ``key in seen`` / ``seen.add(key)`` subset of the set API the detectors use.

    ponytail: swap for a shared store (Redis SETEX) only if dedup must hold across workers.
    """

    __slots__ = ("_keys", "_max")

    def __init__(self, max_size: int = 100_000) -> None:
        self._keys: OrderedDict[str, None] = OrderedDict()
        self._max = max_size

    def __contains__(self, key: str) -> bool:
        return key in self._keys

    def add(self, key: str) -> None:
        if key in self._keys:
            return
        self._keys[key] = None
        if len(self._keys) > self._max:
            self._keys.popitem(last=False)  # evict oldest — bound the dedup window

    def clear(self) -> None:
        self._keys.clear()

    def __len__(self) -> int:
        return len(self._keys)
