"""Regression: session-VP FeatureVector fields are non-constant and live==batch (todo 153).

Phase 163 Plan 02 wires FeatureCache.update_session_vp() (Plan 01's mutator) into both
FeatureFactory.compute() (live) and compute_batch() (backfill), deriving the 14
ATR-normalized/bounded VP FeatureVector fields (poc_dist_atr, va_position, + 12 new
structural fields) from the cache's raw session levels. Before this plan, poc_dist_atr
and va_position were permanently frozen at their 0.0/0.5 defaults in both paths (the
original todo-153 bug) -- these tests would have caught that regression.
"""

from __future__ import annotations

import dataclasses
import math
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from src.intelligence.features.feature_factory_config import FeatureFactoryConfig
from src.intelligence.features.feature_vector import FeatureVector

# ---------------------------------------------------------------------------
# Shared fixtures — single NY session, ~90 1m bars (well within the
# 13:30-20:00 UTC session window so no session-boundary reset fires mid-sequence)
# ---------------------------------------------------------------------------

N = 90
RNG = np.random.default_rng(163)

# VP FeatureVector fields shared between live compute() and batch compute_batch()
_VP_FIELDS = (
    "poc_dist_atr",
    "va_position",
    "nearest_hvn_above_dist_atr",
    "nearest_hvn_below_dist_atr",
    "nearest_lvn_above_dist_atr",
    "nearest_lvn_below_dist_atr",
    "nearest_hvn_dist_atr",
    "va_width_atr",
    "distance_to_vah_atr",
    "distance_to_val_atr",
    "price_in_value_area",
    "in_lvn",
    "poc_rolling_dist_atr",
    "poc_session_rolling_divergence_atr",
)


def _make_cfg() -> FeatureFactoryConfig:
    """Small windows so all features warm up well within N=90 bars."""
    return FeatureFactoryConfig(
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
        rsi_velocity_window=20,
        ofi_velocity_window=20,
        cvd_velocity_window=20,
        volume_velocity_window=20,
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
        # session_vp_rolling_window overridden well below N=90: the production
        # default (480) exceeds the whole test session, so the rolling and
        # session-anchored tracks would only ever differ by the single bar
        # (bar 0) the session accumulator excludes (compute_batch's loop
        # starts at i=1) -- degenerate for exercising divergence. A window of
        # 15 gives a genuine trailing subset once the session has more than
        # 15 bars, so poc_rolling_dist_atr/poc_session_rolling_divergence_atr
        # are actually exercised. n_buckets/value_area_pct/hvn/lvn thresholds
        # left at dataclass defaults (Phase 163 Plan 01).
        session_vp_rolling_window=15,
    )


@pytest.fixture(scope="module")
def cfg() -> FeatureFactoryConfig:
    return _make_cfg()


@pytest.fixture(scope="module")
def bars() -> list[dict]:
    """~90 1m bars, single NY session, realistic swinging price path.

    base_ts is well inside the 13:30-20:00 UTC session window (390 minutes
    available; N=90 minutes used) so no session-boundary reset fires mid-
    sequence. A sine-wave + noise price path gives distinct volume-profile
    buckets real occupancy variety so POC/VAH/VAL shift meaningfully as the
    session progresses -- the exact condition the original todo-153 bug
    (frozen poc_dist_atr=0.0/va_position=0.5) would have masked.
    """
    base_ts = datetime(2023, 1, 3, 14, 0, tzinfo=UTC)
    t = np.arange(N)
    swing = np.sin(t / 12.0) * 2.0
    closes = 100.0 + swing + np.cumsum(RNG.normal(0, 0.05, N))
    spread = np.abs(RNG.normal(0.15, 0.05, N)) + 0.05
    highs = closes + spread
    lows = closes - spread
    opens = closes + RNG.normal(0, 0.05, N)
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


# ---------------------------------------------------------------------------
# (a) VP fields non-constant + bounded (batch path)
# ---------------------------------------------------------------------------


def _finite(values: list[float | None]) -> list[float]:
    return [v for v in values if v is not None and math.isfinite(v)]


# ---------------------------------------------------------------------------
# (b) live == batch parity
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# (c) no raw price level ever persisted (D-16/D-18 guard)
# ---------------------------------------------------------------------------


def test_no_raw_price_persisted():
    """FeatureVector must never carry a raw price-level VP attribute (D-16/D-18)."""
    forbidden = (
        "poc_price",
        "vah",
        "val",
        "poc_price_rolling",
        "vah_rolling",
        "val_rolling",
        "nearest_hvn_level",
        "nearest_lvn_level",
    )
    field_names = {f.name for f in dataclasses.fields(FeatureVector)}
    for name in forbidden:
        assert name not in field_names, f"forbidden raw-price attribute present: {name}"


# ---------------------------------------------------------------------------
# (d) CR-02 (163-REVIEW.md): live's BarHistory(maxlen=200) caps the effective
# rolling-POC window below what session_vp_rolling_window configures, unlike
# backfill which reads unbounded history. Pins the known, documented gap
# (migration 256) so it can't silently widen without a test failure.
# ---------------------------------------------------------------------------
