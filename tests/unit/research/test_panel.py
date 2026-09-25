import numpy as np
import pytest

from src.intelligence.research import panel as panel_mod
from src.intelligence.research.panel import Panel, daily_panel, forward_returns, fwd_span
from src.intelligence.research.snapshot import build_grid


def _bars(times_utc: list[str], closes: list[float]):
    ts = np.array(times_utc, dtype="datetime64[ns]")
    c = np.array(closes, dtype=float)
    return ts, c - 0.5, c, np.full(len(c), 100.0)


def test_forward_returns_daily_is_next_open_to_following_open():
    opens = np.exp(np.arange(6.0))[:, None]
    fwd = forward_returns(opens)
    np.testing.assert_allclose(fwd[:4, 0], 1.0)  # ln(open[t+2] / open[t+1])
    assert np.isnan(fwd[4:]).all()


def test_forward_returns_missing_open_is_nan():
    fwd = forward_returns(np.array([[100.0], [np.nan], [103.0], [102.0]]))
    assert np.isnan(fwd[0, 0]) and np.isfinite(fwd[1, 0])


def test_forward_returns_horizon_and_session_boundary():
    opens = np.exp(np.arange(8.0))[:, None]
    session = np.repeat([0, 1], 4)
    fwd = forward_returns(opens, horizon=2, session=session)
    # t=0: enter row 1, exit row 3, same session.
    np.testing.assert_allclose(fwd[0, 0], 2.0)
    # t=1: enter row 2 (session 0), exit row 4 (session 1): crosses the overnight gap.
    assert np.isnan(fwd[1, 0]) and np.isnan(fwd[2, 0])
    # t=3: signal on session 0's last bar enters session 1's first open, exits within it.
    np.testing.assert_allclose(fwd[3, 0], 2.0)
    assert np.isnan(fwd[5:]).all()
    assert fwd_span(2) == 3


def test_forward_returns_rejects_zero_horizon():
    with pytest.raises(ValueError):
        forward_returns(np.ones((5, 1)), horizon=0)


def test_panel_rejects_ragged_grid():
    with pytest.raises(ValueError, match="whole number"):
        Panel(
            tf="1h",
            symbols=("a",),
            timestamps=np.arange(5),
            bars_per_session=2,
            valid=np.ones(5, dtype=bool),
            open=np.ones((5, 1)),
            close=np.ones((5, 1)),
            volume=np.ones((5, 1)),
        )


def test_intraday_grid_keeps_time_of_day_and_marks_empty_slots():
    # Four sessions of 1h bars in EST (UTC-5) at 09:30, 10:00, 11:00. The last session lacks
    # 11:00 for both symbols (a half day), and "b" has one stray 08:00 pre-market bar: 1 of 4
    # sessions is not the schedule, 3 of 4 is.
    days = ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]
    full = [f"{d}T{t}" for d in days[:3] for t in ("14:30", "15:00", "16:00")]
    half = [f"{days[3]}T14:30", f"{days[3]}T15:00"]
    closes_a = list(range(1, 12))
    bars = {
        "a": _bars(full + half, closes_a),
        "b": _bars(["2024-01-02T13:00"] + full + half, [99] + [10 * c for c in closes_a]),
    }
    p = build_grid(bars, "1h")
    assert p.bars_per_session == 3 and p.n_sessions == 4
    assert p.manifest["dropped_off_grid_bars"] == 1  # the 08:00 bar
    np.testing.assert_array_equal(p.session, np.repeat(np.arange(4), 3))
    assert p.valid[:11].all() and not p.valid[11]
    np.testing.assert_array_equal(p.close[:11, 0], closes_a)
    np.testing.assert_array_equal(p.close[:11, 1], [10 * c for c in closes_a])
    assert np.isnan(p.close[11]).all()
    assert str(p.timestamps[11]) == "2024-01-05T16:00"  # the missing slot keeps its time


def test_daily_grid_uses_the_union_of_session_dates():
    bars = {
        "a": _bars(["2024-01-02T05:00", "2024-01-04T05:00"], [1, 2]),
        "b": _bars(["2024-01-03T05:00"], [5]),
    }
    p = build_grid(bars, "1d")
    assert p.bars_per_session == 1
    np.testing.assert_array_equal(
        p.timestamps, np.array(["2024-01-02", "2024-01-03", "2024-01-04"], dtype="datetime64[D]")
    )
    np.testing.assert_array_equal(p.close[:, 0], [1, np.nan, 2])


