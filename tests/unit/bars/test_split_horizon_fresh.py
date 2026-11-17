"""split_horizon_fresh's pure count (todo 600, admission design section 5: late splits)."""

from __future__ import annotations

from datetime import UTC, date, datetime

import numpy as np

from src.intelligence.bars.integrity_checks import split_horizon_stale
from src.intelligence.bars.split_rescale import SplitFactor, scales_for_sessions

# NVDA 10:1, effective_date 2024-06-07 (the last session on the old scale)
_NVDA = [SplitFactor(date(2024, 6, 7), 10.0)]
_OLD = datetime(2024, 6, 7, 19, 55, tzinfo=UTC)  # 15:55 ET, old scale
_NEW = datetime(2024, 6, 10, 13, 30, tzinfo=UTC)  # 09:30 ET, new scale
_LATE = datetime(2024, 6, 8, 0, 30, tzinfo=UTC)  # 20:30 ET on 06-07: still the 06-07 session


def _arrays(stamps, raw, canonical, massive=None):
    ts = np.array([int(s.timestamp()) for s in stamps], dtype=np.int64)
    massive = np.ones(len(stamps), dtype=bool) if massive is None else np.array(massive)
    return ts, np.array(canonical, dtype=np.float64), np.array(raw, dtype=np.float64), massive


def test_bars_rescaled_by_the_known_splits_are_fresh():
    ts, close, raw, massive = _arrays([_OLD, _NEW], [1205.0, 121.5], [120.5, 121.5])
    assert split_horizon_stale(ts, close, raw, massive, _NVDA) == 0


def test_bars_selected_before_the_split_was_known_are_stale():
    # canonical still equals raw on the old-scale session: the 10:1 was recorded after selection
    ts, close, raw, massive = _arrays([_OLD, _NEW], [1205.0, 121.5], [1205.0, 121.5])
    assert split_horizon_stale(ts, close, raw, massive, _NVDA) == 1


def test_a_voided_split_still_applied_is_stale():
    ts, close, raw, massive = _arrays([_OLD, _NEW], [1205.0, 121.5], [120.5, 121.5])
    assert split_horizon_stale(ts, close, raw, massive, []) == 1


def test_session_date_is_new_york_not_utc():
    ts, close, raw, massive = _arrays([_LATE], [1000.0], [100.0])
    assert split_horizon_stale(ts, close, raw, massive, _NVDA) == 0


def test_a_massive_bar_with_no_raw_row_counts_and_other_vendors_are_ignored():
    ts, close, raw, massive = _arrays(
        [_OLD, _NEW, _NEW], [np.nan, 121.5, 999.0], [120.5, 121.5, 1.0], [True, True, False]
    )
    assert split_horizon_stale(ts, close, raw, massive, _NVDA) == 1


def test_the_check_replays_selection_arithmetic_bit_for_bit():
    # two splits multiplied in effective-date order, one division: the stored value is exactly
    # what canonicalize_winners writes, so equality is exact, never a tolerance
    splits = [SplitFactor(date(2024, 6, 7), 10.0), SplitFactor(date(2021, 7, 19), 4.0)]
    raw_close = 1234.567
    scale = scales_for_sessions([date(2021, 7, 19)], splits)[date(2021, 7, 19)]
    stamp = datetime(2021, 7, 19, 19, 55, tzinfo=UTC)
    ts, close, raw, massive = _arrays([stamp], [raw_close], [raw_close / scale])
    assert split_horizon_stale(ts, close, raw, massive, splits) == 0
    ts, close, raw, massive = _arrays([stamp], [raw_close], [raw_close / scale * (1 + 1e-15)])
    assert split_horizon_stale(ts, close, raw, massive, splits) == 1


def test_no_massive_bar_means_nothing_to_judge():
    ts, close, raw, massive = _arrays([_OLD], [1.0], [2.0], [False])
    assert split_horizon_stale(ts, close, raw, massive, _NVDA) == 0


def test_a_massive_bar_under_a_raw_kind_or_the_adjusted_kind_under_another_vendor_counts():
    # bar 0: vendor massive, kind sip_flat_agg in canonical (unadjusted: never rescaled);
    # bar 1: kind sip_flat_adj, vendor alpaca (a misrouted identity); bar 2: correct
    ts, close, raw, massive = _arrays(
        [_OLD, _NEW, _NEW], [1205.0, 121.5, 121.5], [1205.0, 121.5, 121.5], [False, True, True]
    )
    vendor_massive = np.array([True, False, True])
    assert split_horizon_stale(ts, close, raw, massive, _NVDA, vendor_massive) == 2
    assert split_horizon_stale(ts, close, raw, massive, _NVDA) == 0
    only_raw_kind = np.array([True, False, False])
    assert (
        split_horizon_stale(ts[:1], close[:1], raw[:1], massive[:1], _NVDA, only_raw_kind[:1]) == 1
    )


# --- routed_horizon_stale: a series a split row names unadjusted (todo 625) ---

from src.intelligence.bars.integrity_checks import routed_horizon_stale  # noqa: E402


def test_routed_series_bars_must_equal_raw_over_the_routed_scale():
    old = datetime(2026, 7, 20, 19, 55, tzinfo=UTC).timestamp()
    new = datetime(2026, 7, 21, 13, 30, tzinfo=UTC).timestamp()
    ts = np.array([old, new])
    raw = np.array([24.5, 11.08])
    vendor = np.array(["alpaca", "alpaca"], dtype=object)
    kind = np.array(["sip_rth", "sip_rth"], dtype=object)
    routed = {("alpaca", "sip_rth"): [SplitFactor(date(2026, 7, 20), 2.2)]}
    stale = np.array([24.5, 11.08])
    fresh = np.array([24.5 / 2.2, 11.08])
    assert routed_horizon_stale(ts, stale, raw, vendor, kind, routed) == 1  # the old-scale bar
    assert routed_horizon_stale(ts, fresh, raw, vendor, kind, routed) == 0
    assert routed_horizon_stale(ts, stale, raw, vendor, kind, {}) == 0  # no row names it
    other = np.array(["named", "named"], dtype=object)
    assert routed_horizon_stale(ts, stale, raw, vendor, other, routed) == 0
    assert routed_horizon_stale(ts, fresh, np.array([np.nan, 11.08]), vendor, kind, routed) == 1
