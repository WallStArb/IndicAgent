import random
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from scripts.infrastructure.backfill.infrastructure_run_tradier_daily import (
    TRADIER_OWNED_SQL,
    LoadParams,
    plan_symbol_load,
)
from services.bar_derivation import _SELECT_DAILY_CHANGED_SINCE_SQL
from services.bar_reconciliation_audit import check_tradier_refused
from src.providers.tradier import DailyBar

# Split parameters mirror the live threshold.seam.* seeds (rel_tol 0.002, min_run 5, snap 0.01).
_PARAMS = LoadParams(
    min_session_ratio=0.95,
    first_date_tolerance_days=7,
    max_changed_bar_ratio=0.02,
    rebase=False,
    split_rel_tol=0.002,
    split_min_run=5,
    ratio_snap_tol=0.01,
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
    rebased = plan_symbol_load(bars, existing, replace(_PARAMS, rebase=True))
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


# Plan 185-26 task 1: a nightly refetch whose changes are one constant close ratio across every
# earlier bar is a split the vendor back-adjusted; anything else above the gate stays gated.


def _old_scale(bar: DailyBar, factor: float) -> tuple:
    """The stored bar before a split of `factor` (stored/fresh): prices times factor."""
    return _stored(
        bar,
        o=bar.open * factor,
        h=bar.high * factor,
        l=bar.low * factor,
        c=bar.close * factor,
        v=round(bar.volume / factor),
    )


def test_two_for_one_back_adjustment_is_a_split():
    bars = _weekday_bars(301)
    existing = {b.timestamp: _old_scale(b, 2.0) for b in bars[:300]}
    plan = plan_symbol_load(bars, existing, _PARAMS)
    assert plan.outcome == "loaded"
    assert plan.split is not None
    assert (plan.split.factor, plan.split.kind) == (2.0, "split")
    assert plan.split.effective_date == bars[299].timestamp.date()
    assert plan.split.evidence_days == 300
    assert (plan.n_new, plan.n_changed, len(plan.revisions)) == (1, 300, 300)
    assert plan.revisions[0][1][3] == 21.0  # ohlcv_revision keeps the old-scale close


def test_one_for_ten_reverse_split_is_a_split():
    bars = _weekday_bars(301)
    existing = {b.timestamp: _old_scale(b, 0.1) for b in bars[:300]}
    plan = plan_symbol_load(bars, existing, _PARAMS)
    assert plan.outcome == "loaded"
    assert plan.split is not None
    assert plan.split.kind == "reverse_split"
    assert abs(plan.split.factor - 0.1) < 1e-12


def test_split_crossed_after_missed_nights_keeps_the_new_scale_suffix():
    # Stored bars after the ex-date were already on the new scale: only the prefix changes.
    bars = _weekday_bars(300)
    existing = {b.timestamp: _old_scale(b, 3.0) for b in bars[:250]}
    existing.update({b.timestamp: _stored(b) for b in bars[250:]})
    plan = plan_symbol_load(bars, existing, _PARAMS)
    assert plan.outcome == "loaded" and plan.split is not None
    assert plan.split.factor == 3.0
    assert plan.split.effective_date == bars[249].timestamp.date()
    assert plan.n_changed == 250


def test_noisy_partial_change_is_gated():
    rng = random.Random(185)
    bars = _weekday_bars(300)
    existing = {b.timestamp: _stored(b) for b in bars}
    for b in bars[:150]:
        existing[b.timestamp] = _stored(b, c=b.close * rng.uniform(0.8, 1.2))
    plan = plan_symbol_load(bars, existing, _PARAMS)
    assert plan.outcome == "gated" and plan.split is None


def test_identical_refetch_is_no_change_and_no_split():
    bars = _weekday_bars(300)
    existing = {b.timestamp: _stored(b) for b in bars}
    plan = plan_symbol_load(bars, existing, _PARAMS)
    assert (plan.outcome, plan.n_changed, plan.split) == ("loaded", 0, None)


def test_constant_ratio_inside_one_section_only_is_gated_not_a_split():
    bars = _weekday_bars(300)
    existing = {b.timestamp: _stored(b) for b in bars}
    existing.update({b.timestamp: _old_scale(b, 2.0) for b in bars[100:150]})
    plan = plan_symbol_load(bars, existing, _PARAMS)
    assert plan.outcome == "gated" and plan.split is None


def test_constant_ratio_that_snaps_to_one_is_gated_not_a_split():
    # A uniform 0.4% rescale of the whole history (a bad payload) snaps to 1/1: refused.
    bars = _weekday_bars(301)
    existing = {b.timestamp: _old_scale(b, 1.004) for b in bars[:300]}
    plan = plan_symbol_load(bars, existing, _PARAMS)
    assert plan.outcome == "gated" and plan.split is None


def test_constant_ratio_over_another_vendors_bars_is_a_source_change_not_a_split():
    # A first load over IBKR bars is a source change: --rebase, never an inferred split.
    bars = _weekday_bars(301)
    existing = {
        b.timestamp: _stored(
            b, source="ibkr_named", o=b.open * 2, h=b.high * 2, l=b.low * 2, c=b.close * 2
        )
        for b in bars[:300]
    }
    plan = plan_symbol_load(bars, existing, _PARAMS)
    assert plan.outcome == "gated" and plan.split is None


def test_too_short_a_changed_prefix_is_gated():
    bars = _weekday_bars(303)
    existing = {b.timestamp: _old_scale(b, 2.0) for b in bars[:3]}  # 3 < min_run 5
    plan = plan_symbol_load(bars, existing, _PARAMS)
    assert plan.outcome == "gated" and plan.split is None


def test_nightly_switch_reads_the_apr_value_and_a_missing_key_raises():
    import pytest

    from scripts.infrastructure.backfill.infrastructure_run_tradier_daily import nightly_enabled

    assert nightly_enabled({"infra.tradier.nightly_enabled": "true"})
    assert nightly_enabled({"infra.tradier.nightly_enabled": " True "})
    assert not nightly_enabled({"infra.tradier.nightly_enabled": "false"})
    with pytest.raises(KeyError):
        nightly_enabled({})


def test_job_status_counts_refusals_as_partial_not_failure():
    from scripts.infrastructure.backfill.infrastructure_run_tradier_daily import (
        EXIT_REFUSED,
        job_status,
    )

    assert job_status(0) == "success"
    assert job_status(EXIT_REFUSED) == "partial"
    assert job_status(1) == "failure"


# Plan 185-27: the canonical write carries only new and changed bars, and D1 lands only bars that
# are new or differ from the latest TRADIER observation of their date.


def _latest(bars: list[DailyBar]) -> dict:
    return {b.timestamp.date(): (b.open, b.high, b.low, b.close, b.volume) for b in bars}


def test_plan_writes_only_new_and_changed_bars():
    bars = _weekday_bars(300)
    existing = {b.timestamp: _stored(b) for b in bars[:299]}
    existing[bars[5].timestamp] = _stored(bars[5], c=99.0)
    plan = plan_symbol_load(bars, existing, _PARAMS)
    assert plan.outcome == "loaded" and (plan.n_new, plan.n_changed) == (1, 1)
    assert [b.timestamp for b in plan.writes] == [bars[5].timestamp, bars[299].timestamp]
    assert len(plan.bars) == 300  # the full answer is still the load's bar count


def test_identical_refetch_writes_no_bar():
    bars = _weekday_bars(300)
    plan = plan_symbol_load(bars, {b.timestamp: _stored(b) for b in bars}, _PARAMS)
    assert plan.writes == []


def test_split_refetch_writes_every_changed_bar():
    bars = _weekday_bars(301)
    existing = {b.timestamp: _old_scale(b, 2.0) for b in bars[:300]}
    plan = plan_symbol_load(bars, existing, _PARAMS)
    assert plan.split is not None and len(plan.writes) == 301


def test_d1_identical_refetch_lands_nothing():
    from scripts.infrastructure.backfill.infrastructure_run_tradier_daily import d1_bars_to_land

    bars = _weekday_bars(300)
    assert d1_bars_to_land(bars, _latest(bars)) == []


def test_d1_first_load_lands_every_bar():
    from scripts.infrastructure.backfill.infrastructure_run_tradier_daily import d1_bars_to_land

    bars = _weekday_bars(300)
    assert d1_bars_to_land(bars, {}) == bars


def test_d1_lands_new_and_changed_bars_only():
    from scripts.infrastructure.backfill.infrastructure_run_tradier_daily import d1_bars_to_land

    bars = _weekday_bars(300)
    latest = _latest(bars[:299])
    changed = replace(bars[7], close=bars[7].close + 0.01)
    fresh = bars[:7] + [changed] + bars[8:]
    landed = d1_bars_to_land(fresh, latest)
    assert landed == [changed, bars[299]]


def test_d1_null_volume_compares_as_a_value():
    from scripts.infrastructure.backfill.infrastructure_run_tradier_daily import d1_bars_to_land

    bars = _weekday_bars(10)
    null_bar = replace(bars[3], volume=None)
    fresh = bars[:3] + [null_bar] + bars[4:]
    # Stored null, refetched null: equal. Stored 100, refetched null (or the reverse): differs.
    assert d1_bars_to_land(fresh, _latest(fresh)) == []
    assert d1_bars_to_land(fresh, _latest(bars)) == [null_bar]
    assert d1_bars_to_land(bars, _latest(fresh)) == [bars[3]]


def test_d1_split_back_adjustment_lands_every_changed_bar():
    from scripts.infrastructure.backfill.infrastructure_run_tradier_daily import d1_bars_to_land

    bars = _weekday_bars(301)
    old = {
        b.timestamp.date(): (b.open * 2, b.high * 2, b.low * 2, b.close * 2, b.volume // 2)
        for b in bars[:300]
    }
    assert d1_bars_to_land(bars, old) == bars


# -- ownership and the D7 finding (moved from the deleted nightly's tests, plan 189-07) -------


def test_the_loader_and_d2_use_the_same_ownership_predicate():
    # One predicate: a name some load was accepted for. A later refused load must not hand the
    # name back to IBKR (D2 would then overwrite its bars) or the loader and D2 would disagree.
    d2 = " ".join(_SELECT_DAILY_CHANGED_SINCE_SQL.split())
    assert TRADIER_OWNED_SQL.format(col="$1") in d2
    assert "max(loaded_at)" not in d2


def test_refused_latest_load_of_an_owned_name_is_an_audit_finding():
    result = check_tradier_refused(
        {
            "AAA": ("loaded", None),
            "BBB": ("gated", "40 of 300 existing bars change"),
            "CCC": ("failed", "timeout"),
        }
    )
    assert result.n_findings == 2
    assert result.samples[0].startswith("BBB|gated|")
    assert result.samples[1].startswith("CCC|failed|")


def test_all_loaded_is_clean():
    assert check_tradier_refused({"AAA": ("loaded", None)}).n_findings == 0
