"""Live-path cross-asset series tests -- Plan 151-09 Task 2.

Supersedes the prior version of this file, which tested todo 221/222's
per-timeframe CrossAssetState mechanism (`_refresh_cross_asset_state`/
`_warm_cross_asset_state`/`_get_cross_asset_state`/`_cross_asset_state_for_bar`).
That mechanism computed vix_z/flight_quality/yield_slope_z from THIS
TIMEFRAME's own bar history (`self._bar_history.get(role_symbol, tf)` -- 5m
bars at tf=="5m", 1h bars at tf=="1h", ...), which is a confirmed grain
mismatch against the canonical daily-broadcast definition: schemas.py's
FeatureVector docstring states these fields are "broadcast to every symbol on
a given date, like vix_z above" (one value per calendar date, from DAILY
closes), and build_cross_asset_series (the batch path's own builder) only
ever receives "1d" bars. This is a train-serve skew bug, not merely a
placeholder-vs-real-value gap -- see 151-09-SUMMARY.md's Grain Mismatch
Finding section for the full evidence trail.

This file now tests the REPLACEMENT mechanism: `_load_cross_asset_series()`
(daily bars -> build_cross_asset_series(), the SAME function the batch path
calls), `_cross_asset_record_for_date()` (causal "most recent <= d" lookup),
and `_process_bar_compute()`'s once-per-UTC-day refresh trigger.
"""

from __future__ import annotations

import asyncio
import dataclasses
from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

from src.core.bar_normalizer import SOURCE_IBKR_NAMED
from src.core.schemas.bar_message import BarMessage, SessionType
from src.intelligence.features.cross_asset_series import (
    CROSS_ASSET_SYMBOLS,
    HYG,
    LQD,
    SHY,
    SPY,
    TIP,
    TLT,
    CrossAssetRecord,
    build_cross_asset_series,
)
from tests.unit.pipeline.pipeline_helpers import make_agent

_T0 = datetime(2026, 3, 23, 14, 30, 0, tzinfo=UTC)


def _bar(
    symbol: str, ts: datetime, *, high: float, low: float, close: float, volume: int = 1000
) -> BarMessage:
    return BarMessage(
        ts=ts,
        symbol=symbol,
        tf="1m",
        open=close,
        high=high,
        low=low,
        close=close,
        volume=volume,
        source=SOURCE_IBKR_NAMED,
        session_type=SessionType.RTH,
    )


def _make_test_agent():
    """make_agent() with tiny cross-asset windows so a handful of daily bars, not
    252, is enough for _zscore_from_deque's len(history) >= window gate to compute
    a real value.
    """
    agent = make_agent()
    agent._kafka_producer = AsyncMock()
    agent._bars_processed = MagicMock()
    agent._feature_factory_config = dataclasses.replace(
        agent._feature_factory_config,
        vix_zscore_window=2,
        yield_curve_zscore_window=2,
        cross_asset_rv_window=2,
        tip_tlt_zscore_window=2,
        hyg_lqd_zscore_window=2,
        sb_corr_window_fast=2,
        sb_corr_window_slow=3,
        sb_corr_zscore_window=2,
    )
    return agent


def _tick(agent, symbol: str, minute_offset: int, close: float) -> BarMessage:
    bar = _bar(
        symbol,
        _T0 + timedelta(minutes=minute_offset),
        high=close + 0.5,
        low=close - 0.5,
        close=close,
    )
    agent._bar_history.append(bar)
    return bar


async def _drain_background_tasks(agent) -> None:
    """Await every fire-and-forget task _process_bar_compute() scheduled -- the
    day-rollover refresh runs as asyncio.create_task(), never awaited inline.
    """
    if agent._background_tasks:
        await asyncio.gather(*agent._background_tasks, return_exceptions=True)


def _daily_rows(n: int, seed: int, start_close: float = 100.0) -> list[dict]:
    """Synthetic DB rows shaped like execute_query()'s asyncpg dict output
    (SELECT timestamp, open, high, low, close, volume FROM ...), oldest-first.
    """
    rng = np.random.default_rng(seed)
    closes = start_close * np.cumprod(1 + rng.normal(0, 0.01, n))
    base = datetime(2020, 1, 2, 21, 0, tzinfo=UTC)
    return [
        {
            "timestamp": base + timedelta(days=i),
            "open": float(closes[i] * 0.999),
            "high": float(closes[i] * 1.001),
            "low": float(closes[i] * 0.999),
            "close": float(closes[i]),
            "volume": 1_000_000.0,
        }
        for i in range(n)
    ]


