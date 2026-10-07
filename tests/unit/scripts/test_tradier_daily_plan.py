"""The Tradier loader's raw-only plan (plans 185-26, 185-27 and 185-38).

The plan compares the answer with the name's latest Tradier D1 observations: D1 takes only new
and revised bars; an answer revising more than max_revision_ratio of them is gated (nothing
lands) unless it is a back-adjusted split or --rebase; a short answer lands with a note.
"""

import random
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from scripts.infrastructure.backfill.infrastructure_run_tradier_daily import (
    TRADIER_OWNED_SQL,
    LoadParams,
    d1_bars_to_land,
    plan_symbol_load,
)
from services.bar_derivation import _SELECT_DAILY_CHANGED_SINCE_SQL
from services.bar_reconciliation_audit import check_tradier_refused
from src.providers.tradier import DailyBar

# Split parameters mirror the live threshold.seam.* seeds (rel_tol 0.002, min_run 5, snap 0.01).
_PARAMS = LoadParams(
    min_session_ratio=0.95,
    first_date_tolerance_days=7,
    max_revision_ratio=0.02,
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


def _latest(bars: list[DailyBar]) -> dict:
    return {b.timestamp.date(): (b.open, b.high, b.low, b.close, b.volume) for b in bars}


def _old_scale(bars: list[DailyBar], factor: float) -> dict:
    """Latest observations before a split of `factor` (old/fresh): prices times factor."""
    return {
        b.timestamp.date(): (
            b.open * factor,
            b.high * factor,
            b.low * factor,
            b.close * factor,
            round(b.volume / factor),
        )
        for b in bars
    }


def test_clean_new_name_lands_everything():
    plan = plan_symbol_load(_weekday_bars(300), {}, _PARAMS)
    assert plan.outcome == "loaded"
    assert (plan.n_new, plan.n_changed, len(plan.landed), len(plan.bars)) == (300, 0, 300, 300)


def test_empty_history_is_no_data():
    assert plan_symbol_load([], {}, _PARAMS).outcome == "no_data"


def test_null_volume_bars_land_raw():
    bars = _weekday_bars(300)
    bars[10] = DailyBar(bars[10].timestamp, 10.0, 11.0, 9.0, 10.5, None)
    plan = plan_symbol_load(bars, {}, _PARAMS)
    assert plan.outcome == "loaded" and len(plan.landed) == 300


def test_short_history_lands_and_is_noted_not_refused():
    bars = _weekday_bars(300)
    sparse = bars[:100] + bars[200:]  # 100 weekdays missing
    plan = plan_symbol_load(sparse, {}, _PARAMS)
    assert plan.outcome == "loaded" and len(plan.landed) == 200
    assert plan.detail.startswith("short_history")


def test_answer_starting_after_earlier_observations_is_noted():
    bars = _weekday_bars(300)
    earlier = _latest(_weekday_bars(5, start=datetime(2020, 1, 6, tzinfo=UTC)))
    plan = plan_symbol_load(bars, earlier, _PARAMS)
    assert plan.outcome == "loaded" and "starts" in plan.detail


def test_identical_refetch_lands_nothing():
    bars = _weekday_bars(300)
    plan = plan_symbol_load(bars, _latest(bars), _PARAMS)
    assert (plan.outcome, plan.n_new, plan.n_changed, plan.landed) == ("loaded", 0, 0, [])


def test_a_small_revision_lands_only_the_new_and_revised_bars():
    bars = _weekday_bars(300)
    latest = _latest(bars[:299])
    revised = replace(bars[5], close=10.75)
    fresh = bars[:5] + [revised] + bars[6:]
    plan = plan_symbol_load(fresh, latest, _PARAMS)
    assert plan.outcome == "loaded" and (plan.n_new, plan.n_changed) == (1, 1)
    assert plan.landed == [revised, bars[299]]
    assert len(plan.bars) == 300


def test_revisions_beyond_the_ratio_are_gated_and_land_nothing_unless_rebase():
    bars = _weekday_bars(300)
    latest = _latest(bars)
    rng = random.Random(7)
    fresh = [replace(b, close=b.close + 0.01) if rng.random() < 0.03 else b for b in bars]
    plan = plan_symbol_load(fresh, latest, _PARAMS)
    assert plan.outcome == "gated" and plan.landed == [] and plan.split is None
    rebased = plan_symbol_load(fresh, latest, replace(_PARAMS, rebase=True))
    assert rebased.outcome == "loaded" and rebased.n_changed == len(rebased.landed) > 6


def test_two_for_one_back_adjustment_is_a_split_and_lands():
    bars = _weekday_bars(301)
    plan = plan_symbol_load(bars, _old_scale(bars[:300], 2.0), _PARAMS)
    assert plan.outcome == "loaded" and plan.split is not None
    assert (plan.split.factor, plan.split.kind) == (2.0, "split")
    assert plan.split.effective_date == bars[299].timestamp.date()
    assert len(plan.landed) == 301


def test_one_for_ten_reverse_split_is_a_split():
    bars = _weekday_bars(300)
    plan = plan_symbol_load(bars, _old_scale(bars[:250], 0.1), _PARAMS)
    assert plan.split is not None and plan.split.kind == "reverse_split"


def test_noisy_partial_change_is_gated():
    bars = _weekday_bars(300)
    latest = _latest(bars)
    for b in bars[:20]:
        latest[b.timestamp.date()] = (b.open, b.high, b.low, b.close * 1.3, b.volume)
    for b in bars[20:40]:
        latest[b.timestamp.date()] = (b.open, b.high, b.low, b.close * 1.7, b.volume)
    assert plan_symbol_load(bars, latest, _PARAMS).outcome == "gated"


def test_constant_ratio_that_snaps_to_one_is_gated_not_a_split():
    bars = _weekday_bars(300)
    plan = plan_symbol_load(bars, _old_scale(bars[:100], 1.0005), _PARAMS)
    assert plan.outcome == "gated" and plan.split is None


def test_too_short_a_changed_prefix_is_gated():
    bars = _weekday_bars(303)
    # 3 < min_run 5 revised bars out of 100 latest observations: over 0.02, no split.
    latest = {**_old_scale(bars[:3], 2.0), **_latest(bars[3:100])}
    plan = plan_symbol_load(bars, latest, _PARAMS)
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


def test_d1_null_volume_compares_as_a_value():
    bars = _weekday_bars(10)
    null_bar = replace(bars[3], volume=None)
    fresh = bars[:3] + [null_bar] + bars[4:]
    # Stored null, refetched null: equal. Stored 100, refetched null (or the reverse): differs.
    assert d1_bars_to_land(fresh, _latest(fresh)) == []
    assert d1_bars_to_land(fresh, _latest(bars)) == [null_bar]
    assert d1_bars_to_land(bars, _latest(fresh)) == [bars[3]]


# -- ownership and the D7 finding ------------------------------------------------------------


def test_the_loader_and_the_fetcher_probe_use_the_same_policy_ownership_predicate():
    # One predicate (plan 185-38): the open 1d policy row names Tradier and a Tradier
    # observation exists. The fetcher (phase 189) reads it through tradier_owned.
    probe = " ".join(_SELECT_DAILY_CHANGED_SINCE_SQL.split())
    assert " ".join(TRADIER_OWNED_SQL.format(col="$1").split()) in probe
    assert "bar_source_policy" in TRADIER_OWNED_SQL and "valid_to IS NULL" in TRADIER_OWNED_SQL
    assert "o.route = 'TRADIER'" in TRADIER_OWNED_SQL
    assert "ohlcv_load" not in TRADIER_OWNED_SQL


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
