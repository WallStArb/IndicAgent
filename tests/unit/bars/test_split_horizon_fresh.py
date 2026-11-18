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


def test_the_same_kind_under_another_vendor_is_not_the_routed_series():
    # a route names (vendor, kind): matching on kind alone would count this ibkr sip_rth bar
    ts = np.array([datetime(2026, 7, 20, 19, 55, tzinfo=UTC).timestamp()])
    routed = {("alpaca", "sip_rth"): [SplitFactor(date(2026, 7, 20), 2.2)]}
    args = (ts, np.array([24.5]), np.array([24.5]))
    ibkr = np.array(["ibkr"], dtype=object)
    sip_rth = np.array(["sip_rth"], dtype=object)
    assert routed_horizon_stale(*args, ibkr, sip_rth, routed) == 0


# --- routed_seam_breaks: a restated routed series is divided twice (todo 626) ---

from src.intelligence.bars.integrity_checks import routed_seam_breaks  # noqa: E402


def _seam(close_old: float, open_new: float, *, new_vendor: str = "massive"):
    """Canonical 5m as it is stored: the named Alpaca series up to the effective date, then
    Massive (sip_flat_adj, already on the current scale) from the next session."""
    ts = np.array(
        [
            datetime(2026, 7, 20, 19, 55, tzinfo=UTC).timestamp(),
            datetime(2026, 7, 21, 13, 30, tzinfo=UTC).timestamp(),
        ]
    )
    names = np.array(["alpaca", new_vendor], dtype=object)
    kinds = np.array(["sip_rth", "sip_flat_adj"], dtype=object)
    return ts, np.array([close_old, open_new]), np.array([close_old, open_new]), names, kinds


ROUTED = {("alpaca", "sip_rth"): [SplitFactor(date(2026, 7, 20), 2.2)]}


def test_a_continuous_routed_seam_passes():
    ts, o, c, v, k = _seam(11.12, 10.915)  # the CLBK shape after the rescale
    assert routed_seam_breaks(ts, o, c, v, k, ROUTED, 0.3) == 0


def test_a_restated_series_divided_twice_steps_up_by_the_factor_and_fails():
    ts, o, c, v, k = _seam(24.465 / 2.2 / 2.2, 10.915)  # old side divided twice, new side as served
    assert routed_seam_breaks(ts, o, c, v, k, ROUTED, 0.3) == 1


def test_an_undivided_old_side_is_not_counted_here():
    # the unadjusted shape equals a real drop (RTX 2020-04-03 spin-off, 86.01 to 51.0 under a x2
    # row); routed_horizon_stale and the 1d guard judge an unrescaled series
    ts, o, c, v, k = _seam(24.465, 10.915)
    assert routed_seam_breaks(ts, o, c, v, k, ROUTED, 0.3) == 0
    rtx = {("alpaca", "sip_rth"): [SplitFactor(date(2026, 7, 20), 2.0)]}
    ts, o, c, v, k = _seam(86.01, 51.0)
    assert routed_seam_breaks(ts, o, c, v, k, rtx, 0.3) == 0


def test_the_same_series_on_both_sides_is_judged_too():
    ts, o, c, v, k = _seam(24.465 / 2.2 / 2.2, 10.915, new_vendor="alpaca")
    k[1] = "sip_rth"
    assert routed_seam_breaks(ts, o, c, v, k, ROUTED, 0.3) == 1


def test_an_unmeasurable_seam_or_an_unnamed_series_is_not_judged():
    ts, o, c, v, k = _seam(24.465 / 2.2 / 2.2, 10.915)
    assert routed_seam_breaks(ts[:1], o[:1], c[:1], v[:1], k[:1], ROUTED, 0.3) == 0  # no after
    assert routed_seam_breaks(ts[1:], o[1:], c[1:], v[1:], k[1:], ROUTED, 0.3) == 0  # no before
    assert routed_seam_breaks(ts, o, c, v, k, {}, 0.3) == 0
    other = {("alpaca", "other_kind"): ROUTED[("alpaca", "sip_rth")]}
    assert routed_seam_breaks(ts, o, c, v, k, other, 0.3) == 0
    gap = ts.copy()
    gap[1] += 10 * 86400  # beyond the bracket
    assert routed_seam_breaks(gap, o, c, v, k, ROUTED, 0.3) == 0
    assert routed_seam_breaks(ts[:0], o[:0], c[:0], v[:0], k[:0], ROUTED, 0.3) == 0