def _rows_to_bars(rows: list[dict]) -> list[dict]:
    """Convert execute_query()-shaped rows into build_cross_asset_series()'s own
    bar-dict contract (ts/open/high/low/close/volume) -- mirrors
    _load_cross_asset_series()'s own remap, used here only to build the
    independent reference value for parity assertions."""
    return [
        {
            "ts": r["timestamp"],
            "open": float(r["open"]),
            "high": float(r["high"]),
            "low": float(r["low"]),
            "close": float(r["close"]),
            "volume": float(r["volume"]),
        }
        for r in rows
    ]


def _mock_execute_query_by_symbol(rows_by_symbol: dict[str, list[dict]]):
    async def _execute_query(_sql: str, symbol: str):
        return rows_by_symbol.get(symbol, [])

    return _execute_query


@pytest.mark.unit
@pytest.mark.asyncio
async def test_load_cross_asset_series_matches_build_cross_asset_series_directly():
    """Live-vs-batch parity (must_haves): _load_cross_asset_series()'s DB-row remap
    plus its build_cross_asset_series() call must produce byte-identical values to
    calling build_cross_asset_series() directly on the same bars -- 1e-12 field by
    field. This is the entire parity mechanism: one shared function, two callers.
    """
    agent = _make_test_agent()
    rows_by_symbol = {
        SPY: _daily_rows(60, seed=1, start_close=450.0),
        TLT: _daily_rows(60, seed=2, start_close=95.0),
        SHY: _daily_rows(60, seed=3, start_close=86.0),
        TIP: _daily_rows(60, seed=4, start_close=110.0),
        HYG: _daily_rows(60, seed=5, start_close=78.0),
        LQD: _daily_rows(60, seed=6, start_close=112.0),
    }
    agent._db.execute_query = _mock_execute_query_by_symbol(rows_by_symbol)

    await agent._load_cross_asset_series()

    reference = build_cross_asset_series(
        _rows_to_bars(rows_by_symbol[SPY]),
        _rows_to_bars(rows_by_symbol[TLT]),
        _rows_to_bars(rows_by_symbol[SHY]),
        _rows_to_bars(rows_by_symbol[TIP]),
        _rows_to_bars(rows_by_symbol[HYG]),
        _rows_to_bars(rows_by_symbol[LQD]),
        agent._feature_factory_config,
    )

    assert agent._cross_asset_by_date, "expected at least one date"
    assert set(agent._cross_asset_by_date.keys()) == set(reference.keys())
    for d, ref in reference.items():
        got = agent._cross_asset_by_date[d]
        for field_name in CrossAssetRecord._fields:
            assert abs(getattr(got, field_name) - getattr(ref, field_name)) < 1e-12, (
                f"{d}: {field_name} live={getattr(got, field_name)} "
                f"!= batch={getattr(ref, field_name)}"
            )
    assert agent._cross_asset_dates_sorted == sorted(reference.keys())


