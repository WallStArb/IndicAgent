"""Regression: SMC Break of Structure / Change of Character (Phase 164 Plan 04).

Wires FeatureFactory._compute_bos_choch() (stateless, ported from
archive/smc_context/bos_choch.py) into FeatureFactory.compute()/compute_batch(),
replacing 6 of the final 18 None placeholders Plan 01 threaded for bos_strength/
choch_strength/bos_direction/choch_direction/smc_trend_direction/bars_since_last_shift.
bos_level and bos_confidence (byte-identical to bos_strength in the archived source) are
dropped per the field-by-field raw-price/redundancy audit.
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
    _compute_bos_choch,
)

_BOS_FIELDS = (
    "bos_strength",
    "choch_strength",
    "bos_direction",
    "choch_direction",
    "smc_trend_direction",
    "bars_since_last_shift",
)


def _make_cfg(**overrides: object) -> FeatureFactoryConfig:
    """Small windows so all features warm up well within these fixtures' bar counts.

    smc_bos_choch_lookback left at its dataclass default (120);
    smc_bos_choch_swing_neighbor overridden small (2) so the hand-built
    zigzag fixtures below (short legs) produce clean, unambiguous swing
    points -- same convention as Phase 164 Plans 02/03's own tests.
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
        smc_bos_choch_swing_neighbor=2,
    )
    defaults.update(overrides)
    return FeatureFactoryConfig(**defaults)


@pytest.fixture(scope="module")
def cfg() -> FeatureFactoryConfig:
    return _make_cfg()


# ---------------------------------------------------------------------------
# Fixture builders — a zigzag path of "closes" run through consecutive
# monotonic ramps. Each ramp's turning point is a clean local extremum for
# find_peaks/find_troughs (n=2): strictly increasing on one side, strictly
# decreasing on the other, no held-flat ties to create ambiguity.
# ---------------------------------------------------------------------------

_BASE_TS = datetime(2023, 1, 3, 14, 0, tzinfo=UTC)


def _ramp(start: float, end: float, n: int) -> list[float]:
    """n points strictly between start (exclusive) and end (inclusive)."""
    return list(np.linspace(start, end, n + 1))[1:]


def _bars_from_path(closes_path: list[float], wick: float = 0.05) -> list[dict]:
    """high/low are pinned to close +- wick (NOT max/min(open, close)) so a
    strictly-monotonic closes_path produces a strictly-monotonic highs/lows
    path too -- using max(open, close) instead would tie the turning bar's
    high with its immediate down-ramp neighbor (both bars share the turning
    bar's price as either close or the next bar's open), producing a
    2-wide "double top" that find_peaks reports as two swing highs instead
    of one, corrupting the last-2-swing trend comparison this fixture
    exists to control precisely.
    """
    bars: list[dict] = []
    ts = _BASE_TS
    prior_close = closes_path[0]
    bars.append(
        {
            "open": prior_close,
            "high": prior_close + wick,
            "low": prior_close - wick,
            "close": prior_close,
            "volume": 1e5,
            "ts": ts,
        }
    )
    for close in closes_path[1:]:
        ts = ts + timedelta(minutes=1)
        open_ = prior_close
        high = close + wick
        low = close - wick
        bars.append(
            {"open": open_, "high": high, "low": low, "close": close, "volume": 1e5, "ts": ts}
        )
        prior_close = close
    return bars


def _uptrend_bos_path() -> list[float]:
    """Ascending swing highs (110 -> 125) and swing lows (102 -> 108), then a
    breakout leg closing above the last swing high (125) -- BOS in the SAME
    direction as the prevailing uptrend, so CHoCH must NOT fire.
    """
    path = [100.0]
    path += _ramp(100.0, 110.0, 6)  # H1 = 110
    path += _ramp(110.0, 102.0, 6)  # L1 = 102
    path += _ramp(102.0, 125.0, 6)  # H2 = 125 (> H1 -- ascending)
    path += _ramp(125.0, 108.0, 6)  # L2 = 108 (> L1 -- ascending)
    path += _ramp(108.0, 132.0, 6)  # breakout above H2
    path += _ramp(132.0, 133.0, 3)  # a few bars of hold, for bars_since_last_shift > 0
    return path


def _downtrend_choch_path() -> list[float]:
    """Descending swing highs (125 -> 110) and swing lows (108 -> 95), then a
    breakout leg closing ABOVE the last swing high -- BOS opposite the
    prevailing downtrend, so CHoCH must fire.
    """
    path = [100.0]
    path += _ramp(100.0, 125.0, 6)  # H1 = 125
    path += _ramp(125.0, 108.0, 6)  # L1 = 108
    path += _ramp(108.0, 110.0, 6)  # H2 = 110 (< H1 -- descending)
    path += _ramp(110.0, 95.0, 6)  # L2 = 95 (< L1 -- descending)
    path += _ramp(95.0, 130.0, 6)  # breakout ABOVE H2 -- opposite of downtrend
    path += _ramp(130.0, 131.0, 3)
    return path


def _finite(values: list[float | None]) -> list[float]:
    return [v for v in values if v is not None and math.isfinite(v)]


# ---------------------------------------------------------------------------
# (a) Higher-high BOS fires, in-trend -- no CHoCH
# ---------------------------------------------------------------------------


