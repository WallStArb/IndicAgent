"""d2-v5 (todo 587): a calendar_audit split rescales its recorded unadjusted routes and stales no
one; every other split keeps the D-21 stale semantics. effective_date is the last day on the old
scale (migration 400)."""

from __future__ import annotations

import math
from datetime import UTC, date, datetime, timedelta

import pytest

from services.bar_derivation import split_rescale_routes
from src.intelligence.bars.daily_rule import (
    FLAG_PRE_SPLIT,
    PolicyRow,
    derive_daily,
    rescale_routes,
    split_scale,
)
from src.intelligence.bars.derivation import Observation, SplitRecord

_T0 = datetime(2026, 10, 27, 20, 0, tzinfo=UTC)
_RECORDED = datetime(2026, 11, 4, 12, 0, tzinfo=UTC)  # after every observation: stale-eligible
_IBKR_ONLY = (PolicyRow("1d", None, date(1990, 1, 1), None, "observed", "ibkr", None),)
_SMART = frozenset({"SMART", "LEGACY_IMPORT"})


def _sessions(start: date, n: int) -> list[date]:
    days, day = [], start
    while len(days) < n:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    return days


def _obs(day: date, close: float, volume: int = 1000, route: str = "SMART") -> Observation:
    return Observation(f"{route}-{day}", route, day, close, close, close, close, volume, _T0, False)


def _derive(observations, splits):
    return derive_daily(
        observations,
        list(_IBKR_ONLY),
        list(splits),
        symbol="TEST",
        basis_window_sessions=5,
        basis_tolerance_bp=10.0,
    )


# AAPL-like: 2:1 on 2005-02-28, last old-scale session 2005-02-25.
_DAYS = _sessions(date(2005, 2, 21), 8)
_OLD = date(2005, 2, 25)
_OBS = [_obs(d, 100.0 if d <= _OLD else 50.0) for d in _DAYS]


def _split(routes=_SMART, day=_OLD, factor=2.0):
    return SplitRecord(day, _RECORDED, factor, (), frozenset(routes))


def test_a_calendar_split_rescales_its_span_and_flags_nothing():
    result = _derive(_OBS, [_split()])
    closes = {b.bar_date: b.close for b in result.bars}
    assert all(math.isclose(c, 50.0) for c in closes.values())
    old = next(b for b in result.bars if b.bar_date == _OLD)
    assert old.volume == 2000  # a share count on the new scale
    assert not any(
        FLAG_PRE_SPLIT in f.flags for f in getattr(result, "flags", []) if hasattr(f, "flags")
    )
    assert not result.stale_only


def test_the_same_split_recorded_by_another_writer_keeps_the_stale_semantics():
    stale_split = SplitRecord(_OLD, _RECORDED, 2.0)  # no rescale routes: D-21
    result = _derive(_OBS, [stale_split])
    old = next(b for b in result.bars if b.bar_date == _OLD)
    assert old.close == 100.0  # served stale, flagged pre_split_unrefetched (today's behaviour)


def test_effective_date_is_the_last_old_scale_day_inclusive():
    obs = _obs(_OLD, 100.0)
    assert split_scale(obs, [_split()]) == 2.0
    assert split_scale(_obs(_OLD + timedelta(days=3), 50.0), [_split()]) == 1.0


def test_cumulative_factors_multiply_in_effective_date_order():
    early = _split(day=date(2003, 1, 10), factor=1.5)
    late = _split(day=date(2005, 2, 25), factor=2.0)
    obs = _obs(date(2002, 6, 3), 300.0)
    assert split_scale(obs, [late, early]) == 1.5 * 2.0


def test_a_calendar_split_never_rescales_or_stales_another_route():
    alpaca = _obs(_OLD, 100.0, route="ALPACA")
    assert split_scale(alpaca, [_split()]) == 1.0


def test_rescale_routes_follow_the_recorded_raw_series():
    assert rescale_routes("ibkr", "smart_trades") == _SMART
    assert rescale_routes("alpaca", "sip_rth") == frozenset({"ALPACA"})
    for series in (("tradier", "consolidated"), ("ibkr", "named"), ("ibkr", "smart_adjusted")):
        with pytest.raises(ValueError):
            rescale_routes(*series)


def test_the_loader_reads_every_unadjusted_route_and_refuses_a_calendar_row_without_them():
    assert split_rescale_routes("nightly_overlap", None) == frozenset()
    one = '[{"vendor": "ibkr", "kind": "smart_trades"}]'
    assert split_rescale_routes("calendar_audit", one) == _SMART
    both = [{"vendor": "ibkr", "kind": "smart_trades"}, {"vendor": "alpaca", "kind": "sip_rth"}]
    assert split_rescale_routes("calendar_audit", both) == _SMART | {"ALPACA"}
    # d2-v5's first draft recorded one canonical span: such a row (or none) raises, never stales.
    for bad in (None, [], '{"vendor": "ibkr", "kind": "named"}', [{"vendor": "ibkr"}], ["ibkr"]):
        with pytest.raises(ValueError):
            split_rescale_routes("calendar_audit", bad)