@pytest.mark.unit
@pytest.mark.asyncio
async def test_process_bar_compute_applies_exact_historical_date_match():
    """For a bar on a date that IS a key in self._cross_asset_by_date (a real,
    already-closed historical date -- the only kind the batch path ever sees),
    _cross_asset_record_for_date's "most recent <= d" reduces to an exact match,
    so the values _process_bar_compute() installs onto the cache equal the batch
    builder's own values for that date to 1e-12 -- the live-vs-batch parity claim
    end to end, through the real per-bar code path (not just _load_cross_asset_series
    in isolation, as in the test above).
    """
    agent = _make_test_agent()
    rows_by_symbol = {
        SPY: _daily_rows(40, seed=10, start_close=450.0),
        TLT: _daily_rows(40, seed=11, start_close=95.0),
        SHY: _daily_rows(40, seed=12, start_close=86.0),
        TIP: _daily_rows(40, seed=13, start_close=110.0),
        HYG: _daily_rows(40, seed=14, start_close=78.0),
        LQD: _daily_rows(40, seed=15, start_close=112.0),
    }
    agent._db.execute_query = _mock_execute_query_by_symbol(rows_by_symbol)
    await agent._load_cross_asset_series()

    target_date = agent._cross_asset_dates_sorted[-1]
    expected = agent._cross_asset_by_date[target_date]

    bar_ts = datetime.combine(target_date, datetime.min.time(), tzinfo=UTC) + timedelta(hours=14)
    bar = _bar("AAPL", bar_ts, high=151.0, low=149.0, close=150.0)
    agent._bar_history.append(bar)

    await agent._process_bar_compute(bar, t0=0.0, gap=False)
    await _drain_background_tasks(agent)

    cache = agent._get_cache("AAPL", "1m")
    assert abs(cache.vix_z - expected.vix_z) < 1e-12
    assert abs(cache.flight_quality - expected.flight_quality) < 1e-12
    assert abs(cache.yield_slope_z - expected.yield_slope_z) < 1e-12
    assert abs(cache.tip_tlt_ret_z - expected.tip_tlt_ret_z) < 1e-12
    assert abs(cache.hyg_lqd_ret_z - expected.hyg_lqd_ret_z) < 1e-12
    assert abs(cache.sb_corr_fast - expected.sb_corr_fast) < 1e-12
    assert abs(cache.sb_corr_slow - expected.sb_corr_slow) < 1e-12
    assert abs(cache.sb_corr_z - expected.sb_corr_z) < 1e-12


def test_causal_fallback_exact_match_when_date_is_a_key():
    agent = _make_test_agent()
    d1, d2 = date(2024, 1, 2), date(2024, 1, 3)
    rec1 = CrossAssetRecord(vix_z=1.0, flight_quality=0.1)
    rec2 = CrossAssetRecord(vix_z=2.0, flight_quality=0.2)
    agent._cross_asset_by_date = {d1: rec1, d2: rec2}
    agent._cross_asset_dates_sorted = [d1, d2]

    assert agent._cross_asset_record_for_date(d1) == rec1
    assert agent._cross_asset_record_for_date(d2) == rec2


def test_causal_fallback_uses_most_recent_past_date_for_still_forming_today():
    """A date that postdates every available entry (the live daemon's still-open
    trading day, whose own 1d bar has not been written yet) must fall back to the
    most recent PAST date's record, never to the all-0.0 CrossAssetRecord()
    default -- an exact-date lookup (the batch path's own semantics) would zero
    every cross-asset field for the entire live trading session, every day."""
    agent = _make_test_agent()
    d1, d2 = date(2024, 1, 2), date(2024, 1, 3)
    rec2 = CrossAssetRecord(vix_z=2.0)
    agent._cross_asset_by_date = {d1: CrossAssetRecord(vix_z=1.0), d2: rec2}
    agent._cross_asset_dates_sorted = [d1, d2]

    still_forming_today = date(2024, 1, 4)
    assert agent._cross_asset_record_for_date(still_forming_today) == rec2


def test_causal_fallback_never_uses_a_future_date():
    """A date that predates every available entry must fall back to the all-0.0
    default, never a future date's record (causality)."""
    agent = _make_test_agent()
    d1 = date(2024, 1, 5)
    agent._cross_asset_by_date = {d1: CrossAssetRecord(vix_z=9.0)}
    agent._cross_asset_dates_sorted = [d1]

    before_any_data = date(2024, 1, 1)
    assert agent._cross_asset_record_for_date(before_any_data) == CrossAssetRecord()


