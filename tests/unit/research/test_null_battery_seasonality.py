"""The H-C seasonality E17 battery (todo 635): production members on a dated synthetic panel."""

import numpy as np

from src.intelligence.research import null_battery_seasonality as battery
from src.intelligence.research.families import seasonality


def test_members_and_memories_come_from_the_registered_spec():
    got = battery.members()
    assert [name for name, *_ in got] == ["seasonal_same_month_5", "seasonal_other_months_5"]
    assert {memory for *_, memory in got} == {seasonality.slot_history_sessions(60)}
    assert got[0][2] == {"lags": 5, "min_lags": 3, "max_missing_fraction": 0.25}


def test_the_calendar_is_weekdays_and_panels_cover_the_longest_read_and_the_e17_memory():
    dates = battery.session_dates(10)
    assert dates[0] == np.datetime64("2000-01-03") and dates[5] == np.datetime64("2000-01-10")
    assert all(np.busday_count(a, b) == 1 for a, b in zip(dates[:-1], dates[1:], strict=True))
    longest_read = seasonality.slot_history_sessions(60)
    for sc in battery.scenarios():
        assert sc.sessions >= longest_read + 1408 + 252 + 126, sc.name


def test_scenarios_mirror_the_daily_battery_cells_and_diagnostics():
    names = [sc.name for sc in battery.scenarios()]
    assert names[0] == "seasonal_gaussian" and len(names) == 8
    assert battery.DIAGNOSTIC_CELLS <= set(names) and len(battery.DIAGNOSTIC_CELLS) == 2
    gate = battery.static_gate()
    assert gate.battery == battery.__name__ and gate.static_sd == (0.06,)


def test_one_simulation_scores_both_members_and_the_book_with_finite_statistics():
    sc = battery.scenarios()[0]
    out = battery.simulate(sc, 3)
    assert set(out) == {"seasonal_same_month_5", "seasonal_other_months_5", "book_equal"}
    assert all(np.isfinite(t) and 0.0 <= p <= 1.0 for t, p in out.values())
    series = battery.simulate_series(sc, 3)
    assert all(np.isfinite(s).any() for s in series.values())
