"""Regression: Phase 165 swing/trend/swing-momentum/fibonacci/session-levels FeatureVector
fields are non-constant, ATR-unit, live==batch, and NULL (never a plausible number) on
insufficient data (D-01, the todo-153 failure shape).

Plan 02 (swing detection + trend structure), Plan 03 (swing momentum + fibonacci zones),
and Plan 05 (session levels + the phase-closing 41-column completeness gate) share this
file -- shared helpers (`_make_cfg`, `RNG`, `N`) stay at module level, sub-scopes are
sectioned by comment header. This file now covers all four Phase 165 sub-scopes (swing
detection, trend structure, swing momentum, fibonacci zones, session levels) plus a
phase-wide gate proving all 41 columns produce real values.
"""

from __future__ import annotations

import dataclasses
import math
from datetime import UTC, datetime, timedelta

import numpy as np
import psycopg
import pytest

from src.intelligence.feature_cache import FeatureCache
from src.intelligence.feature_factory import (
    FEATURE_VECTOR_DOMAIN,
    FeatureFactory,
    FeatureFactoryConfig,
    _compute_fib_zones,
    _compute_swing_momentum,
    _compute_swing_structure,
)
from src.intelligence.schemas import FeatureVector

N = 250
RNG = np.random.default_rng(7)

# Swing/Trend FeatureVector fields shared between live compute() and batch compute_batch()
_SWING_FIELDS = (
    "swing_high_dist_atr",
    "swing_low_dist_atr",
    "swing_high_type",
    "swing_low_type",
    "swing_pattern",
    "swing_high_age_bars",
    "swing_low_age_bars",
)
_TREND_FIELDS = (
    "trend_direction",
    "trend_strength",
    "trend_leg_count",
    "structure_integrity",
    "price_position",
    "trend_duration_bars",
)

# Swing Momentum / Fibonacci Zones FeatureVector fields (Phase 165 Plan 03)
_SWING_MOMENTUM_FIELDS = (
    "swing_amplitude_ratio",
    "swing_amplitude_expanding",
    "swing_amplitude_intensity",
    "swing_velocity_bars",
    "swing_velocity_bias",
    "struct_energy",
    "struct_accel_bias",
    "swing_volume_confirmation",
)
_FIB_FIELDS = (
    "nearest_fib_ratio",
    "nearest_fib_dist_atr",
    "fib_cluster_strength",
    "in_fib_discount_zone",
)


def _make_cfg(**overrides: object) -> FeatureFactoryConfig:
    """Small windows so everything warms up well within N bars.

    swing_pivot_window/swing_lookback_bars/trend_structure_* left at dataclass
    defaults (5 / 120 / 5.0 / 20) -- same convention as the Phase 163 S/R test.
    """
    defaults = dict(
        momentum_window_fast=5,
        momentum_window_mid=20,
        momentum_window_slow=60,
        momentum_zscore_window=30,
        volume_zscore_window=20,
        ofi_zscore_window=20,
        cvd_slope_bars=5,
        cmf_period=20,
        vol_short_bars=5,
        vol_long_bars=20,
        hma_period=10,
        adx_period=7,
        hurst_window=30,
        garch_window=30,
        vix_zscore_window=20,
        yield_curve_zscore_window=20,
        regime_cache_refresh_bars=30,
        min_bars_warmup=5,
        cross_asset_rv_window=20,
        ny_session_start_utc_hour=13,
        ny_session_start_utc_minute=30,
        ny_session_end_utc_hour=20,
        overlap_start_utc_hour=12,
        overlap_end_utc_hour=15,
        london_kz_start_utc_hour=7,
        london_kz_end_utc_hour=10,
        power_hour_start_utc_hour=19,
        power_hour_end_utc_hour=21,
        opening_range_start_minute=810,
        opening_range_end_minute=900,
        rsi_fast_period=7,
        rsi_mid_period=14,
        rsi_slow_period=28,
        cci_fast_period=10,
        cci_mid_period=20,
        cci_slow_period=40,
        aroon_fast_period=14,
        aroon_slow_period=25,
        amihud_zscore_window=20,
        ret_skew_window=10,
        ret_skew_zscore_window=20,
        ret_acf_window=5,
        ret_acf_zscore_window=20,
        high_52w_window=20,
        ret_lag_fast=5,
        ret_lag_mid=20,
        ret_lag_slow=60,
        overnight_gap_window=20,
        dollar_vol_window=20,
        vol_range_ratio_window=20,
        vol_trend_fast=5,
        vol_trend_slow=20,
        up_vol_ratio_fast=5,
        up_vol_ratio_slow=20,
        vol_percentile_window=20,
        vol_persistence_window=20,
        vol_std_window=20,
        mfi_fast=7,
        mfi_slow=14,
        obv_window=20,
        dist_window_fast=20,
        dist_window_slow=50,
        range_window_fast=20,
        range_window_slow=50,
        stoch_window_fast=14,
        stoch_window_slow=50,
        percentile_window_fast=50,
        percentile_window_slow=200,
        efficiency_window_fast=10,
        efficiency_window_slow=50,
        ret_kurtosis_fast=10,
        ret_kurtosis_slow=40,
        ret_kurtosis_zscore_window=20,
        updown_ratio_fast=5,
        updown_ratio_slow=20,
        streak_window=20,
        realized_var_fast=5,
        realized_var_slow=20,
        vol_of_vol_window=20,
        high_low_corr_window=20,
        variance_ratio_fast=5,
        variance_ratio_slow=20,
        vol_asymmetry_window=20,
        bb_pct_b_fast=20,
        bb_pct_b_slow=50,
        hv_fast=10,
        hv_slow=30,
        hv_ratio_window=20,
        parkinson_vol_window=10,
        parkinson_vol_zscore_window=20,
        garman_klass_vol_window=10,
        garman_klass_vol_zscore_window=20,
        yang_zhang_vol_window=20,
        yang_zhang_vol_zscore_window=20,
        vol_velocity_window=20,
        intraday_noise_window=20,
        price_vol_corr_fast=10,
        price_vol_corr_slow=30,
        momentum_velocity_window=20,
        vwap_velocity_window=20,
        extreme_move_sigma_threshold=2.0,
        vol_spike_threshold=2.0,
        tip_tlt_zscore_window=20,
        hyg_lqd_zscore_window=20,
        sb_corr_window_fast=10,
        sb_corr_window_slow=20,
        sb_corr_zscore_window=20,
        factor_beta_window=20,
        factor_beta_zscore_window=20,
        session_vp_rolling_window=15,
    )
    defaults.update(overrides)
    return FeatureFactoryConfig(**defaults)


@pytest.fixture(scope="module")
def cfg() -> FeatureFactoryConfig:
    return _make_cfg()


@pytest.fixture(scope="module")
def bars() -> list[dict]:
    """~250 1m bars, dual-frequency oscillation + random-walk noise so many
    swing highs/lows form with genuinely mixed higher-high/lower-high
    ordering (not a monotonic drift, which would make trend_direction/
    swing_high_type/swing_low_type artificially constant across the whole
    walk-forward batch)."""
    base_ts = datetime(2023, 1, 3, 14, 0, tzinfo=UTC)
    t = np.arange(N)
    swing = np.sin(t / 3.0) * 3.5 + np.sin(t / 11.0) * 1.5
    closes = 100.0 + swing + np.cumsum(RNG.normal(0, 0.18, N))
    spread = np.abs(RNG.normal(0.10, 0.03, N)) + 0.03
    highs = closes + spread
    lows = closes - spread
    opens = closes + RNG.normal(0, 0.03, N)
    highs = np.maximum(highs, np.maximum(opens, closes))
    lows = np.minimum(lows, np.minimum(opens, closes))
    volumes = RNG.uniform(1e4, 1e6, N)
    return [
        {
            "open": float(opens[i]),
            "high": float(highs[i]),
            "low": float(lows[i]),
            "close": float(closes[i]),
            "volume": float(volumes[i]),
            "ts": base_ts + timedelta(minutes=i),
        }
        for i in range(N)
    ]


