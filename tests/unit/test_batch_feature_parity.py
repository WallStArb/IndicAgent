"""Parity test: batch precomputed path vs bar-by-bar streaming path.

Tests N=500 synthetic bars — within _READ_CHUNK_BARS=2000 — so both paths
use full history from bar 0. All FeatureVector float fields must agree to 1e-8.
"""

import math
from datetime import UTC, datetime, timedelta

import numpy as np

from src.intelligence.feature_factory import (
    FeatureCache,
    FeatureFactory,
    FeatureFactoryConfig,
    _atr_series_full,
    _rolling_zscore_series,
)
from src.intelligence.schemas import FeatureVector


def _make_synthetic_bars(n: int, seed: int = 42) -> list[dict]:
    rng = np.random.default_rng(seed)
    close = 100.0 * np.cumprod(1 + rng.normal(0, 0.01, n))
    high = close * (1 + rng.uniform(0, 0.005, n))
    low = close * (1 - rng.uniform(0, 0.005, n))
    open_ = np.roll(close, 1)
    open_[0] = close[0]
    vol = rng.uniform(1e6, 5e6, n)
    base = datetime(2020, 1, 2, 9, 30, tzinfo=UTC)
    return [
        {
            "open": float(open_[i]),
            "high": float(high[i]),
            "low": float(low[i]),
            "close": float(close[i]),
            "volume": float(vol[i]),
            "ts": base + timedelta(minutes=5 * i),
        }
        for i in range(n)
    ]


def _default_config() -> FeatureFactoryConfig:
    return FeatureFactoryConfig(
        momentum_window_fast=5,
        momentum_window_mid=20,
        momentum_window_slow=60,
        momentum_zscore_window=100,
        volume_zscore_window=20,
        ofi_zscore_window=20,
        cvd_slope_bars=5,
        cmf_period=20,
        vol_short_bars=5,
        vol_long_bars=20,
        hma_period=20,
        adx_period=14,
        hurst_window=100,
        garch_window=100,
        vix_zscore_window=100,
        yield_curve_zscore_window=100,
        regime_cache_refresh_bars=30,
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
        rsi_fast_period=7,
        rsi_mid_period=14,
        rsi_slow_period=28,
        cci_fast_period=10,
        cci_mid_period=20,
        cci_slow_period=40,
        aroon_fast_period=14,
        aroon_slow_period=25,
        amihud_zscore_window=100,
        ret_skew_window=60,
        ret_skew_zscore_window=100,
        ret_acf_window=30,
        ret_acf_zscore_window=100,
        high_52w_window=252,
    )


def test_atr_gap_parity():
    """Precomputed ATR/gap_z path matches streaming path to 1e-8 for all bars."""
    N = 500
    bars = _make_synthetic_bars(N)
    cfg = _default_config()
    warm_up = 50

    highs_arr = np.array([b["high"] for b in bars], dtype=float)
    lows_arr = np.array([b["low"] for b in bars], dtype=float)
    closes_arr = np.array([b["close"] for b in bars], dtype=float)
    opens_arr = np.array([b["open"] for b in bars], dtype=float)
    zw = cfg.momentum_zscore_window

    # Mirrors backfill_feature_factory precompute block exactly.
    atr_core = _atr_series_full(highs_arr, lows_arr, closes_arr, cfg.adx_period)
    # Prepend 0.0: _atr_padded[j] = ATR(bars[0..j]), matching streaming's atr_series[j].
    atr_padded = np.concatenate([[0.0], atr_core])  # length = N
    atr_z_arr = _rolling_zscore_series(atr_padded, zw)
    # Gap at bar i uses ATR(first i bars) = atr_core[i-2]; denominator for bars 2..N-1.
    atr_for_gap = atr_core[:-1]
    gap_raw = (opens_arr[2:] - closes_arr[1:-1]) / np.where(atr_for_gap > 1e-10, atr_for_gap, 1.0)
    # Prepend 0.0 so at array index j+1, eff_w = min(zw, j+2) = min(zw, i), matching streaming.
    gap_raw_padded = np.concatenate([[0.0], gap_raw])  # length = N-1
    gap_z_core = _rolling_zscore_series(gap_raw_padded, zw)
    # gap_z_core[i-1] = gap_z at bar i for i>=2; prepend one 0.0 → gap_z_arr[i] = gap_z at bar i.
    gap_z_arr = np.concatenate([[0.0], gap_z_core])  # length = N

    cache_stream = FeatureCache()
    cache_batch = FeatureCache()

    for i in range(1, N):
        window = bars[: i + 1]  # full history (N=500 < _READ_CHUNK_BARS=2000)

        if i % cfg.regime_cache_refresh_bars == 0:
            cache_stream.refresh_regime(window, cfg)
            cache_batch.refresh_regime(window, cfg)

        if i < warm_up:
            last = bars[i]
            cache_stream.advance_bar(
                last["ts"], last["high"], last["low"], last["close"], last["volume"]
            )
            cache_batch.advance_bar(
                last["ts"], last["high"], last["low"], last["close"], last["volume"]
            )
            continue

        fv_stream = FeatureFactory.compute(window, "TEST", "5m", cache_stream, cfg)
        fv_batch = FeatureFactory.compute(
            window,
            "TEST",
            "5m",
            cache_batch,
            cfg,
            precomputed={
                "atr": float(atr_padded[i]),
                "atr_z": float(atr_z_arr[i]),
                "gap_z": float(gap_z_arr[i]),
            },
        )

        last = bars[i]
        cache_stream.advance_bar(
            last["ts"], last["high"], last["low"], last["close"], last["volume"]
        )
        cache_batch.advance_bar(
            last["ts"], last["high"], last["low"], last["close"], last["volume"]
        )

        for field in FeatureVector.__dataclass_fields__:
            v_s = getattr(fv_stream, field)
            v_b = getattr(fv_batch, field)
            if isinstance(v_s, float) and isinstance(v_b, float):
                if math.isnan(v_s) and math.isnan(v_b):
                    continue
                assert abs(v_s - v_b) < 1e-8, (
                    f"bar {i} field '{field}': stream={v_s:.10f} batch={v_b:.10f}"
                    f" delta={abs(v_s - v_b):.2e}"
                )
