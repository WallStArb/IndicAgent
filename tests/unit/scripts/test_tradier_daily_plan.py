from datetime import UTC, datetime, timedelta

from scripts.infrastructure.backfill.infrastructure_run_tradier_daily import (
    LoadParams,
    plan_symbol_load,
)
from src.providers.tradier import DailyBar

_PARAMS = LoadParams(
    min_session_ratio=0.95, first_date_tolerance_days=7, max_changed_bar_ratio=0.02, rebase=False
)


def _weekday_bars(n: int, start=datetime(2024, 1, 1, tzinfo=UTC), volume: int | None = 100):
    bars, day = [], start
    while len(bars) < n:
        if day.weekday() < 5:
            bars.append(DailyBar(day, 10.0, 11.0, 9.0, 10.5, volume))
        day += timedelta(days=1)
    return bars


def _stored(bar: DailyBar, source="tradier", **change):
    values = {"o": bar.open, "h": bar.high, "l": bar.low, "c": bar.close, "v": bar.volume}
    values.update(change)
    return (values["o"], values["h"], values["l"], values["c"], values["v"], source)


def test_clean_new_name_loads_everything():
    plan = plan_symbol_load(_weekday_bars(300), {}, _PARAMS)
    assert plan.outcome == "loaded"
    assert (plan.n_new, plan.n_changed, len(plan.bars)) == (300, 0, 300)


def test_empty_history_is_no_data():
    assert plan_symbol_load([], {}, _PARAMS).outcome == "no_data"


def test_null_volume_bars_are_dropped_not_filled():
    bars = _weekday_bars(300)
    bars[10] = DailyBar(bars[10].timestamp, 10.0, 11.0, 9.0, 10.5, None)
    plan = plan_symbol_load(bars, {}, _PARAMS)
    assert plan.outcome == "short_history" or len(plan.bars) == 299
    assert plan.detail is None or "null-volume" in plan.detail


def test_history_with_big_gaps_is_short():
    bars = _weekday_bars(300)
    sparse = bars[:100] + bars[200:]  # 100 weekdays missing
    assert plan_symbol_load(sparse, {}, _PARAMS).outcome == "short_history"


def test_history_starting_after_existing_bars_is_short():
    bars = _weekday_bars(300)
    existing = {datetime(2020, 1, 6, tzinfo=UTC): (1.0, 1.0, 1.0, 1.0, 1, "ibkr_named")}
    plan = plan_symbol_load(bars, existing, _PARAMS)
    assert plan.outcome == "short_history" and "starts" in plan.detail


def test_changed_bars_beyond_ratio_are_gated_unless_rebase():
    bars = _weekday_bars(300)
    existing = {b.timestamp: _stored(b, source="ibkr_named", v=80) for b in bars}
    assert plan_symbol_load(bars, existing, _PARAMS).outcome == "gated"
    rebased = plan_symbol_load(bars, existing, LoadParams(0.95, 7, 0.02, rebase=True))
    assert rebased.outcome == "loaded"
    assert rebased.n_changed == 300 and len(rebased.revisions) == 300


def test_identical_reload_changes_nothing():
    bars = _weekday_bars(300)
    existing = {b.timestamp: _stored(b) for b in bars}
    plan = plan_symbol_load(bars, existing, _PARAMS)
    assert (plan.outcome, plan.n_new, plan.n_changed) == ("loaded", 0, 0)


def test_small_revision_under_the_ratio_loads_and_records_old_values():
    bars = _weekday_bars(300)
    existing = {b.timestamp: _stored(b) for b in bars}
    existing[bars[5].timestamp] = _stored(bars[5], c=99.0)
    plan = plan_symbol_load(bars, existing, _PARAMS)
    assert plan.outcome == "loaded" and plan.n_changed == 1
    assert plan.revisions[0][1][3] == 99.0
