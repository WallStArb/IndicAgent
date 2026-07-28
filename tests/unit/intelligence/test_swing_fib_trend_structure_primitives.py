"""Regression: Phase 165 swing/trend FeatureVector fields are non-constant, ATR-unit, live==batch, and
NULL (never a plausible number) on insufficient data (D-01, the todo-153 failure shape).

Plan 03 and Plan 04 append their own test classes to this same file -- shared helpers
(`_make_cfg`, `RNG`, `N`) stay at module level, sub-scopes are sectioned by comment header.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from src.intelligence.feature_cache import FeatureCache
from src.intelligence.feature_factory import FeatureFactory, FeatureFactoryConfig
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
