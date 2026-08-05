"""Regression: SMC Liquidity Sweeps + Liquidity Pools (Phase 164 Plan 03).

Wires FeatureFactory._compute_liquidity_sweeps() / _compute_liquidity_pools()
(stateless, ported from archive/smc_context/liquidity_sweeps.py + liquidity_pools.py)
into FeatureFactory.compute()/compute_batch(), replacing the 9 None placeholders Plan 01
threaded for sweep_detected/sweep_strength/reclaim_velocity/bars_since_last_sweep/
bsl_dist_atr/ssl_dist_atr/bsl_touches/ssl_touches/pool_count. Liquidity Pools is
single-timeframe-descoped per 164-RESEARCH.md: PWH/PWL/PDH/PDL (which need a 1d frame the
live compute() signature cannot provide) are dropped -- only equal-highs/equal-lows +
session-high/low survive.

_compute_liquidity_sweeps()/_compute_liquidity_pools() land in Task 2 (tdd="true"); this
file is authored in Task 1 and is expected to fail (RED) against Task 1's code (which
still threads None for every field this file exercises) until Task 2 lands.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest

from src.intelligence.feature_cache import FeatureCache
from src.intelligence.feature_factory import (
    FeatureFactory,
    FeatureFactoryConfig,
    _compute_liquidity_pools,
    _compute_liquidity_sweeps,
)

_SWEEP_FIELDS = ("sweep_detected", "sweep_strength", "reclaim_velocity", "bars_since_last_sweep")
_POOL_FIELDS = ("bsl_dist_atr", "ssl_dist_atr", "bsl_touches", "ssl_touches", "pool_count")


def _make_cfg(**overrides: object) -> FeatureFactoryConfig:
    """Small windows so all features warm up well within these fixtures' bar counts.

    smc_liquidity_sweeps_*/smc_liquidity_pools_* left at their dataclass defaults
    (lookback=120/150, swing_neighbor=5, reclaim_bars=3, etc.) -- same convention as
    Phase 164 Plan 02's own tests.
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


# ---------------------------------------------------------------------------
# Fixture builders — small, deterministic, hand-computed OHLCV sequences.
# ---------------------------------------------------------------------------

_BASE_TS = datetime(2023, 1, 3, 14, 0, tzinfo=UTC)


def _extend(bars: list[dict], open_: float, high: float, low: float, close: float) -> None:
    bars.append(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": 1e5,
            "ts": bars[-1]["ts"] + timedelta(minutes=1),
        }
    )


def _flat_bars(n: int, price: float) -> list[dict]:
    """n perfectly flat bars (constant 0.2-wide high/low wick around price).

    Deterministic non-zero true range every bar (keeps ATR positive) without
    ever forming a swing high/low (no strict inequality between bars).
    """
    bars = [
        {
            "open": price,
            "high": price + 0.1,
            "low": price - 0.1,
            "close": price,
            "volume": 1e5,
            "ts": _BASE_TS,
        }
    ]
    for _ in range(n - 1):
        _extend(bars, price, price + 0.1, price - 0.1, price)
    return bars


def _sweep_bars() -> list[dict]:
    """Flat consolidation -> clean swing-high spike -> flat hold -> a bar
    wicking above the swing high and closing back below it (bearish sweep)
    -> 3 bars confirming the reclaim (closing consistently below the level).
    """
    bars = _flat_bars(20, 100.0)
    price = 100.0

    sh_price = price + 2.0
    _extend(bars, price, sh_price, price - 0.1, price + 0.1)
    price = bars[-1]["close"]  # 100.1

    for _ in range(6):
        _extend(bars, price, price + 0.1, price - 0.1, price)

    _extend(bars, price, sh_price + 0.5, price - 0.1, price - 0.1)
    price = bars[-1]["close"]

    for _ in range(3):
        close = price - 0.05
        _extend(bars, price, price + 0.05, close - 0.05, close)
        price = close

    return bars


def _no_sweep_bars() -> list[dict]:
    """No spike anywhere -- pure flat consolidation, no swing structure at all."""
    return _flat_bars(60, 100.0)


def _equal_highs_pool_bars() -> list[dict]:
    """Two swing-high spikes at nearly the same level (an equal-highs
    cluster, both well above the final close), separated by enough flat
    filler for each to register as an independent swing high.
    """
    bars = _flat_bars(20, 100.0)
    price = 100.0

    _extend(bars, price, 102.0, price - 0.1, price + 0.1)
    price = bars[-1]["close"]  # 100.1
    for _ in range(11):
        _extend(bars, price, price + 0.1, price - 0.1, price)

    _extend(bars, price, 102.02, price - 0.1, price + 0.1)
    price = bars[-1]["close"]
    for _ in range(11):
        _extend(bars, price, price + 0.1, price - 0.1, price)

    return bars


