"""Regression test for todo 221 — live vix_z/flight_quality/yield_slope_z permanently 0.0.

_process_bar_compute never called FeatureCache.update_cross_asset() at all -- the only
"update_cross_asset" it invoked was CacheManager's same-named method, which just stores
a raw topic_cross_asset payload for CacheSnapshot and has nothing to do with computing
vix_z/flight_quality/yield_slope_z from SPY/TLT/SHY OHLCV bars. Every live feature vector
carried these three fields at their dataclass default (0.0) forever.

Also guards two correctness hazards a code-review pass on the original todo 221/222 fix
found (both re-opened, in weaker form, the exact silent-zero bug this file guards against):

1. update_cross_asset() appends to an internal realized-vol deque on every call, so
   triggering a refresh on EVERY role symbol's bar (not just one) would append the same
   observation up to 3x per bar period, corrupting the trailing z-score window. Only the
   equity role symbol's (self._cross_asset_symbols[0]) bar triggers a refresh now --
   see test_non_equity_role_bars_do_not_trigger_refresh below.
2. The first-access warm-up must replay buffered history bar-by-bar, not append a single
   observation for the whole buffer -- otherwise vix_z/yield_slope_z cold-start at 0.0 for
   `window` bars after every restart. See test_warm_up_replays_full_buffered_history below.
"""

import dataclasses
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.bar_normalizer import SOURCE_IBKR_NAMED
from src.core.schemas.bar_message import BarMessage, SessionType
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
    """make_agent() with tiny cross-asset windows so a handful of bars, not 252, is enough
    for _zscore_from_deque's len(history) >= window gate to actually compute a real value.
    """
    agent = make_agent()
    agent._kafka_producer = AsyncMock()
    agent._bars_processed = MagicMock()
    agent._feature_factory_config = dataclasses.replace(
        agent._feature_factory_config,
        vix_zscore_window=2,
        yield_curve_zscore_window=2,
        cross_asset_rv_window=2,
    )
    return agent


def _tick(agent, symbol: str, minute_offset: int, close: float) -> BarMessage:
    """Append one bar for `symbol` and run it through the live compute path."""
    bar = _bar(
        symbol,
        _T0 + timedelta(minutes=minute_offset),
        high=close + 0.5,
        low=close - 0.5,
        close=close,
    )
    agent._bar_history.append(bar)
    return bar


_STANDARD_CLOSES = {
    "SPY": (100.0, 102.5, 99.0),
    "TLT": (90.0, 88.0, 91.0),
    "SHY": (80.0, 80.3, 80.1),
}
_SHORT_CLOSES = {"SPY": (100.0, 102.5), "TLT": (90.0, 88.0), "SHY": (80.0, 80.3)}


async def _seed_and_tick_cross_asset(agent, closes: dict[str, tuple[float, ...]]) -> None:
    """Tick SPY/TLT/SHY together for len(closes["SPY"]) rounds, processing the SPY bar
    (the one that triggers a cross-asset refresh) through the live compute path each round.
    """
    n_rounds = len(closes["SPY"])
    for i in range(n_rounds):
        for symbol in ("SPY", "TLT", "SHY"):
            _tick(agent, symbol, i, closes[symbol][i])
        spy_bar = agent._bar_history.get("SPY", "1m")[-1]
        await agent._process_bar_compute(spy_bar, t0=0.0, gap=False)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_spy_ticks_populate_cross_asset_state():
    """3 genuinely new SPY/TLT/SHY bars (2 realized-vol observations) must move vix_z and
    flight_quality off their 0.0 dataclass defaults."""
    agent = _make_test_agent()
    await _seed_and_tick_cross_asset(agent, _STANDARD_CLOSES)

    state = agent._get_cross_asset_state("1m")
    assert state.vix_z != 0.0, "vix_z must move off its dataclass default once SPY bars flow"
    assert state.flight_quality != 0.0, "flight_quality must move off its dataclass default"
    assert state.yield_slope_z != 0.0, "yield_slope_z must move off its dataclass default"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cross_asset_values_broadcast_to_other_symbols():
    """A symbol that never itself carries SPY/TLT/SHY bars must still see the live broadcast
    values on its own cache, not the 0.0 dataclass default (the exact live bug todo 221 found).
    """
    agent = _make_test_agent()
    await _seed_and_tick_cross_asset(agent, _STANDARD_CLOSES)

    aapl_bar = _tick(agent, "AAPL", 3, 150.0)
    await agent._process_bar_compute(aapl_bar, t0=0.0, gap=False)

    aapl_cache = agent._get_cache("AAPL", "1m")
    state = agent._get_cross_asset_state("1m")
    assert aapl_cache.vix_z == state.vix_z != 0.0, (
        "AAPL's own cache must reflect the SPY/TLT/SHY-derived broadcast value, not stay "
        "frozen at the 0.0 dataclass default"
    )
    assert aapl_cache.flight_quality == state.flight_quality
    assert aapl_cache.yield_slope_z == state.yield_slope_z


