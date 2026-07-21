"""Regression test for todo 158 — above_wk_vwap frozen at 0.0 on the live path.

_process_bar_compute calls FeatureFactory.compute() but never calls
cache.advance_bar(), so above_wk_vwap (and hmm_duration) never update on
the live path even though compute_batch() calls advance_bar() per bar.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.bar_normalizer import SOURCE_IBKR_NAMED
from src.core.schemas.bar_message import BarMessage, SessionType
from tests.unit.pipeline.pipeline_helpers import make_agent


def _bar(ts: datetime, *, high: float, low: float, close: float, volume: int = 1000) -> BarMessage:
    return BarMessage(
        ts=ts,
        symbol="SPY",
        tf="1m",
        open=close,
        high=high,
        low=low,
        close=close,
        volume=volume,
        source=SOURCE_IBKR_NAMED,
        session_type=SessionType.RTH,
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_process_bar_compute_updates_above_wk_vwap():
    """Live-path _process_bar_compute must update cache.above_wk_vwap after each bar."""
    agent = make_agent()
    agent._kafka_producer = AsyncMock()
    agent._bars_processed = MagicMock()

    ts1 = datetime(2026, 3, 23, 14, 30, 0, tzinfo=UTC)
    ts2 = datetime(2026, 3, 23, 14, 31, 0, tzinfo=UTC)

    bar1 = _bar(ts1, high=100.0, low=98.0, close=99.0)
    # close sits well above the (high+low+close)/3 typical price of this
    # single-bar accumulation window -> above_wk_vwap must flip to 1.0
    bar2 = _bar(ts2, high=101.0, low=99.0, close=100.9)

    agent._bar_history.append(bar1)
    agent._bar_history.append(bar2)

    cache = agent._get_cache("SPY", "1m")
    assert cache.above_wk_vwap == 0.0  # dataclass default, pre-update

    await agent._process_bar_compute(bar2, t0=0.0, gap=False)

    assert cache.above_wk_vwap == 1.0, (
        "above_wk_vwap must reflect bar2's close vs weekly VWAP after "
        "_process_bar_compute runs -- cache.advance_bar() is never called "
        "on the live path (todo 158)"
    )
