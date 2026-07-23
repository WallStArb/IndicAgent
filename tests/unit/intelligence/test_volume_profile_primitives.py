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

from src.intelligence.feature_cache import FeatureCache
from src.intelligence.feature_factory import FeatureFactory, FeatureFactoryConfig
from src.intelligence.schemas import FeatureVector

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


def test_vp_fields_non_constant_batch(bars, cfg):
    """poc_dist_atr/va_position/+ new fields must vary across bars, not freeze at defaults.

    This is the direct regression for todo 153: pre-Phase-163, poc_dist_atr was
    permanently 0.0 and va_position permanently 0.5 in the batch path.
    """
    cache = FeatureCache()
    results = FeatureFactory.compute_batch(bars, "SPY", "5m", cache, cfg)
    assert len(results) == N - 1  # compute_batch loop is range(1, len(bars))

    poc_dist_atr_vals = _finite([fv.poc_dist_atr for _, fv in results])
    assert len(poc_dist_atr_vals) > 1
    assert len({round(v, 8) for v in poc_dist_atr_vals}) > 1, "poc_dist_atr is constant"
    assert any(v != 0.0 for v in poc_dist_atr_vals), "poc_dist_atr frozen at 0.0"

    va_position_vals = _finite([fv.va_position for _, fv in results])
    assert len(va_position_vals) > 1
    assert all(0.0 <= v <= 1.0 for v in va_position_vals), "va_position out of [0,1]"
    assert len({round(v, 8) for v in va_position_vals}) > 1, "va_position is constant"
    assert any(v != 0.5 for v in va_position_vals), "va_position frozen at 0.5"

    distance_to_vah_atr_vals = _finite([fv.distance_to_vah_atr for _, fv in results])
    assert len(distance_to_vah_atr_vals) > 1
    assert len({round(v, 8) for v in distance_to_vah_atr_vals}) > 1, "distance_to_vah_atr constant"

    poc_rolling_vals = [fv.poc_rolling_dist_atr for _, fv in results]
    poc_rolling_finite = [v for v in poc_rolling_vals if v is not None]
    assert len(poc_rolling_finite) > 1
    assert all(math.isfinite(v) for v in poc_rolling_finite)
    assert len({round(v, 8) for v in poc_rolling_finite}) > 1, "poc_rolling_dist_atr constant"

    divergence_vals = [fv.poc_session_rolling_divergence_atr for _, fv in results]
    divergence_finite = [v for v in divergence_vals if v is not None]
    assert len(divergence_finite) > 1
    assert all(math.isfinite(v) for v in divergence_finite)
    assert (
        len({round(v, 8) for v in divergence_finite}) > 1
    ), "poc_session_rolling_divergence_atr constant"


# ---------------------------------------------------------------------------
# (b) live == batch parity
# ---------------------------------------------------------------------------


def test_live_batch_parity(bars, cfg):
    """Live (per-bar update_session_vp + compute()) must match batch to 1e-6."""
    n = len(bars)

    cache_batch = FeatureCache()
    batch_results = FeatureFactory.compute_batch(bars, "SPY", "5m", cache_batch, cfg)
    _, fv_batch_last = batch_results[-1]

    # Mirror compute_batch's own iteration bounds (range(1, n)) so both paths
    # accumulate the identical set of bars into the session-VP histogram.
    cache_live = FeatureCache()
    fv_live_last: FeatureVector | None = None
    for i in range(1, n):
        bar = bars[i]
        cache_live.update_session_vp(
            bar["ts"], bar["high"], bar["low"], bar["close"], bar["volume"], cfg
        )
        fv_live_last = FeatureFactory.compute(bars[: i + 1], "SPY", "5m", cache_live, cfg)

    assert fv_live_last is not None
    for field in _VP_FIELDS:
        b = getattr(fv_batch_last, field)
        s = getattr(fv_live_last, field)
        if b is None or s is None:
            assert b == s, f"{field}: batch={b} live={s} (None mismatch)"
        else:
            assert abs(b - s) < 1e-6, f"{field}: batch={b:.10f} live={s:.10f}"


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
