"""src/intelligence/bars/complete_bars.py: which served bars are complete vendor answers.

Second review of plan 191-07, finding 5. Pure, no database.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.intelligence.bars.complete_bars import block_end, partial_json, split_complete

SETTLE = timedelta(minutes=30)
EDGE = datetime(2007, 6, 25, 14, 2, 29, tzinfo=UTC)  # KRE: a chunk end inside the 14:00 bar


def _bar(ts: datetime, volume: int = 100) -> dict:
    return {"timestamp": ts, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": volume}


def test_the_bar_straddling_the_request_end_is_partial():
    whole = _bar(datetime(2007, 6, 25, 13, 55, tzinfo=UTC))
    straddler = _bar(datetime(2007, 6, 25, 14, 0, tzinfo=UTC), volume=0)
    later = datetime(2026, 10, 14, tzinfo=UTC)
    kept, partial = split_complete(
        [whole, straddler], "5m", answered_at=later, request_end=EDGE, settle=SETTLE
    )
    assert kept == [whole] and partial == [straddler]


def test_forming_is_judged_against_the_answer_time_not_the_parse_time():
    # answered at 19:52:30: the 19:50 bar was still forming, whatever time the bars are parsed
    answered = datetime(2026, 10, 12, 19, 52, 30, tzinfo=UTC)
    done = _bar(datetime(2026, 10, 12, 19, 45, tzinfo=UTC))
    forming = _bar(datetime(2026, 10, 12, 19, 50, tzinfo=UTC))
    kept, partial = split_complete([done, forming], "5m", answered_at=answered, settle=SETTLE)
    assert (kept, partial) == ([done], [forming])


def test_the_session_closing_bar_is_final_only_after_the_settle_delay():
    # ADM 2026-10-12 19:55 UTC (15:55 ET): the closing auction revised it after the close
    last = _bar(datetime(2026, 10, 12, 19, 55, tzinfo=UTC))
    before_last = _bar(datetime(2026, 10, 12, 19, 50, tzinfo=UTC))
    close = datetime(2026, 10, 12, 20, 0, tzinfo=UTC)
    kept, partial = split_complete(
        [before_last, last], "5m", answered_at=close + timedelta(minutes=10), settle=SETTLE
    )
    assert (kept, partial) == ([before_last], [last])
    kept, _ = split_complete([last], "5m", answered_at=close + SETTLE, settle=SETTLE)
    assert kept == [last]


def test_an_early_close_uses_the_calendar_close():
    # 2026-11-27 closes 13:00 ET (18:00 UTC): its 17:55 bar is the closing one
    last = _bar(datetime(2026, 11, 27, 17, 55, tzinfo=UTC))
    early = datetime(2026, 11, 27, 18, 5, tzinfo=UTC)
    assert split_complete([last], "5m", answered_at=early, settle=SETTLE)[1] == [last]


def test_coarse_session_open_bars_are_judged_by_their_grid_block():
    open_1h = _bar(datetime(2026, 10, 9, 13, 30, tzinfo=UTC))
    assert block_end(open_1h["timestamp"], "1h") == datetime(2026, 10, 9, 14, 0, tzinfo=UTC)
    end = datetime(2026, 10, 9, 14, 0, tzinfo=UTC)
    later = datetime(2026, 10, 10, tzinfo=UTC)
    assert split_complete([open_1h], "1h", answered_at=later, request_end=end)[0] == [open_1h]
    assert split_complete([open_1h], "4h", answered_at=later, request_end=end)[1] == [open_1h]


def test_daily_bars_keep_d_191_j():
    bar = _bar(datetime(2026, 10, 12, tzinfo=UTC))
    at_close = datetime(2026, 10, 12, 20, 0, tzinfo=UTC)
    assert split_complete([bar], "1d", answered_at=at_close)[0] == [bar]
    assert split_complete([bar], "1d", answered_at=at_close - timedelta(seconds=1))[1] == [bar]


def test_partial_bars_are_recorded_with_their_values():
    bar = _bar(datetime(2026, 10, 12, 19, 55, tzinfo=UTC), volume=380459)
    assert partial_json([bar]) == [
        {"t": "2026-10-12T19:55:00+00:00", "o": 1.0, "h": 1.0, "l": 1.0, "c": 1.0, "v": 380459}
    ]


def test_a_bar_starting_inside_its_block_is_partial_but_a_session_open_is_not():
    later = datetime(2026, 10, 14, tzinfo=UTC)
    cut = _bar(datetime(2026, 3, 9, 15, 26, 34, tzinfo=UTC), volume=4828)  # HON
    assert split_complete([cut], "5m", answered_at=later)[1] == [cut]
    session_open = _bar(datetime(2026, 3, 9, 13, 30, tzinfo=UTC))
    assert split_complete([session_open], "1h", answered_at=later)[0] == [session_open]
