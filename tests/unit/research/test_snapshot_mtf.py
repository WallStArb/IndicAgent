"""S0 for multi-timeframe books: closes_at, warmup prefix, derived-vendor rule (plan 184-07)."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime

import numpy as np
import pytest

from src.intelligence.research import clock, snapshot
from src.intelligence.research import panel as panel_mod
from tests.unit.research.mtf_fixtures import HALF_DAY, slot_starts

OOS = datetime(2025, 1, 1, tzinfo=UTC)
HOURLY_DAYS = [
    date(2024, 11, 22),
    date(2024, 11, 25),
    date(2024, 11, 26),
    date(2024, 11, 27),
    HALF_DAY,
    date(2024, 12, 2),
    date(2024, 12, 3),
]
DAILY_DAYS = [
    date(2024, 11, 21),
    date(2024, 11, 22),
    date(2024, 11, 25),
    date(2024, 11, 26),
    date(2024, 11, 27),
    HALF_DAY,
    date(2024, 12, 2),
    date(2024, 12, 3),
    date(2024, 12, 4),
    date(2024, 12, 5),
]
SYMS = ["AAA", "BBB"]

# The store hash of the 1h fixture build with no new option, taken from the code before 184-07.
PRE_CHANGE_HASH = "9ff105717b6a7a71"


def _rows(tf: str, with_range: bool) -> list[tuple]:
    if tf == "1d":
        stamps = [datetime(d.year, d.month, d.day, tzinfo=UTC) for d in DAILY_DAYS]
    else:
        stamps = [t.replace(tzinfo=UTC) for d in HOURLY_DAYS for t in slot_starts(d, tf)]
    out = []
    for i, ts in enumerate(stamps):
        c = 100.0 + i
        row = (ts, c - 0.5, c, 1000.0 + i)
        out.append(row + (c + 1, c - 1) if with_range else row)
    return out


class FakePool:
    def __init__(self, tf: str, vendor_kinds=(("derived", "5m_grid"),)):
        self.tf, self.vendor_kinds, self.calls = tf, vendor_kinds, []

    async def fetchval(self, sql, *args):
        return OOS

    async def fetch(self, sql, *args):
        self.calls.append((sql, args))
        if sql.startswith("SELECT timestamp, open"):
            _, _, lo, hi = args[0], args[1], args[2], args[3]
            with_range = ", high, low" in sql
            return [r for r in _rows(self.tf, with_range) if lo <= r[0] < hi]
        if sql.startswith("SELECT DISTINCT vendor"):
            return [{"vendor": v, "kind": k} for v, k in self.vendor_kinds]
        if sql.startswith("SELECT symbol FROM instruments"):
            return [{"symbol": s} for s in SYMS]
        return []

    def acquire(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def close(self):
        pass


@pytest.fixture
def build(monkeypatch, tmp_path):
    def run(tf, *, start, end, vendor_kinds=(("derived", "5m_grid"),), **kw):
        pool = FakePool(tf, vendor_kinds)

        async def fake_pool(dsn):
            return pool

        async def fake_label_inputs(conn, **_):
            return None

        monkeypatch.setattr(snapshot, "read_only_pool", fake_pool)
        monkeypatch.setattr(snapshot, "load_label_inputs", fake_label_inputs)
        monkeypatch.setattr(snapshot.data_quality, "snapshot_manifest", lambda *a, **k: {})
        out = tmp_path / f"{tf}_{len(list(tmp_path.iterdir()))}"
        path = asyncio.run(
            snapshot.build_panel(
                "dsn", out, symbols=SYMS, tf=tf, start=start, end_exclusive=end, **kw
            )
        )
        return path, pool

    return run


def _bar_calls(pool):
    return [c for c in pool.calls if c[0].startswith("SELECT timestamp, open")]


def test_closes_at_matches_the_clock_on_the_grid(build):
    path, _ = build("1h", start="2024-11-22", end="2024-12-04", fields=("closes_at",))
    p = panel_mod.load(path)
    expected = clock.closes_at(p.timestamps, p.valid, "1h", p.bars_per_session)
    assert p.closes_at is not None
    assert np.array_equal(p.closes_at, expected, equal_nan=True)
    # the half day's last bucket closes at 13:00 ET = 18:00 UTC
    half = np.datetime64("2024-11-29T18:00:00", "ns")
    assert (p.closes_at == half).any()


def test_high_low_come_from_the_same_select(build):
    path, pool = build(
        "15m", start="2024-11-22", end="2024-12-04", fields=("high", "low", "closes_at")
    )
    p = panel_mod.load(path)
    assert p.high is not None and p.low is not None and p.closes_at is not None
    calls = _bar_calls(pool)
    assert len(calls) == len(SYMS)
    assert all(", high, low" in sql for sql, _ in calls)


def test_non_derived_intraday_vendor_refused(build):
    with pytest.raises(ValueError, match="B1d"):
        build("1h", start="2024-11-22", end="2024-12-04", vendor_kinds=(("ibkr", "smart"),))


def test_vendor_set_recorded_only_with_fields(build):
    other = (("alpaca", "sip"), ("ibkr", "smart"))
    plain, _ = build("1d", start="2024-11-21", end="2024-12-04", vendor_kinds=other)
    with_fields, _ = build(
        "1d", start="2024-11-21", end="2024-12-04", vendor_kinds=other, fields=("closes_at",)
    )
    assert "bar_vendor_kinds" not in panel_mod.load(plain).manifest
    assert panel_mod.load(with_fields).manifest["bar_vendor_kinds"] == [
        ["alpaca", "sip"],
        ["ibkr", "smart"],
    ]


def test_unchanged_bytes_and_sql_without_options(build):
    path, pool = build("1h", start="2024-11-22", end="2024-12-04")
    assert path.name.endswith(PRE_CHANGE_HASH)
    assert {sql for sql, _ in _bar_calls(pool)} == {snapshot._BARS_SQL.format(extra="")}
    assert "bar_vendor_kinds" not in panel_mod.load(path).manifest


def test_warmup_daily_skips_holidays(build):
    path, pool = build("1d", start="2024-12-04", end="2024-12-06", warmup_sessions=5)
    p = panel_mod.load(path)
    # five sessions before 12-04: 12-03, 12-02, 11-29, 11-27, 11-26 (Thanksgiving skipped)
    assert str(p.timestamps[0])[:10] == "2024-11-26"
    assert p.manifest["warmup_prefix"] == {
        "sessions": 5,
        "fetch_start": "2024-11-26T00:00:00+00:00",
        "scored_start": "2024-12-04T00:00:00+00:00",
    }
    assert _bar_calls(pool)[0][1][2] == datetime(2024, 11, 26, tzinfo=UTC)


def test_warmup_scored_rows_equal_the_unprefixed_build(build):
    plain, _ = build("1d", start="2024-12-04", end="2024-12-06", fields=("closes_at",))
    pre, _ = build(
        "1d", start="2024-12-04", end="2024-12-06", fields=("closes_at",), warmup_sessions=5
    )
    a, b = panel_mod.load(plain), panel_mod.load(pre)
    k = len(b.timestamps) - len(a.timestamps)
    assert k == 5
    for name in ("open", "close", "volume", "valid", "timestamps", "closes_at"):
        assert np.array_equal(getattr(a, name), getattr(b, name)[k:], equal_nan=True), name


def test_warmup_zero_writes_the_default_bytes(build):
    a, _ = build("1h", start="2024-11-22", end="2024-12-04")
    b, _ = build("1h", start="2024-11-22", end="2024-12-04", warmup_sessions=0)
    assert a.name == b.name
    assert "warmup_prefix" not in panel_mod.load(b).manifest


def test_warmup_never_moves_the_oos_refusal(build):
    with pytest.raises(ValueError, match="oos_start"):
        build("1d", start="2024-12-04", end="2025-01-02", warmup_sessions=5)


def test_warmup_negative_refused(build):
    with pytest.raises(ValueError, match="warmup_sessions"):
        build("1d", start="2024-12-04", end="2024-12-06", warmup_sessions=-1)


def test_warmup_intraday_crosses_holiday_and_half_day(build):
    path, pool = build("1h", start="2024-12-02", end="2024-12-04", warmup_sessions=3)
    p = panel_mod.load(path)
    open_1126 = datetime(2024, 11, 26, 14, 30, tzinfo=UTC)  # 09:30 EST
    assert p.manifest["warmup_prefix"]["fetch_start"] == open_1126.isoformat()
    assert _bar_calls(pool)[0][1][2] == open_1126
    days = snapshot.session_dates(p)
    assert [str(d) for d in days[:4]] == ["2024-11-26", "2024-11-27", "2024-11-29", "2024-12-02"]
    half = p.timestamps[2 * p.bars_per_session : 3 * p.bars_per_session]
    assert p.valid[2 * p.bars_per_session : 3 * p.bars_per_session].sum() == 4, half
