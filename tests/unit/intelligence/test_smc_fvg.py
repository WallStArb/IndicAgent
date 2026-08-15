"""Regression: SMC Fair Value Gaps (Phase 164 Plan 03).

Wires FeatureFactory._compute_fvg() (stateless 3-candle imbalance scan, ported from
archive/smc_context/fair_value_gap.py) into FeatureFactory.compute()/compute_batch(),
replacing the 3 None placeholders Plan 01 threaded for fvg_dist_atr/fvg_size_atr/
fvg_open_count. Also pins that fvg_midpoint (the Plan 04 zones dependency) never leaks
onto FeatureVector as a persisted field.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest

from src.intelligence.feature_cache import FeatureCache
from src.intelligence.feature_factory import FeatureFactory, FeatureFactoryConfig

_FVG_FIELDS = ("fvg_dist_atr", "fvg_size_atr", "fvg_open_count")


def _make_cfg(**overrides: object) -> FeatureFactoryConfig:
    """Small windows so all features warm up well within these fixtures' bar counts.

    smc_fvg_lookback left at its dataclass default (100) -- same convention as
    Phase 164 Plan 02's own tests (leave the feature-under-test's own config at
    its APR-seeded default).
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


def _warmup_bars(n: int, base_price: float) -> list[dict]:
    """n bars of tiny alternating-direction consolidation (no imbalance forms).

    Magnitude (+0.05/-0.04 per bar, wick 0.05) never opens a 3-candle gap on
    its own -- exists purely to give ATR (adx_period=7) enough history.
    """
    price = base_price
    bars = [
        {
            "open": base_price,
            "high": base_price + 0.05,
            "low": base_price - 0.05,
            "close": base_price,
            "volume": 1e5,
            "ts": _BASE_TS,
        }
    ]
    for i in range(n - 1):
        delta = 0.05 if i % 2 == 0 else -0.04
        open_ = price
        close = price + delta
        high, low = max(open_, close) + 0.05, min(open_, close) - 0.05
        _extend(bars, open_, high, low, close)
        price = close
    return bars


def _fvg_base_bars() -> tuple[list[dict], float, float]:
    """Warmup -> bearish bar1 -> bullish impulse bar2 -> bar3 opening a clean
    bullish FVG. Returns (bars, gap_bottom, gap_top) so callers can extend
    with either a "hold above" (unfilled) or "decline through" (filled) tail.
    """
    bars = _warmup_bars(30, base_price=100.0)
    last_close = bars[-1]["close"]

    _extend(bars, last_close, last_close + 0.5, last_close - 0.5, last_close + 0.1)
    bar1_high = bars[-1]["high"]  # last_close + 0.5

    price = bars[-1]["close"]
    _extend(bars, price, price + 3.0, price - 0.1, price + 2.8)
    price = bars[-1]["close"]

    gap_bottom = bar1_high
    gap_top = gap_bottom + 2.0
    _extend(bars, price, gap_top + 0.5, gap_top, gap_top + 0.3)

    return bars, gap_bottom, gap_top


def _fvg_unfilled_bars() -> list[dict]:
    """Forms one clean bullish FVG, then holds well above it (never filled)."""
    bars, _gap_bottom, _gap_top = _fvg_base_bars()
    price = bars[-1]["close"]
    for _ in range(5):
        open_ = price
        close = price + 0.1
        high, low = max(open_, close) + 0.1, min(open_, close) - 0.05
        _extend(bars, open_, high, low, close)
        price = close
    return bars


def _fvg_filled_bars() -> list[dict]:
    """Forms the same bullish FVG, then a single deep-wick bar trades through
    gap_bottom (filling it) before closing back up -- avoids forming a new
    3-candle imbalance of its own, followed by small consolidation bars.
    """
    bars, gap_bottom, gap_top = _fvg_base_bars()
    price = bars[-1]["close"]

    _extend(bars, price, gap_top + 0.4, gap_bottom - 0.5, gap_top + 0.2)
    price = bars[-1]["close"]

    for i in range(3):
        delta = 0.05 if i % 2 == 0 else -0.04
        open_ = price
        close = price + delta
        high, low = max(open_, close) + 0.1, min(open_, close) - 0.1
        _extend(bars, open_, high, low, close)
        price = close

    return bars


