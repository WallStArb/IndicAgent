"""Regression test for todo 221 — live vix_z/flight_quality/yield_slope_z permanently 0.0.

_process_bar_compute never called FeatureCache.update_cross_asset() at all -- the only
"update_cross_asset" it invoked was CacheManager's same-named method, which just stores
a raw topic_cross_asset payload for CacheSnapshot and has nothing to do with computing
vix_z/flight_quality/yield_slope_z from SPY/TLT/SHY OHLCV bars. Every live feature vector
carried these three fields at their dataclass default (0.0) forever.

Also guards the fix's own correctness hazard: FeatureCache.update_cross_asset() appends to
an internal realized-vol deque on every call, so calling it once per-symbol-tick (rather
than once per genuinely-new SPY/TLT/SHY bar) would silently corrupt the trailing z-score
window with duplicate observations.
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


_3_ROUND_CLOSES = {
    "SPY": (100.0, 102.5, 99.0),
    "TLT": (90.0, 88.0, 91.0),
    "SHY": (80.0, 80.3, 80.1),
}
_2_ROUND_CLOSES = {"SPY": (100.0, 102.5), "TLT": (90.0, 88.0), "SHY": (80.0, 80.3)}


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
    await _seed_and_tick_cross_asset(agent, _3_ROUND_CLOSES)

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
    await _seed_and_tick_cross_asset(agent, _3_ROUND_CLOSES)

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
    await _seed_and_tick_cross_asset(agent, _2_ROUND_CLOSES)

    state = agent._get_cross_asset_state("1m")
    depth_after_spy_ticks = len(state._spy_realized_vol_history)
    assert depth_after_spy_ticks > 0

    aapl_bar = _tick(agent, "AAPL", 2, 150.0)
    await agent._process_bar_compute(aapl_bar, t0=0.0, gap=False)

    assert len(state._spy_realized_vol_history) == depth_after_spy_ticks, (
        "AAPL's own bar tick must not append to the SPY realized-vol deque -- it is not a "
        "genuinely new SPY/TLT/SHY bar"
    )
