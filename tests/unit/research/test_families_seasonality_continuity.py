"""The H-C seasonality members (drafts H-C). M3 (drafts H-A) was dropped by amendment A4."""

import numpy as np
import pytest

from src.intelligence.research.families import daily_residual as dr
from src.intelligence.research.families import seasonality as sea
from src.intelligence.research.families.common import SESSION_DATES

FLOOR = 3


def _weekdays(start, n):
    days = np.arange(np.datetime64(start), np.datetime64(start) + 2 * n + 14)
    days = days[(days.astype("datetime64[D]").astype(int) + 4) % 7 < 5]
    return days[:n]


# -- H-C ------------------------------------------------------------------------------------


def _panel(years=7, m=6, seed=1):
    dates = _weekdays("2005-01-03", years * 262)
    rng = np.random.default_rng(seed)
    return dates, rng.normal(0, 0.01, (len(dates), m))


def _c1(e, dates, **kw):
    args = {"lags": 5, "min_lags": 3, "max_missing_fraction": 0.25, **kw}
    return sea.seasonal_same_month(
        e, bars_per_session=1, coverage_floor=FLOOR, session_dates=dates, **args
    )


def _c2(e, dates, **kw):
    args = {"window_months": 60, "max_missing_fraction": 0.25, **kw}
    return sea.seasonal_other_months(
        e, bars_per_session=1, coverage_floor=FLOOR, session_dates=dates, **args
    )


def test_label_month_is_the_month_of_the_next_session_and_the_last_row_is_nan():
    dates = np.array(["2006-01-30", "2006-01-31", "2006-02-01"], dtype="datetime64[D]")
    month = sea._month_index(dates)
    assert sea._label_positions(month).tolist() == [0, 1, -1]  # 01-31's label is Feb: 1
    dates = _weekdays("2005-01-03", 262 * 7)
    e = np.random.default_rng(0).normal(0, 0.01, (len(dates), 6))
    assert np.isnan(_c1(e, dates)[-1]).all()


def test_c1_equals_the_mean_of_the_monthly_sums_one_to_k_years_back():
    dates, e = _panel()
    month = sea._month_index(dates)
    monthly = sea._monthly_sums(e, month, 0.25)
    d = len(dates) - 100  # a row late in the panel
    label = int(sea._label_positions(month)[d])
    lags = [label - 12 * k for k in range(1, 6)]
    expected = np.nanmean(np.stack([monthly[p] for p in lags]), axis=0)
    # the statistic before the centred rank is the lag mean; compare through the rank order
    got = _c1(e, dates)[d]
    assert np.array_equal(np.argsort(got), np.argsort(expected))


def test_c2_excludes_the_same_calendar_month_and_has_sign_minus():
    lags = [k for k in range(1, 61) if k % 12]
    assert len(lags) == 55 and all(k % 12 for k in lags)
    dates, e = _panel(years=8)
    month = sea._month_index(dates)
    monthly = sea._monthly_sums(e, month, 0.25)
    d = len(dates) - 100
    label = int(sea._label_positions(month)[d])
    expected = -np.nanmean(np.stack([monthly[label - k] for k in lags]), axis=0)
    got = _c2(e, dates)[d]
    assert np.array_equal(np.argsort(got), np.argsort(expected))


def test_a_month_with_too_many_missing_sessions_is_masked_never_filled():
    dates, e = _panel()
    month = sea._month_index(dates)
    full = sea._monthly_sums(e, month, 0.25)
    gap = e.copy()
    pos = month - month[0]
    rows = np.flatnonzero(pos == 40)
    gap[rows[: len(rows) // 2 + 1], 0] = np.nan
    masked = sea._monthly_sums(gap, month, 0.25)
    assert np.isnan(masked[40, 0]) and np.isfinite(full[40, 0])
    assert np.isnan(masked[0]).all()  # the panel's first month is always masked


def test_c1_needs_three_finite_lags():
    dates, e = _panel()
    month = sea._month_index(dates)
    d = len(dates) - 100
    label = int(sea._label_positions(month)[d])
    blank = e.copy()
    for k in (1, 2, 3):  # three of five lags missing leaves two finite
        blank[(month - month[0]) == label - 12 * k, 0] = np.nan
    monthly = sea._monthly_sums(blank, month, 0.25)
    lag = sea._lag_mean(monthly, month, 12 * np.arange(1, 6), 3)
    assert np.isnan(lag[label, 0]) and np.isfinite(lag[label, 1])


def test_no_row_reads_a_month_that_is_not_complete_at_its_close():
    dates, e = _panel()
    base = _c1(e, dates)
    # Row d reads months before the label month, all complete at d: changing every session
    # after d (the label month's own and later) must not move rows <= d.
    d = len(dates) - 300
    moved = e.copy()
    moved[d + 1 :] = np.random.default_rng(9).normal(0, 1, moved[d + 1 :].shape)
    assert np.array_equal(base[: d + 1], _c1(moved, dates)[: d + 1], equal_nan=True)
    base2 = _c2(e, dates)
    assert np.array_equal(base2[: d + 1], _c2(moved, dates)[: d + 1], equal_nan=True)


def test_history_beyond_the_declared_bound_does_not_move_a_row():
    dates, e = _panel(years=9)
    d = len(dates) - 50
    bound = sea.slot_history_sessions(60)
    old = e.copy()
    old[: d - bound] += 3.0
    assert np.array_equal(_c2(e, dates)[d], _c2(old, dates)[d], equal_nan=True)
    assert np.array_equal(_c1(e, dates)[d], _c1(old, dates)[d], equal_nan=True)


def test_misfit_dates_and_bad_params_refuse():
    dates, e = _panel(years=2)
    with pytest.raises(ValueError, match="session dates"):
        _c1(e, dates[:-1])
    with pytest.raises(ValueError, match="min_lags"):
        _c1(e, dates, lags=2, min_lags=3)
    with pytest.raises(ValueError, match="no month to read"):
        _c2(e, dates, window_months=0)


def test_the_runner_binds_session_dates_only_for_members_that_declare_the_need():
    assert sea.seasonal_same_month.needs_session_dates is True
    assert not getattr(dr.residual_momentum, "needs_session_dates", False)
    assert SESSION_DATES == "session_dates"


def test_member_fn_binds_the_panels_dates_and_refuses_without_a_daily_panel():
    from types import SimpleNamespace

    from src.intelligence.research import panel as panel_mod
    from src.intelligence.research import runner

    dates, e = _panel(years=3)
    close = 100 * np.exp(np.cumsum(e, axis=0))
    panel = panel_mod.daily_panel(close, dates=dates, opens=close, volume=np.ones_like(close))
    spec = SimpleNamespace(construction=SimpleNamespace(coverage_floor=FLOOR))
    member = SimpleNamespace(
        name="c1",
        signal="src.intelligence.research.families.seasonality.seasonal_same_month",
        params={"lags": 2, "min_lags": 1, "max_missing_fraction": 0.25},
    )
    out = runner._member_fn(spec, member, 1, panel)(e)
    assert np.array_equal(out, _c1(e, dates, lags=2, min_lags=1), equal_nan=True)
    with pytest.raises(ValueError, match="needs the daily panel's session dates"):
        runner._member_fn(spec, member, 1, None)