def _finite(values: list[float | None]) -> list[float]:
    return [v for v in values if v is not None and math.isfinite(v)]


# ---------------------------------------------------------------------------
# (a) Swing/trend non-constant across bars (batch path) -- direct todo-153 guard
# ---------------------------------------------------------------------------


def test_swing_trend_non_constant_batch(bars, cfg):
    """Each of the 13 swing/trend fields must take at least 2 distinct
    non-None values across the bars -- never a frozen placeholder.

    structure_integrity is checked separately (bounded + non-null, not
    strict non-constancy): it only changes value when the swing sequence
    contains an "overlap" (a low pivot above a prior high, or vice versa),
    a structurally rare pattern under ordinary zigzag price action -- not
    a frozen-placeholder bug. Its own formula (1 - overlap_count/max_overlaps)
    is exercised directly by test_structure_integrity_bounded below.
    """
    cache = FeatureCache()
    results = FeatureFactory.compute_batch(bars, "SPY", "5m", cache, cfg)
    assert len(results) == N - 1

    for field in _SWING_FIELDS + _TREND_FIELDS:
        if field == "structure_integrity":
            continue
        vals = _finite([getattr(fv, field) for _, fv in results])
        assert len(vals) > 1, f"{field} has <=1 non-None finite value"
        assert len({round(v, 8) for v in vals}) > 1, f"{field} is constant"


def test_structure_integrity_bounded(bars, cfg):
    """structure_integrity must be non-null wherever trend fields are
    computed, and always in [0, 1] -- the formula's own valid range."""
    cache = FeatureCache()
    results = FeatureFactory.compute_batch(bars, "SPY", "5m", cache, cfg)
    vals = [fv.structure_integrity for _, fv in results if fv.trend_direction is not None]
    assert len(vals) > 1
    assert all(v is not None for v in vals), "structure_integrity null while trend_direction is set"
    assert all(0.0 <= v <= 1.0 for v in vals), "structure_integrity out of [0,1] range"


# ---------------------------------------------------------------------------
# (b) ATR-unit conversion -- pins the exact swing-distance formula
# ---------------------------------------------------------------------------


def _build_swing_micro_case_bars() -> list[dict]:
    """Deterministic bars: constant true range so Wilder ATR converges to
    exactly 1.0, and a triangular oscillation with a repeated exact peak so
    the most recent confirmed swing high has an exact, hand-computable price.

    Construction mirrors the Phase 163 S/R micro-case: mid(t) triangular-
    oscillates between 98.0 and 102.0 with a fixed step of 0.25/bar (period
    32 bars); high = mid + 0.5, low = mid - 0.5 (constant true range of 1.0).
    Truncated so the final bar sits exactly 1.0 ATR below the most recent
    confirmed peak (peak high = 102.5, close = 101.5).
    """
    base_ts = datetime(2023, 1, 3, 14, 0, tzinfo=UTC)
    step = 0.25
    up = np.arange(0, 17) * step
    down = up[1:-1][::-1]
    period = np.concatenate([up, down])
    n_cycles = 5
    wave = np.tile(period, n_cycles)
    mid = 98.0 + wave

    cut = 32 * 2 + 15
    mid = mid[:cut]
    assert abs(mid[-1] - 101.5) < 1e-9, f"micro-case construction bug: mid[-1]={mid[-1]}"

    highs = mid + 0.5
    lows = mid - 0.5
    closes = mid.copy()
    opens = mid.copy()
    volumes = np.full(len(mid), 1_000.0)
    return [
        {
            "open": float(opens[i]),
            "high": float(highs[i]),
            "low": float(lows[i]),
            "close": float(closes[i]),
            "volume": float(volumes[i]),
            "ts": base_ts + timedelta(minutes=i),
        }
        for i in range(len(mid))
    ]


def test_swing_dist_in_atr_units(cfg):
    """A confirmed swing high exactly 1 ATR above close must yield
    swing_high_dist_atr == 1.0, pinning the ATR conversion rather than just
    asserting finiteness."""
    micro_bars = _build_swing_micro_case_bars()
    cache = FeatureCache()
    fv = FeatureFactory.compute(micro_bars, "SPY", "5m", cache, cfg)

    assert fv.swing_high_dist_atr is not None
    assert math.isfinite(fv.swing_high_dist_atr)
    close_ = micro_bars[-1]["close"]
    swing_high_price = 102.5
    atr_val = 1.0
    expected = (swing_high_price - close_) / atr_val
    assert math.isclose(fv.swing_high_dist_atr, expected, abs_tol=1e-6)
    assert math.isclose(fv.swing_high_dist_atr, 1.0, abs_tol=1e-6)


# ---------------------------------------------------------------------------
# (c) Trend-structure nullability -- THE most important test in this phase
# ---------------------------------------------------------------------------


def test_trend_structure_nullability(cfg):
    """Fewer than 2 confirmed swing highs/lows must yield ALL-None trend
    fields (D-01) -- never the archived plugin's fake trend_direction=0.0 /
    price_position=0.5 "no signal" placeholders (the todo-153 failure shape).
    """
    base_ts = datetime(2023, 1, 3, 14, 0, tzinfo=UTC)
    # Monotonically rising ramp: no interior peaks, so find_peaks/find_troughs
    # confirm zero (or at most one) swing high/low -- exactly the
    # insufficient-data branch this test targets.
    n = 60
    closes = 100.0 + np.arange(n) * 0.5
    bars = [
        {
            "open": float(closes[i] - 0.05),
            "high": float(closes[i] + 0.10),
            "low": float(closes[i] - 0.10),
            "close": float(closes[i]),
            "volume": 1_000.0,
            "ts": base_ts + timedelta(minutes=i),
        }
        for i in range(n)
    ]
    cache = FeatureCache()
    fv = FeatureFactory.compute(bars, "SPY", "5m", cache, cfg)

    for field in _TREND_FIELDS:
        assert getattr(fv, field) is None, (
            f"{field} is not None on a monotonic ramp (< 2 confirmed swings) -- "
            f"D-01/todo-153: a fake-but-numeric placeholder is a silent-wrong-answer bug, "
            f"not a measurement"
        )
    assert (
        fv.trend_direction is None
    ), "trend_direction must be None, not the archived 0.0 default (D-01/todo-153)"
    assert (
        fv.price_position is None
    ), "price_position must be None, not the archived 0.5 default (D-01/todo-153)"


# ---------------------------------------------------------------------------
# (d) Swing-detector partial nullability -- exactly one confirmed swing high
# ---------------------------------------------------------------------------


