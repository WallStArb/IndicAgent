"""IBKR history fetcher advisory lock (phase 189 plan 02, CD-07/CD-09), against local PostgreSQL.

Every test uses a unique lock name (never the production "ibkr_history_fetcher": a running
fetcher must never collide with a test run, T-189-08). The key-vector test is pure. Skips
cleanly when no database is reachable, matching tests/unit/core/test_resource_lease.py.
"""

from __future__ import annotations

import functools
import hashlib
import multiprocessing
import time
import uuid

import psycopg
import pytest

from scripts.infrastructure.backfill import _fetcher_lock as fl

_LIVE_DB_DSN = "postgresql://postgres:postgres@localhost:5432/indicagent"


@functools.lru_cache(maxsize=1)
def _db_reachable() -> bool:
    try:
        conn = psycopg.connect(_LIVE_DB_DSN, connect_timeout=3)
    except Exception:
        return False
    conn.close()
    return True


_live = pytest.mark.skipif(not _db_reachable(), reason="local PostgreSQL not reachable")


def _name() -> str:
    return f"test_fetcher_lock_{uuid.uuid4().hex[:8]}"


def test_key_vector_is_pinned():
    assert fl.FETCHER_LOCK_NAME == "ibkr_history_fetcher"
    expected = int.from_bytes(
        hashlib.sha256(b"ibkr_history_fetcher").digest()[:8], "big", signed=True
    )
    assert fl.fetcher_lock_key() == expected


def test_lock_held_message_is_exact():
    assert fl.LOCK_HELD_MESSAGE == "ibkr history fetcher lock held by another process; exiting"


@_live
def test_second_acquirer_refused_without_blocking():
    name = _name()
    first = fl.FetcherLock(_LIVE_DB_DSN, "first", name=name)
    second = fl.FetcherLock(_LIVE_DB_DSN, "second", name=name)
    try:
        assert first.acquire() is True
        started = time.monotonic()
        assert second.acquire() is False
        assert time.monotonic() - started < 1.0
    finally:
        first.close()
        second.close()


@_live
def test_reacquirable_after_close_and_after_release():
    name = _name()
    first = fl.FetcherLock(_LIVE_DB_DSN, "first", name=name)
    assert first.acquire() is True
    first.close()
    second = fl.FetcherLock(_LIVE_DB_DSN, "second", name=name)
    try:
        assert second.acquire() is True
        second.release()
        third = fl.FetcherLock(_LIVE_DB_DSN, "third", name=name)
        try:
            assert third.acquire() is True
        finally:
            third.close()
    finally:
        second.close()


@_live
def test_holder_visible_in_pg_stat_activity():
    name = _name()
    lock = fl.FetcherLock(_LIVE_DB_DSN, "visible", name=name)
    try:
        assert lock.acquire() is True
        with psycopg.connect(_LIVE_DB_DSN) as conn:
            apps = [
                r[0]
                for r in conn.execute(
                    "SELECT application_name FROM pg_stat_activity WHERE application_name LIKE %s",
                    (f"lock:{name}:%",),
                ).fetchall()
            ]
        assert apps == [f"lock:{name}:visible"]
    finally:
        lock.close()


@_live
def test_application_name_truncated_to_63_chars():
    lock = fl.FetcherLock(_LIVE_DB_DSN, "h" * 100, name=_name())
    assert len(lock.application_name) == 63


@_live
def test_hold_or_refuse_raises_when_held():
    name = _name()
    holder = fl.FetcherLock(_LIVE_DB_DSN, "holder", name=name)
    try:
        holder.hold_or_refuse()
        with pytest.raises(fl.FetcherLockHeld) as info:
            with fl.FetcherLock(_LIVE_DB_DSN, "refused", name=name):
                pytest.fail("context body must not run while the lock is held")
        assert str(info.value) == fl.LOCK_HELD_MESSAGE
    finally:
        holder.close()


@_live
def test_context_manager_releases_on_exit():
    name = _name()
    with fl.FetcherLock(_LIVE_DB_DSN, "ctx", name=name):
        pass
    again = fl.FetcherLock(_LIVE_DB_DSN, "again", name=name)
    try:
        assert again.acquire() is True
    finally:
        again.close()


@_live
def test_close_is_idempotent():
    lock = fl.FetcherLock(_LIVE_DB_DSN, "idem", name=_name())
    assert lock.acquire() is True
    lock.close()
    lock.close()


def _child_acquire_and_exit(name: str, result) -> None:
    lock = fl.FetcherLock(_LIVE_DB_DSN, "child", name=name)
    result.value = 1 if lock.acquire() else 0
    # exit without release or close: process death must free the session lock
    import os

    os._exit(0)


@_live
def test_process_death_releases_lock():
    name = _name()
    ctx = multiprocessing.get_context("spawn")
    result = ctx.Value("i", -1)
    child = ctx.Process(target=_child_acquire_and_exit, args=(name, result))
    child.start()
    child.join(30)
    assert result.value == 1
    lock = fl.FetcherLock(_LIVE_DB_DSN, "after-death", name=name)
    try:
        deadline = time.monotonic() + 5.0
        acquired = lock.acquire()
        while not acquired and time.monotonic() < deadline:
            time.sleep(0.1)
            acquired = lock.acquire()
        assert acquired is True
    finally:
        lock.close()
