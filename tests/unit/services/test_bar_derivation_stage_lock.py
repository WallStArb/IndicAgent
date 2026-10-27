"""A writing derivation run holds a stage-wide advisory lock (the alpaca nightly's grid pass
must never write a series beside the fetcher's run-end grid stage)."""

from __future__ import annotations

import socket

import pytest

from services import bar_derivation

_DSN = "postgresql://postgres:postgres@localhost:5432/indicagent"


def _db_reachable() -> bool:
    try:
        socket.create_connection(("localhost", 5432), timeout=1).close()
        return True
    except OSError:
        return False


@pytest.mark.skipif(not _db_reachable(), reason="needs the local database")
@pytest.mark.asyncio
async def test_the_stage_lock_is_held_until_its_session_closes():
    import asyncpg

    held = await bar_derivation.acquire_stage_lock(_DSN, "test_stage_lock")
    probe = await asyncpg.connect(_DSN)
    try:
        key = "bar_derivation|test_stage_lock"
        got = await probe.fetchval("SELECT pg_try_advisory_lock(hashtextextended($1, 0))", key)
        assert got is False
        assert await held.fetchval("SHOW idle_session_timeout") == "0"
        await held.close()
        got = await probe.fetchval("SELECT pg_try_advisory_lock(hashtextextended($1, 0))", key)
        assert got is True
    finally:
        await probe.close()


@pytest.mark.asyncio
async def test_a_dry_run_takes_no_lock(monkeypatch):
    calls = []

    async def _lock(dsn, stage):
        calls.append(stage)
        raise AssertionError("a dry run must not lock")

    async def _dispatch(self, pool):
        return {"ok": 1}

    monkeypatch.setattr(bar_derivation, "acquire_stage_lock", _lock)
    monkeypatch.setattr(bar_derivation.BarDerivation, "_dispatch", _dispatch)
    writer = bar_derivation.BarDerivation(
        _DSN, stage="grid", symbols=None, changed_only=False, apply=False
    )
    assert await writer.execute(object()) == {"ok": 1} and calls == []