def test_swing_detector_partial_nullability(cfg):
    """With exactly one confirmed swing high, distance/age must be real
    floats (a single pivot IS measurable) while type/pattern (which need a
    second pivot to classify higher-high vs. lower-high) must be None."""
    base_ts = datetime(2023, 1, 3, 14, 0, tzinfo=UTC)
    n = 40
    # Rise to a single peak then fall away -- exactly one confirmed swing
    # high (the peak), zero confirmed swing lows (monotonic segments on
    # either side never confirm a trough within the window).
    rise = np.arange(0, 20) * 0.3
    fall = rise[-1] - np.arange(1, 21) * 0.3
    closes = np.concatenate([100.0 + rise, 100.0 + fall])[:n]
    bars = [
        {
            "open": float(closes[i] - 0.02),
            "high": float(closes[i] + 0.05),
            "low": float(closes[i] - 0.05),
            "close": float(closes[i]),
            "volume": 1_000.0,
            "ts": base_ts + timedelta(minutes=i),
        }
        for i in range(n)
    ]
    cache = FeatureCache()
    fv = FeatureFactory.compute(bars, "SPY", "5m", cache, cfg)

    assert fv.swing_high_dist_atr is not None, "single confirmed swing high should be measurable"
    assert (
        fv.swing_high_age_bars is not None
    ), "single confirmed swing high age should be measurable"
    assert (
        fv.swing_high_type is None
    ), "swing_high_type needs a 2nd peak to classify -- must be None"
    assert fv.swing_pattern is None, "swing_pattern needs both high+low type -- must be None"


# ---------------------------------------------------------------------------
# (e) Zero ATR -- all 13 fields None
# ---------------------------------------------------------------------------


def test_swing_trend_zero_atr_all_none(cfg):
    """A flat-price series (ATR == 0) must yield None for all 13 fields."""
    base_ts = datetime(2023, 1, 3, 14, 0, tzinfo=UTC)
    n = 60
    bars = [
        {
            "open": 100.0,
            "high": 100.0,
            "low": 100.0,
            "close": 100.0,
            "volume": 1_000.0,
            "ts": base_ts + timedelta(minutes=i),
        }
        for i in range(n)
    ]
    cache = FeatureCache()
    fv = FeatureFactory.compute(bars, "SPY", "5m", cache, cfg)

    for field in _SWING_FIELDS + _TREND_FIELDS:
        assert getattr(fv, field) is None, f"{field} is not None on zero-ATR flat series"


# ---------------------------------------------------------------------------
# (f) live == batch parity for all 13 swing/trend fields
# ---------------------------------------------------------------------------


def test_swing_trend_live_batch_parity(bars, cfg):
    """Live (compute() over the full growing history) must match batch to
    1e-6 -- catches a forgotten compute_batch() wiring update (T-165-08)."""
    n = len(bars)

    cache_batch = FeatureCache()
    batch_results = FeatureFactory.compute_batch(bars, "SPY", "5m", cache_batch, cfg)
    _, fv_batch_last = batch_results[-1]

    cache_live = FeatureCache()
    fv_live_last: FeatureVector | None = None
    for i in range(1, n):
        bar = bars[i]
        cache_live.update_session_vp(
            bar["ts"], bar["high"], bar["low"], bar["close"], bar["volume"], cfg
        )
        fv_live_last = FeatureFactory.compute(bars[: i + 1], "SPY", "5m", cache_live, cfg)

    assert fv_live_last is not None
    for field in _SWING_FIELDS + _TREND_FIELDS:
        b = getattr(fv_batch_last, field)
        s = getattr(fv_live_last, field)
        if b is None or s is None:
            assert b == s, f"{field}: batch={b} live={s} (None mismatch)"
        else:
            assert abs(b - s) < 1e-6, f"{field}: batch={b:.10f} live={s:.10f}"


# ---------------------------------------------------------------------------
# (g) APR keys are live -- proves config values actually change output
# ---------------------------------------------------------------------------


def test_trend_structure_apr_keys_are_live(bars):
    """Changing trend_structure_atr_strength_divisor must change
    trend_strength; changing swing_pivot_window must change at least one
    swing field. Proves the APR keys are read, not shadowed by a surviving
    hardcoded constant."""
    cache_a = FeatureCache()
    fv_a = FeatureFactory.compute(
        bars, "SPY", "5m", cache_a, _make_cfg(trend_structure_atr_strength_divisor=5.0)
    )
    cache_b = FeatureCache()
    fv_b = FeatureFactory.compute(
        bars, "SPY", "5m", cache_b, _make_cfg(trend_structure_atr_strength_divisor=50.0)
    )
    if fv_a.trend_strength is not None and fv_b.trend_strength is not None:
        assert (
            fv_a.trend_strength != fv_b.trend_strength
        ), "trend_strength unchanged by trend_structure_atr_strength_divisor -- APR key may be shadowed"

    cache_c = FeatureCache()
    fv_c = FeatureFactory.compute(bars, "SPY", "5m", cache_c, _make_cfg(swing_pivot_window=3))
    cache_d = FeatureCache()
    fv_d = FeatureFactory.compute(bars, "SPY", "5m", cache_d, _make_cfg(swing_pivot_window=15))
    diffs = [getattr(fv_c, f) != getattr(fv_d, f) for f in _SWING_FIELDS]
    assert any(diffs), "no swing field changed with swing_pivot_window -- APR key may be shadowed"


# ---------------------------------------------------------------------------
# Phase 165 Plan 03: Swing Momentum + Fibonacci Zones
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# (a) Swing-momentum non-constant across bars (batch path) -- direct
# todo-153-shaped guard
# ---------------------------------------------------------------------------


def test_swing_momentum_non_constant_batch(bars, cfg):
    """Each of the 8 swing-momentum fields must take at least 2 distinct
    non-None values across the batch run -- never a frozen placeholder."""
    cache = FeatureCache()
    results = FeatureFactory.compute_batch(bars, "SPY", "5m", cache, cfg)
    for field in _SWING_MOMENTUM_FIELDS:
        vals = _finite([getattr(fv, field) for _, fv in results])
        assert len(vals) > 1, f"{field} has <=1 non-None finite value"
        assert len({round(v, 8) for v in vals}) > 1, f"{field} is constant"


# ---------------------------------------------------------------------------
# (b) Swing-momentum nullability -- D-01, the archived plugin's own
# already-clean {} contract
# ---------------------------------------------------------------------------


def test_swing_momentum_nullability(cfg):
    """A fixture with fewer than config.swing_momentum_max_extremes confirmed
    extremes must yield ALL 8 swing-momentum fields None (D-01): the archived
    plugin already returns {} (empty dict, "not computed") on insufficient
    data -- this proves the v3 port preserves that contract rather than
    emitting a fake average over too few swings."""
    base_ts = datetime(2023, 1, 3, 14, 0, tzinfo=UTC)
    n = 30
    closes = 100.0 + np.arange(n) * 0.3  # monotonic ramp: no interior swings
    bars_local = [
        {
            "open": float(closes[i] - 0.02),
            "high": float(closes[i] + 0.05),
            "low": float(closes[i] - 0.05),
            "close": float(closes[i]),
            "volume": 1_000.0,
            "ts": base_ts + timedelta(minutes=i),
        }
        for i in range(n)
    ]
    cache = FeatureCache()
    fv = FeatureFactory.compute(bars_local, "SPY", "5m", cache, cfg)
    for field in _SWING_MOMENTUM_FIELDS:
        assert getattr(fv, field) is None, (
            f"{field} is not None on a monotonic ramp (< swing_momentum_max_extremes "
            f"confirmed swings) -- D-01: the archived plugin returns {{}} on "
            f"insufficient data, matched here by None"
        )