def _finite(values: list[float | None]) -> list[float]:
    return [v for v in values if v is not None and math.isfinite(v)]


# ---------------------------------------------------------------------------
# (a) FVG fires -- non-constant, ATR-normalized, real values
# ---------------------------------------------------------------------------


def test_fvg_size_and_dist_atr_finite_nonzero(cfg):
    bars = _fvg_unfilled_bars()
    cache = FeatureCache()
    fv = FeatureFactory.compute(bars, "SPY", "5m", cache, cfg)

    assert fv.fvg_size_atr is not None
    assert math.isfinite(fv.fvg_size_atr)
    assert fv.fvg_size_atr != 0.0, "fvg_size_atr frozen at 0.0 -- no FVG detected"

    assert fv.fvg_dist_atr is not None
    assert math.isfinite(fv.fvg_dist_atr)

    assert fv.fvg_open_count is not None
    assert fv.fvg_open_count >= 1.0


# ---------------------------------------------------------------------------
# (b) fvg_open_count decrements once the gap is filled
# ---------------------------------------------------------------------------


def test_fvg_open_count_decrements_when_filled(cfg):
    fv_unfilled = FeatureFactory.compute(_fvg_unfilled_bars(), "SPY", "5m", FeatureCache(), cfg)
    fv_filled = FeatureFactory.compute(_fvg_filled_bars(), "SPY", "5m", FeatureCache(), cfg)

    assert fv_unfilled.fvg_open_count is not None and fv_unfilled.fvg_open_count >= 1.0
    assert fv_filled.fvg_open_count is not None
    assert fv_filled.fvg_open_count < fv_unfilled.fvg_open_count, (
        f"fvg_open_count did not decrement: unfilled={fv_unfilled.fvg_open_count} "
        f"filled={fv_filled.fvg_open_count}"
    )


# ---------------------------------------------------------------------------
# (c) Raw-price fields must never exist on FeatureVector (T-164-02)
# ---------------------------------------------------------------------------


def test_fvg_no_raw_price_fields_on_feature_vector(cfg):
    cache = FeatureCache()
    fv = FeatureFactory.compute(_fvg_unfilled_bars(), "SPY", "5m", cache, cfg)

    for raw_field in ("fvg_top", "fvg_bottom", "fvg_midpoint"):
        assert not hasattr(fv, raw_field), f"raw-price field {raw_field} leaked onto FeatureVector"


# ---------------------------------------------------------------------------
# (d) Determinism -- pure-function contract (T-164-04)
# ---------------------------------------------------------------------------


def test_fvg_determinism_identical_inputs_identical_outputs(cfg):
    bars = _fvg_unfilled_bars()

    fv1 = FeatureFactory.compute(bars, "SPY", "5m", FeatureCache(), cfg)
    fv2 = FeatureFactory.compute(bars, "SPY", "5m", FeatureCache(), cfg)

    for field in _FVG_FIELDS:
        v1 = getattr(fv1, field)
        v2 = getattr(fv2, field)
        assert v1 == v2, f"{field}: non-deterministic ({v1} != {v2})"


# ---------------------------------------------------------------------------
# (e) compute_batch() produces non-constant FVG fields
# ---------------------------------------------------------------------------


def test_compute_batch_produces_non_constant_fvg_fields(cfg):
    bars = _fvg_filled_bars()
    cache = FeatureCache()
    results = FeatureFactory.compute_batch(bars, "SPY", "5m", cache, cfg)
    assert len(results) == len(bars) - 1

    for field in ("fvg_size_atr", "fvg_open_count"):
        vals = _finite([getattr(fv, field) for _, fv in results])
        assert len(vals) > 1
        assert len({round(v, 8) for v in vals}) > 1, f"{field} is constant across compute_batch()"


def test_fvg_compute_live_batch_parity(cfg):
    """Live (compute() over the full growing history) must match batch to 1e-6."""
    bars = _fvg_filled_bars()
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
    for field in _FVG_FIELDS:
        b = getattr(fv_batch_last, field)
        s = getattr(fv_live_last, field)
        if b is None or s is None:
            assert b == s, f"{field}: batch={b} live={s} (None mismatch)"
        else:
            assert abs(b - s) < 1e-6, f"{field}: batch={b:.10f} live={s:.10f}"
