"""Parity: _*_series_full[i] must equal streaming FeatureFactory.compute() to 1e-8.

Tests run streaming compute at bars 300..349 once (module scope), then compare
each batch function's output at those indices. All windows are kept small so
tests stay fast (momentum_zscore_window=30, etc.).
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from src.intelligence.feature_cache import FeatureCache
from src.intelligence.feature_factory import (
    FeatureFactory,
    FeatureFactoryConfig,
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


def test_full_precomputed_produces_valid_feature_vectors(ohlcv, cfg):
    """Verify the full precomputed path produces valid, non-zero FeatureVectors."""
    from src.intelligence.feature_factory import (
        _amihud_illiq_z_series_full,
        _atr_series_full,
        _cvd_slope_z_series_full,
        _high_52w_dist_series_full,
        _momentum_reversal_z_series_full,
        _momentum_z_series_full,
        _ofi_z_series_full,
        _rel_volume_series_full,
        _ret_acf1_z_series_full,
        _ret_skew_z_series_full,
        _rolling_zscore_series,
        _rsi_series_full,
        _volume_z_series_full,
        _vwap_dev_sigma_series_full,
    )

    closes = ohlcv["closes"]
    highs = ohlcv["highs"]
    lows = ohlcv["lows"]
    opens = ohlcv["opens"]
    volumes = ohlcv["volumes"]
    bars = ohlcv["bars"]
    zw = cfg.momentum_zscore_window

    atr_core = _atr_series_full(highs, lows, closes, cfg.adx_period)
    atr_padded = np.concatenate([[0.0], atr_core])
    atr_z_full = _rolling_zscore_series(atr_padded, zw)
    atr_for_gap = atr_core[:-1]
    gap_raw = (opens[2:] - closes[1:-1]) / np.where(atr_for_gap > 1e-10, atr_for_gap, 1.0)
    gap_raw_padded = np.concatenate([[0.0], gap_raw])
    gap_z_core = _rolling_zscore_series(gap_raw_padded, zw)
    gap_z_full = np.concatenate([[0.0], gap_z_core])

    precomputed_arrays = {
        "atr_padded": atr_padded,
        "atr_z": atr_z_full,
        "gap_z": gap_z_full,
        "mom_fast_z": _momentum_z_series_full(closes, cfg.momentum_window_fast, zw),
        "mom_mid_z": _momentum_z_series_full(closes, cfg.momentum_window_mid, zw),
        "mom_slow_z": _momentum_z_series_full(closes, cfg.momentum_window_slow, zw),
        "mom_rev_z": _momentum_reversal_z_series_full(closes, zw),
        "volume_z": _volume_z_series_full(volumes, cfg.volume_zscore_window),
        "ofi_z": _ofi_z_series_full(closes, highs, lows, volumes, cfg.ofi_zscore_window),
        "cvd_slope_z": _cvd_slope_z_series_full(
            closes, highs, lows, volumes, cfg.cvd_slope_bars, cfg.ofi_zscore_window
        ),
        "rsi_fast": _rsi_series_full(closes, cfg.rsi_fast_period),
        "rsi_mid": _rsi_series_full(closes, cfg.rsi_mid_period),
        "rsi_slow": _rsi_series_full(closes, cfg.rsi_slow_period),
        "ret_skew_z": _ret_skew_z_series_full(
            closes, cfg.ret_skew_window, cfg.ret_skew_zscore_window
        ),
        "ret_acf1_z": _ret_acf1_z_series_full(
            closes, cfg.ret_acf_window, cfg.ret_acf_zscore_window
        ),
        "amihud_illiq_z": _amihud_illiq_z_series_full(closes, volumes, cfg.amihud_zscore_window),
        "high_52w_dist": _high_52w_dist_series_full(closes, cfg.high_52w_window),
        "vwap_dev_sigma": _vwap_dev_sigma_series_full(opens, highs, lows, closes, volumes),
        "rel_volume": _rel_volume_series_full(volumes, cfg.volume_zscore_window),
    }

    min_window = 50
    vectors_produced = 0
    for i in range(300, 350):
        cache = FeatureCache()
        window_start = max(0, i - min_window)
        window = bars[window_start : i + 1]
        fv = FeatureFactory.compute(
            window,
            "SPY",
            "5m",
            cache,
            cfg,
            precomputed={
                "atr": float(precomputed_arrays["atr_padded"][i]),
                "atr_z": float(precomputed_arrays["atr_z"][i]),
                "gap_z": float(precomputed_arrays["gap_z"][i]),
                "momentum_z_fast": float(precomputed_arrays["mom_fast_z"][i]),
                "momentum_z_mid": float(precomputed_arrays["mom_mid_z"][i]),
                "momentum_z_slow": float(precomputed_arrays["mom_slow_z"][i]),
                "momentum_reversal_z": float(precomputed_arrays["mom_rev_z"][i]),
                "volume_z": float(precomputed_arrays["volume_z"][i]),
                "ofi_z": float(precomputed_arrays["ofi_z"][i]),
                "cvd_slope_z": float(precomputed_arrays["cvd_slope_z"][i]),
                "rsi_fast": float(precomputed_arrays["rsi_fast"][i]),
                "rsi_mid": float(precomputed_arrays["rsi_mid"][i]),
                "rsi_slow": float(precomputed_arrays["rsi_slow"][i]),
                "ret_skew_z": float(precomputed_arrays["ret_skew_z"][i]),
                "ret_acf1_z": float(precomputed_arrays["ret_acf1_z"][i]),
                "amihud_illiq_z": float(precomputed_arrays["amihud_illiq_z"][i]),
                "high_52w_dist": float(precomputed_arrays["high_52w_dist"][i]),
                "vwap_dev_sigma": float(precomputed_arrays["vwap_dev_sigma"][i]),
                "rel_volume": float(precomputed_arrays["rel_volume"][i]),
            },
        )
        # Every produced vector must have finite values
        import dataclasses

        for field in dataclasses.fields(fv):
            val = getattr(fv, field.name)
            if val is not None:
                assert math.isfinite(val), f"bar {i} field {field.name} is not finite: {val}"
        vectors_produced += 1

    assert vectors_produced == 50