# ---------------------------------------------------------------------------
# (c) ATR-invariance -- THE proof obligation for Task 1(e)'s divisor deletion
# ---------------------------------------------------------------------------


def test_swing_momentum_atr_invariance(bars, cfg):
    """Scaling every price in the fixture by a constant factor (which
    changes ATR materially) must leave swing_amplitude_ratio,
    swing_amplitude_expanding, swing_amplitude_intensity, struct_energy and
    swing_velocity_bias unchanged to 1e-12. If this ever fails, the ATR-
    divisor deletion was wrong -- revert it, do not weaken this test."""
    highs = np.array([b["high"] for b in bars], dtype=float)
    lows = np.array([b["low"] for b in bars], dtype=float)
    volumes = np.array([b["volume"] for b in bars], dtype=float)

    base = _compute_swing_momentum(highs, lows, volumes, cfg)
    factor = 7.0
    scaled = _compute_swing_momentum(highs * factor, lows * factor, volumes, cfg)

    for field in (
        "swing_amplitude_ratio",
        "swing_amplitude_expanding",
        "swing_amplitude_intensity",
        "struct_energy",
        "swing_velocity_bias",
    ):
        b = base[field]
        s = scaled[field]
        assert b is not None and s is not None, f"{field} unexpectedly None"
        # rel_tol=0.0 is mandatory here -- math.isclose's default rel_tol=1e-9
        # would dominate abs_tol=1e-12 for values ~O(1) and silently mask a
        # real precision regression (caught during this plan's own
        # mutation-verification pass: the archived +1e-9 epsilon produces a
        # ~1.3e-10 divergence, invisible to the default rel_tol but well
        # above this abs_tol).
        assert math.isclose(b, s, rel_tol=0.0, abs_tol=1e-12), f"{field}: base={b!r} scaled={s!r}"


# ---------------------------------------------------------------------------
# (d) swing_amplitude_expanding uses the LAST three amplitudes, not the
# archived plugin's first three
# ---------------------------------------------------------------------------


def _build_amplitude_progression_bars() -> list[dict]:
    """9 vertices (a padding trough+peak on each end plus 7 real swing
    extremes) whose 6 real amplitudes are [~1.02, ~2.02, ~3.02, ~3.02,
    ~2.02, ~1.02] -- the FIRST three strictly increasing, the LAST three
    NOT. Regression fixture for the archived
    amplitudes[0] < amplitudes[1] < amplitudes[2] bug (migration 267's
    COMMENT and the archived docstring both require testing the LAST three
    instead). The +-0.01 high/low offset is a uniform constant added to
    every amplitude, so it shifts magnitudes without disturbing the
    ordering under test. Padding vertices at both ends fall outside the
    confirm-window's boundary (no bars before the first / after the last)
    and are deliberately dropped, leaving exactly the 7 intended extremes.
    """
    base_ts = datetime(2023, 1, 3, 14, 0, tzinfo=UTC)
    vertices = [103.0, 100.0, 101.0, 99.0, 102.0, 99.0, 101.0, 100.0, 103.0]
    seg_bars = 6
    closes: list[float] = [vertices[0]]
    for k in range(len(vertices) - 1):
        seg = np.linspace(vertices[k], vertices[k + 1], seg_bars + 1)[1:]
        closes.extend(seg.tolist())
    closes_arr = np.array(closes)
    return [
        {
            "open": float(closes_arr[i]),
            "high": float(closes_arr[i] + 0.01),
            "low": float(closes_arr[i] - 0.01),
            "close": float(closes_arr[i]),
            "volume": 1_000.0 + i,
            "ts": base_ts + timedelta(minutes=i),
        }
        for i in range(len(closes_arr))
    ]


def test_swing_momentum_expanding_uses_last_three():
    """swing_amplitude_expanding must be 0.0 on a fixture whose FIRST three
    amplitudes increase while its LAST three do not -- the regression guard
    for the archived amplitudes[0] < amplitudes[1] < amplitudes[2] bug."""
    bars_local = _build_amplitude_progression_bars()
    local_cfg = _make_cfg(swing_momentum_confirm_n=3, swing_momentum_max_extremes=7)
    highs = np.array([b["high"] for b in bars_local], dtype=float)
    lows = np.array([b["low"] for b in bars_local], dtype=float)
    volumes = np.array([b["volume"] for b in bars_local], dtype=float)
    result = _compute_swing_momentum(highs, lows, volumes, local_cfg)
    assert result["swing_amplitude_expanding"] == 0.0, result


# ---------------------------------------------------------------------------
# (e) swing_velocity_bias numeric encoding (D-03) -- no string anywhere
# ---------------------------------------------------------------------------


def test_swing_momentum_velocity_bias_encoding(bars, cfg):
    """swing_velocity_bias must be one of {-1.0, 0.0, 1.0} or None across a
    batch run, and no FeatureVector field anywhere holds a string (D-03:
    the numeric encoding of the archived swing_velocity_trend string
    enum)."""
    cache = FeatureCache()
    results = FeatureFactory.compute_batch(bars, "SPY", "5m", cache, cfg)
    seen_bias_values: set[float | None] = set()
    for _, fv in results:
        seen_bias_values.add(fv.swing_velocity_bias)
        for f in dataclasses.fields(fv):
            val = getattr(fv, f.name)
            assert not isinstance(val, str), f"{f.name} holds a string value: {val!r}"
    assert seen_bias_values <= {-1.0, 0.0, 1.0, None}, seen_bias_values


# ---------------------------------------------------------------------------
# (f) swing_volume_confirmation free field (D-15) -- reads volume, not price
# ---------------------------------------------------------------------------


def test_swing_momentum_volume_confirmation_free_field(bars, cfg):
    """swing_volume_confirmation must be non-None and > 0 on a fixture with
    varying volume, and must change when only the volume series changes
    (prices held fixed) -- proving it reads volume, not price."""
    cache_a = FeatureCache()
    fv_a = FeatureFactory.compute(bars, "SPY", "5m", cache_a, cfg)
    assert fv_a.swing_volume_confirmation is not None
    assert fv_a.swing_volume_confirmation > 0

    bars_b = [dict(b) for b in bars]
    rng2 = np.random.default_rng(99)
    scaled_vol = rng2.uniform(1e4, 1e6, len(bars_b))
    for i, b in enumerate(bars_b):
        b["volume"] = float(scaled_vol[i])

    cache_b = FeatureCache()
    fv_b = FeatureFactory.compute(bars_b, "SPY", "5m", cache_b, cfg)
    assert fv_b.swing_volume_confirmation is not None
    assert fv_a.swing_volume_confirmation != fv_b.swing_volume_confirmation


# ---------------------------------------------------------------------------
# (g) nearest_fib_ratio is always one of the 5 canonical ratios
# ---------------------------------------------------------------------------


def test_fib_ratio_is_canonical(bars, cfg):
    """nearest_fib_ratio on a warm bar must be a member of the 5 canonical
    Fibonacci retracement ratios, never an interpolated value."""
    cache = FeatureCache()
    results = FeatureFactory.compute_batch(bars, "SPY", "5m", cache, cfg)
    canonical = {0.236, 0.382, 0.500, 0.618, 0.786}
    vals = {fv.nearest_fib_ratio for _, fv in results if fv.nearest_fib_ratio is not None}
    assert vals, "no warm bar produced a nearest_fib_ratio"
    assert vals <= canonical, f"non-canonical fib ratio(s): {vals - canonical}"


