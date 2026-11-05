"""isolated_wick and busted_trade_window (todo 594): pure rules over a bar and its neighbours."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import numpy as np
import pytest

from services.bar_scrub import BUSTED_TRADE_WINDOWS, load_busted_trade_windows
from src.intelligence.bars.scrub_rules import (
    BustedTradeWindow,
    ScrubParams,
    SymbolBars,
    busted_trade_window,
    isolated_wick,
)
from tests.unit.bars._builders import seeded_apr

_DAY = 86_400


def _params(**overrides: object) -> ScrubParams:
    return ScrubParams.from_apr(seeded_apr() | overrides, "1d", busted_trade_windows=())


def _bars(rows: list[tuple[float, float, float, float]], *, tf: str = "1d", ts=None) -> SymbolBars:
    o, h, lo, c = (np.array(col, dtype=np.float64) for col in zip(*rows, strict=True))
    if ts is None:
        ts = 1_180_000_000 + np.arange(len(rows), dtype=np.int64) * _DAY
    return SymbolBars(
        symbol="T",
        tf=tf,
        ts_seconds=np.asarray(ts, dtype=np.int64),
        open=o,
        high=h,
        low=lo,
        close=c,
        volume=np.full(len(rows), 1000.0),
    )


# ---------------------------------------------------------------------------
# isolated_wick
# ---------------------------------------------------------------------------


def test_spy_2007_05_25_decimal_shifted_high_flags():
    bars = _bars(
        [
            (151.00, 152.10, 150.74, 151.70),
            (151.49, 1511.70, 151.18, 151.80),  # the stored SPY bar: high 10x the body
            (151.90, 153.21, 151.30, 152.90),
        ]
    )
    flags = isolated_wick(bars, _params())
    assert [(f.index, f.fields) for f in flags] == [(1, ("high",))]
    assert flags[0].detail["high_ratio"] == pytest.approx(1511.70 / 151.80)
    assert flags[0].detail["neighbour_span"] < 1.05


def test_gs_2005_09_27_low_side_shift_flags():
    bars = _bars(
        [
            (120.10, 120.87, 119.30, 119.90),
            (119.70, 120.97, 12.15, 119.77),  # the stored GS bar: low 1/10 of the body
            (119.80, 120.60, 119.40, 120.20),
        ]
    )
    assert [(f.index, f.fields) for f in isolated_wick(bars, _params())] == [(1, ("low",))]


def test_real_wide_day_with_wide_neighbours_does_not_flag():
    """A 2008-style crash day: a 3.3x lower wick, but the neighbouring sessions also range
    widely (the neighbourhood spans 2.6x), so the print is market, not a bad tick."""
    bars = _bars(
        [
            (20.0, 21.0, 9.0, 10.0),
            (10.0, 11.0, 3.0, 10.5),
            (10.5, 16.0, 8.0, 15.0),
        ]
    )
    assert isolated_wick(bars, _params()) == []


def test_ratio_below_threshold_does_not_flag():
    bars = _bars([(100.0, 101.0, 99.0, 100.0), (100.0, 240.0, 99.5, 100.5), (100.5, 101, 99, 100)])
    assert isolated_wick(bars, _params()) == []  # 2.39x < 2.5x


def test_series_boundary_uses_the_one_neighbour_and_a_lone_bar_is_never_judged():
    bars = _bars([(50.0, 50.5, 49.5, 50.2), (50.2, 500.0, 50.0, 50.1)])
    assert [f.index for f in isolated_wick(bars, _params())] == [1]
    assert isolated_wick(_bars([(50.2, 500.0, 50.0, 50.1)]), _params()) == []


def test_non_positive_prices_never_flag():
    bars = _bars([(10.0, 10.1, 9.9, 10.0), (10.0, 10.2, 0.0, 10.1), (10.1, 10.2, -1.0, 10.0)])
    assert isolated_wick(bars, _params()) == []


def test_span_threshold_is_apr():
    bars = _bars([(10.0, 10.1, 8.0, 10.0), (10.0, 40.0, 9.9, 10.1), (10.1, 10.2, 10.0, 10.1)])
    assert [f.index for f in isolated_wick(bars, _params())] == [1]  # span 10.2 / 8.0 = 1.275
    tight = {"threshold.bar_scrub.isolated_wick.max_neighbour_span": 1.2}
    assert isolated_wick(bars, _params(**tight)) == []


# ---------------------------------------------------------------------------
# busted_trade_window
# ---------------------------------------------------------------------------


def _utc(hour: int, minute: int, day: int = 6) -> int:
    return int(datetime(2010, 5, day, hour, minute, tzinfo=UTC).timestamp())


_WINDOW = BustedTradeWindow(_utc(18, 40), _utc(19, 0), 0.60, "flash crash")


def _with_window(params: ScrubParams) -> ScrubParams:
    return dataclasses.replace(params, busted_trade_windows=(_WINDOW,))


def test_flash_crash_5m_stub_prints_flag_against_the_14_40_reference():
    ts = [_utc(18, 30), _utc(18, 35), _utc(18, 45), _utc(18, 50), _utc(19, 0)]
    bars = _bars(
        [
            (41.0, 41.2, 40.5, 40.8),
            (40.8, 41.0, 39.8, 40.0),  # ends 14:40 ET: the reference close 40.0
            (39.0, 39.5, 0.01, 30.0),  # a stub print 99.97% below: broken
            (30.0, 35.0, 30.0, 34.0),  # 25% below the reference: stood
            (34.0, 35.0, 0.01, 34.5),  # outside the window
        ],
        tf="5m",
        ts=ts,
    )
    flags = busted_trade_window(bars, _with_window(_params()))
    assert [(f.index, f.fields) for f in flags] == [(2, ("low",))]
    assert flags[0].detail["reference_close"] == 40.0


def test_daily_bar_judged_against_the_prior_session_close():
    ts = [_utc(0, 0, day=5), _utc(0, 0, day=6), _utc(0, 0, day=7)]
    bars = _bars(
        [(40.0, 40.5, 39.5, 40.0), (40.0, 40.2, 0.01, 39.0), (39.0, 39.5, 0.01, 39.2)],
        ts=ts,
    )
    flags = busted_trade_window(bars, _with_window(_params()))
    assert [f.index for f in flags] == [1]


def test_no_reference_bar_judges_nothing():
    bars = _bars([(40.0, 40.2, 0.01, 39.0)], tf="5m", ts=[_utc(18, 45)])
    assert busted_trade_window(bars, _with_window(_params())) == []


def test_shipped_windows_file_holds_the_flash_crash():
    (window,) = load_busted_trade_windows(BUSTED_TRADE_WINDOWS)
    assert (window.start_s, window.end_s, window.max_deviation) == (_utc(18, 40), _utc(19, 0), 0.6)
    assert window.citation


def test_malformed_window_line_raises(tmp_path):
    path = tmp_path / "w.csv"
    path.write_text("date,start_et,end_et,max_deviation,citation\n2010-05-06,15:00,14:40,0.6,x\n")
    with pytest.raises(ValueError, match="start < end"):
        load_busted_trade_windows(path)


def test_a_bar_inside_two_windows_flags_once():
    second = BustedTradeWindow(_utc(18, 50), _utc(19, 10), 0.60, "second")
    ts = [_utc(0, 0, day=5), _utc(0, 0, day=6)]
    bars = _bars([(40.0, 40.5, 39.5, 40.0), (40.0, 40.2, 0.01, 39.0)], ts=ts)
    params = dataclasses.replace(_params(), busted_trade_windows=(_WINDOW, second))
    assert [f.index for f in busted_trade_window(bars, params)] == [1]


def test_intraday_reference_from_an_earlier_day_is_stale_and_judges_nothing():
    ts = [_utc(19, 55, day=5), _utc(18, 45)]
    bars = _bars([(40.0, 40.2, 39.8, 40.0), (12.0, 12.5, 11.5, 12.0)], tf="5m", ts=ts)
    assert busted_trade_window(bars, _with_window(_params())) == []
