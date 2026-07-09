"""Parity: _*_series_full[i] must equal streaming FeatureFactory.compute() to 1e-8.

Tests run streaming compute at bars 300..349 once (module scope), then compare
each batch function's output at those indices. All windows are kept small so
tests stay fast (momentum_zscore_window=30, etc.).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from src.intelligence.feature_cache import FeatureCache
from src.intelligence.feature_factory import (
    FeatureFactory,
    FeatureFactoryConfig,
    _build_feature_vector,
)

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------
N = 500
_CHECK_START = 300
_CHECK_END = 340
RNG = np.random.default_rng(42)


def _make_cfg() -> FeatureFactoryConfig:
    """Small windows so all features warm up well before bar 300."""
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
    )


@pytest.fixture(scope="module")
def ohlcv():
    """500 synthetic OHLCV bars as arrays + dict list with real timestamps."""
    base_ts = datetime(2023, 1, 3, 14, 30, tzinfo=UTC)
    closes = np.cumprod(1.0 + RNG.normal(0, 0.005, N)) * 100.0
    spread = closes * RNG.uniform(0.001, 0.008, N)
    highs = closes + spread
    lows = closes - spread
    opens = closes + RNG.normal(0, 0.003, N) * closes
    highs = np.maximum(highs, np.maximum(opens, closes))
    lows = np.minimum(lows, np.minimum(opens, closes))
    volumes = RNG.uniform(1e5, 1e7, N)
    bars = [
        {
            "open": float(opens[i]),
            "high": float(highs[i]),
            "low": float(lows[i]),
            "close": float(closes[i]),
            "volume": float(volumes[i]),
            "ts": base_ts + timedelta(minutes=5 * i),
        }
        for i in range(N)
    ]
    return dict(closes=closes, highs=highs, lows=lows, opens=opens, volumes=volumes, bars=bars)


@pytest.fixture(scope="module")
def cfg():
    return _make_cfg()


@pytest.fixture(scope="module")
def streaming(ohlcv, cfg):
    """Pre-compute streaming FeatureFactory.compute() for bars 300..339.
    Returns dict: {bar_index: FeatureVector}.
    """
    bars = ohlcv["bars"]
    results = {}
    for i in range(_CHECK_START, _CHECK_END):
        cache = FeatureCache()
        fv = FeatureFactory.compute(bars[: i + 1], "SPY", "5m", cache, cfg)
        results[i] = fv
    return results


def _assert_parity(batch: np.ndarray, streaming: dict, field: str, tol: float = 1e-8) -> None:
    """Assert batch[i] matches the named streaming FeatureVector field at every checked bar."""
    assert len(batch) == N
    for i, fv in streaming.items():
        expected = getattr(fv, field)
        assert (
            abs(batch[i] - expected) < tol
        ), f"{field} bar {i}: batch={batch[i]:.10f} streaming={expected:.10f}"


# ---------------------------------------------------------------------------
# Task 1: Momentum series
# ---------------------------------------------------------------------------


def test_momentum_z_fast_parity(ohlcv, cfg, streaming):
    from src.intelligence.feature_factory import _momentum_z_series_full

    batch = _momentum_z_series_full(
        ohlcv["closes"], cfg.momentum_window_fast, cfg.momentum_zscore_window
    )
    _assert_parity(batch, streaming, "momentum_z_fast")


def test_momentum_z_mid_parity(ohlcv, cfg, streaming):
    from src.intelligence.feature_factory import _momentum_z_series_full

    batch = _momentum_z_series_full(
        ohlcv["closes"], cfg.momentum_window_mid, cfg.momentum_zscore_window
    )
    _assert_parity(batch, streaming, "momentum_z_mid")


def test_momentum_z_slow_parity(ohlcv, cfg, streaming):
    from src.intelligence.feature_factory import _momentum_z_series_full

    batch = _momentum_z_series_full(
        ohlcv["closes"], cfg.momentum_window_slow, cfg.momentum_zscore_window
    )
    _assert_parity(batch, streaming, "momentum_z_slow")


def test_momentum_reversal_z_parity(ohlcv, cfg, streaming):
    from src.intelligence.feature_factory import _momentum_reversal_z_series_full

    batch = _momentum_reversal_z_series_full(ohlcv["closes"], cfg.momentum_zscore_window)
    _assert_parity(batch, streaming, "momentum_reversal_z")


# ---------------------------------------------------------------------------
# Transition-boundary tests: verify cold-start/warm boundary exact parity
# ---------------------------------------------------------------------------


def _streaming_at(bar_idx: int, ohlcv: dict, cfg: FeatureFactoryConfig) -> object:
    """Compute streaming FeatureVector at a specific bar index (inclusive)."""
    cache = FeatureCache()
    return FeatureFactory.compute(ohlcv["bars"][: bar_idx + 1], "SPY", "5m", cache, cfg)


def test_momentum_z_fast_transition_boundary(ohlcv, cfg):
    """Batch must match streaming exactly at cold-start boundary for momentum_z_fast."""
    from src.intelligence.feature_factory import _momentum_z_series_full

    batch = _momentum_z_series_full(
        ohlcv["closes"], cfg.momentum_window_fast, cfg.momentum_zscore_window
    )

    wf = cfg.momentum_window_fast
    zw = cfg.momentum_zscore_window

    # Last bar where streaming returns 0.0 (insufficient history for z-score)
    last_cold = wf + zw - 2
    fv_cold = _streaming_at(last_cold, ohlcv, cfg)
    assert (
        abs(batch[last_cold] - fv_cold.momentum_z_fast) < 1e-8
    ), f"bar {last_cold} (last cold): batch={batch[last_cold]:.10f} streaming={fv_cold.momentum_z_fast:.10f}"

    # First bar where streaming returns non-zero
    first_warm = wf + zw - 1
    fv_warm = _streaming_at(first_warm, ohlcv, cfg)
    assert (
        abs(batch[first_warm] - fv_warm.momentum_z_fast) < 1e-8
    ), f"bar {first_warm} (first warm): batch={batch[first_warm]:.10f} streaming={fv_warm.momentum_z_fast:.10f}"

    # A few bars past the transition
    past_warm = wf + zw + 5
    fv_past = _streaming_at(past_warm, ohlcv, cfg)
    assert (
        abs(batch[past_warm] - fv_past.momentum_z_fast) < 1e-8
    ), f"bar {past_warm} (past warm): batch={batch[past_warm]:.10f} streaming={fv_past.momentum_z_fast:.10f}"


def test_momentum_reversal_z_transition_boundary(ohlcv, cfg):
    """Batch must match streaming exactly at the reversal cold-start boundary.

    The reversal path uses an expanding zscore window (min(zscore_window, len)),
    so streaming returns 0.0 only at bar 1 (single log-return, std=0) and transitions
    to non-zero at bar 2. The batch _rolling_zscore_series uses the same expanding
    semantics. Checks parity at bar 1 (cold), bar 2 (first non-zero), and several
    bars into the fully-saturated window region.
    """
    from src.intelligence.feature_factory import _momentum_reversal_z_series_full

    batch = _momentum_reversal_z_series_full(ohlcv["closes"], cfg.momentum_zscore_window)

    zw = cfg.momentum_zscore_window

    # Bar 1: single log-return; std=0 so streaming returns 0.0
    fv_bar1 = _streaming_at(1, ohlcv, cfg)
    assert (
        abs(batch[1] - fv_bar1.momentum_reversal_z) < 1e-8
    ), f"bar 1 (cold): batch={batch[1]:.10f} streaming={fv_bar1.momentum_reversal_z:.10f}"

    # Bar 2: first non-zero; expanding window of 2
    fv_bar2 = _streaming_at(2, ohlcv, cfg)
    assert (
        abs(batch[2] - fv_bar2.momentum_reversal_z) < 1e-8
    ), f"bar 2 (first warm): batch={batch[2]:.10f} streaming={fv_bar2.momentum_reversal_z:.10f}"

    # Bar at zscore_window - 1: last bar where expanding window is still < zscore_window
    last_expanding = zw - 1
    fv_last_exp = _streaming_at(last_expanding, ohlcv, cfg)
    assert (
        abs(batch[last_expanding] - fv_last_exp.momentum_reversal_z) < 1e-8
    ), f"bar {last_expanding} (last expanding): batch={batch[last_expanding]:.10f} streaming={fv_last_exp.momentum_reversal_z:.10f}"

    # Bar at zscore_window: first bar with fully-saturated window
    fv_sat = _streaming_at(zw, ohlcv, cfg)
    assert (
        abs(batch[zw] - fv_sat.momentum_reversal_z) < 1e-8
    ), f"bar {zw} (first saturated): batch={batch[zw]:.10f} streaming={fv_sat.momentum_reversal_z:.10f}"

    # A few bars past saturation
    past_sat = zw + 5
    fv_past = _streaming_at(past_sat, ohlcv, cfg)
    assert (
        abs(batch[past_sat] - fv_past.momentum_reversal_z) < 1e-8
    ), f"bar {past_sat} (past saturation): batch={batch[past_sat]:.10f} streaming={fv_past.momentum_reversal_z:.10f}"


# ---------------------------------------------------------------------------
# Task 2: Volume / OFI / CVD series
# ---------------------------------------------------------------------------


def test_volume_z_parity(ohlcv, cfg, streaming):
    from src.intelligence.feature_factory import _volume_z_series_full

    batch = _volume_z_series_full(ohlcv["volumes"], cfg.volume_zscore_window)
    _assert_parity(batch, streaming, "volume_z")


def test_ofi_z_parity(ohlcv, cfg, streaming):
    from src.intelligence.feature_factory import _ofi_z_series_full

    batch = _ofi_z_series_full(
        ohlcv["closes"],
        ohlcv["highs"],
        ohlcv["lows"],
        ohlcv["volumes"],
        cfg.ofi_zscore_window,
    )
    _assert_parity(batch, streaming, "ofi_z")


def test_cvd_slope_z_parity(ohlcv, cfg, streaming):
    from src.intelligence.feature_factory import _cvd_slope_z_series_full

    batch = _cvd_slope_z_series_full(
        ohlcv["closes"],
        ohlcv["highs"],
        ohlcv["lows"],
        ohlcv["volumes"],
        cfg.cvd_slope_bars,
        cfg.ofi_zscore_window,
    )
    _assert_parity(batch, streaming, "cvd_slope_z")


# ---------------------------------------------------------------------------
# Task 3: RSI series
# ---------------------------------------------------------------------------


def test_rsi_fast_parity(ohlcv, cfg, streaming):
    from src.intelligence.feature_factory import _rsi_series_full

    batch = _rsi_series_full(ohlcv["closes"], cfg.rsi_fast_period)
    _assert_parity(batch, streaming, "rsi_fast")


def test_rsi_mid_parity(ohlcv, cfg, streaming):
    from src.intelligence.feature_factory import _rsi_series_full

    batch = _rsi_series_full(ohlcv["closes"], cfg.rsi_mid_period)
    _assert_parity(batch, streaming, "rsi_mid")


def test_rsi_slow_parity(ohlcv, cfg, streaming):
    from src.intelligence.feature_factory import _rsi_series_full

    batch = _rsi_series_full(ohlcv["closes"], cfg.rsi_slow_period)
    _assert_parity(batch, streaming, "rsi_slow")


def test_rsi_fast_transition_boundary(ohlcv, cfg):
    """result[period] must match streaming at exactly period+1 closes."""
    from src.intelligence.feature_factory import _rsi_series_full

    period = cfg.rsi_fast_period
    batch = _rsi_series_full(ohlcv["closes"], period)

    # bar = period: streaming has exactly period+1 closes → SMA seed only
    cache = FeatureCache()
    fv = FeatureFactory.compute(ohlcv["bars"][: period + 1], "SPY", "5m", cache, cfg)
    assert (
        abs(batch[period] - fv.rsi_fast) < 1e-8
    ), f"bar {period}: batch={batch[period]:.10f} streaming={fv.rsi_fast:.10f}"

    # bar = period+1: first EMA update
    cache2 = FeatureCache()
    fv2 = FeatureFactory.compute(ohlcv["bars"][: period + 2], "SPY", "5m", cache2, cfg)
    assert (
        abs(batch[period + 1] - fv2.rsi_fast) < 1e-8
    ), f"bar {period+1}: batch={batch[period+1]:.10f} streaming={fv2.rsi_fast:.10f}"


# ---------------------------------------------------------------------------
# Task 4: Statistical series
# ---------------------------------------------------------------------------


def test_ret_skew_z_parity(ohlcv, cfg, streaming):
    from src.intelligence.feature_factory import _ret_skew_z_series_full

    batch = _ret_skew_z_series_full(
        ohlcv["closes"], cfg.ret_skew_window, cfg.ret_skew_zscore_window
    )
    _assert_parity(batch, streaming, "ret_skew_z")


def test_ret_acf1_z_parity(ohlcv, cfg, streaming):
    from src.intelligence.feature_factory import _ret_acf1_z_series_full

    batch = _ret_acf1_z_series_full(ohlcv["closes"], cfg.ret_acf_window, cfg.ret_acf_zscore_window)
    _assert_parity(batch, streaming, "ret_acf1_z")


def test_amihud_illiq_z_parity(ohlcv, cfg, streaming):
    from src.intelligence.feature_factory import _amihud_illiq_z_series_full

    batch = _amihud_illiq_z_series_full(ohlcv["closes"], ohlcv["volumes"], cfg.amihud_zscore_window)
    _assert_parity(batch, streaming, "amihud_illiq_z")


def test_high_52w_dist_parity(ohlcv, cfg, streaming):
    from src.intelligence.feature_factory import _high_52w_dist_series_full

    batch = _high_52w_dist_series_full(ohlcv["closes"], cfg.high_52w_window)
    _assert_parity(batch, streaming, "high_52w_dist")


# ---------------------------------------------------------------------------
# Task 5: vwap_dev_sigma + rel_volume
# ---------------------------------------------------------------------------


def test_vwap_dev_sigma_parity(ohlcv, cfg, streaming):
    from src.intelligence.feature_factory import _vwap_dev_sigma_series_full

    batch = _vwap_dev_sigma_series_full(
        ohlcv["opens"], ohlcv["highs"], ohlcv["lows"], ohlcv["closes"], ohlcv["volumes"]
    )
    # 1e-6 tolerance: running std via cumsum accumulates float error vs numpy's one-shot std
    _assert_parity(batch, streaming, "vwap_dev_sigma", tol=1e-6)


def test_rel_volume_parity(ohlcv, cfg, streaming):
    from src.intelligence.feature_factory import _rel_volume_series_full

    batch = _rel_volume_series_full(ohlcv["volumes"], cfg.volume_zscore_window)
    _assert_parity(batch, streaming, "rel_volume")


# ---------------------------------------------------------------------------
# Task 6: Integration smoke test
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Task 1 (new): _PrecomputedSeries + _precompute_series
# ---------------------------------------------------------------------------


def test_precompute_series_returns_all_fields(ohlcv, cfg):
    """_precompute_series bundles all series arrays with correct lengths."""
    import numpy as np

    from src.intelligence.feature_factory import _precompute_series, _PrecomputedSeries

    opens = np.array([b["open"] for b in ohlcv["bars"]], dtype=float)
    highs = np.array([b["high"] for b in ohlcv["bars"]], dtype=float)
    lows = np.array([b["low"] for b in ohlcv["bars"]], dtype=float)
    closes = np.array([b["close"] for b in ohlcv["bars"]], dtype=float)
    volumes = np.array([b["volume"] for b in ohlcv["bars"]], dtype=float)

    series = _precompute_series(opens, highs, lows, closes, volumes, cfg)

    assert isinstance(series, _PrecomputedSeries)
    n = len(ohlcv["bars"])
    # Each array must have length == len(ohlcv)
    assert len(series.atr_z) == n
    assert len(series.momentum_z_fast) == n
    assert len(series.momentum_z_mid) == n
    assert len(series.momentum_z_slow) == n
    assert len(series.momentum_reversal_z) == n
    assert len(series.volume_z) == n
    assert len(series.ofi_z) == n
    assert len(series.cvd_slope_z) == n
    assert len(series.gap_z) == n
    assert len(series.rel_volume) == n
    assert len(series.vwap_dev_sigma) == n
    assert len(series.rsi_fast) == n
    assert len(series.rsi_mid) == n
    assert len(series.rsi_slow) == n
    assert len(series.amihud_illiq_z) == n
    assert len(series.high_52w_dist) == n
    assert len(series.ret_skew_z) == n
    assert len(series.ret_acf1_z) == n
    # atr_raw needed by compute() for informed_flow
    assert len(series.atr_raw) == n - 1  # atr_series has len n-1


# ---------------------------------------------------------------------------
# _build_feature_vector tests
# ---------------------------------------------------------------------------


def test_build_feature_vector_guards_nan():
    """_build_feature_vector replaces non-finite values with fallbacks."""
    fv = _build_feature_vector(
        momentum_z_fast=float("nan"),
        momentum_z_mid=0.0,
        range_position=float("inf"),
        bar_close_pos=0.5,
        gap_z=0.0,
        momentum_z_slow=0.0,
        momentum_reversal_z=0.0,
        informed_flow=0.0,
        volume_z=0.0,
        ofi_z=0.0,
        ofi_div=0.0,
        cvd_slope_z=0.0,
        cmf=0.0,
        rel_volume=1.0,
        vwap_dev_sigma=0.0,
        atr_z=0.0,
        vol_ratio=1.0,
        poc_dist_atr=0.0,
        va_position=0.5,
        sr_support_dist=0.0,
        sr_resist_dist=0.0,
        hmm_regime_prob=0.0,
        hmm_entropy=0.0,
        hmm_duration=0.0,
        hurst=0.5,
        shannon=1.0,
        garch_ratio=1.0,
        hma_slope_z=0.0,
        adx=0.0,
        aroon_fast=0.0,
        aroon_slow=0.0,
        rsi_fast=50.0,
        rsi_mid=50.0,
        rsi_slow=50.0,
        cci_fast=0.0,
        cci_mid=0.0,
        cci_slow=0.0,
        vix_z=0.0,
        flight_quality=0.0,
        yield_slope_z=0.0,
        in_ny_session=0.0,
        in_london_kz=0.0,
        in_overlap=0.0,
        power_hour=0.0,
        opening_range=0.0,
        above_wk_vwap=0.0,
        dow_sin=0.0,
        dow_cos=1.0,
        month_position=1.0,
        quarter_position=0.0,
        days_to_month_end=0.0,
        ctf_momentum=0.0,
        ctf_vwap_align=0.0,
        ctf_regime_align=0.0,
        amihud_illiq_z=0.0,
        high_52w_dist=0.0,
        ret_skew_z=0.0,
        ret_acf1_z=0.0,
        body_ratio=0.0,
        upper_wick_ratio=0.5,
        lower_wick_ratio=0.5,
        range_vs_atr=0.0,
        close_vs_open_direction=0.0,
        overnight_gap=0.0,
        overnight_gap_z=0.0,
        range_efficiency=0.0,
        ret_lag_1=0.0,
        ret_lag_2=0.0,
        ret_lag_3=0.0,
        ret_lag_fast=0.0,
        ret_lag_mid=0.0,
        ret_lag_slow=0.0,
        open_ret=0.0,
        intraday_ret=0.0,
        open_vs_intraday=0.0,
        session_time_pos=0.0,
        hour_of_day_sin=0.0,
        hour_of_day_cos=1.0,
        week_of_month_sin=0.0,
        week_of_month_cos=1.0,
        day_of_month_sin=0.0,
        day_of_month_cos=1.0,
        week_of_year_sin=0.0,
        week_of_year_cos=1.0,
        month_sin=0.0,
        month_cos=1.0,
        vol_acceleration=1.0,
        dollar_vol_z=0.0,
        vol_range_ratio=0.0,
        vol_trend_ratio=1.0,
        up_vol_ratio_fast=0.5,
        up_vol_ratio_slow=0.5,
        vol_percentile=0.5,
        vol_persistence=0.0,
        vol_std_z=0.0,
        mfi_fast=50.0,
        mfi_slow=50.0,
        obv_z=0.0,
        dist_from_high_fast=0.0,
        dist_from_high_slow=0.0,
        dist_from_low_fast=0.0,
        dist_from_low_slow=0.0,
        range_pct_fast=0.0,
        range_pct_slow=0.0,
        stoch_k_fast=0.5,
        stoch_k_slow=0.5,
        price_percentile_fast=0.5,
        price_percentile_slow=0.5,
        efficiency_ratio_fast=0.0,
        efficiency_ratio_slow=0.0,
        ret_kurtosis_z_fast=0.0,
        ret_kurtosis_z_slow=0.0,
        ret_autocorr_1=0.0,
        ret_autocorr_5=0.0,
        updown_ratio_fast=1.0,
        updown_ratio_slow=1.0,
        streak_z=0.0,
        realized_var_ratio_fast=1.0,
        realized_var_ratio_slow=1.0,
        range_to_close=0.0,
        true_range_pct=0.0,
        vol_of_vol=0.0,
        high_low_corr=0.0,
        variance_ratio_fast=1.0,
        variance_ratio_slow=1.0,
        vol_asymmetry_z=0.0,
        bb_pct_b_fast=0.5,
        bb_pct_b_slow=0.5,
        hv_z_fast=0.0,
        hv_z_slow=0.0,
        hv_ratio=1.0,
        parkinson_vol_z=0.0,
        garman_klass_vol_z=0.0,
        yang_zhang_vol_z=0.0,
        parkinson_vol_velocity=0.0,
        garman_klass_vol_velocity=0.0,
        yang_zhang_vol_velocity=0.0,
        vol_velocity_z=0.0,
        intraday_noise_ratio=1.0,
        vol_body_product=0.0,
        ret_vol_product_fast=0.0,
        price_vol_corr_fast=0.0,
        price_vol_corr_slow=0.0,
        range_vol_product=0.0,
        up_vol_body_diff=0.0,
        ret_vol_ratio_fast=0.0,
        vol_skew_product=0.0,
    )
    assert fv.momentum_z_fast == 0.0  # nan -> fallback 0.0
    assert fv.range_position == 0.5  # inf -> fallback 0.5
    assert fv.momentum_z_mid == 0.0  # finite, unchanged


def test_build_feature_vector_none_passthrough():
    """_build_feature_vector passes None through for nullable VP/SR fields (batch path)."""
    fv = _build_feature_vector(
        momentum_z_fast=0.0,
        momentum_z_mid=0.0,
        range_position=0.5,
        bar_close_pos=0.5,
        gap_z=0.0,
        momentum_z_slow=0.0,
        momentum_reversal_z=0.0,
        informed_flow=0.0,
        volume_z=0.0,
        ofi_z=0.0,
        ofi_div=0.0,
        cvd_slope_z=0.0,
        cmf=0.0,
        rel_volume=1.0,
        vwap_dev_sigma=0.0,
        atr_z=0.0,
        vol_ratio=1.0,
        poc_dist_atr=None,
        va_position=None,
        sr_support_dist=None,
        sr_resist_dist=None,
        hmm_regime_prob=0.0,
        hmm_entropy=0.0,
        hmm_duration=0.0,
        hurst=0.5,
        shannon=1.0,
        garch_ratio=1.0,
        hma_slope_z=0.0,
        adx=0.0,
        aroon_fast=0.0,
        aroon_slow=0.0,
        rsi_fast=50.0,
        rsi_mid=50.0,
        rsi_slow=50.0,
        cci_fast=0.0,
        cci_mid=0.0,
        cci_slow=0.0,
        vix_z=0.0,
        flight_quality=0.0,
        yield_slope_z=0.0,
        in_ny_session=0.0,
        in_london_kz=0.0,
        in_overlap=0.0,
        power_hour=0.0,
        opening_range=0.0,
        above_wk_vwap=0.0,
        dow_sin=0.0,
        dow_cos=1.0,
        month_position=1.0,
        quarter_position=0.0,
        days_to_month_end=0.0,
        ctf_momentum=0.0,
        ctf_vwap_align=0.0,
        ctf_regime_align=0.0,
        amihud_illiq_z=0.0,
        high_52w_dist=0.0,
        ret_skew_z=0.0,
        ret_acf1_z=0.0,
        body_ratio=0.0,
        upper_wick_ratio=0.5,
        lower_wick_ratio=0.5,
        range_vs_atr=0.0,
        close_vs_open_direction=0.0,
        overnight_gap=0.0,
        overnight_gap_z=0.0,
        range_efficiency=0.0,
        ret_lag_1=0.0,
        ret_lag_2=0.0,
        ret_lag_3=0.0,
        ret_lag_fast=0.0,
        ret_lag_mid=0.0,
        ret_lag_slow=0.0,
        open_ret=0.0,
        intraday_ret=0.0,
        open_vs_intraday=0.0,
        session_time_pos=0.0,
        hour_of_day_sin=0.0,
        hour_of_day_cos=1.0,
        week_of_month_sin=0.0,
        week_of_month_cos=1.0,
        day_of_month_sin=0.0,
        day_of_month_cos=1.0,
        week_of_year_sin=0.0,
        week_of_year_cos=1.0,
        month_sin=0.0,
        month_cos=1.0,
        vol_acceleration=1.0,
        dollar_vol_z=0.0,
        vol_range_ratio=0.0,
        vol_trend_ratio=1.0,
        up_vol_ratio_fast=0.5,
        up_vol_ratio_slow=0.5,
        vol_percentile=0.5,
        vol_persistence=0.0,
        vol_std_z=0.0,
        mfi_fast=50.0,
        mfi_slow=50.0,
        obv_z=0.0,
        dist_from_high_fast=0.0,
        dist_from_high_slow=0.0,
        dist_from_low_fast=0.0,
        dist_from_low_slow=0.0,
        range_pct_fast=0.0,
        range_pct_slow=0.0,
        stoch_k_fast=0.5,
        stoch_k_slow=0.5,
        price_percentile_fast=0.5,
        price_percentile_slow=0.5,
        efficiency_ratio_fast=0.0,
        efficiency_ratio_slow=0.0,
        ret_kurtosis_z_fast=0.0,
        ret_kurtosis_z_slow=0.0,
        ret_autocorr_1=0.0,
        ret_autocorr_5=0.0,
        updown_ratio_fast=1.0,
        updown_ratio_slow=1.0,
        streak_z=0.0,
        realized_var_ratio_fast=1.0,
        realized_var_ratio_slow=1.0,
        range_to_close=0.0,
        true_range_pct=0.0,
        vol_of_vol=0.0,
        high_low_corr=0.0,
        variance_ratio_fast=1.0,
        variance_ratio_slow=1.0,
        vol_asymmetry_z=0.0,
        bb_pct_b_fast=0.5,
        bb_pct_b_slow=0.5,
        hv_z_fast=0.0,
        hv_z_slow=0.0,
        hv_ratio=1.0,
        parkinson_vol_z=0.0,
        garman_klass_vol_z=0.0,
        yang_zhang_vol_z=0.0,
        parkinson_vol_velocity=0.0,
        garman_klass_vol_velocity=0.0,
        yang_zhang_vol_velocity=0.0,
        vol_velocity_z=0.0,
        intraday_noise_ratio=1.0,
        vol_body_product=0.0,
        ret_vol_product_fast=0.0,
        price_vol_corr_fast=0.0,
        price_vol_corr_slow=0.0,
        range_vol_product=0.0,
        up_vol_body_diff=0.0,
        ret_vol_ratio_fast=0.0,
        vol_skew_product=0.0,
    )
    assert fv.poc_dist_atr is None
    assert fv.va_position is None