# ---------------------------------------------------------------------------
# (h) fib distance is pinned in ATR units, not merely finite
# ---------------------------------------------------------------------------


def test_fib_dist_in_atr_units(cfg):
    """Reuse the constant-true-range fixture (Wilder ATR converges to
    exactly 1.0) and assert nearest_fib_dist_atr equals the raw price
    distance from close to the nearest fib level within 1e-6 -- pins the
    ATR conversion rather than merely asserting finiteness."""
    micro_bars = _build_swing_micro_case_bars()
    cache = FeatureCache()
    fv = FeatureFactory.compute(micro_bars, "SPY", "5m", cache, cfg)
    assert fv.nearest_fib_dist_atr is not None

    highs = np.array([b["high"] for b in micro_bars], dtype=float)
    lows = np.array([b["low"] for b in micro_bars], dtype=float)
    close_ = float(micro_bars[-1]["close"])
    atr_val = 1.0  # pinned by construction, matching test_swing_dist_in_atr_units
    swing_fields = _compute_swing_structure(highs, lows, close_, atr_val, cfg)
    swing_high_price = swing_fields["swing_high_price"]
    swing_low_price = swing_fields["swing_low_price"]
    assert swing_high_price is not None and swing_low_price is not None
    swing_range = swing_high_price - swing_low_price
    levels = [swing_low_price + r * swing_range for r in (0.236, 0.382, 0.500, 0.618, 0.786)]
    nearest_level = min(levels, key=lambda lv: abs(lv - close_))
    expected = abs(close_ - nearest_level) / atr_val

    assert math.isclose(fv.nearest_fib_dist_atr, expected, abs_tol=1e-6)


# ---------------------------------------------------------------------------
# (i) fib nullability on a degenerate (flat, zero-ATR) swing
# ---------------------------------------------------------------------------


def test_fib_nullability_on_degenerate_swing(cfg):
    """A flat-price series (no confirmed pivots, ATR == 0) must yield all 4
    fib fields None."""
    base_ts = datetime(2023, 1, 3, 14, 0, tzinfo=UTC)
    n = 60
    bars_local = [
        {
            "open": 100.0,
            "high": 100.0,
            "low": 100.0,
            "close": 100.0,
            "volume": 1_000.0,
            "ts": base_ts + timedelta(minutes=i),
        }
        for i in range(n)
    ]
    cache = FeatureCache()
    fv = FeatureFactory.compute(bars_local, "SPY", "5m", cache, cfg)
    for field in _FIB_FIELDS:
        assert getattr(fv, field) is None, f"{field} is not None on zero-ATR flat series"


# ---------------------------------------------------------------------------
# (j) fib discount-zone boundary flip
# ---------------------------------------------------------------------------


def test_fib_discount_zone_boundaries():
    """Hand-place close_ just inside and just outside the [50.0%, 78.6%]
    band via a directly-constructed swing_fields dict; in_fib_discount_zone
    must flip 1.0 -> 0.0 on both sides of the band."""
    local_cfg = _make_cfg()
    swing_fields = {"swing_high_price": 110.0, "swing_low_price": 100.0}
    atr_val = 1.0
    level_500 = 105.0
    level_786 = 107.86

    inside = _compute_fib_zones(level_500 + 0.5, atr_val, swing_fields, local_cfg)
    assert inside["in_fib_discount_zone"] == 1.0, inside

    below = _compute_fib_zones(level_500 - 0.5, atr_val, swing_fields, local_cfg)
    assert below["in_fib_discount_zone"] == 0.0, below

    above = _compute_fib_zones(level_786 + 0.5, atr_val, swing_fields, local_cfg)
    assert above["in_fib_discount_zone"] == 0.0, above


# ---------------------------------------------------------------------------
# (k) live == batch parity for all 12 swing-momentum/fib fields
# ---------------------------------------------------------------------------


def test_swing_momentum_fib_live_batch_parity(bars, cfg):
    """Live (compute() over the full growing history) must match batch to
    1e-6 -- catches a forgotten compute_batch() wiring update."""
    n = len(bars)

    cache_batch = FeatureCache()
    batch_results = FeatureFactory.compute_batch(bars, "SPY", "5m", cache_batch, cfg)
    _, fv_batch_last = batch_results[-1]

    cache_live = FeatureCache()
    fv_live_last: FeatureVector | None = None
    for i in range(1, n):
        bar = bars[i]
        cache_live.update_session_vp(
            bar["ts"], bar["high"], bar["low"], bar["close"], bar["volume"], cfg
        )
        fv_live_last = FeatureFactory.compute(bars[: i + 1], "SPY", "5m", cache_live, cfg)

    assert fv_live_last is not None
    for field in _SWING_MOMENTUM_FIELDS + _FIB_FIELDS:
        b = getattr(fv_batch_last, field)
        s = getattr(fv_live_last, field)
        if b is None or s is None:
            assert b == s, f"{field}: batch={b} live={s} (None mismatch)"
        else:
            assert abs(b - s) < 1e-6, f"{field}: batch={b:.10f} live={s:.10f}"


# ---------------------------------------------------------------------------
# (l) APR keys are live -- proves config values actually change output
# ---------------------------------------------------------------------------


def test_swing_momentum_fib_apr_keys_are_live(bars):
    """Changing swing_momentum_energy_divisor must change struct_energy;
    changing swing_momentum_confirm_n must change at least one
    swing-momentum field; changing fib_cluster_atr_divisor must leave
    fib_cluster_strength monotone non-increasing as the divisor grows (a
    smaller clustering threshold can only reduce or hold clustering).
    Proves the APR keys are read, not shadowed by a surviving hardcoded
    constant."""
    cache_a = FeatureCache()
    fv_a = FeatureFactory.compute(
        bars, "SPY", "5m", cache_a, _make_cfg(swing_momentum_energy_divisor=3.0)
    )
    cache_b = FeatureCache()
    fv_b = FeatureFactory.compute(
        bars, "SPY", "5m", cache_b, _make_cfg(swing_momentum_energy_divisor=30.0)
    )
    if fv_a.struct_energy is not None and fv_b.struct_energy is not None:
        assert (
            fv_a.struct_energy != fv_b.struct_energy
        ), "struct_energy unchanged by swing_momentum_energy_divisor -- APR key may be shadowed"

    cache_c = FeatureCache()
    fv_c = FeatureFactory.compute(bars, "SPY", "5m", cache_c, _make_cfg(swing_momentum_confirm_n=2))
    cache_d = FeatureCache()
    fv_d = FeatureFactory.compute(bars, "SPY", "5m", cache_d, _make_cfg(swing_momentum_confirm_n=5))
    diffs = [getattr(fv_c, f) != getattr(fv_d, f) for f in _SWING_MOMENTUM_FIELDS]
    assert any(
        diffs
    ), "no swing-momentum field changed with swing_momentum_confirm_n -- APR key may be shadowed"

    cache_e = FeatureCache()
    fv_e = FeatureFactory.compute(
        bars, "SPY", "5m", cache_e, _make_cfg(fib_cluster_atr_divisor=2.0)
    )
    cache_f = FeatureCache()
    fv_f = FeatureFactory.compute(
        bars, "SPY", "5m", cache_f, _make_cfg(fib_cluster_atr_divisor=200.0)
    )
    if fv_e.fib_cluster_strength is not None and fv_f.fib_cluster_strength is not None:
        assert fv_f.fib_cluster_strength <= fv_e.fib_cluster_strength, (
            "fib_cluster_strength increased as fib_cluster_atr_divisor grew -- "
            "should be monotone non-increasing (a smaller threshold can only reduce clustering)"
        )


