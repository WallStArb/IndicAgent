"""One computation per refresh interval for the dashboard's summary routes.

A summary route is polled by every open tab; behind `cached` the work runs once per TTL however
many requests arrive at expiry (the lock makes late arrivals wait for, then reuse, the first
computation).
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

_entries: dict[str, tuple[float, Any]] = {}
_locks: dict[str, asyncio.Lock] = {}


async def cached(key: str, ttl_s: float, compute: Callable[[], Awaitable[Any]]) -> Any:
    entry = _entries.get(key)
    if entry is not None and time.monotonic() < entry[0]:
        return entry[1]
    async with _locks.setdefault(key, asyncio.Lock()):
        entry = _entries.get(key)
        if entry is None or time.monotonic() >= entry[0]:
            entry = (time.monotonic() + ttl_s, await compute())
            _entries[key] = entry
            _evict_expired()
    return entry[1]


def _evict_expired() -> None:
    """Drop expired values so per-key entries (one per instrument viewed) cannot accumulate."""
    now = time.monotonic()
    for key in [k for k, (expires, _) in _entries.items() if expires <= now]:
        del _entries[key]


def clear() -> None:
    """Drop every cached value (tests)."""
    _entries.clear()