@pytest.mark.unit
@pytest.mark.asyncio
async def test_non_cross_asset_bar_does_not_duplicate_realized_vol_history():
    """A non-SPY/TLT/SHY symbol's own bar tick must NOT re-append to the shared realized-vol
    deque -- doing so on every other symbol's tick would corrupt the trailing z-score window
    with duplicate observations of the same underlying SPY data.
    """
    agent = _make_test_agent()
    await _seed_and_tick_cross_asset(agent, _SHORT_CLOSES)

    state = agent._get_cross_asset_state("1m")
    depth_after_spy_ticks = len(state._spy_realized_vol_history)
    assert depth_after_spy_ticks > 0

    aapl_bar = _tick(agent, "AAPL", 2, 150.0)
    await agent._process_bar_compute(aapl_bar, t0=0.0, gap=False)

    assert len(state._spy_realized_vol_history) == depth_after_spy_ticks, (
        "AAPL's own bar tick must not append to the SPY realized-vol deque -- it is not a "
        "genuinely new SPY/TLT/SHY bar"
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_non_equity_role_bars_do_not_trigger_refresh():
    """Routing ALL THREE role symbols' bars through _process_bar_compute (not just SPY) must
    still append exactly ONE observation per bar period, not up to 3 -- a prior version of
    this fix refreshed on any of SPY/TLT/SHY's bars, tripling deque appends and corrupting
    the trailing z-score window (each distinct value was repeated exactly 3x).
    """
    agent = _make_test_agent()
    n_rounds = len(_STANDARD_CLOSES["SPY"])
    for i in range(n_rounds):
        for symbol in ("SPY", "TLT", "SHY"):
            bar = _tick(agent, symbol, i, _STANDARD_CLOSES[symbol][i])
            await agent._process_bar_compute(bar, t0=0.0, gap=False)

    state = agent._get_cross_asset_state("1m")
    # n_rounds - 1: the vix_z branch of _compute_cross_asset needs >= 2 SPY bars to compute a
    # return, so round 0's single-bar SPY refresh appends nothing -- that's real math, not the
    # bug under test. What this asserts is "no MORE than one append per subsequent round".
    assert len(state._spy_realized_vol_history) == n_rounds - 1, (
        f"expected exactly {n_rounds - 1} realized-vol observations (one per bar period once "
        f">= 2 SPY bars exist), got {len(state._spy_realized_vol_history)} -- TLT/SHY bars "
        "must not trigger a refresh"
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_warm_up_replays_full_buffered_history():
    """First access after buffered (not live-ticked) SPY/TLT/SHY history must replay it
    bar-by-bar, not append a single observation for the whole buffer -- otherwise vix_z/
    yield_slope_z cold-start at their 0.0 dataclass default for `window` bars after every
    restart, even though history was already seeded from the DB (_seed_bar_history_from_db).
    """
    agent = _make_test_agent()
    closes = {
        "SPY": (100.0, 101.0, 99.0, 102.0),
        "TLT": (90.0, 89.0, 91.0, 88.0),
        "SHY": (80.0, 80.2, 80.1, 80.3),
    }
    n_bars = len(closes["SPY"])
    for i in range(n_bars):
        for symbol in ("SPY", "TLT", "SHY"):
            _tick(agent, symbol, i, closes[symbol][i])

    # No _process_bar_compute call -- this exercises the cold first-access warm-up path only.
    state = agent._get_cross_asset_state("1m")
    assert len(state._spy_realized_vol_history) == n_bars - 1, (
        f"warm-up must replay all {n_bars - 1} realized-vol observations available from the "
        f"buffered history, got {len(state._spy_realized_vol_history)} -- a cold-started "
        "single-entry warm-up would leave vix_z at 0.0 for `window` bars after every restart"
    )
    assert state.vix_z != 0.0, "vix_z must be populated immediately after warm-up, not 0.0"