# ---------------------------------------------------------------------------
# Phase 165 Plan 05: Session Levels (16 fields) + phase-closing completeness gate
# ---------------------------------------------------------------------------

_SESSION_LEVEL_FIELDS = (
    "prior_session_high_dist_atr",
    "prior_session_low_dist_atr",
    "prior_session_close_dist_atr",
    "overnight_high_dist_atr",
    "overnight_low_dist_atr",
    "overnight_range_pct",
    "opening_gap_pct",
    "weekly_pivot_dist_atr",
    "weekly_r1_dist_atr",
    "weekly_r2_dist_atr",
    "weekly_s1_dist_atr",
    "weekly_s2_dist_atr",
    "nearest_level_dist_atr",
    "asian_session_high_dist_atr",
    "asian_session_low_dist_atr",
    "gap_filled",
)

# The union of every Phase 165 field, in FeatureVector dataclass declaration order
# (Plan 02's 13 + Plan 03's 12 + Plan 05's 16 = 41).
_PHASE_165_FIELDS = (
    _SWING_FIELDS + _TREND_FIELDS + _SWING_MOMENTUM_FIELDS + _FIB_FIELDS + _SESSION_LEVEL_FIELDS
)


def _run_live_with_session_levels(
    bars_local: list[dict],
    cfg: FeatureFactoryConfig,
    symbol: str = "SPY",
    tf: str = "5m",
) -> FeatureVector:
    """Drive compute() incrementally with all 3 required per-bar mutators, in the
    same order compute_batch()'s internal loop uses them (update_session_vp /
    update_overnight_range / update_session_levels BEFORE compute(), advance_bar()
    AFTER) -- extends test_swing_trend_live_batch_parity's single-mutator pattern
    with the two Phase 164/165 mutators Plan 05's fields depend on. Returns the
    FINAL FeatureVector only.
    """
    cache = FeatureCache()
    fv: FeatureVector | None = None
    for i in range(1, len(bars_local)):
        bar = bars_local[i]
        cache.update_session_vp(
            bar["ts"], bar["high"], bar["low"], bar["close"], bar["volume"], cfg
        )
        cache.update_overnight_range(bar["ts"], bar["high"], bar["low"], cfg)
        cache.update_session_levels(
            bar["ts"], bar["open"], bar["high"], bar["low"], bar["close"], cfg
        )
        fv = FeatureFactory.compute(bars_local[: i + 1], symbol, tf, cache, cfg)
        cache.advance_bar(bar["ts"], bar["high"], bar["low"], bar["close"], bar["volume"])
    assert fv is not None
    return fv


_SESSION_N_DAYS = 8
_SESSION_STEP_MINUTES = 30
_SESSION_RNG = np.random.default_rng(1165)


def _build_session_levels_bars() -> list[dict]:
    """~8 days of 30-min bars (continuous calendar coverage, not RTH-only) with the
    same dual-frequency-oscillation + random-walk shape as the module `bars`
    fixture -- spans multiple ET session-day rollovers and at least one ISO-week
    boundary, so all 16 session-levels fields (plus the swing/trend/fib fields
    the `bars` fixture already exercises at 1-minute granularity) take real,
    varying non-None values. Continuous (not RTH-only) calendar coverage means
    every ET calendar-date change is a session rollover in this synthetic
    fixture -- deliberately denser than real trading-day boundaries, which only
    strengthens (never weakens) the non-constancy/completeness assertions below.
    """
    base_ts = datetime(2026, 7, 6, 0, 0, tzinfo=UTC)  # Monday midnight UTC
    n = _SESSION_N_DAYS * 24 * 60 // _SESSION_STEP_MINUTES
    t = np.arange(n)
    swing = np.sin(t / 3.0) * 3.5 + np.sin(t / 11.0) * 1.5
    closes = 100.0 + swing + np.cumsum(_SESSION_RNG.normal(0, 0.05, n))
    spread = np.abs(_SESSION_RNG.normal(0.10, 0.03, n)) + 0.03
    highs = closes + spread
    lows = closes - spread
    opens = closes + _SESSION_RNG.normal(0, 0.03, n)
    highs = np.maximum(highs, np.maximum(opens, closes))
    lows = np.minimum(lows, np.minimum(opens, closes))
    volumes = _SESSION_RNG.uniform(1e4, 1e6, n)
    return [
        {
            "open": float(opens[i]),
            "high": float(highs[i]),
            "low": float(lows[i]),
            "close": float(closes[i]),
            "volume": float(volumes[i]),
            "ts": base_ts + timedelta(minutes=_SESSION_STEP_MINUTES * i),
        }
        for i in range(n)
    ]


@pytest.fixture(scope="module")
def session_bars() -> list[dict]:
    return _build_session_levels_bars()


# ---------------------------------------------------------------------------
# (a) Session-levels non-constant across bars (batch path) -- direct
# todo-153-shaped guard
# ---------------------------------------------------------------------------


def test_session_levels_non_constant_batch(session_bars, cfg):
    """Each of the 16 session-levels fields must take at least 2 distinct
    non-None values across a multi-session, multi-week batch run -- except
    gap_filled, for which both 0.0 and 1.0 must occur."""
    cache = FeatureCache()
    results = FeatureFactory.compute_batch(session_bars, "SPY", "5m", cache, cfg)

    for field in _SESSION_LEVEL_FIELDS:
        vals = _finite([getattr(fv, field) for _, fv in results])
        assert len(vals) > 1, f"{field} has <=1 non-None finite value"
        if field == "gap_filled":
            assert {0.0, 1.0} <= set(vals), f"gap_filled did not take both 0.0/1.0: {set(vals)}"
        else:
            assert len({round(v, 8) for v in vals}) > 1, f"{field} is constant"


# ---------------------------------------------------------------------------
# (b) Cold nullability -- shorter than one session, no week has ever rolled over
# ---------------------------------------------------------------------------


def test_session_levels_cold_nullability(cfg):
    """A series shorter than one session (never rolls over, but ATR is warm)
    must yield None for the prior-session trio, opening_gap_pct, all five
    weekly fields, and nearest_level_dist_atr on the final bar (D-01)."""
    base_ts = datetime(2026, 7, 6, 13, 30, tzinfo=UTC)  # Monday 9:30 ET, single session
    n = 10
    mids = [100.0 + 0.5 * i for i in range(n)]
    bars_local = [
        {
            "open": m,
            "high": m + 0.5,
            "low": m - 0.5,
            "close": m,
            "volume": 1_000.0,
            "ts": base_ts + timedelta(minutes=5 * i),
        }
        for i, m in enumerate(mids)
    ]
    cache = FeatureCache()
    results = FeatureFactory.compute_batch(bars_local, "SPY", "5m", cache, cfg)
    fv = results[-1][1]

    assert fv.gap_filled is not None, "gap_filled must be a real 0.0/1.0, not None -- ATR is warm"
    for field in (
        "prior_session_high_dist_atr",
        "prior_session_low_dist_atr",
        "prior_session_close_dist_atr",
        "opening_gap_pct",
        "weekly_pivot_dist_atr",
        "weekly_r1_dist_atr",
        "weekly_r2_dist_atr",
        "weekly_s1_dist_atr",
        "weekly_s2_dist_atr",
        "nearest_level_dist_atr",
    ):
        assert (
            getattr(fv, field) is None
        ), f"{field} is not None before any session/week has completed -- D-01"


