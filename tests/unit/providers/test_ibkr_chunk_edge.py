"""IBKR chunk edges (review finding 2 of plan 191-07): a request end inside a bar truncates it.

KRE 2007-06-25 14:00 UTC: the walk's chunk ended at 14:02:29 (the run's clock time), IBKR
answered a 14:00 bar of 45.61 x4 and volume 0, and last-wins raw took it as a restatement of the
whole bar (45.65, volume 9,500). The walk now asks on the bar grid. A bar that straddles the
request end or is still forming is handed on with its request record like every other bar; the
fetch layer's complete-bar gate holds it back (second review, finding 5).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.providers import ibkr as ibkr_module
from src.providers.base import OHLCVBar
from src.providers.ibkr import IBKRProvider, align_request_end, format_request_end

EDGE = datetime(2007, 6, 25, 14, 2, 29, 679673, tzinfo=UTC)
NOW = datetime(2026, 10, 14, 16, 0, tzinfo=UTC)


def _bar(ts: datetime, timeframe: str = "5m", volume: int = 100) -> OHLCVBar:
    return OHLCVBar(
        symbol="KRE",
        timeframe=timeframe,
        timestamp=ts,
        open=1.0,
        high=1.0,
        low=1.0,
        close=1.0,
        volume=volume,
        source="ibkr_named",
    )


@pytest.mark.parametrize(
    ("timeframe", "expected"),
    [
        ("1m", datetime(2007, 6, 25, 14, 2, tzinfo=UTC)),
        ("5m", datetime(2007, 6, 25, 14, 0, tzinfo=UTC)),
        ("15m", datetime(2007, 6, 25, 14, 0, tzinfo=UTC)),
        ("1h", datetime(2007, 6, 25, 14, 0, tzinfo=UTC)),
        ("4h", datetime(2007, 6, 25, 12, 0, tzinfo=UTC)),
        ("1d", EDGE),
    ],
)
def test_request_end_is_floored_to_the_bar_grid(timeframe, expected):
    assert align_request_end(EDGE, timeframe) == expected


def test_an_aligned_end_stays_where_it_is_and_whole_days_keep_it_aligned():
    end = datetime(2026, 10, 9, 20, 0, tzinfo=UTC)
    assert align_request_end(end, "5m") == end
    assert align_request_end(end - timedelta(days=150), "5m") == end - timedelta(days=150)


def test_the_leaf_holds_no_complete_bar_policy():
    """Second review of 191-07, finding 5: which bars are complete vendor answers is policy and
    lives in the fetch layer (src/intelligence/bars/complete_bars.py), never in a leaf."""
    assert not hasattr(ibkr_module, "complete_intraday_bars")


@pytest.mark.asyncio
async def test_the_walk_asks_on_the_grid_and_hands_every_served_bar_on_with_its_record():
    """Two chunks back from a clock-time end: every endDateTime is on the 5m grid, and every bar
    the vendor returns, the one starting at the request end too, reaches on_observation with the
    record of the request that served it (window_end = that request's end), so the fetch layer
    can judge it; the leaf drops nothing."""
    asked: list[str] = []

    def answer(stamps):
        out = []
        for ts in stamps:
            bar = MagicMock()
            bar.date = ts
            bar.open = bar.high = bar.low = bar.close = 1.0
            bar.volume = 10
            out.append(bar)
        return out

    async def fake_req(contract, **kwargs):
        asked.append(kwargs["endDateTime"])
        end = datetime.strptime(kwargs["endDateTime"], "%Y%m%d-%H:%M:%S").replace(tzinfo=UTC)
        # a vendor that also returns the bar starting at the end (as a partial would be)
        return answer([end - timedelta(minutes=5), end])

    ib = MagicMock()
    ib.reqHistoricalDataAsync = AsyncMock(side_effect=fake_req)
    provider = IBKRProvider(host="127.0.0.1", port=7497, client_id=1)
    provider._ib = ib
    provider._qualified_contracts["KRE"] = MagicMock(secType="")
    observed: list[tuple[object, list[OHLCVBar]]] = []

    original = ibkr_module._MAX_CHUNK_DAYS["5m"]
    ibkr_module._MAX_CHUNK_DAYS["5m"] = 2
    try:
        await provider.fetch_historical_bars(
            symbol="KRE",
            timeframe="5m",
            start=datetime(2007, 6, 22, tzinfo=UTC),
            end=EDGE,
            on_request=lambda record: None,
            on_observation=lambda record, bars: observed.append((record, list(bars))),
        )
    finally:
        ibkr_module._MAX_CHUNK_DAYS["5m"] = original
    assert asked and all(a.endswith(("0:00", "5:00")) for a in asked)
    assert asked[0] == "20070625-14:00:00"
    assert observed
    for record, bars in observed:
        assert len(bars) == 2
        assert bars[-1].timestamp == record.window_end  # the straddler is handed on


def test_request_end_is_sent_in_explicit_utc_form():
    """IBKR reads yyyymmdd-hh:mm:ss as UTC (warning 2174 retires the implied zone, todo 540):
    an aware end in any zone goes out as its UTC wall time, and a naive end is refused rather
    than sent in whatever zone the gateway happens to run in."""
    assert format_request_end(datetime(2026, 10, 23, 20, 0, tzinfo=UTC)) == "20261023-20:00:00"
    eastern = timezone(timedelta(hours=-4))
    assert format_request_end(datetime(2026, 10, 23, 16, 0, tzinfo=eastern)) == "20261023-20:00:00"
    with pytest.raises(ValueError):
        format_request_end(datetime(2026, 10, 23, 20, 0))