def test_a_split_rescales_every_measured_route_across_the_vendor_seam():
    """SNX-shaped (review 2026-11-04): IBKR serves before 2016, Alpaca after, the split is in the
    Alpaca era and both series measured unadjusted. The rule must rescale the IBKR span too, or
    the seam carries a fabricated -log f step."""
    policy = (
        PolicyRow("1d", None, date(1990, 1, 1), date(2016, 1, 4), "observed", "ibkr", None),
        PolicyRow("1d", None, date(2016, 1, 4), None, "observed", "alpaca", "ibkr"),
    )
    ibkr = [_obs(d, 100.0) for d in _sessions(date(2015, 12, 28), 5)]
    split_day = date(2016, 1, 6)
    alpaca = [
        _obs(d, 100.0 if d <= split_day else 50.0, route="ALPACA")
        for d in _sessions(date(2016, 1, 4), 5)
    ]
    split = _split(_SMART | {"ALPACA"}, day=split_day)
    result = derive_daily(
        ibkr + alpaca,
        list(policy),
        [split],
        symbol="TEST",
        basis_window_sessions=5,
        basis_tolerance_bp=10.0,
    )
    assert {b.close for b in result.bars} == {50.0}
    assert len(result.bars) == len({o.bar_date for o in ibkr + alpaca})


def test_split_scale_is_one_left_fold_in_effective_date_order():
    """The lineage view's split_factor_product (migration 568) is float8mul folded from 1 in
    ORDER BY effective_date, then one division: split_scale must be the same IEEE sequence."""
    factors = [(date(2001, 3, 1), 1.5), (date(2004, 7, 1), 4 / 3), (date(2010, 2, 1), 1.25)]
    splits = [_split(day=d, factor=f) for d, f in reversed(factors)]
    obs = _obs(date(2000, 1, 3), 300.0)
    expected = 1.0
    for _, f in factors:
        expected *= f
    assert split_scale(obs, splits) == expected
    rescaled = derive_daily(
        [obs],
        list(_IBKR_ONLY),
        splits,
        symbol="TEST",
        basis_window_sessions=5,
        basis_tolerance_bp=10.0,
    ).bars[0]
    assert rescaled.close == 300.0 / expected and rescaled.volume == math.floor(
        1000 * expected + 0.5
    )
    sql = open("production/migrations/568_canonical_bar_lineage_calendar_rescale.sql").read()
    assert "SFUNC = float8mul" in sql and "INITCOND = '1'" in sql
    assert "split_factor_product(c.factor ORDER BY c.effective_date)" in sql
    assert "o.close / s.scale IS NOT DISTINCT FROM m.close" in sql
    assert "floor(o.volume * s.scale + 0.5)::bigint" in sql
    assert "'unadjusted_routes'" in sql and "'unadjusted_span'" not in sql


def test_a_stale_split_stales_the_bar_on_its_effective_date():
    """d2-v5 fixes d2-v4's off-by-one (lead ruling 2026-11-04): effective_date is the last day on
    the old scale, so an observation dated on it and fetched before the row is stale."""
    from src.intelligence.bars.daily_rule import _stale_for

    overlap_row = SplitRecord(_OLD, _RECORDED, 2.0)  # a nightly_overlap row: no rescale routes
    assert _stale_for(_obs(_OLD, 100.0), overlap_row)
    assert not _stale_for(_obs(_OLD + timedelta(days=3), 50.0), overlap_row)
    evidence = SplitRecord(_OLD, _RECORDED, 2.0, (f"SMART-{_OLD}",))
    assert not _stale_for(_obs(_OLD, 50.0), evidence)  # the refetch that revealed it


def test_a_legacy_observation_under_a_calendar_split_rescales_like_smart():
    """LEGACY_IMPORT sits on SMART's basis on the confirmed spans (2026-11-04: 3 legacy dates in
    1 of 380 splits, both route switches flat), so the rescale treats it identically."""
    smart = _obs(_OLD, 100.0, volume=1001)
    legacy = Observation("L", "LEGACY_IMPORT", _OLD, 100.0, 100.0, 100.0, 100.0, 1001, _T0, True)
    from src.intelligence.bars.daily_rule import _rescaled

    a, b = _rescaled(smart, [_split()]), _rescaled(legacy, [_split()])
    assert (a.open, a.close, a.volume) == (b.open, b.close, b.volume) == (50.0, 50.0, 2002)


def test_a_calendar_row_without_a_finite_calendar_step_raises_in_the_loader():
    """D7 judges a calendar split's date against the calendar's real move; a row without it
    would be judged against 0 (review 2026-11-05)."""
    from services.bar_derivation import split_record

    row = {
        "effective_date": _OLD,
        "recorded_at": _RECORDED,
        "factor": 2.0,
        "evidence_request_ids": [],
        "inferred_by": "calendar_audit",
        "unadjusted_routes": [{"vendor": "ibkr", "kind": "smart_trades"}],
        "calendar_adjusted_step": 0.01,
        "operator_rows_file": False,  # _SELECT_DAILY_SPLITS_SQL's column since d2-v6
    }
    assert split_record(row).calendar_adjusted_step == 0.01
    for bad in (None, float("nan")):
        with pytest.raises(ValueError, match="calendar_adjusted_step"):
            split_record({**row, "calendar_adjusted_step": bad})
    other = {**row, "inferred_by": "operator", "calendar_adjusted_step": None}
    assert split_record(other).calendar_adjusted_step == 0.0
