"""S0 snapshot against the live database: read-only, on a 2-symbol, 3-month slice.

tests/live/: reads the real DB read-only; kept out of tests/integration/, whose autouse
conftest builds a scratch DB from migrations. Run explicitly: pytest tests/live/."""

import asyncio
import os

import asyncpg
import numpy as np
import pytest

from scripts.analysis.sleeve_walk_forward.snapshot import (
    build_snapshot,
    load_snapshot,
    read_only_pool,
)

SLICE = dict(
    symbols=["SPY", "TLT"], sleeve=("TLT",), start="2019-01-01", end_exclusive="2019-04-01"
)


def _dsn():
    # tests/conftest.py forces DATABASE_URL to indicagent_test; these tests read production.
    return os.environ.get(
        "HARNESS_LIVE_DSN", "postgresql://postgres:postgres@localhost:5432/indicagent"
    )


def test_snapshot_builds_and_hash_is_stable(tmp_path):
    a = asyncio.run(build_snapshot(_dsn(), tmp_path / "a", **SLICE))
    b = asyncio.run(build_snapshot(_dsn(), tmp_path / "b", **SLICE))
    assert a.name == b.name and a.name.startswith("snapshot_")
    snap = load_snapshot(a)
    assert snap.sessions[0] >= np.datetime64("2019-01-01") and snap.sessions[-1] < np.datetime64(
        "2019-04-01"
    )
    assert snap.all_1d.X.shape[1] == len(snap.feature_names)
    assert set(snap.all_1d.symbols) == {"SPY", "TLT"}
    assert snap.sleeve_closes.shape == (len(snap.sessions), 1)
    assert np.isfinite(snap.sleeve_closes).mean() > 0.9
    assert snap.manifest["oos_start"].startswith("2025-12-24")
    assert "alpha.ic.bootstrap_resamples" in snap.apr
    assert snap.manifest["max_bar_ts"] < "2019-04-01"


def test_connection_is_read_only():
    async def attempt():
        pool = await read_only_pool(_dsn())
        try:
            async with pool.acquire() as conn:
                await conn.execute("CREATE TEMP TABLE harness_write_probe (x int)")
        finally:
            await pool.close()

    with pytest.raises(asyncpg.exceptions.ReadOnlySQLTransactionError):
        asyncio.run(attempt())


def test_end_past_oos_start_raises_before_fetching(tmp_path):
    with pytest.raises(ValueError, match="past oos_start"):
        asyncio.run(build_snapshot(_dsn(), tmp_path, **{**SLICE, "end_exclusive": "2026-01-01"}))
