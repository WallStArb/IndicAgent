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


# ---------------------------------------------------------------------------
# Task 1: Momentum series
# ---------------------------------------------------------------------------


def test_momentum_z_fast_parity(ohlcv, cfg, streaming):
    from src.intelligence.feature_factory import _momentum_z_series_full

    batch = _momentum_z_series_full(
        ohlcv["closes"], cfg.momentum_window_fast, cfg.momentum_zscore_window
    )
    assert len(batch) == N
    for i, fv in streaming.items():
        assert (
            abs(batch[i] - fv.momentum_z_fast) < 1e-8
        ), f"bar {i}: batch={batch[i]:.10f} streaming={fv.momentum_z_fast:.10f}"


def test_momentum_z_mid_parity(ohlcv, cfg, streaming):
    from src.intelligence.feature_factory import _momentum_z_series_full

    batch = _momentum_z_series_full(
        ohlcv["closes"], cfg.momentum_window_mid, cfg.momentum_zscore_window
    )
    assert len(batch) == N
    for i, fv in streaming.items():
        assert (
            abs(batch[i] - fv.momentum_z_mid) < 1e-8
        ), f"bar {i}: batch={batch[i]:.10f} streaming={fv.momentum_z_mid:.10f}"


def test_momentum_z_slow_parity(ohlcv, cfg, streaming):
    from src.intelligence.feature_factory import _momentum_z_series_full

    batch = _momentum_z_series_full(
        ohlcv["closes"], cfg.momentum_window_slow, cfg.momentum_zscore_window
    )
    assert len(batch) == N
    for i, fv in streaming.items():
        assert (
            abs(batch[i] - fv.momentum_z_slow) < 1e-8
        ), f"bar {i}: batch={batch[i]:.10f} streaming={fv.momentum_z_slow:.10f}"


def test_momentum_reversal_z_parity(ohlcv, cfg, streaming):
    from src.intelligence.feature_factory import _momentum_reversal_z_series_full

    batch = _momentum_reversal_z_series_full(ohlcv["closes"], cfg.momentum_zscore_window)
    assert len(batch) == N
    for i, fv in streaming.items():
        assert (
            abs(batch[i] - fv.momentum_reversal_z) < 1e-8
        ), f"bar {i}: batch={batch[i]:.10f} streaming={fv.momentum_reversal_z:.10f}"