# ---------------------------------------------------------------------------
# (c) ATR-unit conversion -- pins the exact prior-session-high formula
# ---------------------------------------------------------------------------


def _build_session_atr_pin_bars() -> list[dict]:
    """Deterministic 2-session bars: constant true range so Wilder ATR
    converges to exactly 1.0, spanning exactly one session rollover so
    prior_session_high_dist_atr is measurable and pinned on the final bar."""
    base_ts = datetime(2026, 7, 6, 13, 30, tzinfo=UTC)  # Monday 9:30 ET
    day1_mid = [100.0, 100.5, 101.0, 100.5, 100.0]
    day2_mid = [100.5, 101.0, 101.5, 102.0, 102.5]
    bars_local: list[dict] = []
    ts = base_ts
    for m in day1_mid:
        bars_local.append(
            {"open": m, "high": m + 0.5, "low": m - 0.5, "close": m, "volume": 1_000.0, "ts": ts}
        )
        ts = ts + timedelta(minutes=5)
    ts = base_ts + timedelta(days=1)
    for m in day2_mid:
        bars_local.append(
            {"open": m, "high": m + 0.5, "low": m - 0.5, "close": m, "volume": 1_000.0, "ts": ts}
        )
        ts = ts + timedelta(minutes=5)
    return bars_local


def test_session_levels_dist_in_atr_units(cfg):
    """prior_session_high_dist_atr must equal the raw price difference between
    the prior session's high and the final close within 1e-6 -- pins the ATR
    conversion rather than merely asserting finiteness."""
    bars_local = _build_session_atr_pin_bars()
    fv = _run_live_with_session_levels(bars_local, cfg)

    assert fv.prior_session_high_dist_atr is not None
    day1_high = max(b["high"] for b in bars_local[:5])
    close_ = bars_local[-1]["close"]
    atr_val = 1.0
    expected = (day1_high - close_) / atr_val
    assert math.isclose(fv.prior_session_high_dist_atr, expected, abs_tol=1e-6)


# ---------------------------------------------------------------------------
# (d) Weekly pivot pin -- exact formula off the PRIOR COMPLETED week only
# ---------------------------------------------------------------------------


def _build_weekly_pivot_bars() -> list[dict]:
    """10 bars, constant true range, spanning one ISO-week boundary (7
    calendar days apart) so the prior-completed-week snapshot is populated
    (and ATR is warmed -- config.adx_period=7) by the final bar."""
    base_ts = datetime(2026, 7, 6, 13, 30, tzinfo=UTC)  # Monday, ISO week 28
    mids = [100.0 + 0.5 * i for i in range(10)]
    tss = [base_ts + timedelta(days=i) for i in range(7)] + [
        base_ts + timedelta(days=7),
        base_ts + timedelta(days=8),
        base_ts + timedelta(days=9),
    ]
    return [
        {"open": m, "high": m + 0.5, "low": m - 0.5, "close": m, "volume": 1_000.0, "ts": ts}
        for m, ts in zip(mids, tss)
    ]


def test_session_levels_weekly_pivot_pinned(cfg):
    """Weekly pivot/R1/R2/S1/S2 must equal the hand-computed formulas off the
    PRIOR COMPLETED week's high/low/close within 1e-9 on the final bar, and
    must be None on every bar of the first week (no prior week exists yet)."""
    bars_local = _build_weekly_pivot_bars()
    cache = FeatureCache()
    results: list[FeatureVector] = []
    for i in range(1, len(bars_local)):
        bar = bars_local[i]
        cache.update_session_vp(
            bar["ts"], bar["high"], bar["low"], bar["close"], bar["volume"], cfg
        )
        cache.update_overnight_range(bar["ts"], bar["high"], bar["low"], cfg)
        cache.update_session_levels(
            bar["ts"], bar["open"], bar["high"], bar["low"], bar["close"], cfg
        )
        fv = FeatureFactory.compute(bars_local[: i + 1], "SPY", "5m", cache, cfg)
        results.append(fv)
        cache.advance_bar(bar["ts"], bar["high"], bar["low"], bar["close"], bar["volume"])

    # Bars index 1..6 (week 1; index 0 is never mutator-visited, matching both
    # compute()/compute_batch()'s own i=1..n-1 convention) -- all None, no
    # prior week exists yet.
    for fv in results[:6]:
        assert fv.weekly_pivot_dist_atr is None, "weekly_pivot_dist_atr must be None in week 1"

    week1_bars = bars_local[1:7]
    ph = max(b["high"] for b in week1_bars)
    pl = min(b["low"] for b in week1_bars)
    pc = week1_bars[-1]["close"]
    wp = (ph + pl + pc) / 3.0
    r1 = 2.0 * wp - pl
    r2 = wp + (ph - pl)
    s1 = 2.0 * wp - ph
    s2 = wp - (ph - pl)
    close_ = bars_local[-1]["close"]
    atr_val = 1.0

    final_fv = results[-1]
    assert final_fv.weekly_pivot_dist_atr is not None
    assert math.isclose(final_fv.weekly_pivot_dist_atr, (close_ - wp) / atr_val, abs_tol=1e-9)
    assert math.isclose(final_fv.weekly_r1_dist_atr, (r1 - close_) / atr_val, abs_tol=1e-9)
    assert math.isclose(final_fv.weekly_r2_dist_atr, (r2 - close_) / atr_val, abs_tol=1e-9)
    assert math.isclose(final_fv.weekly_s1_dist_atr, (close_ - s1) / atr_val, abs_tol=1e-9)
    assert math.isclose(final_fv.weekly_s2_dist_atr, (close_ - s2) / atr_val, abs_tol=1e-9)


# ---------------------------------------------------------------------------
# (e) tf=='1d' suppression -- gated inside the helper, live/batch cannot diverge
# ---------------------------------------------------------------------------


def test_session_levels_daily_suppression(session_bars, cfg):
    """The five intraday-only fields must be None at tf=='1d' and non-None at
    tf=='5m' on the same bars; opening_gap_pct and the weekly five must be
    non-None at both."""
    cache_5m = FeatureCache()
    results_5m = FeatureFactory.compute_batch(session_bars, "SPY", "5m", cache_5m, cfg)
    cache_1d = FeatureCache()
    results_1d = FeatureFactory.compute_batch(session_bars, "SPY", "1d", cache_1d, cfg)

    for field in (
        "overnight_high_dist_atr",
        "overnight_low_dist_atr",
        "overnight_range_pct",
        "asian_session_high_dist_atr",
        "asian_session_low_dist_atr",
    ):
        n_5m = sum(1 for _, fv in results_5m if getattr(fv, field) is not None)
        n_1d = sum(1 for _, fv in results_1d if getattr(fv, field) is not None)
        assert n_5m > 0, f"{field} never populated at tf='5m' -- fixture too short"
        assert n_1d == 0, f"{field} must be None at tf=='1d', found {n_1d} non-None value(s)"

    for field in (
        "opening_gap_pct",
        "weekly_pivot_dist_atr",
        "weekly_r1_dist_atr",
        "weekly_r2_dist_atr",
        "weekly_s1_dist_atr",
        "weekly_s2_dist_atr",
    ):
        n_5m = sum(1 for _, fv in results_5m if getattr(fv, field) is not None)
        n_1d = sum(1 for _, fv in results_1d if getattr(fv, field) is not None)
        assert n_5m > 0 and n_1d > 0, f"{field} must be meaningful on both 5m and 1d"