# ---------------------------------------------------------------------------
# (a) Liquidity sweep fires -- bounded strength/velocity, real bars_since
# ---------------------------------------------------------------------------


def test_sweep_detected_fires_with_bounded_strength_and_velocity(cfg):
    bars = _sweep_bars()
    cache = FeatureCache()
    fv = FeatureFactory.compute(bars, "SPY", "5m", cache, cfg)

    assert fv.sweep_detected == 1.0
    assert fv.sweep_strength is not None and 0.0 <= fv.sweep_strength <= 1.0
    assert fv.reclaim_velocity is not None and 0.0 <= fv.reclaim_velocity <= 1.0
    assert fv.bars_since_last_sweep is not None
    assert math.isfinite(fv.bars_since_last_sweep)
    assert fv.bars_since_last_sweep >= 0.0
    assert fv.bars_since_last_sweep == float(
        int(fv.bars_since_last_sweep)
    ), "bars_since_last_sweep must be integer-valued"


def test_no_sweep_in_window_never_nan(cfg):
    bars = _no_sweep_bars()
    cache = FeatureCache()
    fv = FeatureFactory.compute(bars, "SPY", "5m", cache, cfg)

    assert fv.sweep_detected == 0.0
    assert fv.bars_since_last_sweep is not None
    assert math.isfinite(fv.bars_since_last_sweep)


# ---------------------------------------------------------------------------
# (b) Liquidity pools -- equal-highs cluster, single-tf descoped
# ---------------------------------------------------------------------------


def test_equal_highs_cluster_produces_bsl_pool(cfg):
    bars = _equal_highs_pool_bars()
    cache = FeatureCache()
    fv = FeatureFactory.compute(bars, "SPY", "5m", cache, cfg)

    assert fv.bsl_dist_atr is not None
    assert math.isfinite(fv.bsl_dist_atr)
    assert fv.bsl_touches is not None and fv.bsl_touches >= 2.0
    assert fv.pool_count is not None and fv.pool_count >= 1.0


def test_pwh_pwl_pdh_pdl_never_computed(cfg):
    """PWH/PWL/PDH/PDL are descoped -- no such field exists on FeatureVector,
    and _compute_liquidity_pools() has no 1d-frame parameter at all.
    """
    bars = _equal_highs_pool_bars()
    cache = FeatureCache()
    fv = FeatureFactory.compute(bars, "SPY", "5m", cache, cfg)

    for raw_field in (
        "pwh_dist_atr",
        "pwl_dist_atr",
        "pdh_dist_atr",
        "pdl_dist_atr",
        "pwh_level",
        "pwl_level",
        "pdh_level",
        "pdl_level",
    ):
        assert not hasattr(fv, raw_field), f"descoped field {raw_field} leaked onto FeatureVector"

    import inspect

    sig = inspect.signature(_compute_liquidity_pools)
    assert "df_1d" not in sig.parameters
    assert "frames" not in sig.parameters
    assert not any(
        "1d" in p for p in sig.parameters
    ), "liquidity pools helper must not accept a 1d-timeframe argument"


# ---------------------------------------------------------------------------
# (c) Fallback contract -- never raises on atr<=0 or too-short window (T-164-05)
# ---------------------------------------------------------------------------


def test_sweeps_fallback_on_invalid_atr():
    import numpy as np

    highs = np.array([100.0, 101.0, 100.5, 101.5, 100.0])
    lows = np.array([99.0, 99.5, 99.0, 100.0, 99.5])
    closes = np.array([99.5, 100.5, 99.5, 100.5, 99.8])

    result = _compute_liquidity_sweeps(highs, lows, closes, 99.8, 0.0, _make_cfg())
    assert result["sweep_detected"] == 0.0
    assert result["bars_since_last_sweep"] == 0.0
    for v in result.values():
        assert math.isfinite(v)


