"""Unit tests for Phase 137 P7: the 18 new FeatureVector features."""

from __future__ import annotations

import dataclasses
import math
from datetime import UTC, datetime

import numpy as np
import pytest

from services.backfill_feature_factory import _vector_to_params
from src.intelligence.feature_cache import FeatureCache
from src.intelligence.feature_factory import (
    FEATURE_VECTOR_DOMAIN,
    FeatureFactory,
    FeatureFactoryConfig,
    _amihud_illiq_z_series_full,
    _aroon_osc,
    _cci,
    _high_52w_dist_series_full,
    _in_london_kz,
    _opening_range,
    _pearson_acf1,
    _power_hour,
    _ret_acf1_z_series_full,
    _ret_skew_z_series_full,
    _rsi,
    _skewness,
)
from src.intelligence.schemas import FeatureVector

UTC = UTC


def _make_cfg(**overrides) -> FeatureFactoryConfig:
    defaults = dict(
        momentum_window_fast=5,
        momentum_window_mid=20,
        momentum_window_slow=60,
        momentum_zscore_window=20,
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
        min_bars_warmup=16,
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
    )
    defaults.update(overrides)
    return FeatureFactoryConfig(**defaults)


def _bars(n: int, start: float = 100.0, step: float = 0.1) -> list[dict]:
    ts = datetime(2026, 1, 7, 14, 0, tzinfo=UTC)
    return [
        {
            "open": start + i * step,
            "high": start + i * step + 1.0,
            "low": start + i * step - 1.0,
            "close": start + i * step,
            "volume": 1000.0 + i,
            "ts": ts,
        }
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# RSI
# ---------------------------------------------------------------------------


def test_rsi_neutral_flat_prices():
    closes = np.full(30, 100.0)
    assert _rsi(closes, 14) == 50.0


def test_rsi_all_up_days():
    closes = np.linspace(100.0, 130.0, 50)
    result = _rsi(closes, 14)
    assert result > 90.0


def test_rsi_range():
    rng = np.random.default_rng(42)
    closes = 100.0 + np.cumsum(rng.standard_normal(60))
    result = _rsi(closes, 14)
    assert 0.0 <= result <= 100.0


def test_rsi_cold_start():
    closes = np.array([100.0, 101.0, 102.0])
    assert _rsi(closes, 14) == 50.0


# ---------------------------------------------------------------------------
# CCI
# ---------------------------------------------------------------------------


def test_cci_uniform_prices():
    h = np.full(30, 101.0)
    lo = np.full(30, 99.0)
    c = np.full(30, 100.0)
    assert _cci(h, lo, c, 20) == 0.0


def test_cci_cold_start():
    h = np.array([101.0, 102.0])
    lo = np.array([99.0, 100.0])
    c = np.array([100.0, 101.0])
    assert _cci(h, lo, c, 10) == 0.0


def test_cci_finite():
    rng = np.random.default_rng(7)
    h = 100.0 + rng.uniform(0, 2, 50)
    lo = 100.0 - rng.uniform(0, 2, 50)
    c = 100.0 + rng.uniform(-1, 1, 50)
    assert math.isfinite(_cci(h, lo, c, 20))


# ---------------------------------------------------------------------------
# Aroon
# ---------------------------------------------------------------------------


def test_aroon_monotone_rise():
    h = np.linspace(100.0, 115.0, 30)
    lo = np.linspace(99.0, 114.0, 30)
    result = _aroon_osc(h, lo, 14)
    assert result == 1.0


def test_aroon_range():
    rng = np.random.default_rng(3)
    h = 100.0 + rng.uniform(0, 3, 40)
    lo = 100.0 - rng.uniform(0, 3, 40)
    result = _aroon_osc(h, lo, 14)
    assert -1.0 <= result <= 1.0


def test_aroon_cold_start():
    h = np.array([101.0, 102.0])
    lo = np.array([99.0, 100.0])
    assert _aroon_osc(h, lo, 14) == 0.0


# ---------------------------------------------------------------------------
# OFI divergence (via full compute)
# ---------------------------------------------------------------------------


def test_ofi_div_in_feature_vector():
    cfg = _make_cfg()
    cache = FeatureCache()
    bars = _bars(50)
    fv = FeatureFactory.compute(bars, "SPY", "1m", cache, cfg)
    assert math.isfinite(fv.ofi_div)


# ---------------------------------------------------------------------------
# Amihud
# ---------------------------------------------------------------------------


def test_amihud_zero_returns():
    closes = np.full(30, 100.0)
    volumes = np.full(30, 1000.0)
    assert _amihud_illiq_z_series_full(closes, volumes, 20)[-1] == 0.0


def test_amihud_cold_start():
    assert _amihud_illiq_z_series_full(np.array([100.0]), np.array([1000.0]), 20)[-1] == 0.0


def test_amihud_finite():
    rng = np.random.default_rng(11)
    closes = 100.0 + np.cumsum(rng.standard_normal(40))
    volumes = rng.uniform(500, 2000, 40)
    assert math.isfinite(_amihud_illiq_z_series_full(closes, volumes, 20)[-1])


# ---------------------------------------------------------------------------
# 52-week high distance
# ---------------------------------------------------------------------------


def test_high_52w_at_high():
    closes = np.linspace(90.0, 100.0, 30)
    assert _high_52w_dist_series_full(closes, 20)[-1] == pytest.approx(0.0)


def test_high_52w_below_high():
    closes = np.array([100.0] * 20 + [90.0])
    result = _high_52w_dist_series_full(closes, 21)[-1]
    assert result < 0.0


def test_high_52w_cold_start():
    assert _high_52w_dist_series_full(np.array([100.0]), 20)[-1] == 0.0


# ---------------------------------------------------------------------------
# Return skewness
# ---------------------------------------------------------------------------


def test_ret_skew_cold_start():
    closes = np.linspace(100.0, 105.0, 5)
    assert _ret_skew_z_series_full(closes, 10, 20)[-1] == 0.0


def test_ret_skew_finite():
    rng = np.random.default_rng(99)
    closes = 100.0 + np.cumsum(rng.standard_normal(80))
    assert math.isfinite(_ret_skew_z_series_full(closes, 10, 20)[-1])


def test_skewness_uniform_returns_zero():
    arr = np.linspace(-1.0, 1.0, 21)
    assert abs(_skewness(arr)) < 1e-6


# ---------------------------------------------------------------------------
# Return autocorrelation
# ---------------------------------------------------------------------------


def test_ret_acf1_cold_start():
    closes = np.linspace(100.0, 101.0, 4)
    assert _ret_acf1_z_series_full(closes, 5, 20)[-1] == 0.0


def test_ret_acf1_finite():
    rng = np.random.default_rng(55)
    closes = 100.0 + np.cumsum(rng.standard_normal(60))
    assert math.isfinite(_ret_acf1_z_series_full(closes, 5, 20)[-1])


def test_pearson_acf1_cold_start():
    assert _pearson_acf1(np.array([1.0])) == 0.0


# ---------------------------------------------------------------------------
# Calendar features
# ---------------------------------------------------------------------------


def test_in_london_kz_inside():
    ts = datetime(2026, 1, 7, 8, 30, tzinfo=UTC)
    cfg = _make_cfg()
    assert _in_london_kz(ts, cfg) == 1.0


def test_in_london_kz_outside():
    ts = datetime(2026, 1, 7, 12, 0, tzinfo=UTC)
    cfg = _make_cfg()
    assert _in_london_kz(ts, cfg) == 0.0


def test_power_hour_inside():
    ts = datetime(2026, 1, 7, 19, 30, tzinfo=UTC)
    cfg = _make_cfg()
    assert _power_hour(ts, cfg) == 1.0


def test_power_hour_outside():
    ts = datetime(2026, 1, 7, 15, 0, tzinfo=UTC)
    cfg = _make_cfg()
    assert _power_hour(ts, cfg) == 0.0


def test_opening_range_inside():
    ts = datetime(2026, 1, 7, 14, 0, tzinfo=UTC)
    cfg = _make_cfg()
    assert _opening_range(ts, cfg) == 1.0


def test_opening_range_outside():
    ts = datetime(2026, 1, 7, 16, 0, tzinfo=UTC)
    cfg = _make_cfg()
    assert _opening_range(ts, cfg) == 0.0


# ---------------------------------------------------------------------------
# above_wk_vwap and FeatureCache.update_wk_vwap
# ---------------------------------------------------------------------------


def test_above_wk_vwap_above():
    cache = FeatureCache()
    ts = datetime(2026, 1, 7, 14, 0, tzinfo=UTC)
    cache.update_wk_vwap(ts, 105.0, 95.0, 110.0, 1000.0)
    assert cache.above_wk_vwap == 1.0


def test_above_wk_vwap_below():
    cache = FeatureCache()
    ts = datetime(2026, 1, 7, 14, 0, tzinfo=UTC)
    cache.update_wk_vwap(ts, 105.0, 95.0, 90.0, 1000.0)
    assert cache.above_wk_vwap == 0.0


def test_wk_vwap_resets_on_new_week():
    cache = FeatureCache()
    ts_w1 = datetime(2026, 1, 5, 14, 0, tzinfo=UTC)  # ISO week 2
    ts_w2 = datetime(2026, 1, 12, 14, 0, tzinfo=UTC)  # ISO week 3
    cache.update_wk_vwap(ts_w1, 101.0, 99.0, 100.0, 5000.0)
    pre_vol = cache._wk_vol_sum
    cache.update_wk_vwap(ts_w2, 101.0, 99.0, 100.0, 1000.0)
    assert cache._wk_vol_sum < pre_vol  # reset then one bar added


# ---------------------------------------------------------------------------
# hmm_duration increments
# ---------------------------------------------------------------------------


def test_hmm_duration_increments():
    cache = FeatureCache()
    assert cache.hmm_duration == 0.0
    cache.hmm_duration += 1.0
    cache.hmm_duration += 1.0
    assert cache.hmm_duration == 2.0


# ---------------------------------------------------------------------------
# FEATURE_VECTOR_DOMAIN completeness
# ---------------------------------------------------------------------------


def test_feature_vector_domain_complete():
    """61 baseline + 18 Plan 01 + 22 Plan 02 + 14 Plan 05 + 21 Plan 03 + 8 Plan 04
    Renaissance primitives = 144."""
    fv_fields = {f.name for f in dataclasses.fields(FeatureVector)}
    assert len(FEATURE_VECTOR_DOMAIN) == 144
    assert set(FEATURE_VECTOR_DOMAIN.keys()) == fv_fields


# ---------------------------------------------------------------------------
# _vector_to_params length
# ---------------------------------------------------------------------------


def test_vector_to_params_length():
    cfg = _make_cfg()
    cache = FeatureCache()
    bars = _bars(50)
    ts = datetime(2026, 1, 7, 14, 0, tzinfo=UTC)
    fv = FeatureFactory.compute(bars, "SPY", "1m", cache, cfg)
    row = _vector_to_params("SPY", "1m", ts, "v3.0.0", None, fv)
    assert len(row) == 70, f"Expected 70, got {len(row)}"