def test_bos_bullish_no_choch(cfg):
    bars = _bars_from_path(_uptrend_bos_path())
    cache = FeatureCache()
    fv = FeatureFactory.compute(bars, "SPY", "5m", cache, cfg)

    assert fv.bos_direction == 1.0
    assert fv.bos_strength is not None
    assert math.isfinite(fv.bos_strength)
    assert fv.bos_strength > 0.0

    assert fv.smc_trend_direction == 1.0
    assert fv.choch_direction == 0.0, "CHoCH must not fire when BOS agrees with the trend"

    assert fv.bars_since_last_shift is not None
    assert fv.bars_since_last_shift >= 0.0
    assert fv.bars_since_last_shift == float(int(fv.bars_since_last_shift))


# ---------------------------------------------------------------------------
# (b) Change-of-character fires (BOS opposes prevailing trend)
# ---------------------------------------------------------------------------


def test_choch_fires_against_downtrend(cfg):
    bars = _bars_from_path(_downtrend_choch_path())
    cache = FeatureCache()
    fv = FeatureFactory.compute(bars, "SPY", "5m", cache, cfg)

    assert fv.smc_trend_direction == -1.0
    assert fv.bos_direction == 1.0, "BOS must break bullish (opposite the downtrend) here"
    assert fv.choch_direction == 1.0
    assert fv.choch_strength is not None
    assert math.isfinite(fv.choch_strength)
    assert fv.choch_strength > 0.0
    assert fv.choch_strength == fv.bos_strength, "choch_strength must equal the break magnitude"


# ---------------------------------------------------------------------------
# (c) Raw-price / redundant fields must never exist on FeatureVector
# ---------------------------------------------------------------------------


def test_no_raw_or_redundant_fields_on_feature_vector(cfg):
    cache = FeatureCache()
    fv = FeatureFactory.compute(_bars_from_path(_uptrend_bos_path()), "SPY", "5m", cache, cfg)

    for raw_field in ("bos_level", "bos_confidence", "bos_detected", "choch_detected"):
        assert not hasattr(fv, raw_field), f"field {raw_field} leaked onto FeatureVector"


# ---------------------------------------------------------------------------
# (d) Fallback contract -- never raises on atr<=0 or too-few swing points (T-164-05)
# ---------------------------------------------------------------------------


def test_bos_choch_fallback_on_invalid_atr(cfg):
    highs = np.array([100.0, 101.0, 100.5, 101.5, 100.0])
    lows = np.array([99.0, 99.5, 99.0, 100.0, 99.5])
    closes = np.array([99.5, 100.5, 99.5, 100.5, 99.8])

    result = _compute_bos_choch(highs, lows, closes, 99.8, 0.0, cfg)
    assert result["bos_direction"] == 0.0
    assert result["smc_trend_direction"] == 0.0
    for v in result.values():
        assert math.isfinite(v)


def test_bos_choch_fallback_on_too_few_swings(cfg):
    highs = np.array([100.0, 100.1, 100.05, 100.15, 100.0, 100.2])
    lows = np.array([99.5, 99.6, 99.55, 99.65, 99.5, 99.7])
    closes = np.array([99.8, 99.9, 99.85, 99.95, 99.8, 100.0])

    result = _compute_bos_choch(highs, lows, closes, 100.0, 1.0, cfg)
    assert result["bos_direction"] == 0.0
    assert result["bars_since_last_shift"] == 0.0
    for v in result.values():
        assert math.isfinite(v)


# ---------------------------------------------------------------------------
# (e) Determinism -- pure-function contract (T-164-04)
# ---------------------------------------------------------------------------


def test_structure_determinism_identical_inputs_identical_outputs(cfg):
    bars = _bars_from_path(_downtrend_choch_path())

    fv1 = FeatureFactory.compute(bars, "SPY", "5m", FeatureCache(), cfg)
    fv2 = FeatureFactory.compute(bars, "SPY", "5m", FeatureCache(), cfg)

    for field in _BOS_FIELDS:
        v1 = getattr(fv1, field)
        v2 = getattr(fv2, field)
        assert v1 == v2, f"{field}: non-deterministic ({v1} != {v2})"


# ---------------------------------------------------------------------------
# (f) compute_batch() produces non-constant structure fields
# ---------------------------------------------------------------------------


def test_compute_batch_produces_non_constant_structure_fields(cfg):
    bars = _bars_from_path(_downtrend_choch_path())
    cache = FeatureCache()
    results = FeatureFactory.compute_batch(bars, "SPY", "5m", cache, cfg)
    assert len(results) == len(bars) - 1

    for field in ("bos_strength", "smc_trend_direction"):
        vals = _finite([getattr(fv, field) for _, fv in results])
        assert len(vals) > 1
        assert len({round(v, 8) for v in vals}) > 1, f"{field} is constant across compute_batch()"


def test_structure_compute_live_batch_parity(cfg):
    """Live (compute() over the full growing history) must match batch to 1e-6."""
    bars = _bars_from_path(_downtrend_choch_path())
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
        cache_live.update_overnight_range(bar["ts"], bar["high"], bar["low"], cfg)
        fv_live_last = FeatureFactory.compute(bars[: i + 1], "SPY", "5m", cache_live, cfg)

    assert fv_live_last is not None
    for field in _BOS_FIELDS:
        b = getattr(fv_batch_last, field)
        s = getattr(fv_live_last, field)
        if b is None or s is None:
            assert b == s, f"{field}: batch={b} live={s} (None mismatch)"
        else:
            assert abs(b - s) < 1e-6, f"{field}: batch={b:.10f} live={s:.10f}"
