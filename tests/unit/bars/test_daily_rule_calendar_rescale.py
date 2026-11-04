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
    derive_daily_v2,
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
    return derive_daily_v2(
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


def test_rescale_routes_follow_the_recorded_canonical_span():
    assert rescale_routes("ibkr", "named") == _SMART
    assert rescale_routes("ibkr", "fallback") == _SMART
    assert rescale_routes("alpaca", "sip_rth") == frozenset({"ALPACA"})
    with pytest.raises(ValueError):
        rescale_routes("tradier", "consolidated")


def test_the_loader_reads_the_span_and_refuses_a_calendar_row_without_one():
    assert split_rescale_routes("nightly_overlap", None) == frozenset()
    assert split_rescale_routes("calendar_audit", '{"vendor": "ibkr", "kind": "named"}') == _SMART
    with pytest.raises(ValueError):
        split_rescale_routes("calendar_audit", None)


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