def test_causal_fallback_empty_series_degrades_to_zero_defaults():
    """Cold start / total load failure: self._cross_asset_by_date/dates_sorted are
    both empty (never populated) -- every date must degrade to the all-0.0 default,
    never crash."""
    agent = _make_test_agent()
    assert agent._cross_asset_by_date == {}
    assert agent._cross_asset_dates_sorted == []
    assert agent._cross_asset_record_for_date(date(2026, 1, 1)) == CrossAssetRecord()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_refresh_failure_logs_one_warning_and_keeps_prior_series():
    """When the 1d bar fetch raises, _refresh_cross_asset_series() must log exactly
    one warning and leave self._cross_asset_by_date/_cross_asset_dates_sorted at
    their PRIOR state -- never crash, never wipe good data to 0.0 on a transient
    failure (CLAUDE.md: never drop data that could contain signal)."""
    agent = _make_test_agent()
    prior_record = CrossAssetRecord(vix_z=5.0)
    prior_date = date(2024, 6, 1)
    agent._cross_asset_by_date = {prior_date: prior_record}
    agent._cross_asset_dates_sorted = [prior_date]

    async def _raising_execute_query(_sql: str, _symbol: str):
        raise RuntimeError("db unreachable")

    agent._db.execute_query = _raising_execute_query

    await agent._refresh_cross_asset_series(date(2026, 1, 2))

    assert agent._cross_asset_by_date == {prior_date: prior_record}
    assert agent._cross_asset_dates_sorted == [prior_date]
    agent.logger.warning.assert_called_once()
    assert agent.logger.warning.call_args[0][0] == "cross_asset.series_load_failed"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_setup_load_failure_leaves_series_empty_not_crashed():
    """Cold-start equivalent of the refresh-failure test: _load_cross_asset_series()
    itself must propagate (not swallow) an exception -- _setup()'s try/except is
    what converts that into a single warning and an empty (all-0.0-default) series,
    never a crash. Exercised directly against _load_cross_asset_series() since a
    full _setup() call requires mocking Kafka/DB-init/ConfigService."""
    agent = _make_test_agent()

    async def _raising_execute_query(_sql: str, _symbol: str):
        raise RuntimeError("db unreachable")

    agent._db.execute_query = _raising_execute_query

    with pytest.raises(RuntimeError):
        await agent._load_cross_asset_series()

    # State untouched by the failed attempt -- still whatever make_agent() seeded
    # (empty), which _cross_asset_record_for_date degrades to 0.0 from.
    assert agent._cross_asset_by_date == {}
    assert agent._cross_asset_dates_sorted == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_day_rollover_triggers_exactly_one_refresh_per_boundary():
    """Two _process_bar_compute() calls on the same (simulated-stale) UTC day must
    trigger exactly one refresh; a simulated day change must trigger exactly one
    more -- never a rebuild on every bar (the per-bar hot path must never await a
    DB read)."""
    agent = _make_test_agent()
    refresh_calls: list[date] = []

    async def _fake_refresh(built_for: date) -> None:
        refresh_calls.append(built_for)

    agent._refresh_cross_asset_series = _fake_refresh
    agent._cross_asset_built_on = date(2000, 1, 1)  # force stale on first bar

    bar1 = _tick(agent, "AAPL", 0, 100.0)
    await agent._process_bar_compute(bar1, t0=0.0, gap=False)
    bar2 = _tick(agent, "AAPL", 1, 101.0)
    await agent._process_bar_compute(bar2, t0=0.0, gap=False)
    await _drain_background_tasks(agent)

    assert (
        len(refresh_calls) == 1
    ), f"expected exactly 1 refresh across 2 same-day bars, got {len(refresh_calls)}"

    # Simulate a day change -- force stale again.
    agent._cross_asset_built_on = date(2000, 1, 1)
    bar3 = _tick(agent, "AAPL", 2, 102.0)
    await agent._process_bar_compute(bar3, t0=0.0, gap=False)
    await _drain_background_tasks(agent)

    assert len(refresh_calls) == 2, (
        f"expected exactly 1 more refresh after a simulated day change, got "
        f"{len(refresh_calls) - 1} additional"
    )


def test_cross_asset_symbols_constant_has_all_six_expected_tickers():
    """Guards against a silent drift between CROSS_ASSET_SYMBOLS (Task 1's shared
    Ring-1 constant) and the individual SPY/TLT/SHY/TIP/HYG/LQD names used to key
    _load_cross_asset_series()'s per-symbol fetch dict."""
    assert set(CROSS_ASSET_SYMBOLS) == {SPY, TLT, SHY, TIP, HYG, LQD}
    assert len(CROSS_ASSET_SYMBOLS) == 6