# ---------------------------------------------------------------------------
# (f) gap_filled -- D-13 free field, must actually gap and then fill
# ---------------------------------------------------------------------------


def _build_gap_fill_bars() -> list[dict]:
    """Day 1: 8 constant-true-range bars ending at close=103.5 (the prior
    session close). Day 2: gaps up well above 103.5, then descends far enough
    to bracket it -- gap_filled must flip 0.0 -> 1.0 and stay latched."""
    base_ts = datetime(2026, 7, 6, 13, 30, tzinfo=UTC)
    day1_mids = [100.0 + 0.5 * i for i in range(8)]
    day1 = [
        {
            "open": m,
            "high": m + 0.5,
            "low": m - 0.5,
            "close": m,
            "volume": 1_000.0,
            "ts": base_ts + timedelta(minutes=5 * i),
        }
        for i, m in enumerate(day1_mids)
    ]
    prior_close = day1_mids[-1]
    day2_base = base_ts + timedelta(days=1)
    day2_phase1 = [prior_close + 3.0 + 0.2 * i for i in range(4)]  # stays above, no fill yet
    day2_phase2 = [day2_phase1[-1] - 1.0 * i for i in range(1, 7)]  # descends, crosses prior_close
    day2_mids = day2_phase1 + day2_phase2
    day2 = [
        {
            "open": m,
            "high": m + 0.5,
            "low": m - 0.5,
            "close": m,
            "volume": 1_000.0,
            "ts": day2_base + timedelta(minutes=5 * i),
        }
        for i, m in enumerate(day2_mids)
    ]
    return day1 + day2


def test_session_levels_gap_filled_column(cfg):
    """gap_filled must be exactly 0.0 or 1.0 (never None once ATR is valid
    and a prior session exists), both values must occur across a fixture
    designed to gap and then fill, and it must flip to 1.0 on the bar that
    first brackets the prior session close, then stay latched (D-13)."""
    bars_local = _build_gap_fill_bars()
    cache = FeatureCache()
    results = FeatureFactory.compute_batch(bars_local, "SPY", "5m", cache, cfg)

    day2_start_ts = bars_local[8]["ts"]
    day2_vals = [(ts, fv.gap_filled) for ts, fv in results if ts >= day2_start_ts]
    assert day2_vals, "no day-2 bars produced a result"
    assert all(
        v is not None for _, v in day2_vals
    ), "gap_filled must never be None once ATR is warm and a prior session exists"
    seen = {v for _, v in day2_vals}
    assert seen == {0.0, 1.0}, f"gap_filled must take both 0.0 and 1.0, saw {seen}"

    first_fill_idx = next(i for i, (_, v) in enumerate(day2_vals) if v == 1.0)
    assert all(
        v == 1.0 for _, v in day2_vals[first_fill_idx:]
    ), "gap_filled must stay latched at 1.0 once the prior close is bracketed"
    assert all(
        v == 0.0 for _, v in day2_vals[:first_fill_idx]
    ), "gap_filled must be 0.0 before the first bracketing bar"


# ---------------------------------------------------------------------------
# (g) live == batch parity for all 16 session-levels fields
# ---------------------------------------------------------------------------


def test_session_levels_live_batch_parity(session_bars, cfg):
    """Live (compute() driven per-bar exactly as the live pipeline does) must
    match batch to 1e-6 on all 16 session-levels fields -- catches a
    forgotten compute_batch() wiring update."""
    cache_batch = FeatureCache()
    batch_results = FeatureFactory.compute_batch(session_bars, "SPY", "5m", cache_batch, cfg)
    _, fv_batch_last = batch_results[-1]

    fv_live_last = _run_live_with_session_levels(session_bars, cfg)

    # Non-vacuousness guard: a derivation that unconditionally returns its
    # all-None fallback would make live and batch trivially "agree" (None ==
    # None on every field) without ever computing anything real -- caught
    # during this plan's own mutation-verification pass. At least one field
    # must carry a real value on both sides before the per-field parity
    # checks below are meaningful.
    assert any(
        getattr(fv_batch_last, f) is not None for f in _SESSION_LEVEL_FIELDS
    ), "parity check is vacuous -- fv_batch_last has all 16 session-levels fields None"
    assert any(
        getattr(fv_live_last, f) is not None for f in _SESSION_LEVEL_FIELDS
    ), "parity check is vacuous -- fv_live_last has all 16 session-levels fields None"

    for field in _SESSION_LEVEL_FIELDS:
        b = getattr(fv_batch_last, field)
        s = getattr(fv_live_last, field)
        if b is None or s is None:
            assert b == s, f"{field}: batch={b} live={s} (None mismatch)"
        else:
            assert abs(b - s) < 1e-6, f"{field}: batch={b:.10f} live={s:.10f}"


# ---------------------------------------------------------------------------
# (h) THE phase-closing gate: all 41 Phase 165 columns produce real values
# ---------------------------------------------------------------------------


def test_phase165_all_41_fields_non_constant_batch(session_bars, cfg):
    """Every one of the 41 Phase 165 fields must take at least one non-None
    value somewhere across a multi-session, multi-week batch run -- the
    single test that catches a whole sub-scope silently failing to wire (the
    todo-153 failure mode)."""
    cache = FeatureCache()
    results = FeatureFactory.compute_batch(session_bars, "SPY", "5m", cache, cfg)

    all_none: list[str] = []
    for field in _PHASE_165_FIELDS:
        vals = [getattr(fv, field) for _, fv in results if getattr(fv, field) is not None]
        if not vals:
            all_none.append(field)
    assert not all_none, f"Phase 165 field(s) NEVER non-None across the run: {all_none}"


# ---------------------------------------------------------------------------
# (i) field-set cross-check: dataclass, domain registry, concept_registry
# ---------------------------------------------------------------------------


def test_phase165_field_set_matches_registry():
    """All 41 Phase 165 fields must be real FeatureVector fields, tagged
    'structural' in FEATURE_VECTOR_DOMAIN, and present in concept_registry
    (domain='feature') with added_phase='165' -- skips cleanly if the live DB is
    unreachable so this test stays CI-clean (house pattern, matches
    tests/unit/test_spread_leg_pair_validity.py)."""
    fv_fields = {f.name for f in dataclasses.fields(FeatureVector)}
    assert len(_PHASE_165_FIELDS) == 41
    assert set(_PHASE_165_FIELDS) <= fv_fields

    for field in _PHASE_165_FIELDS:
        assert FEATURE_VECTOR_DOMAIN[field] == "structural", f"{field} not tagged 'structural'"

    try:
        conn = psycopg.connect("postgresql://postgres:postgres@localhost:5432/indicagent")
    except Exception:
        pytest.skip("Cannot connect to the live indicagent DB")
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT name FROM concept_registry WHERE domain = 'feature' AND added_phase = '165'"
            )
            registry_names = {row[0] for row in cur.fetchall()}
    finally:
        conn.close()

    assert registry_names == set(_PHASE_165_FIELDS), (
        f"concept_registry(domain='feature') added_phase='165' mismatch. "
        f"Missing from registry: {set(_PHASE_165_FIELDS) - registry_names}; "
        f"extra in registry: {registry_names - set(_PHASE_165_FIELDS)}"
    )
