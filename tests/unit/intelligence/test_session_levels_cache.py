"""Regression: Phase 165 FeatureCache session-levels state is timestamp-driven (never
bar-count, D-07), resets on real ET session / ISO-week / Asian-block boundaries, and
reads None rather than a manufactured value before its first boundary transition (D-01).
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.intelligence.feature_cache import FeatureCache
from tests.unit.intelligence.test_swing_fib_trend_structure_primitives import (
    _make_cfg,
)


def _bars_utc(start_utc: datetime, count: int, step_minutes: int, price_fn):
    """Build `count` (ts, open, high, low, close) tuples on a UTC grid starting at
    `start_utc`, `step_minutes` apart. `price_fn(i)` returns (open, high, low, close)
    for the i-th bar (0-indexed)."""
    bars = []
    for i in range(count):
        ts = start_utc + timedelta(minutes=step_minutes * i)
        o, h, low, c = price_fn(i)
        bars.append((ts, o, h, low, c))
    return bars


def _cfg(**overrides: object):
    """Default FeatureFactoryConfig -- session_levels_asia_start_et_hour/asia_end_et_hour
    default to 20/4 (Plan 01) unless overridden."""
    return _make_cfg(**overrides)


# ---------------------------------------------------------------------------
# (a) cold start
# ---------------------------------------------------------------------------


def test_session_levels_cold_start_is_none() -> None:
    cache = FeatureCache()
    cfg = _cfg()
    ts = datetime(2026, 7, 6, 13, 30, tzinfo=UTC)  # Monday 9:30 AM ET (EDT)
    cache.update_session_levels(ts, 100.0, 101.0, 99.0, 100.5, cfg)

    for attr in (
        "_sl_prior_session_high",
        "_sl_prior_session_low",
        "_sl_prior_session_close",
        "_sl_overnight_high",
        "_sl_overnight_low",
        "_prior_wk_high",
        "_prior_wk_low",
        "_prior_wk_close",
    ):
        assert getattr(cache, attr) is None, (
            f"D-01: {attr} must stay None after the very first call -- "
            "no session/week has completed yet, never a manufactured value"
        )
    assert cache._sl_gap_filled == 0.0


# ---------------------------------------------------------------------------
# (b) session rollover snapshots the completed session
# ---------------------------------------------------------------------------


def test_session_levels_rollover_snapshots_prior_session() -> None:
    cache = FeatureCache()
    cfg = _cfg()

    day1 = datetime(2026, 7, 6, 13, 30, tzinfo=UTC)  # Monday 9:30 AM ET
    day1_bars = [
        (day1, 100.0, 101.0, 99.0, 100.5),
        (day1 + timedelta(minutes=5), 100.5, 102.0, 98.0, 101.0),
        (day1 + timedelta(minutes=10), 101.0, 101.5, 100.0, 100.8),
    ]
    for ts, o, h, low, c in day1_bars:
        cache.update_session_levels(ts, o, h, low, c, cfg)

    assert cache._sl_session_high == 102.0
    assert cache._sl_session_low == 98.0
    assert cache._sl_session_close == 100.8
    assert cache._sl_prior_session_high is None  # no session has completed yet

    day2 = datetime(2026, 7, 7, 13, 30, tzinfo=UTC)  # Tuesday 9:30 AM ET
    cache.update_session_levels(day2, 105.0, 106.0, 104.0, 105.5, cfg)

    assert cache._sl_prior_session_high == 102.0
    assert cache._sl_prior_session_low == 98.0
    assert cache._sl_prior_session_close == 100.8
    assert cache._sl_session_high == 106.0
    assert cache._sl_session_low == 104.0
    assert cache._sl_session_open == 105.0


# ---------------------------------------------------------------------------
# (c) overnight accumulator freezes at rollover
# ---------------------------------------------------------------------------


def test_session_levels_overnight_freezes_at_rollover() -> None:
    cache = FeatureCache()
    cfg = _cfg()

    rth_bar = datetime(2026, 7, 6, 13, 30, tzinfo=UTC)  # Monday 9:30 AM ET
    cache.update_session_levels(rth_bar, 100.0, 101.0, 99.0, 100.5, cfg)
    assert (
        cache._sl_on_acc_high is None
    ), "an RTH bar alone must never populate the overnight accumulator"

    post_close = datetime(2026, 7, 6, 20, 5, tzinfo=UTC)  # 4:05 PM ET, same session_day
    cache.update_session_levels(post_close, 100.0, 103.0, 97.0, 100.0, cfg)
    late_evening = datetime(2026, 7, 7, 2, 0, tzinfo=UTC)  # 10:00 PM ET, same session_day
    cache.update_session_levels(late_evening, 100.0, 104.0, 96.0, 100.0, cfg)
    pre_open = datetime(
        2026, 7, 7, 7, 0, tzinfo=UTC
    )  # 3:00 AM ET next day, still session_day Jul 6
    cache.update_session_levels(pre_open, 100.0, 105.0, 95.0, 100.0, cfg)

    assert cache._sl_on_acc_high == 105.0
    assert cache._sl_on_acc_low == 95.0
    assert cache._sl_overnight_high is None, "not yet frozen -- the session hasn't rolled over"

    next_rth = datetime(2026, 7, 7, 13, 30, tzinfo=UTC)  # Tuesday 9:30 AM ET -- rollover
    cache.update_session_levels(next_rth, 110.0, 111.0, 109.0, 110.5, cfg)

    assert cache._sl_overnight_high == 105.0
    assert cache._sl_overnight_low == 95.0
    assert cache._sl_on_acc_high is None
    assert cache._sl_on_acc_low is None


# ---------------------------------------------------------------------------
# (d) gap_filled latches within a session and resets at rollover
# ---------------------------------------------------------------------------


def test_session_levels_gap_filled_latches_and_resets() -> None:
    cache = FeatureCache()
    cfg = _cfg()

    day1 = datetime(2026, 7, 6, 13, 30, tzinfo=UTC)
    cache.update_session_levels(
        day1, 100.0, 101.0, 99.0, 100.0, cfg
    )  # prior_session_close will be 100.0

    day2_bar1 = datetime(
        2026, 7, 7, 13, 30, tzinfo=UTC
    )  # rollover; range [104,106] doesn't bracket 100
    cache.update_session_levels(day2_bar1, 105.0, 106.0, 104.0, 105.5, cfg)
    assert cache._sl_gap_filled == 0.0

    day2_bar2 = day2_bar1 + timedelta(minutes=5)  # low drops to 99 -- now brackets prior close 100
    cache.update_session_levels(day2_bar2, 105.0, 105.0, 99.0, 101.0, cfg)
    assert cache._sl_gap_filled == 1.0

    day2_bar3 = day2_bar1 + timedelta(minutes=10)  # price runs far away; latch must STAY set
    cache.update_session_levels(day2_bar3, 150.0, 151.0, 149.0, 150.0, cfg)
    assert cache._sl_gap_filled == 1.0

    day3_bar1 = datetime(2026, 7, 8, 13, 30, tzinfo=UTC)  # rollover -- resets to 0.0
    cache.update_session_levels(day3_bar1, 200.0, 201.0, 199.0, 200.5, cfg)
    assert cache._sl_gap_filled == 0.0

    # A session that never brackets the prior close stays 0.0 throughout.
    cache2 = FeatureCache()
    d1 = datetime(2026, 7, 6, 13, 30, tzinfo=UTC)
    cache2.update_session_levels(d1, 100.0, 101.0, 99.0, 100.0, cfg)
    d2 = datetime(2026, 7, 7, 13, 30, tzinfo=UTC)
    for offset in (0, 5, 10):
        cache2.update_session_levels(
            d2 + timedelta(minutes=offset), 150.0, 160.0, 150.0, 155.0, cfg
        )
        assert cache2._sl_gap_filled == 0.0


# ---------------------------------------------------------------------------
# (e) Asian block cycle key
# ---------------------------------------------------------------------------


def test_session_levels_asian_block_cycle_key() -> None:
    cache = FeatureCache()
    cfg = _cfg()  # defaults: asia_start_et_hour=20, asia_end_et_hour=4

    outside_before = datetime(2026, 7, 6, 23, 0, tzinfo=UTC)  # 19:00 ET -- outside
    cache.update_session_levels(outside_before, 100.0, 100.0, 99.0, 100.0, cfg)
    assert cache._sl_asia_high is None

    block_start = datetime(2026, 7, 7, 0, 30, tzinfo=UTC)  # 20:30 ET Jul 6 -- inside, block start
    cache.update_session_levels(block_start, 105.0, 105.0, 104.0, 105.0, cfg)
    assert cache._sl_asia_high == 105.0
    assert cache._sl_asia_low == 104.0

    same_block = datetime(2026, 7, 7, 6, 0, tzinfo=UTC)  # 02:00 ET Jul 7 -- inside, same block
    cache.update_session_levels(same_block, 106.0, 106.0, 103.0, 106.0, cfg)
    assert cache._sl_asia_high == 106.0, "midnight-straddle: same block, extremes extend"
    assert cache._sl_asia_low == 103.0

    outside_after = datetime(2026, 7, 7, 9, 0, tzinfo=UTC)  # 05:00 ET -- outside
    cache.update_session_levels(outside_after, 200.0, 200.0, 1.0, 200.0, cfg)
    assert cache._sl_asia_high == 106.0, "outside-window bars must never touch the accumulator"
    assert cache._sl_asia_low == 103.0

    new_block = datetime(2026, 7, 8, 0, 30, tzinfo=UTC)  # 20:30 ET Jul 7 -- inside, NEW block
    cache.update_session_levels(new_block, 110.0, 110.0, 109.0, 110.0, cfg)
    assert cache._sl_asia_high == 110.0, "new block must reset before accumulating"
    assert cache._sl_asia_low == 109.0

    # Parametrized non-default asia hours: proves the APR keys are actually read.
    moved_cache = FeatureCache()
    moved_cfg = _cfg(session_levels_asia_start_et_hour=22, session_levels_asia_end_et_hour=2)
    # 20:30 ET is inside the DEFAULT window but OUTSIDE this moved window (start=22).
    moved_cache.update_session_levels(block_start, 105.0, 105.0, 104.0, 105.0, moved_cfg)
    assert moved_cache._sl_asia_high is None, (
        "with asia_start_et_hour=22, a 20:30 ET bar must NOT start a block -- "
        "proves the APR key value, not a hardcoded 20, gates the window"
    )


# ---------------------------------------------------------------------------
# (f) weekly snapshot on ISO-week rollover
# ---------------------------------------------------------------------------


def test_weekly_snapshot_on_iso_week_rollover() -> None:
    cache = FeatureCache()

    w1_bar1 = datetime(2026, 7, 6, 13, 30, tzinfo=UTC)  # Monday, week 1
    cache.update_wk_vwap(w1_bar1, 101.0, 99.0, 100.0, 1000.0)
    w1_bar2 = datetime(2026, 7, 7, 13, 30, tzinfo=UTC)  # Tuesday, still week 1
    cache.update_wk_vwap(w1_bar2, 103.0, 97.0, 102.0, 1000.0)

    assert cache._prior_wk_high is None  # first week hasn't completed yet
    assert cache._wk_high == 103.0
    assert cache._wk_low == 97.0

    w2_bar1 = datetime(2026, 7, 13, 13, 30, tzinfo=UTC)  # next Monday, week 2 -- rollover
    cache.update_wk_vwap(w2_bar1, 110.0, 108.0, 109.0, 1000.0)

    assert cache._prior_wk_high == 103.0
    assert cache._prior_wk_low == 97.0
    assert cache._prior_wk_close == 102.0
    assert cache._wk_high == 110.0, "new week's running high restarts from its own first bar"
    assert cache._wk_low == 108.0


# ---------------------------------------------------------------------------
# (g) weekly VWAP behaviour unchanged by the D-09 extension
# ---------------------------------------------------------------------------


def test_weekly_vwap_behaviour_unchanged() -> None:
    cache = FeatureCache()

    ts1 = datetime(2026, 7, 6, 13, 30, tzinfo=UTC)
    cache.update_wk_vwap(ts1, 102.0, 98.0, 101.0, 1000.0)
    expected_tp_vol_sum_1 = (102.0 + 98.0 + 101.0) / 3.0 * 1000.0
    expected_vol_sum_1 = 1000.0
    assert math.isclose(cache._wk_tp_vol_sum, expected_tp_vol_sum_1, rel_tol=1e-12)
    assert math.isclose(cache._wk_vol_sum, expected_vol_sum_1, rel_tol=1e-12)
    expected_vwap_1 = expected_tp_vol_sum_1 / expected_vol_sum_1
    assert cache.above_wk_vwap == float(101.0 > expected_vwap_1)

    ts2 = datetime(2026, 7, 7, 13, 30, tzinfo=UTC)
    cache.update_wk_vwap(ts2, 105.0, 100.0, 103.0, 1500.0)
    expected_tp_vol_sum_2 = expected_tp_vol_sum_1 + (105.0 + 100.0 + 103.0) / 3.0 * 1500.0
    expected_vol_sum_2 = expected_vol_sum_1 + 1500.0
    assert math.isclose(cache._wk_tp_vol_sum, expected_tp_vol_sum_2, rel_tol=1e-12)
    assert math.isclose(cache._wk_vol_sum, expected_vol_sum_2, rel_tol=1e-12)
    expected_vwap_2 = expected_tp_vol_sum_2 / expected_vol_sum_2
    assert cache.above_wk_vwap == float(103.0 > expected_vwap_2)


# ---------------------------------------------------------------------------
# (h) DST boundary
# ---------------------------------------------------------------------------


def test_session_levels_dst_boundary() -> None:
    cfg = _cfg()

    # 2026 US spring-forward: Sunday March 8. Friday Mar 6 is EST (UTC-5);
    # Monday Mar 9 is EDT (UTC-4).
    cache_spring = FeatureCache()
    friday_post_open = datetime(2026, 3, 6, 14, 35, tzinfo=UTC)  # 9:35 AM EST
    cache_spring.update_session_levels(friday_post_open, 100.0, 101.0, 99.0, 100.5, cfg)
    assert cache_spring._sl_session_day == datetime(2026, 3, 6).date()

    monday_post_open = datetime(2026, 3, 9, 13, 35, tzinfo=UTC)  # 9:35 AM EDT
    cache_spring.update_session_levels(monday_post_open, 100.0, 101.0, 99.0, 100.5, cfg)
    assert cache_spring._sl_session_day == datetime(2026, 3, 9).date(), (
        "session_day must advance exactly once across the DST weekend, "
        "never stay stuck on Friday or skip past Monday"
    )

    # 2026 US fall-back: Sunday November 1. Friday Oct 30 is EDT (UTC-4);
    # Monday Nov 2 is EST (UTC-5).
    cache_fall = FeatureCache()
    friday_fall = datetime(2026, 10, 30, 13, 35, tzinfo=UTC)  # 9:35 AM EDT
    cache_fall.update_session_levels(friday_fall, 100.0, 101.0, 99.0, 100.5, cfg)
    assert cache_fall._sl_session_day == datetime(2026, 10, 30).date()

    monday_fall = datetime(2026, 11, 2, 14, 35, tzinfo=UTC)  # 9:35 AM EST
    cache_fall.update_session_levels(monday_fall, 100.0, 101.0, 99.0, 100.5, cfg)
    assert (
        cache_fall._sl_session_day == datetime(2026, 11, 2).date()
    ), "session_day must advance exactly once across the fall-back weekend too"


# ---------------------------------------------------------------------------
# (i) no collision with Phase 163/164 accumulator state
# ---------------------------------------------------------------------------


def test_session_levels_no_collision_with_amd_or_vp_state() -> None:
    """Direct guard for T-165-14. Deliberately drives update_session_levels
    BEFORE update_session_vp/update_overnight_range on every bar (the reverse
    of production call order) -- both mutators derive an identical session-day
    value from the identical bar_ts, so a shared-key collision is invisible
    when the production ordering (VP first) is used verbatim: whichever
    mutator's write "wins" writes the SAME value the other would have written
    anyway. Reversing the order makes update_session_vp the second-running
    mutator instead, which is what actually exposes the hazard: if
    update_session_levels wrote to the shared _session_day key, VP's own
    `session_day != self._session_day` reset check would already see "no
    change" (session_levels advanced it moments earlier in the same bar), so
    VP's _sess_bars would never reset at a real session boundary and would
    grow across days instead of restarting -- a divergence from a
    session_levels-free cache that this test would catch either direction the
    real call sites are ever wired.
    """
    cfg = _cfg()
    cache_with = FeatureCache()
    cache_without = FeatureCache()

    bars = _bars_utc(
        datetime(2026, 7, 6, 13, 30, tzinfo=UTC),
        6,
        1440,  # one bar per calendar day -- every bar is a session rollover
        lambda i: (100.0 + i, 101.0 + i, 99.0 + i, 100.5 + i),
    )
    for ts, o, h, low, c in bars:
        cache_with.update_session_levels(ts, o, h, low, c, cfg)
        cache_with.update_session_vp(ts, h, low, c, 1000.0, cfg)
        cache_with.update_overnight_range(ts, h, low, cfg)

        cache_without.update_session_vp(ts, h, low, c, 1000.0, cfg)
        cache_without.update_overnight_range(ts, h, low, cfg)

    assert cache_with._session_day == cache_without._session_day
    assert cache_with._sess_bars == cache_without._sess_bars
    assert cache_with._overnight_day == cache_without._overnight_day
    assert cache_with._overnight_high == cache_without._overnight_high
    assert cache_with._overnight_low == cache_without._overnight_low


# ---------------------------------------------------------------------------
# (j) structural: wired at all 3 call sites
# ---------------------------------------------------------------------------


def test_session_levels_wired_at_all_three_call_sites() -> None:
    ff = "\n".join(
        line
        for line in Path("src/intelligence/feature_factory.py").read_text().splitlines()
        if not line.lstrip().startswith("#")
    )
    fp = "\n".join(
        line
        for line in Path("services/feature_vector_pipeline.py").read_text().splitlines()
        if not line.lstrip().startswith("#")
    )
    assert ff.count("update_session_levels(") == 1, (
        "T-164-07: update_session_levels() must be wired into compute_batch()'s "
        "per-bar loop exactly once (compute_batch())"
    )
    assert fp.count("update_session_levels(") == 2, (
        "T-164-07: update_session_levels() must be wired into exactly two sites "
        "in feature_vector_pipeline.py -- the live per-bar handler "
        "(_process_bar_compute) and the warm-up replay block (_get_cache)"
    )
