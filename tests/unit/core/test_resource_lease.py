"""Unit tests for ResourceLease (phase 185 plan 09, D-29), against the local PostgreSQL.

Real advisory locks on a live server, one test-only lease name per test (never the
production "ibkr_history_stream" name, and never a fixed name: a parallel CI run
holding the same key would turn the blocking tests into flaky timeouts). Skips
cleanly when no database is reachable, matching the live-DB convention of
tests/unit/test_spread_leg_pair_validity.py.

The threaded tests drive the queue semantics PostgreSQL actually implements: a
waiting session appears in pg_locks as not-granted, and a holder that unlocks and
immediately re-requests queues behind the waiter it just saw.
"""

from __future__ import annotations

import functools
import hashlib
import threading
import time
import uuid

import psycopg
import pytest

from src.core.resource_lease import LeaseTimeout, ResourceLease, Tier

_LIVE_DB_DSN = "postgresql://postgres:postgres@localhost:5432/indicagent"

# Fixed vector: the production lease name must hash to exactly this 64-bit signed
# key (first 8 bytes of sha256, big-endian, signed). If this changes, every holder
# and waiter in flight sees a different key and the lease silently stops
# serializing, so the test pins it.
_IBKR_HISTORY_STREAM_KEY = int.from_bytes(
    hashlib.sha256(b"ibkr_history_stream").digest()[:8], "big", signed=True
)


@functools.lru_cache(maxsize=1)
def _db_reachable() -> bool:
    try:
        conn = psycopg.connect(_LIVE_DB_DSN, connect_timeout=3)
    except Exception:
        return False
    conn.close()
    return True


pytestmark = pytest.mark.skipif(not _db_reachable(), reason="local PostgreSQL not reachable")


def _lease_name(tag: str) -> str:
    return f"test_resource_lease_{uuid.uuid4().hex[:8]}_{tag}"


def _wait_until(condition, timeout_s: float = 5.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.05)
    raise AssertionError("condition not met within timeout")


class _Waiter:
    """A second lease acquiring in a background thread, then holding briefly."""

    def __init__(self, name: str, tier: Tier, *, hold_s: float = 0.3) -> None:
        self.lease = ResourceLease(_LIVE_DB_DSN, name, tier=tier, holder=f"waiter-{tier.value}")
        self.result: dict[str, object] = {}
        self._hold_s = hold_s
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        try:
            self.lease.acquire(30.0)
            self.result["acquired"] = True
            time.sleep(self._hold_s)
            self.lease.release()
            self.result["released"] = True
        except Exception as error:  # noqa: BLE001 - recorded for the main thread to assert
            self.result["error"] = repr(error)
        finally:
            self.lease.close()

    def start(self) -> _Waiter:
        self._thread.start()
        return self

    def join(self) -> None:
        self._thread.join(timeout=15)
        assert not self._thread.is_alive(), "waiter thread did not finish"


def test_lock_key_is_a_stable_known_vector() -> None:
    lease = ResourceLease(_LIVE_DB_DSN, "ibkr_history_stream", tier=Tier.BULK, holder="vector")
    assert lease.key == _IBKR_HISTORY_STREAM_KEY
    # Stable across constructions (sha256, never the per-process salted hash()).
    again = ResourceLease(_LIVE_DB_DSN, "ibkr_history_stream", tier=Tier.PRIORITY, holder="v2")
    assert again.key == _IBKR_HISTORY_STREAM_KEY


def test_connection_carries_the_lease_application_name() -> None:
    name = _lease_name("appname")
    lease = ResourceLease(_LIVE_DB_DSN, name, tier=Tier.BULK, holder="app-holder")
    lease.acquire(None)
    try:
        with psycopg.connect(_LIVE_DB_DSN) as admin:
            pid = lease.backend_pid()
            app = admin.execute(
                "SELECT application_name FROM pg_stat_activity WHERE pid = %s", (pid,)
            ).fetchone()[0]
        assert app == f"lease:{name}:bulk:app-holder"
    finally:
        lease.release()
        lease.close()


def test_second_acquire_times_out_then_succeeds_after_release() -> None:
    name = _lease_name("mutual")
    holder = ResourceLease(_LIVE_DB_DSN, name, tier=Tier.BULK, holder="holder")
    holder.acquire(None)
    contender = ResourceLease(_LIVE_DB_DSN, name, tier=Tier.BULK, holder="contender")
    try:
        with pytest.raises(LeaseTimeout):
            contender.acquire(0.5)
        holder.release()
        contender.acquire(5.0)
    finally:
        holder.close()
        contender.release()
        contender.close()