@pytest.mark.parametrize("stamp", ["2024-01-06T05:00", "2024-12-25T05:00"])  # Sat, Christmas
def test_grid_rejects_bars_on_non_trading_days(stamp):
    with pytest.raises(ValueError, match="non-NYSE-trading"):
        build_grid({"a": _bars([stamp], [1])}, "1d")


def test_save_and_load_round_trip_verifies_hash(tmp_path):
    p = daily_panel(np.arange(6.0).reshape(3, 2) + 1, symbols=("x", "y"), manifest={"k": 1})
    path = panel_mod.save(p, tmp_path)
    loaded = panel_mod.load(path)
    assert loaded.symbols == ("x", "y") and loaded.manifest == {"k": 1}
    np.testing.assert_array_equal(loaded.close, p.close)
    arr = np.load(path / "close.npy")
    arr[0, 0] = 99.0
    np.save(path / "close.npy", arr)
    with pytest.raises(ValueError, match="hash mismatch"):
        panel_mod.load(path)


def _close_exit_grid():
    """Two 3-bar sessions for one name; open[t] = e^t, close[t] = e^(t + 0.5)."""
    opens = np.exp(np.arange(6.0))[:, None]
    closes = np.exp(np.arange(6.0) + 0.5)[:, None]
    return opens, closes, np.repeat([0, 1], 3)


def test_close_exit_uses_the_session_final_close():
    opens, closes, session = _close_exit_grid()
    fwd = forward_returns(opens, horizon=1, session=session, closes=closes)
    np.testing.assert_allclose(fwd[0, 0], 1.0)  # enter row 1, exit row 2's open
    # Enter row 2 (the final slot), exit at the same bar's close.
    np.testing.assert_allclose(fwd[1, 0], 0.5)
    # Signal on session 0's last bar: enter session 1's first open, exit within session 1.
    np.testing.assert_allclose(fwd[2, 0], 1.0)
    np.testing.assert_allclose(fwd[4, 0], 0.5)
    assert np.isnan(fwd[5, 0])  # no entry row


def test_close_exit_longer_horizon_is_capped_at_the_final_close():
    opens, closes, session = _close_exit_grid()
    fwd = forward_returns(opens, horizon=5, session=session, closes=closes)
    np.testing.assert_allclose(fwd[0, 0], np.log(closes[2, 0] / opens[1, 0]))


def test_close_exit_missing_final_bar_gives_nan_not_an_earlier_close():
    opens, closes, session = _close_exit_grid()
    opens = np.hstack([opens, opens])
    closes = np.hstack([closes, closes])
    closes[2, 1] = np.nan  # name 1 has no bar in session 0's final slot; name 0 does
    fwd = forward_returns(opens, horizon=1, session=session, closes=closes)
    np.testing.assert_allclose(fwd[1, 0], 0.5)
    assert np.isnan(fwd[1, 1])


def test_close_exit_half_day_uses_that_day_last_bar():
    opens, closes, session = _close_exit_grid()
    opens[2] = np.nan  # session 0's last grid slot is empty for every name (a half day)
    closes[2] = np.nan
    fwd = forward_returns(opens, horizon=1, session=session, closes=closes)
    # Enter row 1, the half day's last bar: exit at its own close, not the next session.
    np.testing.assert_allclose(fwd[0, 0], 0.5)
    assert np.isnan(fwd[1, 0])  # entry slot is past the day's last bar


def test_close_exit_never_reads_the_next_session():
    opens, closes, session = _close_exit_grid()
    base = forward_returns(opens, horizon=2, session=session, closes=closes)
    opens2, closes2 = opens.copy(), closes.copy()
    opens2[3:] *= 7.0
    closes2[3:] *= 7.0
    moved = forward_returns(opens2, horizon=2, session=session, closes=closes2)
    np.testing.assert_array_equal(base[:2], moved[:2])


def test_close_exit_needs_session():
    with pytest.raises(ValueError, match="session"):
        forward_returns(np.ones((4, 1)), closes=np.ones((4, 1)))


def test_session_on_a_daily_panel_is_rejected():
    with pytest.raises(ValueError, match="intraday"):
        forward_returns(np.ones((4, 1)), session=np.arange(4))
