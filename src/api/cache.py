"""One computation per refresh interval for the dashboard's summary routes.

A summary route is polled by every open tab; behind `cached` the work runs once per TTL however
many requests arrive at expiry: the key's lock queues late arrivals, and each of them takes the
outcome of the computation that ran while it waited (its value, or its exception) instead of
running another. The TTL is an APR read, resolved on a miss only and before the computation, so
a cache hit costs no query and a failed TTL read never discards finished work. A result `keep`
rejects (a page with a failed section) is shared with the queued requests but not stored, so the
next poll retries instead of serving the failure for a whole TTL.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class _Slot:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    expires: float = 0.0
    value: Any = None
    # Computations finished in this slot, and the last one's result or exception.
    attempts: int = 0
    outcome: Any = None
    # Requests inside the miss path; a slot with any is never evicted.
    users: int = 0


_slots: dict[str, _Slot] = {}


async def cached(
    key: str,
    ttl_s: Callable[[], Awaitable[float]],
    compute: Callable[[], Awaitable[Any]],
    keep: Callable[[Any], bool] = lambda _value: True,
) -> Any:
    slot = _slots.get(key) or _slots.setdefault(key, _Slot())
    if time.monotonic() < slot.expires:
        return slot.value
    seen = slot.attempts
    slot.users += 1
    try:
        async with slot.lock:
            if slot.attempts == seen:
                await _attempt(slot, ttl_s, compute, keep)
            outcome = slot.outcome
    finally:
        slot.users -= 1
    _evict_expired()
    if isinstance(outcome, Exception):
        raise outcome
    return outcome


async def _attempt(
    slot: _Slot,
    ttl_s: Callable[[], Awaitable[float]],
    compute: Callable[[], Awaitable[Any]],
    keep: Callable[[Any], bool],
) -> None:
    """Run one computation and record its outcome for every request queued behind it.
    Cancellation records nothing, so a queued request then runs its own."""
    try:
        ttl = await ttl_s()
        value = await compute()
    except Exception as error:
        slot.attempts, slot.outcome = slot.attempts + 1, error
        return
    slot.attempts, slot.outcome = slot.attempts + 1, value
    if keep(value):
        slot.value, slot.expires = value, time.monotonic() + ttl


def _evict_expired() -> None:
    """Drop expired slots that no request is using, so per-key slots (one per instrument viewed)
    cannot accumulate."""
    now = time.monotonic()
    for key in [k for k, s in _slots.items() if s.expires <= now and s.users == 0]:
        del _slots[key]


def clear() -> None:
    """Drop every slot, locks included, so no lock outlives the event loop that used it (tests)."""
    _slots.clear()
