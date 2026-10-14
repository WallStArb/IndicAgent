"""IBKR chunk edges (review finding 2 of plan 191-07): a request end inside a bar truncates it.

KRE 2007-06-25 14:00 UTC: the walk's chunk ended at 14:02:29 (the run's clock time), IBKR
answered a 14:00 bar of 45.61 x4 and volume 0, and last-wins raw took it as a restatement of the
whole bar (45.65, volume 9,500). The walk now asks on the bar grid and drops any bar that
straddles the request end or is still forming.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.providers import ibkr as ibkr_module
from src.providers.base import OHLCVBar
from src.providers.ibkr import IBKRProvider, align_request_end, complete_intraday_bars

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


def test_the_bar_straddling_the_request_end_is_dropped():
    whole = _bar(datetime(2007, 6, 25, 13, 55, tzinfo=UTC))
    straddler = _bar(datetime(2007, 6, 25, 14, 0, tzinfo=UTC), volume=0)
    kept, dropped = complete_intraday_bars([whole, straddler], "5m", EDGE, NOW)
    assert kept == [whole] and dropped == [straddler]


def test_a_bar_still_forming_is_dropped():
    now = datetime(2026, 10, 12, 19, 57, 30, tzinfo=UTC)  # ADM 2026-10-12 19:55 served mid-bar
    forming = _bar(datetime(2026, 10, 12, 19, 55, tzinfo=UTC))
    done = _bar(datetime(2026, 10, 12, 19, 50, tzinfo=UTC))
    end = datetime(2026, 10, 13, tzinfo=UTC)
    assert complete_intraday_bars([done, forming], "5m", end, now) == ([done], [forming])


def test_session_open_bars_of_coarse_grids_are_judged_by_their_grid_block():
    # 1h 13:30 is the first bar of the 13:00-14:00 block; 4h 13:30 of 12:00-16:00
    end = datetime(2026, 10, 9, 14, 0, tzinfo=UTC)
    open_1h = _bar(datetime(2026, 10, 9, 13, 30, tzinfo=UTC), "1h")
    assert complete_intraday_bars([open_1h], "1h", end, NOW)[0] == [open_1h]
    open_4h = _bar(datetime(2026, 10, 9, 13, 30, tzinfo=UTC), "4h")
    assert complete_intraday_bars([open_4h], "4h", end, NOW)[1] == [open_4h]
    assert complete_intraday_bars([open_4h], "4h", end + timedelta(hours=2), NOW)[0] == [open_4h]


def test_daily_bars_pass_through():
    bar = _bar(datetime(2026, 10, 14, tzinfo=UTC), "1d")
    assert complete_intraday_bars([bar], "1d", EDGE, EDGE) == ([bar], [])


@pytest.mark.asyncio
async def test_the_walk_asks_on_the_grid_and_never_stores_a_partial_bar():
    """Two chunks back from a clock-time end: every endDateTime is on the 5m grid, and a bar the
    vendor returns at or after the request end is not handed to on_chunk."""
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
        end = datetime.strptime(kwargs["endDateTime"], "%Y%m%d %H:%M:%S").replace(tzinfo=UTC)
        # a vendor that also returns the bar starting at the end (as a partial would be)
        return answer([end - timedelta(minutes=5), end])

    ib = MagicMock()
    ib.reqHistoricalDataAsync = AsyncMock(side_effect=fake_req)
    provider = IBKRProvider(host="127.0.0.1", port=7497, client_id=1)
    provider._ib = ib
    provider._qualified_contracts["KRE"] = MagicMock(secType="")
    stored: list[OHLCVBar] = []

    async def on_chunk(bars):
        stored.extend(bars)

    original = ibkr_module._MAX_CHUNK_DAYS["5m"]
    ibkr_module._MAX_CHUNK_DAYS["5m"] = 2
    try:
        await provider.fetch_historical_bars(
            symbol="KRE",
            timeframe="5m",
            start=datetime(2007, 6, 22, tzinfo=UTC),
            end=EDGE,
            on_chunk=on_chunk,
        )
    finally:
        ibkr_module._MAX_CHUNK_DAYS["5m"] = original
    assert asked and all(a.endswith(("0:00", "5:00")) for a in asked)
    assert asked[0] == "20070625 14:00:00"
    ends = {datetime.strptime(a, "%Y%m%d %H:%M:%S").replace(tzinfo=UTC) for a in asked}
    assert stored and not any(b.timestamp in ends for b in stored)