def test_bulk_checkpoint_without_waiters_keeps_the_lock() -> None:
    name = _lease_name("nowaiter")
    holder = ResourceLease(_LIVE_DB_DSN, name, tier=Tier.BULK, holder="holder")
    contender = ResourceLease(_LIVE_DB_DSN, name, tier=Tier.BULK, holder="contender")
    holder.acquire(None)
    try:
        assert holder.waiters() == []
        assert holder.checkpoint() is False
        with pytest.raises(LeaseTimeout):
            contender.acquire(0.5)
    finally:
        holder.release()
        holder.close()
        contender.close()


def test_bulk_checkpoint_yields_to_any_waiter_and_reacquires_behind_it() -> None:
    name = _lease_name("bulk_yield")
    holder = ResourceLease(_LIVE_DB_DSN, name, tier=Tier.BULK, holder="holder")
    contender = ResourceLease(_LIVE_DB_DSN, name, tier=Tier.BULK, holder="contender")
    holder.acquire(None)
    waiter = _Waiter(name, Tier.PRIORITY).start()
    try:
        _wait_until(lambda: holder.waiters() == ["priority"])
        # Yields: unlock, waiter takes the lock, holder re-queues behind it and
        # returns only once the waiter has released. checkpoint() therefore blocks
        # here and comes back True with the lock held again.
        assert holder.checkpoint() is True
        waiter.join()
        assert waiter.result.get("acquired") is True
        assert waiter.result.get("released") is True
        with pytest.raises(LeaseTimeout):
            contender.acquire(0.5)
    finally:
        holder.release()
        holder.close()
        contender.close()


def test_priority_checkpoint_ignores_a_bulk_waiter() -> None:
    name = _lease_name("prio_ignores_bulk")
    holder = ResourceLease(_LIVE_DB_DSN, name, tier=Tier.PRIORITY, holder="holder")
    holder.acquire(None)
    waiter = _Waiter(name, Tier.BULK).start()
    try:
        _wait_until(lambda: holder.waiters() == ["bulk"])
        assert holder.checkpoint() is False
        # Still held: the waiter has not acquired.
        assert waiter.result == {}
    finally:
        holder.release()
        holder.close()
        waiter.join()
    assert waiter.result.get("acquired") is True


def test_priority_checkpoint_yields_to_a_priority_waiter() -> None:
    name = _lease_name("prio_yield")
    holder = ResourceLease(_LIVE_DB_DSN, name, tier=Tier.PRIORITY, holder="holder")
    contender = ResourceLease(_LIVE_DB_DSN, name, tier=Tier.PRIORITY, holder="contender")
    holder.acquire(None)
    waiter = _Waiter(name, Tier.PRIORITY).start()
    try:
        _wait_until(lambda: holder.waiters() == ["priority"])
        assert holder.checkpoint() is True
        waiter.join()
        assert waiter.result.get("released") is True
        with pytest.raises(LeaseTimeout):
            contender.acquire(0.5)
    finally:
        holder.release()
        holder.close()
        contender.close()


def test_killing_the_holding_connection_frees_the_lock() -> None:
    name = _lease_name("death")
    holder = ResourceLease(_LIVE_DB_DSN, name, tier=Tier.BULK, holder="holder")
    holder.acquire(None)
    pid = holder.backend_pid()
    with psycopg.connect(_LIVE_DB_DSN) as admin:
        admin.execute("SELECT pg_terminate_backend(%s)", (pid,))
    waiter = ResourceLease(_LIVE_DB_DSN, name, tier=Tier.BULK, holder="waiter")
    try:
        # No stale lease: the server released the session lock on termination.
        waiter.acquire(5.0)
    finally:
        holder.close()
        waiter.release()
        waiter.close()


def test_checkpoint_reacquires_after_connection_loss() -> None:
    name = _lease_name("reacquire")
    holder = ResourceLease(_LIVE_DB_DSN, name, tier=Tier.BULK, holder="holder")
    contender = ResourceLease(_LIVE_DB_DSN, name, tier=Tier.BULK, holder="contender")
    holder.acquire(None)
    with psycopg.connect(_LIVE_DB_DSN) as admin:
        admin.execute("SELECT pg_terminate_backend(%s)", (holder.backend_pid(),))
    try:
        # The next unit boundary notices the loss (pg_locks shows the lock gone),
        # reconnects and re-acquires; no waiter exists, so checkpoint returns False.
        assert holder.checkpoint() is False
        with pytest.raises(LeaseTimeout):
            contender.acquire(0.5)
    finally:
        holder.release()
        holder.close()
        contender.close()


def test_context_manager_releases_on_exit() -> None:
    name = _lease_name("ctx")
    contender = ResourceLease(_LIVE_DB_DSN, name, tier=Tier.BULK, holder="contender")
    with ResourceLease(_LIVE_DB_DSN, name, tier=Tier.BULK, holder="holder") as holder:
        holder.acquire(None)
    try:
        contender.acquire(5.0)
    finally:
        contender.release()
        contender.close()