def test_pools_fallback_on_invalid_atr():
    import numpy as np

    highs = np.array([100.0, 101.0, 100.5, 101.5, 100.0])
    lows = np.array([99.0, 99.5, 99.0, 100.0, 99.5])
    closes = np.array([99.5, 100.5, 99.5, 100.5, 99.8])

    result = _compute_liquidity_pools(highs, lows, closes, 99.8, 0.0, _make_cfg())
    assert result["pool_count"] == 0.0
    assert result["bsl_dist_atr"] == 0.0
    assert result["ssl_dist_atr"] == 0.0
    for v in result.values():
        assert math.isfinite(v)


def test_sweeps_fallback_on_short_window():
    import numpy as np

    highs = np.array([100.0, 101.0])
    lows = np.array([99.0, 99.5])
    closes = np.array([99.5, 100.5])

    result = _compute_liquidity_sweeps(highs, lows, closes, 100.5, 1.0, _make_cfg())
    assert result["sweep_detected"] == 0.0
    for v in result.values():
        assert math.isfinite(v)


def test_pools_fallback_on_short_window():
    import numpy as np

    highs = np.array([100.0, 101.0])
    lows = np.array([99.0, 99.5])
    closes = np.array([99.5, 100.5])

    result = _compute_liquidity_pools(highs, lows, closes, 100.5, 1.0, _make_cfg())
    assert result["pool_count"] == 0.0
    for v in result.values():
        assert math.isfinite(v)


# ---------------------------------------------------------------------------
# (d) Raw-price / redundant-copy fields must never exist on FeatureVector
# ---------------------------------------------------------------------------


def test_liquidity_no_raw_price_fields_on_feature_vector(cfg):
    cache = FeatureCache()
    fv = FeatureFactory.compute(_sweep_bars(), "SPY", "5m", cache, cfg)

    for raw_field in ("sweep_level", "bsl_level", "ssl_level", "bsl_type", "ssl_type"):
        assert not hasattr(fv, raw_field), f"raw-price field {raw_field} leaked onto FeatureVector"


# ---------------------------------------------------------------------------
# (e) Determinism -- pure-function contract (T-164-04)
# ---------------------------------------------------------------------------


def test_liquidity_determinism_identical_inputs_identical_outputs(cfg):
    bars = _sweep_bars()

    fv1 = FeatureFactory.compute(bars, "SPY", "5m", FeatureCache(), cfg)
    fv2 = FeatureFactory.compute(bars, "SPY", "5m", FeatureCache(), cfg)

    for field in _SWEEP_FIELDS + _POOL_FIELDS:
        v1 = getattr(fv1, field)
        v2 = getattr(fv2, field)
        assert v1 == v2, f"{field}: non-deterministic ({v1} != {v2})"


# ---------------------------------------------------------------------------
# (f) compute_batch() produces non-constant liquidity fields
# ---------------------------------------------------------------------------


def _finite(values: list[float | None]) -> list[float]:
    return [v for v in values if v is not None and math.isfinite(v)]


def test_compute_batch_produces_non_constant_liquidity_fields(cfg):
    bars = _sweep_bars()
    cache = FeatureCache()
    results = FeatureFactory.compute_batch(bars, "SPY", "5m", cache, cfg)
    assert len(results) == len(bars) - 1

    for field in ("sweep_detected", "bars_since_last_sweep"):
        vals = _finite([getattr(fv, field) for _, fv in results])
        assert len(vals) > 1
        assert len({round(v, 8) for v in vals}) > 1, f"{field} is constant across compute_batch()"


def test_liquidity_compute_live_batch_parity(cfg):
    """Live (compute() over the full growing history) must match batch to 1e-6."""
    bars = _equal_highs_pool_bars()
    n = len(bars)

    cache_batch = FeatureCache()
    batch_results = FeatureFactory.compute_batch(bars, "SPY", "5m", cache_batch, cfg)
    _, fv_batch_last = batch_results[-1]

    cache_live = FeatureCache()
    fv_live_last = None
    for i in range(1, n):
        bar = bars[i]
        cache_live.update_session_vp(
            bar["ts"], bar["high"], bar["low"], bar["close"], bar["volume"], cfg
        )
        fv_live_last = FeatureFactory.compute(bars[: i + 1], "SPY", "5m", cache_live, cfg)

    assert fv_live_last is not None
    for field in _SWEEP_FIELDS + _POOL_FIELDS:
        b = getattr(fv_batch_last, field)
        s = getattr(fv_live_last, field)
        if b is None or s is None:
            assert b == s, f"{field}: batch={b} live={s} (None mismatch)"
        else:
            assert abs(b - s) < 1e-6, f"{field}: batch={b:.10f} live={s:.10f}"
