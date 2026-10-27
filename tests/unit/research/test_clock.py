"""clock.closes_at (184 B1b, design D7 guard 3): the calendar-exact availability time per row."""

import dataclasses

import numpy as np
import pytest

from src.intelligence.research.clock import closes_at
from tests.unit.research import mtf_fixtures as fx


def _closes(panel):
    return closes_at(panel.timestamps, panel.valid, panel.tf, panel.bars_per_session)


def _session_closes(panel, day):
    rows = fx.session_rows(panel, day)
    return rows, _closes(panel)[rows]


@pytest.mark.parametrize(
    ("day", "last_close"),
    [(fx.BEFORE_DST_SPRING, "2024-03-08T21:00"), (fx.DST_SPRING, "2024-03-11T20:00")],
)
def test_1h_short_last_bucket_closes_at_session_close_across_spring_dst(day, last_close):
    panel = fx.intraday_grid("1h", [fx.BEFORE_DST_SPRING, fx.DST_SPRING])
    assert panel.bars_per_session == 7
    rows, closes = _session_closes(panel, day)
    assert closes[-1] == fx.utc(last_close)
    starts = panel.timestamps[rows].astype("datetime64[ns]")
    np.testing.assert_array_equal(closes[:-1], starts[:-1] + np.timedelta64(60, "m"))
    # The 15:30 ET bucket is 30 minutes long, not 60.
    assert closes[-1] - starts[-1] == np.timedelta64(30, "m")


def test_1h_half_day_bucket_caps_at_1300_et():
    panel = fx.intraday_grid("1h", [fx.BEFORE_HALF_DAY, fx.HALF_DAY])
    rows, closes = _session_closes(panel, fx.HALF_DAY)
    starts = panel.timestamps[rows].astype("datetime64[ns]")
    i = int(np.flatnonzero(starts == fx.utc("2024-11-29T17:30"))[0])  # 12:30 ET
    assert closes[i] == fx.utc("2024-11-29T18:00")  # 13:00 ET, not 13:30
    finite = closes[~np.isnat(closes)]
    assert len(finite) == 4 and (finite <= fx.utc("2024-11-29T18:00")).all()
    # Slots after the early close are untraded: NaT.
    assert np.isnat(closes[4:]).all() and not panel.valid[rows[4:]].any()


def test_5m_missing_final_bar_is_nat_and_previous_row_is_slot_end():
    panel = fx.intraday_grid("5m", [fx.BEFORE_DST_FALL, fx.DST_FALL])
    rows = fx.session_rows(panel, fx.DST_FALL)
    dropped = fx.drop_rows(panel, [rows[-1]])
    closes = _closes(dropped)
    assert np.isnat(closes[rows[-1]])
    prev = rows[-2]
    assert closes[prev] == panel.timestamps[prev].astype("datetime64[ns]") + np.timedelta64(5, "m")
    assert closes[prev] == fx.utc("2024-11-04T20:55")


@pytest.mark.parametrize("tf", ["5m", "15m", "1h"])
def test_invalid_row_is_nat_on_every_intraday_tf(tf):
    panel = fx.intraday_grid(tf, [fx.BEFORE_DST_SPRING, fx.DST_SPRING])
    dropped = fx.drop_rows(panel, [0, 3])
    closes = _closes(dropped)
    assert np.isnat(closes[[0, 3]]).all()
    assert not np.isnat(closes[[1, 2]]).any()


def test_invalid_row_is_nat_on_1d():
    panel = fx.drop_rows(fx.daily_grid(), [2])
    closes = _closes(panel)
    assert np.isnat(closes[2]) and not np.isnat(np.delete(closes, 2)).any()


def test_1d_is_each_sessions_calendar_close():
    panel = fx.daily_grid()
    closes = dict(zip(panel.timestamps.astype("datetime64[D]").astype(object), _closes(panel)))
    assert closes[fx.BEFORE_DST_SPRING] == fx.utc("2024-03-08T21:00")
    assert closes[fx.DST_SPRING] == fx.utc("2024-03-11T20:00")
    assert closes[fx.HALF_DAY] == fx.utc("2024-11-29T18:00")


@pytest.mark.parametrize(
    ("day", "last_close"),
    [(fx.BEFORE_DST_FALL, "2024-11-01T20:00"), (fx.DST_FALL, "2024-11-04T21:00")],
)
def test_15m_last_row_across_fall_dst(day, last_close):
    panel = fx.intraday_grid("15m", [fx.BEFORE_DST_FALL, fx.DST_FALL])
    _, closes = _session_closes(panel, day)
    assert closes[-1] == fx.utc(last_close)
    assert panel.bars_per_session == 26


def test_traded_slot_after_early_close_is_refused():
    panel = fx.intraday_grid("1h", [fx.BEFORE_HALF_DAY, fx.HALF_DAY])
    rows = fx.session_rows(panel, fx.HALF_DAY)
    late = int(rows[4])  # 13:30 ET on the half day: no calendar session
    valid = panel.valid.copy()
    valid[late] = True
    with pytest.raises(ValueError, match=f"row {late} starts at .* outside the 2024-11-29"):
        closes_at(panel.timestamps, valid, "1h", panel.bars_per_session)


def test_traded_row_on_a_non_session_date_is_refused():
    panel = fx.daily_grid([fx.BEFORE_HALF_DAY, fx.HALF_DAY])
    stamps = panel.timestamps.copy()
    stamps[0] = np.datetime64("2024-11-28")  # Thanksgiving
    with pytest.raises(ValueError, match="row 0 .*not an NYSE session"):
        closes_at(stamps, panel.valid, "1d", 1)


def test_unknown_tf_and_bad_shapes_raise():
    panel = fx.daily_grid([fx.HALF_DAY])
    with pytest.raises(ValueError, match="unknown tf"):
        closes_at(panel.timestamps, panel.valid, "30m", 1)
    with pytest.raises(ValueError, match="valid has shape"):
        closes_at(panel.timestamps, panel.valid[:0], "1d", 1)
    intraday = fx.intraday_grid("1h", [fx.HALF_DAY, fx.BEFORE_HALF_DAY])
    with pytest.raises(ValueError, match="whole number"):
        closes_at(intraday.timestamps[:-1], intraday.valid[:-1], "1h", intraday.bars_per_session)


def test_returns_ns_and_leaves_inputs_alone():
    panel = fx.intraday_grid("15m", [fx.HALF_DAY])
    before = dataclasses.replace(panel, timestamps=panel.timestamps.copy())
    out = _closes(panel)
    assert out.dtype == np.dtype("datetime64[ns]") and out.shape == panel.valid.shape
    np.testing.assert_array_equal(panel.timestamps, before.timestamps)
