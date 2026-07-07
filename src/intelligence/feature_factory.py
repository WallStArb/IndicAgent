"""FeatureFactory — pure-function library for computing all 54 FeatureVector primitives.

STATELESS CONTRACT (D-08): FeatureFactory has no __init__ and stores no config.
The FeatureFactoryConfig frozen dataclass is built ONCE by the caller
(IntelligencePipeline._prewarm_threshold_config in P6, or the backfill init in P5)
and passed as an explicit argument on EVERY compute() call. The signature is:

    FeatureFactory.compute(bars, symbol, tf, cache: FeatureCache, config: FeatureFactoryConfig) -> FeatureVector

Config is never stored on the class — always passed as a compute() argument.

PURITY CONTRACT: compute() performs zero IO. No ConfigService.get(), no DB reads,
no Kafka. No async def or await. Deterministic: same inputs -> identical output.

CAUSAL PURITY:
- HMM: forward Viterbi only (D-07). No lookahead via reverse pass. Regime values
  served from FeatureCache (refreshed every regime_cache_refresh_bars by caller).
- OFI/CVD: OHLCV bar proxy path only. No live tick data path.
- Cross-asset (vix_z/flight_quality/yield_slope_z): read from FeatureCache populated
  by update_cross_asset(). Not computed inside compute().
- hmm_duration / above_wk_vwap: state tracked in FeatureCache; incremented/reset by caller.

APR CONTRACT (SC-9): All tunable numeric values come from the FeatureFactoryConfig
argument. Zero inline magic numbers in primitive bodies.
"""

from __future__ import annotations

import bisect
import calendar
import dataclasses
import math
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np

from src.intelligence.feature_cache import (
    FeatureCache,
)
from src.intelligence.schemas import FeatureVector

# ---------------------------------------------------------------------------
# Algorithm version tracking
# ---------------------------------------------------------------------------

# Bump on any algorithm change; IC engine filters by version to avoid mixing IC estimates.
FEATURE_FACTORY_VERSION: str = "1.0.0"

# Calendar constant: average days per quarter (365.25 / 4). Not a tunable — fixed by definition.
_QUARTER_LENGTH_DAYS: float = 91.25

# ---------------------------------------------------------------------------
# Feature-to-vector domain registry (IC Engine reads this at startup)
# ---------------------------------------------------------------------------

FEATURE_VECTOR_DOMAIN: dict[str, str] = {
    # Momentum
    "momentum_z_fast": "quant",
    "momentum_z_mid": "quant",
    "range_position": "quant",
    "bar_close_pos": "quant",
    "gap_z": "quant",
    "momentum_z_slow": "quant",
    "momentum_reversal_z": "quant",
    # Volume and order flow
    "informed_flow": "quant",
    "volume_z": "quant",
    "ofi_z": "quant",
    "ofi_div": "quant",
    "cvd_slope_z": "quant",
    "cmf": "quant",
    "rel_volume": "quant",
    "vwap_dev_sigma": "quant",
    # Volatility
    "atr_z": "quant",
    "vol_ratio": "quant",
    # Session-level / market structure
    "poc_dist_atr": "structural",
    "va_position": "structural",
    "sr_support_dist": "structural",
    "sr_resist_dist": "structural",
    # Regime-level
    "hmm_regime_prob": "regime",
    "hmm_entropy": "regime",
    "hmm_duration": "regime",
    "hurst": "quant",
    "shannon": "quant",
    "garch_ratio": "regime",
    "hma_slope_z": "quant",
    "adx": "quant",
    "aroon_fast": "quant",
    "aroon_slow": "quant",
    # Oscillators
    "rsi_fast": "quant",
    "rsi_mid": "quant",
    "rsi_slow": "quant",
    "cci_fast": "quant",
    "cci_mid": "quant",
    "cci_slow": "quant",
    # Cross-asset / macro
    "vix_z": "macro",
    "flight_quality": "macro",
    "yield_slope_z": "macro",
    # Calendar / session
    "in_ny_session": "calendar",
    "in_london_kz": "calendar",
    "in_overlap": "calendar",
    "power_hour": "calendar",
    "opening_range": "calendar",
    "above_wk_vwap": "calendar",
    "dow_sin": "calendar",
    "dow_cos": "calendar",
    "month_position": "calendar",
    "quarter_position": "calendar",
    "days_to_month_end": "calendar",
    # Cross-timeframe
    "ctf_momentum": "quant",
    "ctf_vwap_align": "quant",
    "ctf_regime_align": "regime",
    # Statistical / liquidity
    "amihud_illiq_z": "quant",
    "high_52w_dist": "quant",
    "ret_skew_z": "quant",
    "ret_acf1_z": "quant",
    # Renaissance Primitives — Bar Anatomy Ratios (Phase 142.5 Plan 01)
    "body_ratio": "quant",
    "upper_wick_ratio": "quant",
    "lower_wick_ratio": "quant",
    "range_vs_atr": "quant",
    "close_vs_open_direction": "quant",
    "overnight_gap": "quant",
    "overnight_gap_z": "quant",
    "range_efficiency": "quant",
    # Renaissance Primitives — Lagged Return Series (Phase 142.5 Plan 01)
    "ret_lag_1": "quant",
    "ret_lag_2": "quant",
    "ret_lag_3": "quant",
    "ret_lag_fast": "quant",
    "ret_lag_mid": "quant",
    "ret_lag_slow": "quant",
    # Renaissance Primitives — Open-to-Close Split (Phase 142.5 Plan 01)
    "open_ret": "quant",
    "intraday_ret": "quant",
    "open_vs_intraday": "quant",
    "session_time_pos": "calendar",
    # Renaissance Primitives — Temporal Coordinates (Phase 142.5 Plan 02)
    "hour_of_day_sin": "calendar",
    "hour_of_day_cos": "calendar",
    "week_of_month_sin": "calendar",
    "week_of_month_cos": "calendar",
    "day_of_month_sin": "calendar",
    "day_of_month_cos": "calendar",
    "week_of_year_sin": "calendar",
    "week_of_year_cos": "calendar",
    "month_sin": "calendar",
    "month_cos": "calendar",
    # Renaissance Primitives — Volume Structure (Phase 142.5 Plan 02)
    "vol_acceleration": "quant",
    "dollar_vol_z": "quant",
    "vol_range_ratio": "quant",
    "vol_trend_ratio": "quant",
    "up_vol_ratio_fast": "quant",
    "up_vol_ratio_slow": "quant",
    "vol_percentile": "quant",
    "vol_persistence": "quant",
    "vol_std_z": "quant",
    "mfi_fast": "quant",
    "mfi_slow": "quant",
    "obv_z": "quant",
    # Renaissance Primitives — Breakout Distance (Phase 142.5 Plan 05)
    "dist_from_high_fast": "quant",
    "dist_from_high_slow": "quant",
    "dist_from_low_fast": "quant",
    "dist_from_low_slow": "quant",
    "range_pct_fast": "quant",
    "range_pct_slow": "quant",
    "new_high_flag": "quant",
    "new_low_flag": "quant",
    "stoch_k_fast": "quant",
    "stoch_k_slow": "quant",
    "price_percentile_fast": "quant",
    "price_percentile_slow": "quant",
    "efficiency_ratio_fast": "quant",
    "efficiency_ratio_slow": "quant",
    # Renaissance Primitives — Return Distribution (Phase 142.5 Plan 03)
    "ret_kurtosis_z_fast": "quant",
    "ret_kurtosis_z_slow": "quant",
    "ret_autocorr_1": "quant",
    "ret_autocorr_5": "quant",
    "updown_ratio_fast": "quant",
    "updown_ratio_slow": "quant",
    "streak_z": "quant",
    # Renaissance Primitives — Realized Variance / Volatility (Phase 142.5 Plan 03)
    "realized_var_ratio_fast": "quant",
    "realized_var_ratio_slow": "quant",
    "range_to_close": "quant",
    "true_range_pct": "quant",
    "vol_of_vol": "quant",
    "high_low_corr": "quant",
    "variance_ratio_fast": "quant",
    "variance_ratio_slow": "quant",
    "vol_asymmetry_z": "quant",
    "bb_pct_b_fast": "quant",
    "bb_pct_b_slow": "quant",
    "hv_z_fast": "quant",
    "hv_z_slow": "quant",
    "hv_ratio": "quant",
    # Renaissance Primitives — Alternative Volatility Estimators (Phase 142.5 Plan 04)
    "parkinson_vol_z": "quant",
    "garman_klass_vol_z": "quant",
    "yang_zhang_vol_z": "quant",
    # Renaissance Primitives — Volatility Dynamics (Phase 142.5 Plan 04)
    "parkinson_vol_velocity": "quant",
    "garman_klass_vol_velocity": "quant",
    "yang_zhang_vol_velocity": "quant",
    "vol_velocity_z": "quant",
    "intraday_noise_ratio": "quant",
    # Cross-sectional (nullable — populated by Phase 139)
    "momentum_rank_z": "quant",
    "volume_rank_z": "quant",
    "volatility_rank_z": "quant",
}

# ---------------------------------------------------------------------------
# APR-backed configuration (frozen, built once by caller)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FeatureFactoryConfig:
    """Frozen APR-backed parameter container for FeatureFactory.compute().

    Built ONCE by IntelligencePipeline._prewarm_threshold_config() or the
    backfill init. Passed as an explicit argument to compute() on every bar.
    APR keys (feature.* namespace) map directly to these fields.

    Fields:
        momentum_window_fast: APR feature.momentum.window_fast
        momentum_window_mid: APR feature.momentum.window_mid
        momentum_window_slow: APR feature.momentum.window_slow
        momentum_zscore_window: APR feature.momentum.zscore_window
        volume_zscore_window: APR feature.volume.zscore_window
        ofi_zscore_window: APR feature.ofi.zscore_window
        cvd_slope_bars: APR feature.cvd.slope_bars
        cmf_period: APR feature.cmf.period
        vol_short_bars: APR feature.vol.short_bars
        vol_long_bars: APR feature.vol.long_bars
        hma_period: APR feature.hma.period
        adx_period: APR feature.adx.period
        hurst_window: APR feature.hurst.window
        garch_window: APR feature.garch.window
        vix_zscore_window: APR feature.vix.zscore_window
        yield_curve_zscore_window: APR feature.yield_curve.zscore_window
        regime_cache_refresh_bars: APR feature.regime.cache_refresh_bars
        min_bars_warmup: APR feature.cache.min_bars_warmup
        cross_asset_rv_window: APR feature.cross_asset.rv_window
        ny_session_start_utc_hour: APR feature.session.ny_start_utc_hour
        ny_session_start_utc_minute: APR feature.session.ny_start_utc_minute
        ny_session_end_utc_hour: APR feature.session.ny_end_utc_hour
        overlap_start_utc_hour: APR feature.session.overlap_start_utc_hour
        overlap_end_utc_hour: APR feature.session.overlap_end_utc_hour
        london_kz_start_utc_hour: APR feature.session.london_kz_start_utc_hour
        london_kz_end_utc_hour: APR feature.session.london_kz_end_utc_hour
        power_hour_start_utc_hour: APR feature.session.power_hour_start_utc_hour
        power_hour_end_utc_hour: APR feature.session.power_hour_end_utc_hour
        opening_range_start_minute: APR feature.session.opening_range_start_minute
        opening_range_end_minute: APR feature.session.opening_range_end_minute
        ret_lag_fast: APR feature.ret_lag.fast
        ret_lag_mid: APR feature.ret_lag.mid
        ret_lag_slow: APR feature.ret_lag.slow
        overnight_gap_window: APR feature.overnight_gap.window
        dollar_vol_window: APR feature.dollar_vol.window
        vol_range_ratio_window: APR feature.vol_range_ratio.window
        vol_trend_fast: APR feature.vol_trend.fast
        vol_trend_slow: APR feature.vol_trend.slow
        up_vol_ratio_fast: APR feature.up_vol_ratio.fast
        up_vol_ratio_slow: APR feature.up_vol_ratio.slow
        vol_percentile_window: APR feature.vol_percentile.window
        vol_persistence_window: APR feature.vol_persistence.window
        vol_std_window: APR feature.vol_std.window
        mfi_fast: APR feature.mfi.fast
        mfi_slow: APR feature.mfi.slow
        obv_window: APR feature.obv.window
        dist_window_fast: APR feature.breakout.dist_window_fast
        dist_window_slow: APR feature.breakout.dist_window_slow
        range_window_fast: APR feature.breakout.range_window_fast
        range_window_slow: APR feature.breakout.range_window_slow
        stoch_window_fast: APR feature.breakout.stoch_window_fast
        stoch_window_slow: APR feature.breakout.stoch_window_slow
        percentile_window_fast: APR feature.breakout.percentile_window_fast
        percentile_window_slow: APR feature.breakout.percentile_window_slow
        efficiency_window_fast: APR feature.breakout.efficiency_window_fast
        efficiency_window_slow: APR feature.breakout.efficiency_window_slow
        ret_kurtosis_fast: APR feature.ret_kurtosis.fast
        ret_kurtosis_slow: APR feature.ret_kurtosis.slow
        ret_kurtosis_zscore_window: APR feature.ret_kurtosis.zscore_window
        updown_ratio_fast: APR feature.updown_ratio.fast
        updown_ratio_slow: APR feature.updown_ratio.slow
        streak_window: APR feature.streak.window
        realized_var_fast: APR feature.realized_var.fast
        realized_var_slow: APR feature.realized_var.slow
        vol_of_vol_window: APR feature.vol_of_vol.window
        high_low_corr_window: APR feature.high_low_corr.window
        variance_ratio_fast: APR feature.variance_ratio.fast
        variance_ratio_slow: APR feature.variance_ratio.slow
        vol_asymmetry_window: APR feature.vol_asymmetry.window
        bb_pct_b_fast: APR feature.bb_pct_b.fast
        bb_pct_b_slow: APR feature.bb_pct_b.slow
        hv_fast: APR feature.hv.fast
        hv_slow: APR feature.hv.slow
        hv_ratio_window: APR feature.hv.ratio_window
        parkinson_vol_window: APR feature.parkinson_vol.window
        parkinson_vol_zscore_window: APR feature.parkinson_vol.zscore_window
        garman_klass_vol_window: APR feature.garman_klass_vol.window
        garman_klass_vol_zscore_window: APR feature.garman_klass_vol.zscore_window
        yang_zhang_vol_window: APR feature.yang_zhang_vol.window
        yang_zhang_vol_zscore_window: APR feature.yang_zhang_vol.zscore_window
        vol_velocity_window: APR feature.vol_velocity.window
        intraday_noise_window: APR feature.intraday_noise.window
    """

    momentum_window_fast: int  # feature.momentum.window_fast
    momentum_window_mid: int  # feature.momentum.window_mid
    momentum_window_slow: int  # feature.momentum.window_slow
    momentum_zscore_window: int  # feature.momentum.zscore_window
    volume_zscore_window: int  # feature.volume.zscore_window
    ofi_zscore_window: int  # feature.ofi.zscore_window
    cvd_slope_bars: int  # feature.cvd.slope_bars
    cmf_period: int  # feature.cmf.period
    vol_short_bars: int  # feature.vol.short_bars
    vol_long_bars: int  # feature.vol.long_bars
    hma_period: int  # feature.hma.period
    adx_period: int  # feature.adx.period
    hurst_window: int  # feature.hurst.window
    garch_window: int  # feature.garch.window
    vix_zscore_window: int  # feature.vix.zscore_window
    yield_curve_zscore_window: int  # feature.yield_curve.zscore_window
    regime_cache_refresh_bars: int  # feature.regime.cache_refresh_bars
    # Cache warmup / cross-asset
    min_bars_warmup: int  # feature.cache.min_bars_warmup
    cross_asset_rv_window: int  # feature.cross_asset.rv_window
    # Session / calendar (APR-backed so DST/market-hour adjustments are operationally safe)
    ny_session_start_utc_hour: int  # feature.session.ny_start_utc_hour
    ny_session_start_utc_minute: int  # feature.session.ny_start_utc_minute
    ny_session_end_utc_hour: int  # feature.session.ny_end_utc_hour
    overlap_start_utc_hour: int  # feature.session.overlap_start_utc_hour
    overlap_end_utc_hour: int  # feature.session.overlap_end_utc_hour
    london_kz_start_utc_hour: int  # feature.session.london_kz_start_utc_hour
    london_kz_end_utc_hour: int  # feature.session.london_kz_end_utc_hour
    power_hour_start_utc_hour: int  # feature.session.power_hour_start_utc_hour
    power_hour_end_utc_hour: int  # feature.session.power_hour_end_utc_hour
    opening_range_start_minute: int  # feature.session.opening_range_start_minute
    opening_range_end_minute: int  # feature.session.opening_range_end_minute
    # Oscillators (added in P7)
    rsi_fast_period: int  # feature.period.rsi.fast
    rsi_mid_period: int  # feature.period.rsi.mid
    rsi_slow_period: int  # feature.period.rsi.slow
    cci_fast_period: int  # feature.period.cci.fast
    cci_mid_period: int  # feature.period.cci.mid
    cci_slow_period: int  # feature.period.cci.slow
    # Trend freshness
    aroon_fast_period: int  # feature.period.aroon.fast
    aroon_slow_period: int  # feature.period.aroon.slow
    # Statistical / liquidity
    amihud_zscore_window: int  # feature.amihud.zscore_window
    ret_skew_window: int  # feature.ret_skew.window
    ret_skew_zscore_window: int  # feature.ret_skew.zscore_window
    ret_acf_window: int  # feature.ret_acf.window
    ret_acf_zscore_window: int  # feature.ret_acf.zscore_window
    high_52w_window: int  # feature.high_52w.window
    # Renaissance Primitives — lagged returns + overnight gap z-score (Phase 142.5 Plan 01)
    ret_lag_fast: int  # feature.ret_lag.fast
    ret_lag_mid: int  # feature.ret_lag.mid
    ret_lag_slow: int  # feature.ret_lag.slow
    overnight_gap_window: int  # feature.overnight_gap.window
    # Renaissance Primitives — volume structure (Phase 142.5 Plan 02)
    dollar_vol_window: int  # feature.dollar_vol.window
    vol_range_ratio_window: int  # feature.vol_range_ratio.window
    vol_trend_fast: int  # feature.vol_trend.fast
    vol_trend_slow: int  # feature.vol_trend.slow
    up_vol_ratio_fast: int  # feature.up_vol_ratio.fast
    up_vol_ratio_slow: int  # feature.up_vol_ratio.slow
    vol_percentile_window: int  # feature.vol_percentile.window
    vol_persistence_window: int  # feature.vol_persistence.window
    vol_std_window: int  # feature.vol_std.window
    mfi_fast: int  # feature.mfi.fast
    mfi_slow: int  # feature.mfi.slow
    obv_window: int  # feature.obv.window
    # Renaissance Primitives — breakout distance (Phase 142.5 Plan 05)
    dist_window_fast: int  # feature.breakout.dist_window_fast
    dist_window_slow: int  # feature.breakout.dist_window_slow
    range_window_fast: int  # feature.breakout.range_window_fast
    range_window_slow: int  # feature.breakout.range_window_slow
    stoch_window_fast: int  # feature.breakout.stoch_window_fast
    stoch_window_slow: int  # feature.breakout.stoch_window_slow
    percentile_window_fast: int  # feature.breakout.percentile_window_fast
    percentile_window_slow: int  # feature.breakout.percentile_window_slow
    efficiency_window_fast: int  # feature.breakout.efficiency_window_fast
    efficiency_window_slow: int  # feature.breakout.efficiency_window_slow
    # Renaissance Primitives — return distribution + realized variance (Phase 142.5 Plan 03)
    ret_kurtosis_fast: int  # feature.ret_kurtosis.fast
    ret_kurtosis_slow: int  # feature.ret_kurtosis.slow
    ret_kurtosis_zscore_window: int  # feature.ret_kurtosis.zscore_window
    updown_ratio_fast: int  # feature.updown_ratio.fast
    updown_ratio_slow: int  # feature.updown_ratio.slow
    streak_window: int  # feature.streak.window
    realized_var_fast: int  # feature.realized_var.fast
    realized_var_slow: int  # feature.realized_var.slow
    vol_of_vol_window: int  # feature.vol_of_vol.window
    high_low_corr_window: int  # feature.high_low_corr.window
    variance_ratio_fast: int  # feature.variance_ratio.fast
    variance_ratio_slow: int  # feature.variance_ratio.slow
    vol_asymmetry_window: int  # feature.vol_asymmetry.window
    bb_pct_b_fast: int  # feature.bb_pct_b.fast
    bb_pct_b_slow: int  # feature.bb_pct_b.slow
    hv_fast: int  # feature.hv.fast
    hv_slow: int  # feature.hv.slow
    hv_ratio_window: int  # feature.hv.ratio_window
    # Renaissance Primitives — Alternative Volatility + Volatility Dynamics (Phase 142.5 Plan 04)
    parkinson_vol_window: int  # feature.parkinson_vol.window
    parkinson_vol_zscore_window: int  # feature.parkinson_vol.zscore_window
    garman_klass_vol_window: int  # feature.garman_klass_vol.window
    garman_klass_vol_zscore_window: int  # feature.garman_klass_vol.zscore_window
    yang_zhang_vol_window: int  # feature.yang_zhang_vol.window
    yang_zhang_vol_zscore_window: int  # feature.yang_zhang_vol.zscore_window
    vol_velocity_window: int  # feature.vol_velocity.window
    intraday_noise_window: int  # feature.intraday_noise.window


# ---------------------------------------------------------------------------
# Rolling z-score helper (module-level, used across primitives)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Bar-level primitive functions
# ---------------------------------------------------------------------------


def _bar_close_pos(high: float, low: float, close: float, eps: float = 1e-10) -> float:
    """Intra-bar conviction: close position within high-low range.

    Formula: (close - low) / (high - low + eps)
    Returns 0.5 when high == low (epsilon guard; degenerate doji bar).
    """
    hl = high - low
    if hl < eps:
        return 0.5
    return (close - low) / hl


def _range_position(
    close: float,
    highs: np.ndarray,
    lows: np.ndarray,
    eps: float = 1e-10,
) -> float:
    """Close position within N-bar high-low range.

    Formula: (close - min(low_N)) / (max(high_N) - min(low_N))
    Returns 0.5 on degenerate range.
    """
    range_low = float(np.min(lows))
    range_high = float(np.max(highs))
    rng = range_high - range_low
    return (close - range_low) / (rng + eps)


def _rel_volume(volume: float, vol_history: deque, window: int) -> float:
    """Relative volume: volume / mean(volume over window).

    Returns 1.0 on cold start (neutral).
    """
    vol_history.append(volume)
    if len(vol_history) < 2:
        return 1.0
    arr = np.array(list(vol_history)[-window:])
    mean_vol = float(arr.mean())
    return volume / mean_vol if mean_vol > 1e-10 else 1.0


def _informed_flow(open_price: float, close: float, atr: float) -> float:
    """Directional informed flow proxy: (close - open) / ATR.

    Returns 0.0 when ATR is zero.
    """
    return (close - open_price) / atr if atr > 1e-10 else 0.0


def _vol_ratio(closes: np.ndarray, short_bars: int, long_bars: int) -> float:
    """Realized volatility ratio: std(short) / std(long).

    Returns 1.0 on cold start or degenerate std.
    """
    if len(closes) < long_bars + 1:
        return 1.0
    long_returns = np.diff(np.log(np.maximum(closes[-(long_bars + 1) :], 1e-10)))
    short_returns = long_returns[-short_bars:]
    vol_short = float(np.std(short_returns))
    vol_long = float(np.std(long_returns))
    return vol_short / vol_long if vol_long > 1e-10 else 1.0


def _atr_wilder(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int) -> float:
    """ATR using Wilder's EWM smoothing. Returns 0.0 on insufficient data.

    Reference implementation — used in tests only.
    """
    n = len(closes)
    if n < period + 1:
        return 0.0
    high = highs[1:]
    low = lows[1:]
    prev_close = closes[:-1]
    tr = np.maximum(
        high - low,
        np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)),
    )
    # Wilder: alpha = 1/period; use ewm equivalent
    alpha = 1.0 / period
    atr = float(tr[0])
    for val in tr[1:]:
        atr = alpha * float(val) + (1.0 - alpha) * atr
    return atr


def _atr_series_full(
    highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int
) -> np.ndarray:
    """Full Wilder ATR series in O(n). result[j] = ATR after bar index j+1.
    Length = len(closes) - 1. Returns empty array when len(closes) < 2.

    Matches _atr_wilder semantics exactly: result[j] = 0.0 when j+2 < period+1
    (insufficient bars). Non-zero values begin at j = period-1.
    """
    n = len(closes)
    if n < 2:
        return np.zeros(0, dtype=float)
    tr = np.maximum(
        highs[1:] - lows[1:],
        np.maximum(np.abs(highs[1:] - closes[:-1]), np.abs(lows[1:] - closes[:-1])),
    )
    alpha = 1.0 / max(period, 1)
    atr = np.zeros(len(tr), dtype=float)
    # _atr_wilder requires n >= period+1, i.e. len(tr) >= period.
    # The EWM always seeds from tr[0] and accumulates forward. We zero out positions
    # where _atr_wilder would return 0.0 (j < period-1), but carry the EWM state
    # forward so position j = period-1 onward is numerically identical to _atr_wilder.
    if len(tr) < period:
        return atr  # all zeros — no valid position exists
    running = float(tr[0])
    for k in range(1, len(tr)):
        running = alpha * float(tr[k]) + (1.0 - alpha) * running
        if k >= period - 1:
            atr[k] = running
    return atr


def _rolling_zscore_series(arr: np.ndarray, window: int) -> np.ndarray:
    """Rolling z-score series matching _zscore_last semantics.

    At position i, scores arr[i] against arr[max(0, i-window+1):i+1] using the
    effective window min(window, i+1) — the series expands until it saturates at
    `window` elements. This matches _zscore_last(arr[:i+1], min(window, i+1)).

    Uses cumulative sums — O(n) total.
    Returns 0.0 where fewer than 2 samples or std < 1e-8.
    """
    n = len(arr)
    out = np.zeros(n, dtype=float)
    if n < 2 or window < 2:
        return out
    cs = np.cumsum(arr)
    cs2 = np.cumsum(arr * arr)
    for i in range(1, n):
        eff_w = min(window, i + 1)
        start = i + 1 - eff_w  # first index included (0-based)
        s = cs[i] - (cs[start - 1] if start > 0 else 0.0)
        s2 = cs2[i] - (cs2[start - 1] if start > 0 else 0.0)
        mean = s / eff_w
        var = max(s2 / eff_w - mean * mean, 0.0)
        std = math.sqrt(var)
        out[i] = (arr[i] - mean) / std if std > 1e-8 else 0.0
    return out


def _fixed_window_zscore_series(arr: np.ndarray, window: int) -> np.ndarray:
    """Rolling z-score series matching streaming `_zscore_last(arr, window)`.

    `_rolling_zscore_series` expands the window until it saturates; the streaming
    `_zscore_last` instead returns 0.0 until `window` samples exist. This forces
    that fixed-window cold-start by zeroing the first `window - 1` positions.
    """
    z = _rolling_zscore_series(arr, window)
    z[: window - 1] = 0.0
    return z


def _cmf(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    volumes: np.ndarray,
    period: int,
) -> float:
    """Chaikin Money Flow over period. Returns 0.0 on insufficient data.

    CMF = sum(MFV, period) / sum(volume, period)
    MFV = volume * (2*close - high - low) / (high - low)
    """
    if len(closes) < period:
        return 0.0
    h = highs[-period:]
    lo = lows[-period:]
    c = closes[-period:]
    v = volumes[-period:]
    hl_range = h - lo
    safe_range = np.where(hl_range > 0, hl_range, 1.0)
    mfm = np.where(hl_range > 0, (2.0 * c - h - lo) / safe_range, 0.0)
    mfv = mfm * v
    vol_sum = float(np.sum(v))
    return float(np.sum(mfv)) / vol_sum if vol_sum > 1e-10 else 0.0


# ---------------------------------------------------------------------------
# Renaissance Primitives — Bar Anatomy Ratios (Phase 142.5 Plan 01)
# ---------------------------------------------------------------------------


def _body_ratio(
    open_price: float, high: float, low: float, close: float, eps: float = 1e-10
) -> float:
    """Bar body ratio: (C - O) / (H - L). Bounded [-1, 1]. Returns 0.0 on degenerate bar (H == L)."""
    hl = high - low
    if hl < eps:
        return 0.0
    return (close - open_price) / hl


def _upper_wick_ratio(
    open_price: float, high: float, low: float, close: float, eps: float = 1e-10
) -> float:
    """Upper wick ratio: (H - max(O, C)) / (H - L). Bounded [0, 1]. Returns 0.5 on degenerate bar."""
    hl = high - low
    if hl < eps:
        return 0.5
    return (high - max(open_price, close)) / hl


def _lower_wick_ratio(
    open_price: float, high: float, low: float, close: float, eps: float = 1e-10
) -> float:
    """Lower wick ratio: (min(O, C) - L) / (H - L). Bounded [0, 1]. Returns 0.5 on degenerate bar."""
    hl = high - low
    if hl < eps:
        return 0.5
    return (min(open_price, close) - low) / hl


def _range_vs_atr(high: float, low: float, atr: float, eps: float = 1e-10) -> float:
    """Bar range relative to ATR: (H - L) / ATR_N. Unbounded positive. Returns 0.0 when atr < eps."""
    return (high - low) / atr if atr > eps else 0.0


def _close_vs_open_direction(open_price: float, close: float) -> float:
    """Directional sign of the bar: sign(C - O). Categorical {-1.0, 0.0, 1.0}."""
    diff = close - open_price
    if diff == 0.0:
        return 0.0
    return math.copysign(1.0, diff)


def _overnight_gap(open_price: float, prev_close: float, eps: float = 1e-10) -> float:
    """Overnight gap return: (O - prev_C) / prev_C. Unbounded. Returns 0.0 when prev_C < eps."""
    return (open_price - prev_close) / prev_close if prev_close > eps else 0.0


def _overnight_gap_series_full(
    opens: np.ndarray, closes: np.ndarray, eps: float = 1e-10
) -> np.ndarray:
    """Raw overnight_gap value per bar index i (i >= 1); index 0 padded with 0.0.

    result[i] == streaming _overnight_gap(opens[i], closes[i-1]) for i >= 1.
    Batch precompute helper — used only to feed _overnight_gap_z_series_full below;
    the raw per-bar overnight_gap value itself is O(1) via _overnight_gap() directly.
    """
    n = len(closes)
    if n < 2:
        return np.zeros(n, dtype=float)
    prev_closes = closes[:-1]
    raw_gaps = np.where(prev_closes > eps, (opens[1:] - prev_closes) / prev_closes, 0.0)
    return np.concatenate([[0.0], raw_gaps])


def _overnight_gap_z(
    opens: np.ndarray, closes: np.ndarray, window: int, eps: float = 1e-10
) -> float:
    """Z-score of overnight_gap over a trailing window of bars (streaming path).

    Builds the full overnight_gap series then z-scores the last value against the
    trailing `window`, matching _zscore_last semantics. Returns 0.0 on insufficient
    history (fewer than `window` gap observations).
    """
    if len(closes) < 2:
        return 0.0
    prev_closes = closes[:-1]
    gaps = np.where(prev_closes > eps, (opens[1:] - prev_closes) / prev_closes, 0.0)
    return _zscore_last(gaps, window)


def _overnight_gap_z_series_full(opens: np.ndarray, closes: np.ndarray, window: int) -> np.ndarray:
    """Z-scored overnight_gap series (batch path). result[i] == streaming
    _overnight_gap_z(opens[:i+1], closes[:i+1], window) for i >= 1.

    O(n) total — required because _overnight_gap_z rebuilds the full gap array per
    call; looping compute_batch() calling the streaming version would be O(n^2).
    """
    n = len(closes)
    if n < 2:
        return np.zeros(n, dtype=float)
    raw_gaps = _overnight_gap_series_full(opens, closes)[1:]  # index j == gap at bar j+1
    z = _fixed_window_zscore_series(raw_gaps, window)
    return np.concatenate([[0.0], z])  # index i == z-score at bar i (i >= 1)


def _range_efficiency(
    close: float, prev_close: float, high: float, low: float, eps: float = 1e-10
) -> float:
    """Range efficiency: abs(C - prev_C) / (H - L). Bounded [0, 1]. Returns 0.0 on degenerate bar."""
    hl = high - low
    if hl < eps:
        return 0.0
    return min(abs(close - prev_close) / hl, 1.0)


# ---------------------------------------------------------------------------
# Renaissance Primitives — Lagged Return Series (Phase 142.5 Plan 01)
# ---------------------------------------------------------------------------


def _ret_lag_k(closes: np.ndarray, k: int, eps: float = 1e-10) -> float:
    """Shared implementation: log(C_t / C_{t-k}). Returns 0.0 when history < k + 1."""
    if len(closes) < k + 1:
        return 0.0
    return float(np.log(max(float(closes[-1]), eps) / max(float(closes[-(k + 1)]), eps)))


def _ret_lag_1(closes: np.ndarray, eps: float = 1e-10) -> float:
    """1-bar lagged log return: log(C_t / C_{t-1}). Definitional — no APR key."""
    return _ret_lag_k(closes, 1, eps)


def _ret_lag_2(closes: np.ndarray, eps: float = 1e-10) -> float:
    """2-bar lagged log return: log(C_t / C_{t-2}). Definitional — no APR key."""
    return _ret_lag_k(closes, 2, eps)


def _ret_lag_3(closes: np.ndarray, eps: float = 1e-10) -> float:
    """3-bar lagged log return: log(C_t / C_{t-3}). Definitional — no APR key."""
    return _ret_lag_k(closes, 3, eps)


def _ret_lag_fast(closes: np.ndarray, window: int, eps: float = 1e-10) -> float:
    """Gradient fast-scale lagged log return: log(C_t / C_{t-window}). APR: feature.ret_lag.fast"""
    return _ret_lag_k(closes, window, eps)


def _ret_lag_mid(closes: np.ndarray, window: int, eps: float = 1e-10) -> float:
    """Gradient mid-scale lagged log return: log(C_t / C_{t-window}). APR: feature.ret_lag.mid"""
    return _ret_lag_k(closes, window, eps)


def _ret_lag_slow(closes: np.ndarray, window: int, eps: float = 1e-10) -> float:
    """Gradient slow-scale lagged log return: log(C_t / C_{t-window}). APR: feature.ret_lag.slow"""
    return _ret_lag_k(closes, window, eps)


# ---------------------------------------------------------------------------
# Renaissance Primitives — Open-to-Close Split (Phase 142.5 Plan 01)
# ---------------------------------------------------------------------------


def _open_ret(open_price: float, prev_close: float, eps: float = 1e-10) -> float:
    """Overnight component of return: log(O_t / prev_C). Returns 0.0 when prev_C < eps."""
    if prev_close < eps:
        return 0.0
    return float(np.log(max(open_price, eps) / prev_close))


def _intraday_ret(close: float, open_price: float, eps: float = 1e-10) -> float:
    """Intraday component of return: log(C_t / O_t). Returns 0.0 when O_t < eps."""
    if open_price < eps:
        return 0.0
    return float(np.log(max(close, eps) / open_price))


def _open_vs_intraday(open_ret: float, intraday_ret: float) -> float:
    """Overnight-vs-intraday return decomposition gap: open_ret - intraday_ret."""
    return open_ret - intraday_ret


def _session_time_pos(bar_ts: datetime, config: FeatureFactoryConfig) -> float:
    """Continuous [0, 1] position within the NY regular session for bar_ts's date.

    Formula: clamp((total_minutes - start_minutes) / (end_minutes - start_minutes), 0.0, 1.0).
    0.0 before/at session open, 1.0 at/after session close. Pure timestamp arithmetic — no
    OHLCV. Deviation from source spec (discrete bar_index/total_session_bars) documented in
    142.5-01-PLAN.md: continuous fraction is TF-independent (session bar count varies by TF).
    """
    total_minutes = bar_ts.hour * 60 + bar_ts.minute
    start_minutes = config.ny_session_start_utc_hour * 60 + config.ny_session_start_utc_minute
    end_minutes = config.ny_session_end_utc_hour * 60
    session_length = end_minutes - start_minutes
    if session_length <= 0:
        return 0.0
    frac = (total_minutes - start_minutes) / session_length
    return max(0.0, min(1.0, frac))


# ---------------------------------------------------------------------------
# Renaissance Primitives — Temporal Coordinates (Phase 142.5 Plan 02)
# ---------------------------------------------------------------------------
# Pure timestamp arithmetic — no state, no OHLCV, no APR keys. Sin/cos encodings
# preserve circular distance (e.g. 23:00 is 1 hour from 00:00, not 23 hours).
# All bounded [-1, 1] by construction (math.sin/math.cos range).


def _hour_of_day_sin(bar_ts: datetime) -> float:
    """Circular hour-of-day encoding: sin(2*pi*(hour + minute/60)/24)."""
    hour = bar_ts.hour + bar_ts.minute / 60.0
    return math.sin(2.0 * math.pi * hour / 24.0)


def _hour_of_day_cos(bar_ts: datetime) -> float:
    """Circular hour-of-day encoding: cos(2*pi*(hour + minute/60)/24)."""
    hour = bar_ts.hour + bar_ts.minute / 60.0
    return math.cos(2.0 * math.pi * hour / 24.0)


def _week_of_month_sin(bar_ts: datetime) -> float:
    """Circular week-of-month encoding: sin(2*pi*week/5). week = (day-1)//7 + 1."""
    week = (bar_ts.day - 1) // 7 + 1
    return math.sin(2.0 * math.pi * week / 5.0)


def _week_of_month_cos(bar_ts: datetime) -> float:
    """Circular week-of-month encoding: cos(2*pi*week/5). week = (day-1)//7 + 1."""
    week = (bar_ts.day - 1) // 7 + 1
    return math.cos(2.0 * math.pi * week / 5.0)


def _day_of_month_sin(bar_ts: datetime) -> float:
    """Circular day-of-month encoding: sin(2*pi*day/31)."""
    return math.sin(2.0 * math.pi * bar_ts.day / 31.0)


def _day_of_month_cos(bar_ts: datetime) -> float:
    """Circular day-of-month encoding: cos(2*pi*day/31)."""
    return math.cos(2.0 * math.pi * bar_ts.day / 31.0)


def _week_of_year_sin(bar_ts: datetime) -> float:
    """Circular week-of-year encoding: sin(2*pi*isocalendar_week/52)."""
    _, week, _ = bar_ts.isocalendar()
    return math.sin(2.0 * math.pi * week / 52.0)


def _week_of_year_cos(bar_ts: datetime) -> float:
    """Circular week-of-year encoding: cos(2*pi*isocalendar_week/52)."""
    _, week, _ = bar_ts.isocalendar()
    return math.cos(2.0 * math.pi * week / 52.0)


def _month_sin(bar_ts: datetime) -> float:
    """Circular month-of-year encoding: sin(2*pi*month/12). NEW pair — only
    _month_position (linear) existed before this plan."""
    return math.sin(2.0 * math.pi * bar_ts.month / 12.0)


def _month_cos(bar_ts: datetime) -> float:
    """Circular month-of-year encoding: cos(2*pi*month/12). NEW pair — only
    _month_position (linear) existed before this plan."""
    return math.cos(2.0 * math.pi * bar_ts.month / 12.0)


# ---------------------------------------------------------------------------
# Renaissance Primitives — Volume Structure (Phase 142.5 Plan 02)
# ---------------------------------------------------------------------------
# Beyond simple z-scores of volume level. Streaming (per-bar) implementations —
# see _*_series_full below for the O(n) batch/backfill precompute path.


def _percentile_rank(hist: np.ndarray, current: float) -> float:
    """Percentile rank of `current` within `hist` (inclusive, "weak" semantics).

    Uses scipy.stats.percentileofscore when available; falls back to a manual
    rank computation if scipy is not importable (T-142.5-02-02 mitigation).
    Bounded [0, 1].
    """
    try:
        from scipy import stats  # noqa: PLC0415

        pct = stats.percentileofscore(hist, current, kind="weak") / 100.0
    except ImportError:
        rank = float(np.sum(hist <= current))
        pct = rank / len(hist)
    return float(np.clip(pct, 0.0, 1.0))


def _vol_acceleration(volumes: np.ndarray, eps: float = 1e-10) -> float:
    """Volume surge relative to prior bar: V_t / V_{t-1}. Unbounded positive.

    Returns 1.0 (neutral) on insufficient history or near-zero prior volume.
    """
    if len(volumes) < 2:
        return 1.0
    prev = float(volumes[-2])
    if prev < eps:
        return 1.0
    return float(volumes[-1]) / prev


def _dollar_vol_z(volumes: np.ndarray, closes: np.ndarray, window: int) -> float:
    """Z-score of dollar volume (V * C) over the trailing window. Returns 0.0 on cold start."""
    if len(volumes) < 2:
        return 0.0
    dollar_vol = volumes.astype(float) * closes.astype(float)
    return _zscore_last(dollar_vol, window)


def _vol_range_ratio(
    volumes: np.ndarray, highs: np.ndarray, lows: np.ndarray, window: int, eps: float = 1e-10
) -> float:
    """Volume per unit of price range, normalized against its own trailing average.

    raw_t = V_t / (H_t - L_t); result = raw_t / mean(raw, trailing window).
    Unbounded positive. Returns 0.0 on a degenerate current bar (H == L) or cold start.
    """
    n = len(volumes)
    if n < 1:
        return 0.0
    ranges = highs.astype(float) - lows.astype(float)
    raw = np.where(ranges > eps, volumes.astype(float) / np.where(ranges > eps, ranges, 1.0), 0.0)
    w = min(window, n)
    mean_raw = float(np.mean(raw[-w:]))
    if mean_raw < eps:
        return 0.0
    return float(raw[-1]) / mean_raw


def _vol_trend_ratio(
    volumes: np.ndarray, fast_window: int, slow_window: int, eps: float = 1e-10
) -> float:
    """Volume participation trend: vol_MA_fast / vol_MA_slow. Unbounded positive.

    Returns 1.0 (neutral) on cold start (fewer than slow_window bars).
    """
    n = len(volumes)
    if n < slow_window:
        return 1.0
    v = volumes.astype(float)
    ma_fast = float(np.mean(v[-fast_window:]))
    ma_slow = float(np.mean(v[-slow_window:]))
    return ma_fast / ma_slow if ma_slow > eps else 1.0


def _up_vol_ratio(
    volumes: np.ndarray,
    opens: np.ndarray,
    closes: np.ndarray,
    window: int,
    eps: float = 1e-10,
) -> float:
    """Fraction of volume occurring on up bars: sum(V | C > O) / sum(V) over window.

    Bounded [0, 1]. Returns 0.5 (neutral) on cold start or near-zero total volume.
    Shared implementation for up_vol_ratio_fast/slow (different window arguments).
    """
    n = len(volumes)
    w = min(window, n)
    if w < 1:
        return 0.5
    v = volumes[-w:].astype(float)
    o = opens[-w:].astype(float)
    c = closes[-w:].astype(float)
    total = float(np.sum(v))
    if total < eps:
        return 0.5
    up_vol = float(np.sum(np.where(c > o, v, 0.0)))
    return up_vol / total


def _vol_percentile(volumes: np.ndarray, window: int) -> float:
    """Rolling percentile rank of V_t over the trailing window. Bounded [0, 1].

    Returns 0.5 (neutral) on cold start (fewer than 2 bars in the window).
    """
    n = len(volumes)
    w = min(window, n)
    if w < 2:
        return 0.5
    hist = volumes[-w:].astype(float)
    return _percentile_rank(hist, float(hist[-1]))


def _vol_persistence(volumes: np.ndarray, window: int) -> float:
    """Lag-1 autocorrelation of volume over the trailing window. Bounded [-1, 1].

    Returns 0.0 on cold start (fewer than 2 bars in the window). Reuses _pearson_acf1.
    """
    n = len(volumes)
    w = min(window, n)
    if w < 2:
        return 0.0
    hist = volumes[-w:].astype(float)
    return _pearson_acf1(hist)


def _rolling_std_series(arr: np.ndarray, window: int) -> np.ndarray:
    """Trailing rolling std series (expanding until `window` bars, then fixed window).

    O(n) via cumulative sums. Shared building block for _vol_std_z (streaming) and
    _vol_std_z_series_full (batch).
    """
    n = len(arr)
    out = np.zeros(n, dtype=float)
    if n == 0:
        return out
    cs = np.cumsum(arr)
    cs2 = np.cumsum(arr * arr)
    for i in range(n):
        eff_w = min(window, i + 1)
        start = i + 1 - eff_w
        s = cs[i] - (cs[start - 1] if start > 0 else 0.0)
        s2 = cs2[i] - (cs2[start - 1] if start > 0 else 0.0)
        mean = s / eff_w
        var = max(s2 / eff_w - mean * mean, 0.0)
        out[i] = math.sqrt(var)
    return out


def _rolling_mean_series(arr: np.ndarray, window: int) -> np.ndarray:
    """Trailing rolling mean series (expanding until `window` bars, then fixed window).

    O(n) via cumulative sums. Shared building block for the Parkinson/Garman-Klass
    alternative volatility estimators (Phase 142.5 Plan 04), which smooth their
    per-bar variance proxy over `window` bars before z-scoring.
    """
    n = len(arr)
    out = np.zeros(n, dtype=float)
    if n == 0:
        return out
    cs = np.cumsum(arr)
    for i in range(n):
        eff_w = min(window, i + 1)
        start = i + 1 - eff_w
        s = cs[i] - (cs[start - 1] if start > 0 else 0.0)
        out[i] = s / eff_w
    return out


def _vol_std_z(volumes: np.ndarray, window: int) -> float:
    """Z-score of rolling std(V) over the trailing window (single-window design:
    the same `window` both computes the rolling std series and z-scores its last
    value). Returns 0.0 on cold start.
    """
    if len(volumes) < 2:
        return 0.0
    std_series = _rolling_std_series(volumes.astype(float), window)
    return _zscore_last(std_series, window)


def _mfi(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    volumes: np.ndarray,
    window: int,
    eps: float = 1e-10,
) -> float:
    """Money Flow Index: 100 * sum(tp*V | tp rising) / sum(tp*V) over window.

    tp = (H + L + C) / 3. Bounded [0, 100]. Returns 50.0 (neutral) on cold start
    or near-zero total money flow. Shared implementation for mfi_fast/slow.
    """
    n = len(closes)
    w = min(window, n - 1) if n >= 2 else 0
    if w < 1:
        return 50.0
    tp_full = (highs[-(w + 1) :].astype(float) + lows[-(w + 1) :].astype(float)) + closes[
        -(w + 1) :
    ].astype(float)
    tp_full = tp_full / 3.0
    v_full = volumes[-(w + 1) :].astype(float)
    tp = tp_full[1:]
    prev_tp = tp_full[:-1]
    v = v_full[1:]
    money_flow = tp * v
    total = float(np.sum(money_flow))
    if total < eps:
        return 50.0
    rising_flow = float(np.sum(money_flow[tp > prev_tp]))
    return float(np.clip(100.0 * rising_flow / total, 0.0, 100.0))


def _obv_z(closes: np.ndarray, volumes: np.ndarray, window: int) -> float:
    """Z-score of On-Balance Volume (cumulative +V on up bars, -V on down bars).

    Returns 0.0 on cold start (fewer than 2 bars).
    """
    n = len(closes)
    if n < 2:
        return 0.0
    diffs = np.diff(closes.astype(float))
    signed_vol = np.where(
        diffs > 0,
        volumes[1:].astype(float),
        np.where(diffs < 0, -volumes[1:].astype(float), 0.0),
    )
    obv = np.cumsum(signed_vol)
    return _zscore_last(obv, window)


# ---------------------------------------------------------------------------
# Renaissance Primitives — Breakout Distance (Phase 142.5 Plan 05)
#
# Price structure primitives with no theory: raw distance from recent extremes,
# range position, and trend-purity — the IC engine evaluates whether any of
# these carry signal. No S/R zone semantics, no chart-pattern logic.
# ---------------------------------------------------------------------------


def _dist_from_high(close: float, highs: np.ndarray, atr: float, eps: float = 1e-10) -> float:
    """Distance from the rolling high, ATR-normalized: (rolling_high_N - C) / ATR.

    Unbounded non-negative (the current bar's high is always in the window,
    so rolling_high_N >= C by construction). Returns 0.0 when ATR is near zero
    (cold start / degenerate volatility).
    """
    if atr < eps:
        return 0.0
    rolling_high = float(np.max(highs))
    return (rolling_high - close) / atr


def _dist_from_low(close: float, lows: np.ndarray, atr: float, eps: float = 1e-10) -> float:
    """Distance from the rolling low, ATR-normalized: (C - rolling_low_N) / ATR.

    Unbounded non-negative (the current bar's low is always in the window,
    so rolling_low_N <= C by construction). Returns 0.0 when ATR is near zero.
    """
    if atr < eps:
        return 0.0
    rolling_low = float(np.min(lows))
    return (close - rolling_low) / atr


def _range_pct(close: float, highs: np.ndarray, lows: np.ndarray, eps: float = 1e-10) -> float:
    """Rolling range as a fraction of price: (rolling_high_N - rolling_low_N) / C.

    Unbounded non-negative. Returns 0.0 when close is near zero.
    """
    if close < eps:
        return 0.0
    return (float(np.max(highs)) - float(np.min(lows))) / close


def _new_high_flag(close: float, highs: np.ndarray, eps: float = 1e-10) -> float:
    """1.0 if the current close is at (or above, epsilon-tolerant) the rolling
    high, else 0.0. Binary {0.0, 1.0}.
    """
    rolling_high = float(np.max(highs))
    return 1.0 if close >= rolling_high - eps else 0.0


def _new_low_flag(close: float, lows: np.ndarray, eps: float = 1e-10) -> float:
    """1.0 if the current close is at (or below, epsilon-tolerant) the rolling
    low, else 0.0. Binary {0.0, 1.0}.
    """
    rolling_low = float(np.min(lows))
    return 1.0 if close <= rolling_low + eps else 0.0


def _stoch_k(close: float, highs: np.ndarray, lows: np.ndarray, eps: float = 1e-10) -> float:
    """Stochastic %K: (C - L_N) / (H_N - L_N). Bounded [0, 1].

    Returns 0.5 (neutral) on a degenerate range (H_N == L_N).
    """
    rolling_high = float(np.max(highs))
    rolling_low = float(np.min(lows))
    rng = rolling_high - rolling_low
    if rng < eps:
        return 0.5
    return (close - rolling_low) / rng


def _price_percentile(close: float, closes: np.ndarray) -> float:
    """Rolling percentile rank of the current close within its trailing window.

    Bounded [0, 1]. Returns 0.5 (neutral) on cold start (fewer than 2 bars).
    Reuses _percentile_rank (scipy percentileofscore with manual fallback).
    """
    if len(closes) < 2:
        return 0.5
    return _percentile_rank(closes, close)


def _efficiency_ratio(closes: np.ndarray, eps: float = 1e-10) -> float:
    """Kaufman efficiency ratio: |C_t - C_{t-N}| / sum(|C_i - C_{i-1}|) over the window.

    Bounded [0, 1] (0 = pure chop, 1 = perfectly linear trend). Returns 0.0 for
    fewer than 2 bars or a degenerate (zero-movement) window.
    """
    if len(closes) < 2:
        return 0.0
    net = abs(float(closes[-1]) - float(closes[0]))
    total = float(np.sum(np.abs(np.diff(closes))))
    if total < eps:
        return 0.0
    return float(np.clip(net / total, 0.0, 1.0))


# ---------------------------------------------------------------------------
# Renaissance Primitives — Return Distribution (Phase 142.5 Plan 03)
#
# Statistical moments and streak/win-rate structure of the return series.
# ---------------------------------------------------------------------------


def _kurtosis(arr: np.ndarray) -> float:
    """Pearson excess kurtosis: mean(((x-mean)/std)**4) - 3.0.

    Returns 0.0 for degenerate input (fewer than 4 samples or std < 1e-10).
    """
    if len(arr) < 4:
        return 0.0
    mean = arr.mean()
    std = arr.std()
    if std < 1e-10:
        return 0.0
    result = float(np.mean(((arr - mean) / std) ** 4) - 3.0)
    return result if math.isfinite(result) else 0.0


def _ret_autocorr(closes: np.ndarray, lag: int) -> float:
    """Lag-k Pearson autocorrelation of log returns, computed over ALL
    available return history (expanding window, not a rolling APR window).

    The lag itself is a definitional constant (1 or 5), matching the
    ret_lag_1/2/3 convention of fixed-lag primitives with no tunable window
    (source spec: "Number (definitional)"). Bounded [-1, 1] by construction.
    Returns 0.0 when fewer than lag + 2 return observations exist.
    """
    if len(closes) < lag + 3:
        return 0.0
    log_rets = np.diff(np.log(np.maximum(closes.astype(float), 1e-10)))
    if len(log_rets) < lag + 2:
        return 0.0
    x = log_rets[:-lag] - log_rets[:-lag].mean()
    y = log_rets[lag:] - log_rets[lag:].mean()
    denom = float(np.sqrt(np.dot(x, x) * np.dot(y, y)))
    if denom < 1e-10:
        return 0.0
    return float(np.dot(x, y) / denom)


def _updown_ratio(rets: np.ndarray, eps: float = 1e-10) -> float:
    """count(up bars) / count(down bars) over the given return window.

    Returns 1.0 (neutral) when there are zero down bars — including an empty
    window — rather than an unbounded/undefined ratio.
    """
    up = int(np.sum(rets > eps))
    down = int(np.sum(rets < -eps))
    return float(up) / down if down > 0 else 1.0


def _streak_length(signs: np.ndarray) -> float:
    """Current signed directional streak length ending at the last element:
    positive for an up-streak, negative for a down-streak, magnitude = number
    of consecutive same-sign observations. Returns 0.0 for empty input or a
    zero-return final bar (streak reset).
    """
    if len(signs) == 0:
        return 0.0
    last_sign = signs[-1]
    if last_sign == 0:
        return 0.0
    streak = 0
    for s in signs[::-1]:
        if s == last_sign:
            streak += 1
        else:
            break
    return float(streak) if last_sign > 0 else -float(streak)


# ---------------------------------------------------------------------------
# Renaissance Primitives — Realized Variance / Volatility (Phase 142.5 Plan 03)
#
# Second-moment structure beyond ATR: aggregated-return variance ratios
# (Lo-MacKinlay VR), close-to-close historical volatility, Bollinger %B band
# position, H/L correlation, and up/down volatility asymmetry.
# ---------------------------------------------------------------------------


def _realized_var_ratio(closes: np.ndarray, fast_window: int, slow_window: int) -> float:
    """Ratio of realized return variance across two window scales:
    var(ret, fast) / var(ret, slow). Uses expanding windows
    (min(window, available)) for consistency with the batch series
    precompute. Returns 1.0 (neutral) on insufficient history in either
    window or near-zero slow-window variance.
    """
    if len(closes) < 2:
        return 1.0
    log_rets = np.diff(np.log(np.maximum(closes.astype(float), 1e-10)))
    w_slow = min(slow_window, len(log_rets))
    w_fast = min(fast_window, len(log_rets))
    if w_slow < 2 or w_fast < 2:
        return 1.0
    var_slow = float(np.var(log_rets[-w_slow:]))
    var_fast = float(np.var(log_rets[-w_fast:]))
    return var_fast / var_slow if var_slow > 1e-14 else 1.0


def _range_to_close(high: float, low: float, close: float, eps: float = 1e-10) -> float:
    """Rolling range as a fraction of price: (H - L) / C. Unbounded non-negative.
    Returns 0.0 when close is near zero.
    """
    return (high - low) / close if close > eps else 0.0


def _true_range_pct(
    high: float, low: float, prev_close: float, close: float, eps: float = 1e-10
) -> float:
    """True range as a fraction of price: TR / C, where
    TR = max(H-L, |H-prev_C|, |L-prev_C|). Unbounded non-negative.
    Returns 0.0 when close is near zero.
    """
    if close < eps:
        return 0.0
    tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
    return tr / close


def _correlation(x: np.ndarray, y: np.ndarray) -> float:
    """Pearson correlation coefficient between two equal-length arrays.
    Returns 0.0 for degenerate input (fewer than 2 samples or zero variance
    in either series).
    """
    if len(x) < 2 or len(y) < 2:
        return 0.0
    xm = x - x.mean()
    ym = y - y.mean()
    denom = float(np.sqrt(np.dot(xm, xm) * np.dot(ym, ym)))
    if denom < 1e-10:
        return 0.0
    return float(np.dot(xm, ym) / denom)


def _variance_ratio(closes: np.ndarray, n: int) -> float:
    """Lo-MacKinlay variance ratio: Var(N-period return) / (N * Var(1-period
    return)), using overlapping N-period sums computed over ALL available
    return history (the classic full-sample VR specification-test estimator
    — no separate sample-window APR key). Under a random walk, VR -> 1.0.
    Returns 1.0 (random-walk neutral) when insufficient history exists for
    either variance estimate.
    """
    if len(closes) < 2 or n < 1:
        return 1.0
    log_rets = np.diff(np.log(np.maximum(closes.astype(float), 1e-10)))
    m = len(log_rets)
    if m < n + 1:
        return 1.0
    var_1 = float(np.var(log_rets))
    if var_1 < 1e-14:
        return 1.0
    cs = np.concatenate([[0.0], np.cumsum(log_rets)])
    agg = cs[n:] - cs[:-n]
    if len(agg) < 2:
        return 1.0
    var_n = float(np.var(agg))
    return var_n / (n * var_1)


def _vol_asymmetry_ratio(rets_window: np.ndarray, eps: float = 1e-10) -> float:
    """Ratio of up-bar return std to down-bar return std within the window:
    std(ret | ret > 0) / std(ret | ret < 0). Returns 1.0 (neutral) when
    fewer than 2 up or 2 down observations exist in the window.
    """
    up = rets_window[rets_window > eps]
    down = rets_window[rets_window < -eps]
    if len(up) < 2 or len(down) < 2:
        return 1.0
    std_up = float(np.std(up))
    std_down = float(np.std(down))
    return std_up / std_down if std_down > eps else 1.0


def _bb_pct_b(closes_window: np.ndarray, eps: float = 1e-10) -> float:
    """Bollinger %B: (C - lower_band) / (upper_band - lower_band), where the
    bands are SMA +/- 2*std over the window. Returns 0.5 (neutral) on a
    degenerate (near-zero-std) band.
    """
    if len(closes_window) < 2:
        return 0.5
    mean = float(np.mean(closes_window))
    std = float(np.std(closes_window))
    if std < eps:
        return 0.5
    upper = mean + 2.0 * std
    lower = mean - 2.0 * std
    c = float(closes_window[-1])
    return (c - lower) / (upper - lower)


# ---------------------------------------------------------------------------
# Renaissance Primitives — Alternative Volatility Estimators (Phase 142.5 Plan 04)
#
# Parkinson/Garman-Klass/Yang-Zhang all extract more information from a single
# bar's OHLC than a close-only estimator (ATR/HV). The scalar raw-term
# functions below compute the classic single-bar (Parkinson/GK) or windowed
# (YZ) variance proxy; the _z wrappers smooth (Parkinson/GK) or window (YZ)
# that proxy and z-score it -- both delegate to the vectorized _series_full
# implementations further below so there is one source of truth for the
# math (compute() and compute_batch() both read those same arrays).
# ---------------------------------------------------------------------------


def _parkinson_vol(high: float, low: float, eps: float = 1e-10) -> float:
    """Parkinson single-bar variance proxy: ln(H/L)^2 / (4*ln(2)).

    4*ln(2) is the Parkinson estimator's definitional normalizing constant
    (not APR-tunable — same status as Garman-Klass's `2*ln(2)-1` term below).
    Returns 0.0 on a degenerate/inverted bar (H <= L or L <= eps).
    """
    if high <= low or low <= eps:
        return 0.0
    return (math.log(high / low) ** 2) / (4.0 * math.log(2.0))


def _garman_klass_vol(
    open_: float, high: float, low: float, close: float, eps: float = 1e-10
) -> float:
    """Garman-Klass single-bar variance proxy:
    0.5*ln(H/L)^2 - (2*ln(2)-1)*ln(C/O)^2.

    `2*ln(2)-1` is the estimator's definitional weighting constant (not
    APR-tunable). Returns 0.0 on a degenerate bar (H <= L, or O/C <= eps).
    """
    if high <= low or low <= eps or open_ <= eps or close <= eps:
        return 0.0
    hl_term = 0.5 * (math.log(high / low) ** 2)
    co_term = (2.0 * math.log(2.0) - 1.0) * (math.log(close / open_) ** 2)
    return hl_term - co_term


def _yang_zhang_vol(
    opens_window: np.ndarray,
    closes_window: np.ndarray,
    prev_closes_window: np.ndarray,
    k: float = 0.34,
) -> float:
    """Yang-Zhang variance estimator over a window of bars:
    var(overnight_gap) + k*var(open-to-close), where overnight_gap =
    ln(O_t/prev_C_{t-1}) and open-to-close = ln(C_t/O_t).

    k ~= 0.34 is the standard Yang-Zhang weighting constant (definitional,
    not APR-tunable -- same status as the Parkinson/GK constants above).
    Returns 0.0 on insufficient history (fewer than 2 bars in the window).
    """
    if len(opens_window) < 2:
        return 0.0
    o = opens_window.astype(float)
    c = closes_window.astype(float)
    prev_c = prev_closes_window.astype(float)
    overnight = np.log(np.maximum(o, 1e-10) / np.maximum(prev_c, 1e-10))
    o2c = np.log(np.maximum(c, 1e-10) / np.maximum(o, 1e-10))
    return float(np.var(overnight) + k * np.var(o2c))


def _parkinson_vol_z(highs: np.ndarray, lows: np.ndarray, window: int, zscore_window: int) -> float:
    """Z-score of the rolling-averaged Parkinson variance proxy. Delegates to
    `_parkinson_vol_z_series_full` (single source of truth shared with
    compute_batch()) and returns its last element. Returns 0.0 on cold start.
    """
    return _series_last(_parkinson_vol_z_series_full(highs, lows, window, zscore_window), 0.0)


def _garman_klass_vol_z(
    opens: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    window: int,
    zscore_window: int,
) -> float:
    """Z-score of the rolling-averaged Garman-Klass variance proxy. Delegates
    to `_garman_klass_vol_z_series_full`. Returns 0.0 on cold start.
    """
    return _series_last(
        _garman_klass_vol_z_series_full(opens, highs, lows, closes, window, zscore_window), 0.0
    )


def _yang_zhang_vol_z(
    opens: np.ndarray, closes: np.ndarray, window: int, zscore_window: int
) -> float:
    """Z-score of the rolling Yang-Zhang variance estimator. Delegates to
    `_yang_zhang_vol_z_series_full`. Returns 0.0 on cold start.
    """
    return _series_last(_yang_zhang_vol_z_series_full(opens, closes, window, zscore_window), 0.0)


# ---------------------------------------------------------------------------
# Renaissance Primitives — Volatility Dynamics (Phase 142.5 Plan 04)
#
# First derivatives of the 3 alt-vol z-scores (panic onset vs stabilization),
# a normalized velocity of atr_z, and an intraday choppiness measure.
# parkinson/garman_klass/yang_zhang_vol_velocity are computed inline in
# compute()/compute_batch() as a difference of two precomputed z-score-series
# elements (stateless, no separate helper needed -- see Deviations/decisions
# in the plan summary).
# ---------------------------------------------------------------------------


def _vol_velocity_z(atr_z_values: np.ndarray, window: int) -> float:
    """Z-score of the rolling velocity (first difference) of atr_z. Delegates
    to `_vol_velocity_z_series_full`. Returns 0.0 on cold start.
    """
    return _series_last(_vol_velocity_z_series_full(atr_z_values, window), 0.0)


def _intraday_noise_ratio(closes: np.ndarray, session_bars: int, eps: float = 1e-10) -> float:
    """Intraday noise ratio: sum(|log_ret|) / |net log_ret| over the trailing
    `session_bars` window. High values indicate choppy back-and-forth
    movement; values near 1.0 indicate a clean directional move. Returns 1.0
    (neutral) when net progress is at or near zero, 0.0 when insufficient
    history exists (fewer than session_bars + 1 closes).
    """
    n = len(closes)
    if n < session_bars + 1:
        return 0.0
    window = closes[-(session_bars + 1) :].astype(float)
    log_rets = np.diff(np.log(np.maximum(window, 1e-10)))
    sum_abs = float(np.sum(np.abs(log_rets)))
    net = float(np.sum(log_rets))
    if abs(net) < eps:
        return 1.0
    return sum_abs / abs(net)


# ---------------------------------------------------------------------------
# Calendar primitive functions
# ---------------------------------------------------------------------------


def _in_ny_session(bar_ts: datetime, config: FeatureFactoryConfig) -> float:
    """1.0 if bar_ts is within NY RTH, else 0.0."""
    total_minutes = bar_ts.hour * 60 + bar_ts.minute
    start_minutes = config.ny_session_start_utc_hour * 60 + config.ny_session_start_utc_minute
    end_minutes = config.ny_session_end_utc_hour * 60
    return 1.0 if start_minutes <= total_minutes < end_minutes else 0.0


def _in_overlap(bar_ts: datetime, config: FeatureFactoryConfig) -> float:
    """1.0 if bar_ts is in London-NY overlap, else 0.0."""
    return (
        1.0 if config.overlap_start_utc_hour <= bar_ts.hour < config.overlap_end_utc_hour else 0.0
    )


def _dow_encoding(bar_ts: datetime) -> tuple[float, float]:
    """Cyclic weekday encoding: (sin(2*pi*weekday/5), cos(2*pi*weekday/5)).

    weekday() returns 0=Monday, 4=Friday. Weekends treated as Friday.
    """
    weekday = min(bar_ts.weekday(), 4)
    angle = 2.0 * math.pi * weekday / 5.0
    return math.sin(angle), math.cos(angle)


def _month_position(bar_ts: datetime) -> float:
    """day_of_month / days_in_month: position within the month in (0, 1]."""
    days = calendar.monthrange(bar_ts.year, bar_ts.month)[1]
    return bar_ts.day / days


def _in_london_kz(bar_ts: datetime, config: FeatureFactoryConfig) -> float:
    """1.0 if bar_ts is in the London killzone, else 0.0."""
    return (
        1.0
        if config.london_kz_start_utc_hour <= bar_ts.hour < config.london_kz_end_utc_hour
        else 0.0
    )


def _power_hour(bar_ts: datetime, config: FeatureFactoryConfig) -> float:
    """1.0 if bar_ts is in power hour, else 0.0."""
    return (
        1.0
        if config.power_hour_start_utc_hour <= bar_ts.hour < config.power_hour_end_utc_hour
        else 0.0
    )


def _opening_range(bar_ts: datetime, config: FeatureFactoryConfig) -> float:
    """1.0 if bar_ts is in the first 30 min of NY session, else 0.0."""
    total_minutes = bar_ts.hour * 60 + bar_ts.minute
    return (
        1.0
        if config.opening_range_start_minute <= total_minutes < config.opening_range_end_minute
        else 0.0
    )


# ---------------------------------------------------------------------------
# Oscillator helpers (stateless, array-based)
# ---------------------------------------------------------------------------


def _rsi(closes: np.ndarray, period: int) -> float:
    """Wilder's RSI. Returns 50.0 on cold start. Result clamped to [0.0, 100.0]."""
    if len(closes) < period + 1:
        return 50.0
    deltas = np.diff(closes.astype(float))
    return _rsi_wilder(
        np.where(deltas > 0, deltas, 0.0), np.where(deltas < 0, -deltas, 0.0), period
    )


def _rsi_wilder(gains: np.ndarray, losses: np.ndarray, period: int) -> float:
    """Wilder smoothing from pre-split gains/losses arrays."""
    alpha = 1.0 / period
    avg_gain = float(np.mean(gains[:period]))
    avg_loss = float(np.mean(losses[:period]))
    for i in range(period, len(gains)):
        avg_gain = alpha * gains[i] + (1.0 - alpha) * avg_gain
        avg_loss = alpha * losses[i] + (1.0 - alpha) * avg_loss
    if avg_loss < 1e-10:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return float(np.clip(100.0 - 100.0 / (1.0 + rs), 0.0, 100.0))


def _cci(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int) -> float:
    """Commodity Channel Index: (typical - SMA_typical) / (0.015 * MAD).

    Returns 0.0 when MAD < 1e-10 or insufficient bars.
    Unbounded — typically in [-200, +200] but can exceed in extreme moves.
    """
    if len(closes) < period:
        return 0.0
    typical = (highs[-period:] + lows[-period:] + closes[-period:]) / 3.0
    sma = float(np.mean(typical))
    mad = float(np.mean(np.abs(typical - sma)))
    if mad < 1e-10:
        return 0.0
    return float((float(typical[-1]) - sma) / (0.015 * mad))


def _aroon_osc(highs: np.ndarray, lows: np.ndarray, period: int) -> float:
    """Aroon Oscillator = (aroon_up - aroon_down) / 100, range [-1.0, 1.0].

    Returns 0.0 when insufficient bars (< period + 1).
    """
    if len(highs) < period + 1:
        return 0.0
    window_h = highs[-(period + 1) :]
    window_l = lows[-(period + 1) :]
    aroon_up = int(np.argmax(window_h)) / period * 100.0
    aroon_down = int(np.argmin(window_l)) / period * 100.0
    return float(np.clip((aroon_up - aroon_down) / 100.0, -1.0, 1.0))


# ---------------------------------------------------------------------------
# Statistical / liquidity helpers (stateless, array-based)
# ---------------------------------------------------------------------------


def _skewness(arr: np.ndarray) -> float:
    if len(arr) < 3:
        return 0.0
    mean = arr.mean()
    std = arr.std()
    if std < 1e-10:
        return 0.0
    result = float(np.mean(((arr - mean) / std) ** 3))
    return result if math.isfinite(result) else 0.0


def _pearson_acf1(arr: np.ndarray) -> float:
    """Pearson lag-1 autocorrelation. Returns 0.0 if std < 1e-10 or len < 2."""
    if len(arr) < 2:
        return 0.0
    x = arr[:-1] - arr[:-1].mean()
    y = arr[1:] - arr[1:].mean()
    denom = float(np.sqrt(np.dot(x, x) * np.dot(y, y)))
    if denom < 1e-10:
        return 0.0
    return float(np.dot(x, y) / denom)


# ---------------------------------------------------------------------------
# Batch z-score helper (stateless: computes from arrays, no deque accumulation)
# ---------------------------------------------------------------------------


def _zscore_last(series: np.ndarray, window: int) -> float:
    """Z-score of the last element relative to the trailing window.

    Stateless: takes full array, uses last `window` elements for mean/std,
    scores the final element. Returns 0.0 on cold start or near-zero std.
    """
    if len(series) < window:
        return 0.0
    window_data = series[-window:]
    std = float(window_data.std())
    if std < 1e-8:
        return 0.0
    return float((float(series[-1]) - float(window_data.mean())) / std)


# ---------------------------------------------------------------------------
# Batch series functions — O(n) total, backfill compute stage only.
# result[i] matches FeatureFactory.compute(bars[:i+1], ...) for the named feature.
# The streaming per-bar functions above are untouched — live pipeline uses them.
# ---------------------------------------------------------------------------


def _momentum_z_series_full(closes: np.ndarray, window: int, zscore_window: int) -> np.ndarray:
    """Log-return velocity series, z-scored. result[i] == streaming momentum_z at bar i.
    Returns zeros for i < window (cold start matches streaming's 0.0).
    """
    n = len(closes)
    if n <= window:
        return np.zeros(n, dtype=float)
    log_returns = np.log(np.maximum(closes[window:], 1e-10) / np.maximum(closes[:-window], 1e-10))
    z = _fixed_window_zscore_series(log_returns, zscore_window)
    return np.concatenate([np.zeros(window, dtype=float), z])


def _momentum_reversal_z_series_full(closes: np.ndarray, zscore_window: int) -> np.ndarray:
    """1-bar log-return z-scored series. result[i] == streaming momentum_reversal_z at bar i."""
    n = len(closes)
    if n < 2:
        return np.zeros(n, dtype=float)
    log_rets = np.diff(np.log(np.maximum(closes.astype(float), 1e-10)))
    z = _rolling_zscore_series(log_rets, zscore_window)
    return np.concatenate([[0.0], z])


def _volume_z_series_full(volumes: np.ndarray, zscore_window: int) -> np.ndarray:
    """Volume z-score series. result[i] == streaming volume_z at bar i."""
    return _fixed_window_zscore_series(volumes.astype(float), zscore_window)


def _ofi_z_series_full(
    closes: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    volumes: np.ndarray,
    zscore_window: int,
) -> np.ndarray:
    """OFI z-score series. result[i] == streaming ofi_z at bar i."""
    ofi_raw = (closes - lows) / (highs - lows + 1e-10) * volumes
    return _fixed_window_zscore_series(ofi_raw.astype(float), zscore_window)


def _cvd_slope_z_series_full(
    closes: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    volumes: np.ndarray,
    slope_bars: int,
    zscore_window: int,
) -> np.ndarray:
    """CVD slope z-score series. result[i] == streaming cvd_slope_z at bar i.
    Returns zeros for i < slope_bars (cold start: len(cum_cvd) <= slope_bars).
    """
    n = len(closes)
    if n <= slope_bars:
        return np.zeros(n, dtype=float)
    cvd_raw = (2.0 * closes - highs - lows) / (highs - lows + 1e-10) * volumes
    cum_cvd = np.cumsum(cvd_raw.astype(float))
    slope_vals = (cum_cvd[slope_bars:] - cum_cvd[: n - slope_bars]) / slope_bars
    z = _fixed_window_zscore_series(slope_vals, zscore_window)
    return np.concatenate([np.zeros(slope_bars, dtype=float), z])


def _rsi_series_full(closes: np.ndarray, period: int) -> np.ndarray:
    """Wilder RSI for every bar in O(n). result[i] == streaming RSI at bar i.
    Returns 50.0 for i <= period (cold start matches streaming's fallback).
    Single forward Wilder pass — numerically identical to _rsi_wilder at every bar.
    """
    n = len(closes)
    result = np.full(n, 50.0, dtype=float)
    if n < period + 1:
        return result
    deltas = np.diff(closes.astype(float))
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    alpha = 1.0 / period
    avg_gain = float(np.mean(gains[:period]))
    avg_loss = float(np.mean(losses[:period]))
    # Write bar `period` from the SMA seed (matches streaming _rsi_wilder with exactly period deltas)
    if avg_loss < 1e-10:
        result[period] = 100.0 if avg_gain > 0 else 50.0
    else:
        rs = avg_gain / avg_loss
        result[period] = float(np.clip(100.0 - 100.0 / (1.0 + rs), 0.0, 100.0))
    for i in range(period, len(gains)):
        avg_gain = alpha * gains[i] + (1.0 - alpha) * avg_gain
        avg_loss = alpha * losses[i] + (1.0 - alpha) * avg_loss
        if avg_loss < 1e-10:
            result[i + 1] = 100.0 if avg_gain > 0 else 50.0
        else:
            rs = avg_gain / avg_loss
            result[i + 1] = float(np.clip(100.0 - 100.0 / (1.0 + rs), 0.0, 100.0))
    return result


def _ret_skew_z_series_full(closes: np.ndarray, skew_window: int, zscore_window: int) -> np.ndarray:
    """Rolling return skewness z-score series. result[i] == streaming ret_skew_z at bar i.
    O(n × skew_window) total — called once, vs O(n² × skew_window) previously.
    Returns zeros for i < skew_window (cold start).
    """
    n = len(closes)
    if n < skew_window + 3:
        return np.zeros(n, dtype=float)
    log_rets = np.diff(np.log(np.maximum(closes.astype(float), 1e-10)))
    # skew_vals[k] = skewness(log_rets[k : k+skew_window]) for k=0..n-1-skew_window
    skew_vals = np.array(
        [_skewness(log_rets[k : k + skew_window]) for k in range(len(log_rets) - skew_window + 1)],
        dtype=float,
    )
    z = _fixed_window_zscore_series(skew_vals, zscore_window)
    # result[skew_window + k] = z[k], prepend skew_window zeros for cold-start bars
    return np.concatenate([np.zeros(skew_window, dtype=float), z])


def _ret_acf1_z_series_full(closes: np.ndarray, acf_window: int, zscore_window: int) -> np.ndarray:
    """Rolling lag-1 autocorrelation z-score series. result[i] == streaming ret_acf1_z at bar i.
    O(n × acf_window) total. Returns zeros for i < acf_window (cold start).
    """
    n = len(closes)
    if n < acf_window + 2:
        return np.zeros(n, dtype=float)
    log_rets = np.diff(np.log(np.maximum(closes.astype(float), 1e-10)))
    acf_vals = np.array(
        [
            _pearson_acf1(log_rets[k : k + acf_window])
            for k in range(len(log_rets) - acf_window + 1)
        ],
        dtype=float,
    )
    z = _fixed_window_zscore_series(acf_vals, zscore_window)
    return np.concatenate([np.zeros(acf_window, dtype=float), z])


def _amihud_illiq_z_series_full(
    closes: np.ndarray, volumes: np.ndarray, zscore_window: int
) -> np.ndarray:
    """Amihud illiquidity z-score series. result[i] == streaming amihud_illiq_z at bar i.
    Prepends 0.0 at index 0 (cold start — streaming returns 0.0 when len(closes) < 2).
    """
    n = len(closes)
    if n < 2:
        return np.zeros(n, dtype=float)
    log_rets_abs = np.abs(np.diff(np.log(np.maximum(closes.astype(float), 1e-10))))
    dollar_vols = closes[1:].astype(float) * np.maximum(volumes[1:].astype(float), 1.0)
    illiq = log_rets_abs / dollar_vols
    z = _fixed_window_zscore_series(illiq, zscore_window)
    return np.concatenate([[0.0], z])


def _high_52w_dist_series_full(closes: np.ndarray, window: int) -> np.ndarray:
    """Distance from rolling-max series. result[i] == streaming high_52w_dist at bar i.
    O(n × window) — called once vs per-bar (not per-bar O(n^2) total).
    """
    n = len(closes)
    result = np.zeros(n, dtype=float)
    for b in range(1, n):
        w = min(window, b + 1)
        rolling_max = float(np.max(closes[b + 1 - w : b + 1]))
        if rolling_max >= 1e-10:
            result[b] = (float(closes[b]) - rolling_max) / rolling_max
    return result


def _vwap_dev_sigma_series_full(
    opens: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    volumes: np.ndarray,
) -> np.ndarray:
    """VWAP deviation in sigma series. result[i] == streaming vwap_dev_sigma at bar i.
    Uses running VWAP (cumsum) + running std (Welford via cumsums) — O(n) total.
    Parity tolerance 1e-6 due to cumulative floating-point accumulation vs np.std.
    """
    n = len(closes)
    result = np.zeros(n, dtype=float)
    if n < 2:
        return result
    typical = (highs.astype(float) + lows.astype(float) + closes.astype(float)) / 3.0
    cum_tp_vol = np.cumsum(typical * volumes.astype(float))
    cum_vol = np.cumsum(volumes.astype(float))
    vwap_arr = np.where(cum_vol > 1e-10, cum_tp_vol / cum_vol, typical)
    dev = closes.astype(float) - vwap_arr
    cum_dev = np.cumsum(dev)
    cum_dev_sq = np.cumsum(dev * dev)
    counts = np.arange(1, n + 1, dtype=float)
    mean_dev = cum_dev / counts
    var = np.maximum(cum_dev_sq / counts - mean_dev * mean_dev, 0.0)
    std_arr = np.sqrt(var)
    mask = std_arr > 1e-10
    result[mask] = (closes.astype(float)[mask] - vwap_arr[mask]) / std_arr[mask]
    return result


def _gap_z_series_full(
    opens: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    period: int,
    zscore_window: int,
) -> np.ndarray:
    """Gap-z series: ATR-normalized open gap, rolling z-scored."""
    n = len(closes)
    result = np.zeros(n, dtype=float)
    if n < 2:
        return result

    # ATR series (length = n-1)
    atr_core = _atr_series_full(highs, lows, closes, period)

    # For gap computation, we need ATR at position j to normalize gap[j+1]
    # gap[j+1] = (open[j+1] - close[j]) / ATR[j]
    # atr_core has length n-1, where atr_core[k] = ATR after bar index k+1
    # So atr_for_gap[k] = ATR for gap at position k+1
    atr_for_gap = atr_core[:-1] if len(atr_core) >= 2 else atr_core

    # Compute gap_raw: (open[i] - close[i-1]) / ATR[i-1]
    # opens[2:] corresponds to gap at positions 2..n-1
    # closes[1:-1] corresponds to close at positions 1..n-2
    if len(atr_for_gap) > 0 and len(opens) >= 2 and len(closes) >= 2:
        gap_high = min(len(opens) - 2, len(atr_for_gap))
        gap_raw = (opens[2 : 2 + gap_high] - closes[1 : 1 + gap_high]) / np.where(
            atr_for_gap[:gap_high] > 1e-10, atr_for_gap[:gap_high], 1.0
        )
        # Z-score the gap series
        gap_z_core = _rolling_zscore_series(np.concatenate([[0.0], gap_raw]), zscore_window)
        # Build result: position 0 = 0.0, position 1 = 0.0 (no prev close), then gap_z values
        result = np.zeros(n, dtype=float)
        if len(gap_z_core) > 2:
            result[2 : 2 + len(gap_z_core) - 2] = gap_z_core[2:]

    return result


def _rel_volume_series_full(volumes: np.ndarray, window: int) -> np.ndarray:
    """Relative volume series. result[i] == streaming rel_volume at bar i.
    Uses cumulative sum for O(n) rolling mean.
    """
    n = len(volumes)
    result = np.ones(n, dtype=float)
    cs = np.cumsum(volumes.astype(float))
    for b in range(n):
        eff_w = min(window, b + 1)
        start = b + 1 - eff_w
        total = cs[b] - (cs[start - 1] if start > 0 else 0.0)
        mean_v = total / eff_w
        result[b] = float(volumes[b]) / mean_v if mean_v > 1e-10 else 1.0
    return result


# ---------------------------------------------------------------------------
# Renaissance Primitives — Volume Structure batch series (Phase 142.5 Plan 02)
# result[i] matches the streaming per-bar helper above at bar i. O(n) except
# vol_percentile/vol_persistence which are O(n x window) (same cost class as
# the pre-existing ret_skew_z_series_full / ret_acf1_z_series_full).
# ---------------------------------------------------------------------------


def _vol_acceleration_series_full(volumes: np.ndarray, eps: float = 1e-10) -> np.ndarray:
    """result[i] == streaming _vol_acceleration at bar i. Index 0 padded with 1.0."""
    n = len(volumes)
    result = np.ones(n, dtype=float)
    if n < 2:
        return result
    v = volumes.astype(float)
    prev = v[:-1]
    curr = v[1:]
    safe_prev = np.where(prev > eps, prev, 1.0)
    result[1:] = np.where(prev > eps, curr / safe_prev, 1.0)
    return result


def _dollar_vol_z_series_full(volumes: np.ndarray, closes: np.ndarray, window: int) -> np.ndarray:
    """result[i] == streaming _dollar_vol_z at bar i."""
    dollar_vol = volumes.astype(float) * closes.astype(float)
    return _fixed_window_zscore_series(dollar_vol, window)


def _vol_range_ratio_series_full(
    volumes: np.ndarray, highs: np.ndarray, lows: np.ndarray, window: int, eps: float = 1e-10
) -> np.ndarray:
    """result[i] == streaming _vol_range_ratio at bar i. O(n) via cumsum."""
    n = len(volumes)
    result = np.zeros(n, dtype=float)
    if n < 1:
        return result
    ranges = highs.astype(float) - lows.astype(float)
    raw = np.where(ranges > eps, volumes.astype(float) / np.where(ranges > eps, ranges, 1.0), 0.0)
    cs = np.cumsum(raw)
    for i in range(n):
        w = min(window, i + 1)
        start = i + 1 - w
        s = cs[i] - (cs[start - 1] if start > 0 else 0.0)
        mean_raw = s / w
        result[i] = raw[i] / mean_raw if mean_raw > eps else 0.0
    return result


def _vol_trend_ratio_series_full(
    volumes: np.ndarray, fast_window: int, slow_window: int, eps: float = 1e-10
) -> np.ndarray:
    """result[i] == streaming _vol_trend_ratio at bar i. O(n) via cumsum."""
    n = len(volumes)
    result = np.ones(n, dtype=float)
    v = volumes.astype(float)
    cs = np.cumsum(v)
    for i in range(n):
        if i + 1 < slow_window:
            continue
        sum_f = cs[i] - (cs[i - fast_window] if i - fast_window >= 0 else 0.0)
        sum_s = cs[i] - (cs[i - slow_window] if i - slow_window >= 0 else 0.0)
        ma_f = sum_f / fast_window
        ma_s = sum_s / slow_window
        result[i] = ma_f / ma_s if ma_s > eps else 1.0
    return result


def _up_vol_ratio_series_full(
    volumes: np.ndarray,
    opens: np.ndarray,
    closes: np.ndarray,
    window: int,
    eps: float = 1e-10,
) -> np.ndarray:
    """result[i] == streaming _up_vol_ratio at bar i. O(n) via cumsum."""
    n = len(volumes)
    result = np.full(n, 0.5, dtype=float)
    v = volumes.astype(float)
    up_v = np.where(closes.astype(float) > opens.astype(float), v, 0.0)
    cs_total = np.cumsum(v)
    cs_up = np.cumsum(up_v)
    for i in range(n):
        w = min(window, i + 1)
        start = i + 1 - w
        total = cs_total[i] - (cs_total[start - 1] if start > 0 else 0.0)
        up = cs_up[i] - (cs_up[start - 1] if start > 0 else 0.0)
        if total > eps:
            result[i] = up / total
    return result


def _vol_percentile_series_full(volumes: np.ndarray, window: int) -> np.ndarray:
    """result[i] == streaming _vol_percentile at bar i. O(n x window)."""
    n = len(volumes)
    result = np.full(n, 0.5, dtype=float)
    if n < 2:
        return result
    vols = volumes.astype(float)
    for i in range(n):
        w = min(window, i + 1)
        if w < 2:
            continue
        hist = vols[i + 1 - w : i + 1]
        result[i] = _percentile_rank(hist, float(hist[-1]))
    return result


def _vol_persistence_series_full(volumes: np.ndarray, window: int) -> np.ndarray:
    """result[i] == streaming _vol_persistence at bar i. O(n x window)."""
    n = len(volumes)
    result = np.zeros(n, dtype=float)
    if n < 2:
        return result
    vols = volumes.astype(float)
    for i in range(n):
        w = min(window, i + 1)
        if w < 2:
            continue
        hist = vols[i + 1 - w : i + 1]
        result[i] = _pearson_acf1(hist)
    return result


def _vol_std_z_series_full(volumes: np.ndarray, window: int) -> np.ndarray:
    """result[i] == streaming _vol_std_z at bar i. O(n) total."""
    std_series = _rolling_std_series(volumes.astype(float), window)
    return _fixed_window_zscore_series(std_series, window)


def _mfi_series_full(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    volumes: np.ndarray,
    window: int,
    eps: float = 1e-10,
) -> np.ndarray:
    """result[i] == streaming _mfi at bar i. O(n) via cumsum (rising-flag is
    fixed per bar regardless of window; only the rolling sums need cumsum).
    """
    n = len(closes)
    result = np.full(n, 50.0, dtype=float)
    if n < 2:
        return result
    tp = (highs.astype(float) + lows.astype(float) + closes.astype(float)) / 3.0
    money_flow = tp * volumes.astype(float)
    rising = np.zeros(n, dtype=bool)
    rising[1:] = tp[1:] > tp[:-1]
    rising_flow = np.where(rising, money_flow, 0.0)
    cs_total = np.cumsum(money_flow)
    cs_rising = np.cumsum(rising_flow)
    for i in range(1, n):
        w = min(window, i)
        start = i - w + 1
        total = cs_total[i] - (cs_total[start - 1] if start > 0 else 0.0)
        rise = cs_rising[i] - (cs_rising[start - 1] if start > 0 else 0.0)
        if total > eps:
            result[i] = float(np.clip(100.0 * rise / total, 0.0, 100.0))
    return result


def _obv_z_series_full(closes: np.ndarray, volumes: np.ndarray, window: int) -> np.ndarray:
    """result[i] == streaming _obv_z at bar i. Index 0 padded with 0.0 (cold start)."""
    n = len(closes)
    if n < 2:
        return np.zeros(n, dtype=float)
    diffs = np.diff(closes.astype(float))
    signed_vol = np.where(
        diffs > 0,
        volumes[1:].astype(float),
        np.where(diffs < 0, -volumes[1:].astype(float), 0.0),
    )
    obv = np.cumsum(signed_vol)
    z = _fixed_window_zscore_series(obv, window)
    return np.concatenate([[0.0], z])


# ---------------------------------------------------------------------------
# Renaissance Primitives — Breakout Distance batch precompute (Phase 142.5 Plan 05)
#
# Rolling max/min via np.lib.stride_tricks.sliding_window_view: a single
# vectorized numpy call over the saturated region (no Python-level per-bar
# loop for the O(n x window) work), plus a small Python loop only for the
# initial `window - 1` expanding-window bars. Avoids the O(n x window)
# per-bar-call cost of invoking the streaming primitives directly in a loop.
# ---------------------------------------------------------------------------


def _sliding_rolling_max(arr: np.ndarray, window: int) -> np.ndarray:
    """result[i] == max(arr[max(0, i-window+1):i+1]) for every i. O(n) calls,
    vectorized over the saturated region via sliding_window_view."""
    n = len(arr)
    out = np.empty(n, dtype=float)
    if n == 0:
        return out
    expand_n = min(window - 1, n)
    for i in range(expand_n):
        out[i] = np.max(arr[: i + 1])
    if n >= window:
        windows = np.lib.stride_tricks.sliding_window_view(arr, window)
        out[window - 1 :] = np.max(windows, axis=1)
    return out


def _sliding_rolling_min(arr: np.ndarray, window: int) -> np.ndarray:
    """result[i] == min(arr[max(0, i-window+1):i+1]) for every i. O(n) calls,
    vectorized over the saturated region via sliding_window_view."""
    n = len(arr)
    out = np.empty(n, dtype=float)
    if n == 0:
        return out
    expand_n = min(window - 1, n)
    for i in range(expand_n):
        out[i] = np.min(arr[: i + 1])
    if n >= window:
        windows = np.lib.stride_tricks.sliding_window_view(arr, window)
        out[window - 1 :] = np.min(windows, axis=1)
    return out


def _dist_from_high_series_full(
    closes: np.ndarray, highs: np.ndarray, atr_padded: np.ndarray, window: int, eps: float = 1e-10
) -> np.ndarray:
    """result[i] == streaming _dist_from_high at bar i."""
    rolling_high = _sliding_rolling_max(highs, window)
    safe_atr = np.where(atr_padded > eps, atr_padded, 1.0)
    raw = (rolling_high - closes.astype(float)) / safe_atr
    return np.where(atr_padded > eps, raw, 0.0)


def _dist_from_low_series_full(
    closes: np.ndarray, lows: np.ndarray, atr_padded: np.ndarray, window: int, eps: float = 1e-10
) -> np.ndarray:
    """result[i] == streaming _dist_from_low at bar i."""
    rolling_low = _sliding_rolling_min(lows, window)
    safe_atr = np.where(atr_padded > eps, atr_padded, 1.0)
    raw = (closes.astype(float) - rolling_low) / safe_atr
    return np.where(atr_padded > eps, raw, 0.0)


def _range_pct_series_full(
    closes: np.ndarray, highs: np.ndarray, lows: np.ndarray, window: int, eps: float = 1e-10
) -> np.ndarray:
    """result[i] == streaming _range_pct at bar i."""
    rolling_high = _sliding_rolling_max(highs, window)
    rolling_low = _sliding_rolling_min(lows, window)
    c = closes.astype(float)
    safe_c = np.where(c > eps, c, 1.0)
    raw = (rolling_high - rolling_low) / safe_c
    return np.where(c > eps, raw, 0.0)


def _new_high_flag_series_full(
    closes: np.ndarray, highs: np.ndarray, window: int, eps: float = 1e-10
) -> np.ndarray:
    """result[i] == streaming _new_high_flag at bar i."""
    rolling_high = _sliding_rolling_max(highs, window)
    return np.where(closes.astype(float) >= rolling_high - eps, 1.0, 0.0)


def _new_low_flag_series_full(
    closes: np.ndarray, lows: np.ndarray, window: int, eps: float = 1e-10
) -> np.ndarray:
    """result[i] == streaming _new_low_flag at bar i."""
    rolling_low = _sliding_rolling_min(lows, window)
    return np.where(closes.astype(float) <= rolling_low + eps, 1.0, 0.0)


def _stoch_k_series_full(
    closes: np.ndarray, highs: np.ndarray, lows: np.ndarray, window: int, eps: float = 1e-10
) -> np.ndarray:
    """result[i] == streaming _stoch_k at bar i. 0.5 on degenerate range."""
    rolling_high = _sliding_rolling_max(highs, window)
    rolling_low = _sliding_rolling_min(lows, window)
    rng = rolling_high - rolling_low
    safe_rng = np.where(rng > eps, rng, 1.0)
    raw = (closes.astype(float) - rolling_low) / safe_rng
    return np.where(rng > eps, raw, 0.5)


def _price_percentile_series_full(closes: np.ndarray, window: int) -> np.ndarray:
    """result[i] == streaming _price_percentile at bar i. O(n x window)."""
    n = len(closes)
    result = np.full(n, 0.5, dtype=float)
    if n < 2:
        return result
    c = closes.astype(float)
    for i in range(n):
        w = min(window, i + 1)
        if w < 2:
            continue
        hist = c[i + 1 - w : i + 1]
        result[i] = _percentile_rank(hist, float(hist[-1]))
    return result


def _efficiency_ratio_series_full(
    closes: np.ndarray, window: int, eps: float = 1e-10
) -> np.ndarray:
    """result[i] == streaming _efficiency_ratio at bar i. O(n) via cumsum of |diffs|."""
    n = len(closes)
    result = np.zeros(n, dtype=float)
    if n < 2:
        return result
    c = closes.astype(float)
    diffs = np.abs(np.diff(c))
    cs_padded = np.concatenate([[0.0], np.cumsum(diffs)])  # cs_padded[i] = sum(|diffs[0:i]|)
    for i in range(n):
        w = min(window, i)
        if w < 1:
            continue
        start = i - w
        net = abs(c[i] - c[start])
        total = cs_padded[i] - cs_padded[start]
        result[i] = net / total if total > eps else 0.0
    return result


# ---------------------------------------------------------------------------
# Renaissance Primitives — Return Distribution batch precompute (Phase 142.5 Plan 03)
# result[i] matches the corresponding value function above at bar i.
# ---------------------------------------------------------------------------


def _ret_kurtosis_z_series_full(
    closes: np.ndarray, kurt_window: int, zscore_window: int
) -> np.ndarray:
    """Rolling return-kurtosis z-score series. result[i] == z-score of
    kurtosis(log_rets[i-kurt_window+1:i+1]) against a trailing zscore_window
    of kurtosis values. O(n x kurt_window) total — same cost class as the
    pre-existing _ret_skew_z_series_full. Returns zeros for i < kurt_window
    (cold start).
    """
    n = len(closes)
    if n < kurt_window + 3:
        return np.zeros(n, dtype=float)
    log_rets = np.diff(np.log(np.maximum(closes.astype(float), 1e-10)))
    kurt_vals = np.array(
        [_kurtosis(log_rets[k : k + kurt_window]) for k in range(len(log_rets) - kurt_window + 1)],
        dtype=float,
    )
    z = _fixed_window_zscore_series(kurt_vals, zscore_window)
    return np.concatenate([np.zeros(kurt_window, dtype=float), z])


def _ret_autocorr_series_full(closes: np.ndarray, lag: int) -> np.ndarray:
    """Expanding-window lag-k Pearson autocorrelation of log returns, computed
    over ALL available history up to each bar. result[i] == streaming
    _ret_autocorr(closes[:i+1], lag). O(n) total via incremental running sums
    (one new pair added per bar, no window to re-sum).
    """
    n = len(closes)
    result = np.zeros(n, dtype=float)
    if n < 2:
        return result
    log_rets = np.diff(np.log(np.maximum(closes.astype(float), 1e-10)))
    m = len(log_rets)
    if m < lag + 2:
        return result
    sum_x = sum_y = sum_x2 = sum_y2 = sum_xy = 0.0
    count = 0
    for j in range(m):
        if j >= lag:
            x = float(log_rets[j - lag])
            y = float(log_rets[j])
            sum_x += x
            sum_y += y
            sum_x2 += x * x
            sum_y2 += y * y
            sum_xy += x * y
            count += 1
        if count >= 2:
            mean_x = sum_x / count
            mean_y = sum_y / count
            var_x = sum_x2 / count - mean_x * mean_x
            var_y = sum_y2 / count - mean_y * mean_y
            denom = math.sqrt(max(var_x, 0.0) * max(var_y, 0.0))
            if denom > 1e-10:
                cov = sum_xy / count - mean_x * mean_y
                result[j + 1] = cov / denom
    return result


def _updown_ratio_series_full(closes: np.ndarray, window: int, eps: float = 1e-10) -> np.ndarray:
    """result[i] == streaming _updown_ratio over the trailing `window` returns
    ending at bar i. O(n) via cumulative up/down bar counts.
    """
    n = len(closes)
    result = np.ones(n, dtype=float)
    if n < 2:
        return result
    log_rets = np.diff(np.log(np.maximum(closes.astype(float), 1e-10)))
    up_flags = (log_rets > eps).astype(float)
    down_flags = (log_rets < -eps).astype(float)
    cs_up = np.concatenate([[0.0], np.cumsum(up_flags)])
    cs_down = np.concatenate([[0.0], np.cumsum(down_flags)])
    m = len(log_rets)
    for j in range(m):
        w = min(window, j + 1)
        start = j + 1 - w
        up_count = cs_up[j + 1] - cs_up[start]
        down_count = cs_down[j + 1] - cs_down[start]
        result[j + 1] = up_count / down_count if down_count > 0 else 1.0
    return result


def _streak_length_series_full(closes: np.ndarray) -> np.ndarray:
    """Full signed streak-length series. O(n) single forward pass (does NOT
    call _streak_length per bar — that would be O(n^2); this maintains the
    running streak incrementally instead). result[i] is the streak ending at
    bar i (i >= 1); index 0 padded with 0.0.
    """
    n = len(closes)
    result = np.zeros(n, dtype=float)
    if n < 2:
        return result
    log_rets = np.diff(np.log(np.maximum(closes.astype(float), 1e-10)))
    signs = np.sign(log_rets)
    current = 0.0
    for j in range(len(signs)):
        s = float(signs[j])
        if s == 0.0:
            current = 0.0
        elif current != 0.0 and math.copysign(1.0, current) == s:
            current += s
        else:
            current = s
        result[j + 1] = current
    return result


def _streak_z_series_full(closes: np.ndarray, streak_window: int) -> np.ndarray:
    """z-score of the signed streak-length series over a trailing window.
    result[i] == streaming streak_z at bar i.
    """
    streak_series = _streak_length_series_full(closes)
    return _fixed_window_zscore_series(streak_series, streak_window)


# ---------------------------------------------------------------------------
# Renaissance Primitives — Realized Variance / Volatility batch precompute
# (Phase 142.5 Plan 03)
# ---------------------------------------------------------------------------


def _realized_var_ratio_series_full(
    closes: np.ndarray, fast_window: int, slow_window: int
) -> np.ndarray:
    """result[i] == streaming _realized_var_ratio(closes[:i+1], fast_window,
    slow_window). O(n) via cumsum of returns and squared returns.
    """
    n = len(closes)
    result = np.ones(n, dtype=float)
    if n < 2:
        return result
    log_rets = np.diff(np.log(np.maximum(closes.astype(float), 1e-10)))
    m = len(log_rets)
    cs = np.cumsum(log_rets)
    cs2 = np.cumsum(log_rets * log_rets)
    for j in range(m):
        bar_idx = j + 1
        w_slow = min(slow_window, j + 1)
        w_fast = min(fast_window, j + 1)
        if w_slow < 2 or w_fast < 2:
            continue
        start_slow = j + 1 - w_slow
        s_slow = cs[j] - (cs[start_slow - 1] if start_slow > 0 else 0.0)
        s2_slow = cs2[j] - (cs2[start_slow - 1] if start_slow > 0 else 0.0)
        mean_slow = s_slow / w_slow
        var_slow = s2_slow / w_slow - mean_slow * mean_slow
        if var_slow < 1e-14:
            continue
        start_fast = j + 1 - w_fast
        s_fast = cs[j] - (cs[start_fast - 1] if start_fast > 0 else 0.0)
        s2_fast = cs2[j] - (cs2[start_fast - 1] if start_fast > 0 else 0.0)
        mean_fast = s_fast / w_fast
        var_fast = s2_fast / w_fast - mean_fast * mean_fast
        result[bar_idx] = var_fast / var_slow
    return result


def _range_to_close_series_full(
    highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, eps: float = 1e-10
) -> np.ndarray:
    """result[i] == streaming _range_to_close at bar i. Fully vectorized O(n)."""
    c = closes.astype(float)
    safe_c = np.where(c > eps, c, 1.0)
    raw = (highs.astype(float) - lows.astype(float)) / safe_c
    return np.where(c > eps, raw, 0.0)


def _true_range_pct_series_full(
    highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, eps: float = 1e-10
) -> np.ndarray:
    """result[i] == streaming _true_range_pct at bar i. Fully vectorized O(n).
    Index 0 padded with 0.0 (no prev close available).
    """
    n = len(closes)
    result = np.zeros(n, dtype=float)
    if n < 2:
        return result
    h = highs[1:].astype(float)
    lo = lows[1:].astype(float)
    prev_c = closes[:-1].astype(float)
    tr = np.maximum(h - lo, np.maximum(np.abs(h - prev_c), np.abs(lo - prev_c)))
    c = closes[1:].astype(float)
    safe_c = np.where(c > eps, c, 1.0)
    raw = np.where(c > eps, tr / safe_c, 0.0)
    result[1:] = raw
    return result


def _vol_of_vol_series_full(atr_z: np.ndarray, window: int) -> np.ndarray:
    """z-score of rolling std(atr_z) over `window` (single window used for
    both the std computation and the z-score, matching the vol_std_z
    double-duty convention). result[i] == streaming vol_of_vol at bar i.
    """
    std_series = _rolling_std_series(atr_z.astype(float), window)
    return _fixed_window_zscore_series(std_series, window)


def _high_low_corr_series_full(highs: np.ndarray, lows: np.ndarray, window: int) -> np.ndarray:
    """result[i] == streaming _correlation(H, L) over the trailing (expanding
    until saturated) `window` bars ending at bar i. O(n x window).
    """
    n = len(highs)
    result = np.zeros(n, dtype=float)
    h = highs.astype(float)
    lo = lows.astype(float)
    for i in range(n):
        w = min(window, i + 1)
        start = i + 1 - w
        result[i] = _correlation(h[start : i + 1], lo[start : i + 1])
    return result


def _variance_ratio_series_full(closes: np.ndarray, n_window: int) -> np.ndarray:
    """result[i] == streaming _variance_ratio(closes[:i+1], n_window). O(n)
    via prefix sums of the 1-period return series and its N-period
    overlapping aggregate (both expanding over ALL available history, no
    bounded rolling sample — matches the full-sample Lo-MacKinlay estimator).
    """
    total = len(closes)
    result = np.ones(total, dtype=float)
    if total < 2 or n_window < 1:
        return result
    log_rets = np.diff(np.log(np.maximum(closes.astype(float), 1e-10)))
    m = len(log_rets)
    if m < n_window + 1:
        return result
    cs1 = np.cumsum(log_rets)
    cs1_sq = np.cumsum(log_rets * log_rets)
    cs_pad = np.concatenate([[0.0], cs1])
    agg = cs_pad[n_window:] - cs_pad[:-n_window]  # length m - n_window + 1
    cs_agg = np.cumsum(agg)
    cs_agg_sq = np.cumsum(agg * agg)

    for j in range(m):
        cnt1 = j + 1
        if cnt1 < 2:
            continue
        mean1 = cs1[j] / cnt1
        var1 = cs1_sq[j] / cnt1 - mean1 * mean1
        if var1 < 1e-14:
            continue
        agg_upper = j - n_window + 1
        if agg_upper < 1:
            continue
        cnt_agg = agg_upper + 1
        mean_agg = cs_agg[agg_upper] / cnt_agg
        var_agg = cs_agg_sq[agg_upper] / cnt_agg - mean_agg * mean_agg
        result[j + 1] = var_agg / (n_window * var1)
    return result


def _vol_asymmetry_z_series_full(closes: np.ndarray, window: int) -> np.ndarray:
    """z-score of the up/down volatility-asymmetry ratio series over `window`
    (single window used for both the ratio computation and the z-score,
    matching the vol_std_z double-duty convention). O(n x window).
    """
    n = len(closes)
    if n < 2:
        return np.zeros(n, dtype=float)
    log_rets = np.diff(np.log(np.maximum(closes.astype(float), 1e-10)))
    m = len(log_rets)
    ratio_vals = np.ones(m, dtype=float)
    for j in range(m):
        w = min(window, j + 1)
        ratio_vals[j] = _vol_asymmetry_ratio(log_rets[j + 1 - w : j + 1])
    z = _fixed_window_zscore_series(ratio_vals, window)
    return np.concatenate([[0.0], z])


def _bb_pct_b_series_full(closes: np.ndarray, window: int, eps: float = 1e-10) -> np.ndarray:
    """result[i] == streaming _bb_pct_b over the trailing (expanding until
    saturated) `window` bars ending at bar i. O(n) via cumsum of price and
    squared price.
    """
    n = len(closes)
    result = np.full(n, 0.5, dtype=float)
    if n < 2:
        return result
    c = closes.astype(float)
    cs = np.cumsum(c)
    cs2 = np.cumsum(c * c)
    for i in range(n):
        w = min(window, i + 1)
        start = i + 1 - w
        s = cs[i] - (cs[start - 1] if start > 0 else 0.0)
        s2 = cs2[i] - (cs2[start - 1] if start > 0 else 0.0)
        mean = s / w
        var = max(s2 / w - mean * mean, 0.0)
        std = math.sqrt(var)
        if std < eps:
            continue
        upper = mean + 2.0 * std
        lower = mean - 2.0 * std
        result[i] = (c[i] - lower) / (upper - lower)
    return result


def _hv_z_series_full(closes: np.ndarray, window: int) -> np.ndarray:
    """z-score of rolling std(log returns) over `window` (single window used
    for both the HV computation and the z-score, matching the vol_std_z
    double-duty convention). result[i] == streaming hv_z at bar i.
    """
    n = len(closes)
    if n < 2:
        return np.zeros(n, dtype=float)
    log_rets = np.diff(np.log(np.maximum(closes.astype(float), 1e-10)))
    hv_series = _rolling_std_series(log_rets.astype(float), window)
    z = _fixed_window_zscore_series(hv_series, window)
    return np.concatenate([[0.0], z])


def _hv_ratio_series_full(
    closes: np.ndarray, hv_fast_window: int, ratio_window: int, eps: float = 1e-10
) -> np.ndarray:
    """hv_fast / rolling_mean(hv_fast series, ratio_window). result[i] ==
    streaming hv_ratio at bar i. O(n) via cumsum of the HV series.
    """
    n = len(closes)
    result = np.ones(n, dtype=float)
    if n < 2:
        return result
    log_rets = np.diff(np.log(np.maximum(closes.astype(float), 1e-10)))
    hv_series = _rolling_std_series(log_rets.astype(float), hv_fast_window)
    m = len(hv_series)
    cs = np.cumsum(hv_series)
    for j in range(m):
        w = min(ratio_window, j + 1)
        start = j + 1 - w
        s = cs[j] - (cs[start - 1] if start > 0 else 0.0)
        mean_hv = s / w
        result[j + 1] = hv_series[j] / mean_hv if mean_hv > eps else 1.0
    return result


# ---------------------------------------------------------------------------
# Renaissance Primitives — Alternative Volatility + Volatility Dynamics batch
# precompute (Phase 142.5 Plan 04)
# result[i] matches the corresponding streaming value function above at bar i.
# ---------------------------------------------------------------------------


def _parkinson_vol_z_series_full(
    highs: np.ndarray, lows: np.ndarray, window: int, zscore_window: int
) -> np.ndarray:
    """z-score of the rolling-averaged Parkinson variance proxy. `window`
    smooths the per-bar ln(H/L)^2/(4*ln(2)) term via a rolling mean;
    `zscore_window` normalizes the smoothed series against its own trailing
    history. Fully vectorized O(n) via boolean masking + cumsum.
    """
    n = len(highs)
    terms = np.zeros(n, dtype=float)
    h = highs.astype(float)
    lo = lows.astype(float)
    valid = (h > lo) & (lo > 1e-10)
    terms[valid] = (np.log(h[valid] / lo[valid]) ** 2) / (4.0 * math.log(2.0))
    smoothed = _rolling_mean_series(terms, window)
    return _fixed_window_zscore_series(smoothed, zscore_window)


def _garman_klass_vol_z_series_full(
    opens: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    window: int,
    zscore_window: int,
) -> np.ndarray:
    """z-score of the rolling-averaged Garman-Klass variance proxy. `window`
    smooths the per-bar GK term via a rolling mean; `zscore_window`
    normalizes the smoothed series. Fully vectorized O(n) via boolean
    masking + cumsum.
    """
    n = len(closes)
    terms = np.zeros(n, dtype=float)
    o = opens.astype(float)
    h = highs.astype(float)
    lo = lows.astype(float)
    c = closes.astype(float)
    valid = (h > lo) & (lo > 1e-10) & (o > 1e-10) & (c > 1e-10)
    hl_term = 0.5 * (np.log(h[valid] / lo[valid]) ** 2)
    co_term = (2.0 * math.log(2.0) - 1.0) * (np.log(c[valid] / o[valid]) ** 2)
    terms[valid] = hl_term - co_term
    smoothed = _rolling_mean_series(terms, window)
    return _fixed_window_zscore_series(smoothed, zscore_window)


def _yang_zhang_vol_z_series_full(
    opens: np.ndarray, closes: np.ndarray, window: int, zscore_window: int
) -> np.ndarray:
    """z-score of the rolling Yang-Zhang variance estimator (var(overnight) +
    k*var(open-to-close), k ~= 0.34, definitional). O(n x window) — same
    cost class as the pre-existing _high_low_corr_series_full/
    _vol_asymmetry_z_series_full nested-window loops.
    """
    n = len(closes)
    if n < 2:
        return np.zeros(n, dtype=float)
    o = opens.astype(float)
    c = closes.astype(float)
    prev_c = np.concatenate([[c[0]], c[:-1]])  # prev_close[0] undefined -> neutral (zero gap)
    overnight = np.log(np.maximum(o, 1e-10) / np.maximum(prev_c, 1e-10))
    o2c = np.log(np.maximum(c, 1e-10) / np.maximum(o, 1e-10))
    k = 0.34
    yz = np.zeros(n, dtype=float)
    for i in range(n):
        w = min(window, i + 1)
        if w < 2:
            continue
        start = i + 1 - w
        var_overnight = float(np.var(overnight[start : i + 1]))
        var_o2c = float(np.var(o2c[start : i + 1]))
        yz[i] = var_overnight + k * var_o2c
    return _fixed_window_zscore_series(yz, zscore_window)


def _vol_velocity_z_series_full(atr_z: np.ndarray, window: int) -> np.ndarray:
    """z-score of the rolling velocity (first difference) of atr_z over
    `window`. result[i] == streaming vol_velocity_z at bar i. Fully
    vectorized O(n).
    """
    n = len(atr_z)
    if n < 2:
        return np.zeros(n, dtype=float)
    velocity = np.diff(atr_z.astype(float))
    padded = np.concatenate([[0.0], velocity])
    return _fixed_window_zscore_series(padded, window)


def _intraday_noise_ratio_series_full(
    closes: np.ndarray, session_bars: int, eps: float = 1e-10
) -> np.ndarray:
    """result[i] == streaming _intraday_noise_ratio(closes[:i+1], session_bars)
    at bar i. O(n) via cumsum of |log_ret| and log_ret over a fixed
    `session_bars` window. Stays 0.0 until i >= session_bars (matches the
    streaming function's insufficient-history guard).
    """
    n = len(closes)
    result = np.zeros(n, dtype=float)
    if n < session_bars + 1:
        return result
    log_rets = np.diff(np.log(np.maximum(closes.astype(float), 1e-10)))
    cs_abs = np.concatenate([[0.0], np.cumsum(np.abs(log_rets))])
    cs_net = np.concatenate([[0.0], np.cumsum(log_rets)])
    for idx in range(session_bars, n):
        start = idx - session_bars
        sum_abs = cs_abs[idx] - cs_abs[start]
        net = cs_net[idx] - cs_net[start]
        result[idx] = sum_abs / abs(net) if abs(net) > eps else 1.0
    return result


# ---------------------------------------------------------------------------
# Calendar helpers (shared by compute() and compute_batch())
# ---------------------------------------------------------------------------


def _quarter_position(bar_ts: datetime) -> float:
    """Position within the quarter: 0.0 at quarter start, approaching 1.0 at end.

    Formula: (month_in_quarter * 30 + day) / QUARTER_LENGTH_DAYS
    """
    month_in_q = (bar_ts.month - 1) % 3
    day_in_q = month_in_q * 30 + bar_ts.day
    return min(1.0, day_in_q / _QUARTER_LENGTH_DAYS)


def _days_to_month_end_fraction(bar_ts: datetime) -> float:
    """Fraction of month remaining: 0.0 at month end, approaching 1.0 at start."""
    days_in_month = calendar.monthrange(bar_ts.year, bar_ts.month)[1]
    days_remaining = days_in_month - bar_ts.day
    return days_remaining / days_in_month


# ---------------------------------------------------------------------------
# _PrecomputedSeries — bundled series arrays for a bar window
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class _PrecomputedSeries:
    """All series arrays precomputed from a bar window. Each has length == len(bars)
    except atr_raw which has length len(bars)-1 (ATR needs prev close)."""

    atr_raw: np.ndarray  # raw ATR series, length n-1
    atr_z: np.ndarray  # ATR z-score padded to length n
    gap_z: np.ndarray
    rel_volume: np.ndarray
    ofi_z: np.ndarray
    cvd_slope_z: np.ndarray
    volume_z: np.ndarray
    momentum_z_fast: np.ndarray
    momentum_z_mid: np.ndarray
    momentum_z_slow: np.ndarray
    momentum_reversal_z: np.ndarray
    vwap_dev_sigma: np.ndarray
    rsi_fast: np.ndarray
    rsi_mid: np.ndarray
    rsi_slow: np.ndarray
    amihud_illiq_z: np.ndarray
    high_52w_dist: np.ndarray
    ret_skew_z: np.ndarray
    ret_acf1_z: np.ndarray
    overnight_gap_z: np.ndarray  # Renaissance Primitives (Phase 142.5 Plan 01)
    # Renaissance Primitives — Volume Structure (Phase 142.5 Plan 02)
    vol_acceleration: np.ndarray
    dollar_vol_z: np.ndarray
    vol_range_ratio: np.ndarray
    vol_trend_ratio: np.ndarray
    up_vol_ratio_fast: np.ndarray
    up_vol_ratio_slow: np.ndarray
    vol_percentile: np.ndarray
    vol_persistence: np.ndarray
    vol_std_z: np.ndarray
    mfi_fast: np.ndarray
    mfi_slow: np.ndarray
    obv_z: np.ndarray
    # Renaissance Primitives — Breakout Distance (Phase 142.5 Plan 05)
    dist_from_high_fast: np.ndarray
    dist_from_high_slow: np.ndarray
    dist_from_low_fast: np.ndarray
    dist_from_low_slow: np.ndarray
    range_pct_fast: np.ndarray
    range_pct_slow: np.ndarray
    new_high_flag: np.ndarray
    new_low_flag: np.ndarray
    stoch_k_fast: np.ndarray
    stoch_k_slow: np.ndarray
    price_percentile_fast: np.ndarray
    price_percentile_slow: np.ndarray
    efficiency_ratio_fast: np.ndarray
    efficiency_ratio_slow: np.ndarray
    # Renaissance Primitives — Return Distribution (Phase 142.5 Plan 03)
    ret_kurtosis_z_fast: np.ndarray
    ret_kurtosis_z_slow: np.ndarray
    ret_autocorr_1: np.ndarray
    ret_autocorr_5: np.ndarray
    updown_ratio_fast: np.ndarray
    updown_ratio_slow: np.ndarray
    streak_z: np.ndarray
    # Renaissance Primitives — Realized Variance / Volatility (Phase 142.5 Plan 03)
    realized_var_ratio_fast: np.ndarray
    realized_var_ratio_slow: np.ndarray
    range_to_close: np.ndarray
    true_range_pct: np.ndarray
    vol_of_vol: np.ndarray
    high_low_corr: np.ndarray
    variance_ratio_fast: np.ndarray
    variance_ratio_slow: np.ndarray
    vol_asymmetry_z: np.ndarray
    bb_pct_b_fast: np.ndarray
    bb_pct_b_slow: np.ndarray
    hv_z_fast: np.ndarray
    hv_z_slow: np.ndarray
    hv_ratio: np.ndarray
    # Renaissance Primitives — Alternative Volatility / Volatility Dynamics (Phase 142.5 Plan 04)
    parkinson_vol_z: np.ndarray
    garman_klass_vol_z: np.ndarray
    yang_zhang_vol_z: np.ndarray
    vol_velocity_z: np.ndarray
    intraday_noise_ratio: np.ndarray


def _precompute_series(
    opens: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    volumes: np.ndarray,
    config: FeatureFactoryConfig,
) -> _PrecomputedSeries:
    """Call every _*_series_full helper once and bundle results.

    Both compute() and compute_batch() delegate here so the series calls
    are never duplicated.
    """
    atr_raw = _atr_series_full(highs, lows, closes, config.adx_period)
    atr_padded = np.concatenate([[0.0], atr_raw])
    atr_z = _rolling_zscore_series(atr_padded, config.momentum_zscore_window)

    return _PrecomputedSeries(
        atr_raw=atr_raw,
        atr_z=atr_z,
        gap_z=_gap_z_series_full(
            opens, highs, lows, closes, config.adx_period, config.momentum_zscore_window
        ),
        rel_volume=_rel_volume_series_full(volumes, config.volume_zscore_window),
        ofi_z=_ofi_z_series_full(closes, highs, lows, volumes, config.ofi_zscore_window),
        cvd_slope_z=_cvd_slope_z_series_full(
            closes, highs, lows, volumes, config.cvd_slope_bars, config.ofi_zscore_window
        ),
        volume_z=_volume_z_series_full(volumes, config.volume_zscore_window),
        momentum_z_fast=_momentum_z_series_full(
            closes, config.momentum_window_fast, config.momentum_zscore_window
        ),
        momentum_z_mid=_momentum_z_series_full(
            closes, config.momentum_window_mid, config.momentum_zscore_window
        ),
        momentum_z_slow=_momentum_z_series_full(
            closes, config.momentum_window_slow, config.momentum_zscore_window
        ),
        momentum_reversal_z=_momentum_reversal_z_series_full(closes, config.momentum_zscore_window),
        vwap_dev_sigma=_vwap_dev_sigma_series_full(opens, highs, lows, closes, volumes),
        rsi_fast=_rsi_series_full(closes, config.rsi_fast_period),
        rsi_mid=_rsi_series_full(closes, config.rsi_mid_period),
        rsi_slow=_rsi_series_full(closes, config.rsi_slow_period),
        amihud_illiq_z=_amihud_illiq_z_series_full(closes, volumes, config.amihud_zscore_window),
        high_52w_dist=_high_52w_dist_series_full(closes, config.high_52w_window),
        ret_skew_z=_ret_skew_z_series_full(
            closes, config.ret_skew_window, config.ret_skew_zscore_window
        ),
        ret_acf1_z=_ret_acf1_z_series_full(
            closes, config.ret_acf_window, config.ret_acf_zscore_window
        ),
        overnight_gap_z=_overnight_gap_z_series_full(opens, closes, config.overnight_gap_window),
        vol_acceleration=_vol_acceleration_series_full(volumes),
        dollar_vol_z=_dollar_vol_z_series_full(volumes, closes, config.dollar_vol_window),
        vol_range_ratio=_vol_range_ratio_series_full(
            volumes, highs, lows, config.vol_range_ratio_window
        ),
        vol_trend_ratio=_vol_trend_ratio_series_full(
            volumes, config.vol_trend_fast, config.vol_trend_slow
        ),
        up_vol_ratio_fast=_up_vol_ratio_series_full(
            volumes, opens, closes, config.up_vol_ratio_fast
        ),
        up_vol_ratio_slow=_up_vol_ratio_series_full(
            volumes, opens, closes, config.up_vol_ratio_slow
        ),
        vol_percentile=_vol_percentile_series_full(volumes, config.vol_percentile_window),
        vol_persistence=_vol_persistence_series_full(volumes, config.vol_persistence_window),
        vol_std_z=_vol_std_z_series_full(volumes, config.vol_std_window),
        mfi_fast=_mfi_series_full(highs, lows, closes, volumes, config.mfi_fast),
        mfi_slow=_mfi_series_full(highs, lows, closes, volumes, config.mfi_slow),
        obv_z=_obv_z_series_full(closes, volumes, config.obv_window),
        dist_from_high_fast=_dist_from_high_series_full(
            closes, highs, atr_padded, config.dist_window_fast
        ),
        dist_from_high_slow=_dist_from_high_series_full(
            closes, highs, atr_padded, config.dist_window_slow
        ),
        dist_from_low_fast=_dist_from_low_series_full(
            closes, lows, atr_padded, config.dist_window_fast
        ),
        dist_from_low_slow=_dist_from_low_series_full(
            closes, lows, atr_padded, config.dist_window_slow
        ),
        range_pct_fast=_range_pct_series_full(closes, highs, lows, config.range_window_fast),
        range_pct_slow=_range_pct_series_full(closes, highs, lows, config.range_window_slow),
        new_high_flag=_new_high_flag_series_full(closes, highs, config.dist_window_fast),
        new_low_flag=_new_low_flag_series_full(closes, lows, config.dist_window_fast),
        stoch_k_fast=_stoch_k_series_full(closes, highs, lows, config.stoch_window_fast),
        stoch_k_slow=_stoch_k_series_full(closes, highs, lows, config.stoch_window_slow),
        price_percentile_fast=_price_percentile_series_full(closes, config.percentile_window_fast),
        price_percentile_slow=_price_percentile_series_full(closes, config.percentile_window_slow),
        efficiency_ratio_fast=_efficiency_ratio_series_full(closes, config.efficiency_window_fast),
        efficiency_ratio_slow=_efficiency_ratio_series_full(closes, config.efficiency_window_slow),
        ret_kurtosis_z_fast=_ret_kurtosis_z_series_full(
            closes, config.ret_kurtosis_fast, config.ret_kurtosis_zscore_window
        ),
        ret_kurtosis_z_slow=_ret_kurtosis_z_series_full(
            closes, config.ret_kurtosis_slow, config.ret_kurtosis_zscore_window
        ),
        ret_autocorr_1=_ret_autocorr_series_full(closes, 1),
        ret_autocorr_5=_ret_autocorr_series_full(closes, 5),
        updown_ratio_fast=_updown_ratio_series_full(closes, config.updown_ratio_fast),
        updown_ratio_slow=_updown_ratio_series_full(closes, config.updown_ratio_slow),
        streak_z=_streak_z_series_full(closes, config.streak_window),
        realized_var_ratio_fast=_realized_var_ratio_series_full(
            closes, config.realized_var_fast, config.realized_var_slow
        ),
        realized_var_ratio_slow=_realized_var_ratio_series_full(
            closes, config.realized_var_fast, config.realized_var_slow
        ),
        range_to_close=_range_to_close_series_full(highs, lows, closes),
        true_range_pct=_true_range_pct_series_full(highs, lows, closes),
        vol_of_vol=_vol_of_vol_series_full(atr_z, config.vol_of_vol_window),
        high_low_corr=_high_low_corr_series_full(highs, lows, config.high_low_corr_window),
        variance_ratio_fast=_variance_ratio_series_full(closes, config.variance_ratio_fast),
        variance_ratio_slow=_variance_ratio_series_full(closes, config.variance_ratio_slow),
        vol_asymmetry_z=_vol_asymmetry_z_series_full(closes, config.vol_asymmetry_window),
        bb_pct_b_fast=_bb_pct_b_series_full(closes, config.bb_pct_b_fast),
        bb_pct_b_slow=_bb_pct_b_series_full(closes, config.bb_pct_b_slow),
        hv_z_fast=_hv_z_series_full(closes, config.hv_fast),
        hv_z_slow=_hv_z_series_full(closes, config.hv_slow),
        hv_ratio=_hv_ratio_series_full(closes, config.hv_fast, config.hv_ratio_window),
        parkinson_vol_z=_parkinson_vol_z_series_full(
            highs, lows, config.parkinson_vol_window, config.parkinson_vol_zscore_window
        ),
        garman_klass_vol_z=_garman_klass_vol_z_series_full(
            opens,
            highs,
            lows,
            closes,
            config.garman_klass_vol_window,
            config.garman_klass_vol_zscore_window,
        ),
        yang_zhang_vol_z=_yang_zhang_vol_z_series_full(
            opens, closes, config.yang_zhang_vol_window, config.yang_zhang_vol_zscore_window
        ),
        vol_velocity_z=_vol_velocity_z_series_full(atr_z, config.vol_velocity_window),
        intraday_noise_ratio=_intraday_noise_ratio_series_full(
            closes, config.intraday_noise_window
        ),
    )


def _guard(v: float | None, fallback: float = 0.0) -> float | None:
    """Replace non-finite floats with fallback. Pass None through unchanged."""
    if v is None:
        return None
    return v if math.isfinite(v) else fallback


def _series_last(arr: np.ndarray, fallback: float) -> float:
    """Safely extract the last element of a series array with fallback."""
    return float(arr[-1]) if len(arr) > 0 else fallback


def _build_feature_vector(
    *,
    momentum_z_fast: float,
    momentum_z_mid: float,
    range_position: float,
    bar_close_pos: float,
    gap_z: float,
    momentum_z_slow: float,
    momentum_reversal_z: float,
    informed_flow: float,
    volume_z: float,
    ofi_z: float,
    ofi_div: float,
    cvd_slope_z: float,
    cmf: float,
    rel_volume: float,
    vwap_dev_sigma: float,
    atr_z: float,
    vol_ratio: float,
    poc_dist_atr: float | None,
    va_position: float | None,
    sr_support_dist: float | None,
    sr_resist_dist: float | None,
    hmm_regime_prob: float,
    hmm_entropy: float,
    hmm_duration: float,
    hurst: float,
    shannon: float,
    garch_ratio: float,
    hma_slope_z: float,
    adx: float,
    aroon_fast: float,
    aroon_slow: float,
    rsi_fast: float,
    rsi_mid: float,
    rsi_slow: float,
    cci_fast: float,
    cci_mid: float,
    cci_slow: float,
    vix_z: float,
    flight_quality: float,
    yield_slope_z: float,
    in_ny_session: float,
    in_london_kz: float,
    in_overlap: float,
    power_hour: float,
    opening_range: float,
    above_wk_vwap: float,
    dow_sin: float,
    dow_cos: float,
    month_position: float,
    quarter_position: float,
    days_to_month_end: float,
    ctf_momentum: float,
    ctf_vwap_align: float,
    ctf_regime_align: float,
    amihud_illiq_z: float,
    high_52w_dist: float,
    ret_skew_z: float,
    ret_acf1_z: float,
    body_ratio: float,
    upper_wick_ratio: float,
    lower_wick_ratio: float,
    range_vs_atr: float,
    close_vs_open_direction: float,
    overnight_gap: float,
    overnight_gap_z: float,
    range_efficiency: float,
    ret_lag_1: float,
    ret_lag_2: float,
    ret_lag_3: float,
    ret_lag_fast: float,
    ret_lag_mid: float,
    ret_lag_slow: float,
    open_ret: float,
    intraday_ret: float,
    open_vs_intraday: float,
    session_time_pos: float,
    hour_of_day_sin: float,
    hour_of_day_cos: float,
    week_of_month_sin: float,
    week_of_month_cos: float,
    day_of_month_sin: float,
    day_of_month_cos: float,
    week_of_year_sin: float,
    week_of_year_cos: float,
    month_sin: float,
    month_cos: float,
    vol_acceleration: float,
    dollar_vol_z: float,
    vol_range_ratio: float,
    vol_trend_ratio: float,
    up_vol_ratio_fast: float,
    up_vol_ratio_slow: float,
    vol_percentile: float,
    vol_persistence: float,
    vol_std_z: float,
    mfi_fast: float,
    mfi_slow: float,
    obv_z: float,
    dist_from_high_fast: float,
    dist_from_high_slow: float,
    dist_from_low_fast: float,
    dist_from_low_slow: float,
    range_pct_fast: float,
    range_pct_slow: float,
    new_high_flag: float,
    new_low_flag: float,
    stoch_k_fast: float,
    stoch_k_slow: float,
    price_percentile_fast: float,
    price_percentile_slow: float,
    efficiency_ratio_fast: float,
    efficiency_ratio_slow: float,
    ret_kurtosis_z_fast: float,
    ret_kurtosis_z_slow: float,
    ret_autocorr_1: float,
    ret_autocorr_5: float,
    updown_ratio_fast: float,
    updown_ratio_slow: float,
    streak_z: float,
    realized_var_ratio_fast: float,
    realized_var_ratio_slow: float,
    range_to_close: float,
    true_range_pct: float,
    vol_of_vol: float,
    high_low_corr: float,
    variance_ratio_fast: float,
    variance_ratio_slow: float,
    vol_asymmetry_z: float,
    bb_pct_b_fast: float,
    bb_pct_b_slow: float,
    hv_z_fast: float,
    hv_z_slow: float,
    hv_ratio: float,
    parkinson_vol_z: float,
    garman_klass_vol_z: float,
    yang_zhang_vol_z: float,
    parkinson_vol_velocity: float,
    garman_klass_vol_velocity: float,
    yang_zhang_vol_velocity: float,
    vol_velocity_z: float,
    intraday_noise_ratio: float,
) -> FeatureVector:
    return FeatureVector(
        momentum_z_fast=_guard(momentum_z_fast),
        momentum_z_mid=_guard(momentum_z_mid),
        range_position=_guard(range_position, 0.5),
        bar_close_pos=_guard(bar_close_pos, 0.5),
        gap_z=_guard(gap_z),
        momentum_z_slow=_guard(momentum_z_slow),
        momentum_reversal_z=_guard(momentum_reversal_z),
        informed_flow=_guard(informed_flow),
        volume_z=_guard(volume_z),
        ofi_z=_guard(ofi_z),
        ofi_div=_guard(ofi_div),
        cvd_slope_z=_guard(cvd_slope_z),
        cmf=_guard(cmf),
        rel_volume=_guard(rel_volume, 1.0),
        vwap_dev_sigma=_guard(vwap_dev_sigma),
        atr_z=_guard(atr_z),
        vol_ratio=_guard(vol_ratio, 1.0),
        poc_dist_atr=_guard(poc_dist_atr),
        va_position=_guard(va_position, 0.5),
        sr_support_dist=_guard(sr_support_dist),
        sr_resist_dist=_guard(sr_resist_dist),
        hmm_regime_prob=_guard(hmm_regime_prob),
        hmm_entropy=_guard(hmm_entropy),
        hmm_duration=_guard(hmm_duration),
        hurst=_guard(hurst, 0.5),
        shannon=_guard(shannon, 1.0),
        garch_ratio=_guard(garch_ratio, 1.0),
        hma_slope_z=_guard(hma_slope_z),
        adx=_guard(adx),
        aroon_fast=_guard(aroon_fast),
        aroon_slow=_guard(aroon_slow),
        rsi_fast=_guard(rsi_fast, 50.0),
        rsi_mid=_guard(rsi_mid, 50.0),
        rsi_slow=_guard(rsi_slow, 50.0),
        cci_fast=_guard(cci_fast),
        cci_mid=_guard(cci_mid),
        cci_slow=_guard(cci_slow),
        vix_z=_guard(vix_z),
        flight_quality=_guard(flight_quality),
        yield_slope_z=_guard(yield_slope_z),
        in_ny_session=in_ny_session,
        in_london_kz=in_london_kz,
        in_overlap=in_overlap,
        power_hour=power_hour,
        opening_range=opening_range,
        above_wk_vwap=above_wk_vwap,
        dow_sin=dow_sin,
        dow_cos=dow_cos,
        month_position=month_position,
        quarter_position=_guard(quarter_position, 0.0),
        days_to_month_end=_guard(days_to_month_end, 0.0),
        ctf_momentum=_guard(ctf_momentum),
        ctf_vwap_align=_guard(ctf_vwap_align),
        ctf_regime_align=_guard(ctf_regime_align),
        amihud_illiq_z=_guard(amihud_illiq_z),
        high_52w_dist=_guard(high_52w_dist),
        ret_skew_z=_guard(ret_skew_z),
        ret_acf1_z=_guard(ret_acf1_z),
        body_ratio=_guard(body_ratio, 0.0),
        upper_wick_ratio=_guard(upper_wick_ratio, 0.5),
        lower_wick_ratio=_guard(lower_wick_ratio, 0.5),
        range_vs_atr=_guard(range_vs_atr, 0.0),
        close_vs_open_direction=close_vs_open_direction,
        overnight_gap=_guard(overnight_gap, 0.0),
        overnight_gap_z=_guard(overnight_gap_z, 0.0),
        range_efficiency=_guard(range_efficiency, 0.0),
        ret_lag_1=_guard(ret_lag_1, 0.0),
        ret_lag_2=_guard(ret_lag_2, 0.0),
        ret_lag_3=_guard(ret_lag_3, 0.0),
        ret_lag_fast=_guard(ret_lag_fast, 0.0),
        ret_lag_mid=_guard(ret_lag_mid, 0.0),
        ret_lag_slow=_guard(ret_lag_slow, 0.0),
        open_ret=_guard(open_ret, 0.0),
        intraday_ret=_guard(intraday_ret, 0.0),
        open_vs_intraday=_guard(open_vs_intraday, 0.0),
        session_time_pos=session_time_pos,
        hour_of_day_sin=hour_of_day_sin,
        hour_of_day_cos=hour_of_day_cos,
        week_of_month_sin=week_of_month_sin,
        week_of_month_cos=week_of_month_cos,
        day_of_month_sin=day_of_month_sin,
        day_of_month_cos=day_of_month_cos,
        week_of_year_sin=week_of_year_sin,
        week_of_year_cos=week_of_year_cos,
        month_sin=month_sin,
        month_cos=month_cos,
        vol_acceleration=_guard(vol_acceleration, 1.0),
        dollar_vol_z=_guard(dollar_vol_z, 0.0),
        vol_range_ratio=_guard(vol_range_ratio, 0.0),
        vol_trend_ratio=_guard(vol_trend_ratio, 1.0),
        up_vol_ratio_fast=_guard(up_vol_ratio_fast, 0.5),
        up_vol_ratio_slow=_guard(up_vol_ratio_slow, 0.5),
        vol_percentile=_guard(vol_percentile, 0.5),
        vol_persistence=_guard(vol_persistence, 0.0),
        vol_std_z=_guard(vol_std_z, 0.0),
        mfi_fast=_guard(mfi_fast, 50.0),
        mfi_slow=_guard(mfi_slow, 50.0),
        obv_z=_guard(obv_z, 0.0),
        dist_from_high_fast=_guard(dist_from_high_fast, 0.0),
        dist_from_high_slow=_guard(dist_from_high_slow, 0.0),
        dist_from_low_fast=_guard(dist_from_low_fast, 0.0),
        dist_from_low_slow=_guard(dist_from_low_slow, 0.0),
        range_pct_fast=_guard(range_pct_fast, 0.0),
        range_pct_slow=_guard(range_pct_slow, 0.0),
        new_high_flag=_guard(new_high_flag, 0.0),
        new_low_flag=_guard(new_low_flag, 0.0),
        stoch_k_fast=_guard(stoch_k_fast, 0.5),
        stoch_k_slow=_guard(stoch_k_slow, 0.5),
        price_percentile_fast=_guard(price_percentile_fast, 0.5),
        price_percentile_slow=_guard(price_percentile_slow, 0.5),
        efficiency_ratio_fast=_guard(efficiency_ratio_fast, 0.0),
        efficiency_ratio_slow=_guard(efficiency_ratio_slow, 0.0),
        ret_kurtosis_z_fast=_guard(ret_kurtosis_z_fast, 0.0),
        ret_kurtosis_z_slow=_guard(ret_kurtosis_z_slow, 0.0),
        ret_autocorr_1=_guard(ret_autocorr_1, 0.0),
        ret_autocorr_5=_guard(ret_autocorr_5, 0.0),
        updown_ratio_fast=_guard(updown_ratio_fast, 1.0),
        updown_ratio_slow=_guard(updown_ratio_slow, 1.0),
        streak_z=_guard(streak_z, 0.0),
        realized_var_ratio_fast=_guard(realized_var_ratio_fast, 1.0),
        realized_var_ratio_slow=_guard(realized_var_ratio_slow, 1.0),
        range_to_close=_guard(range_to_close, 0.0),
        true_range_pct=_guard(true_range_pct, 0.0),
        vol_of_vol=_guard(vol_of_vol, 0.0),
        high_low_corr=_guard(high_low_corr, 0.0),
        variance_ratio_fast=_guard(variance_ratio_fast, 1.0),
        variance_ratio_slow=_guard(variance_ratio_slow, 1.0),
        vol_asymmetry_z=_guard(vol_asymmetry_z, 0.0),
        bb_pct_b_fast=_guard(bb_pct_b_fast, 0.5),
        bb_pct_b_slow=_guard(bb_pct_b_slow, 0.5),
        hv_z_fast=_guard(hv_z_fast, 0.0),
        hv_z_slow=_guard(hv_z_slow, 0.0),
        hv_ratio=_guard(hv_ratio, 1.0),
        parkinson_vol_z=_guard(parkinson_vol_z, 0.0),
        garman_klass_vol_z=_guard(garman_klass_vol_z, 0.0),
        yang_zhang_vol_z=_guard(yang_zhang_vol_z, 0.0),
        parkinson_vol_velocity=_guard(parkinson_vol_velocity, 0.0),
        garman_klass_vol_velocity=_guard(garman_klass_vol_velocity, 0.0),
        yang_zhang_vol_velocity=_guard(yang_zhang_vol_velocity, 0.0),
        vol_velocity_z=_guard(vol_velocity_z, 0.0),
        intraday_noise_ratio=_guard(intraday_noise_ratio, 1.0),
        momentum_rank_z=None,
        volume_rank_z=None,
        volatility_rank_z=None,
    )


# ---------------------------------------------------------------------------
# FeatureFactory — stateless pure-function class
# ---------------------------------------------------------------------------


class FeatureFactory:
    """Pure-function feature library. Stateless: no constructor, no stored config.

    The only public API is compute(). All bar-level rolling computations are
    performed directly from the `bars` array (the full history provided by the
    caller), making compute() deterministic for identical inputs with no
    external accumulator state. Regime/session/CTF state lives in FeatureCache.
    """

    @staticmethod
    def compute(
        bars: list[dict],
        symbol: str,
        tf: str,
        cache: FeatureCache,
        config: FeatureFactoryConfig,
    ) -> FeatureVector:
        """Compute all 54 FeatureVector primitives from bars + cache + config.

        PURE FUNCTION: no IO, no ConfigService.get(), no DB reads, no Kafka.
        All tunable numerics come from the config argument (SC-9).
        Cold-start (insufficient history) yields 0.0 for continuous features.
        Deterministic: identical (bars, symbol, tf, cache, config) -> identical output.

        Parameters
        ----------
        bars: Full bar history (list of OHLCV dicts with 'open','high','low',
              'close','volume','ts' keys). Must have at least 2 entries.
        symbol: Instrument symbol (e.g. 'SPY'). Used only for type annotation.
        tf: Timeframe string (e.g. '1m', '5m', '1d').
        cache: Mutable FeatureCache holding regime/session/CTF state.
        config: Frozen FeatureFactoryConfig with all APR-backed parameters.

        Returns
        -------
        FeatureVector with all 54 fields set to finite floats.
        """
        if len(bars) < 2:
            return _cold_start_vector(cache, tf)

        opens = np.array([b["open"] for b in bars], dtype=float)
        highs = np.array([b["high"] for b in bars], dtype=float)
        lows = np.array([b["low"] for b in bars], dtype=float)
        closes = np.array([b["close"] for b in bars], dtype=float)
        volumes = np.array([b["volume"] for b in bars], dtype=float)

        last = bars[-1]
        open_ = float(last["open"])
        high_ = float(last["high"])
        low_ = float(last["low"])
        close_ = float(last["close"])
        bar_ts = last["ts"]
        if isinstance(bar_ts, datetime) and bar_ts.tzinfo is None:
            bar_ts = bar_ts.replace(tzinfo=UTC)

        s = _precompute_series(opens, highs, lows, closes, volumes, config)

        atr_val = float(s.atr_raw[-1]) if len(s.atr_raw) > 0 else 0.0

        range_bars = min(config.momentum_window_mid, len(bars))
        range_position_val = _range_position(close_, highs[-range_bars:], lows[-range_bars:])

        if tf == "1d":
            poc_dist_atr_val: float | None = 0.0
            va_position_val: float | None = 0.5
            sr_support_dist_val: float | None = 0.0
            sr_resist_dist_val: float | None = 0.0
        else:
            poc_dist_atr_val = cache.poc_dist_atr
            va_position_val = cache.va_position
            sr_support_dist_val = cache.sr_support_dist
            sr_resist_dist_val = cache.sr_resist_dist

        _dow = _dow_encoding(bar_ts)

        # Renaissance Primitives (Phase 142.5 Plan 01)
        prev_close_ = float(closes[-2])
        body_ratio_val = _body_ratio(open_, high_, low_, close_)
        upper_wick_ratio_val = _upper_wick_ratio(open_, high_, low_, close_)
        lower_wick_ratio_val = _lower_wick_ratio(open_, high_, low_, close_)
        range_vs_atr_val = _range_vs_atr(high_, low_, atr_val)
        close_vs_open_direction_val = _close_vs_open_direction(open_, close_)
        overnight_gap_val = _overnight_gap(open_, prev_close_)
        overnight_gap_z_val = _overnight_gap_z(opens, closes, config.overnight_gap_window)
        range_efficiency_val = _range_efficiency(close_, prev_close_, high_, low_)
        ret_lag_1_val = _ret_lag_1(closes)
        ret_lag_2_val = _ret_lag_2(closes)
        ret_lag_3_val = _ret_lag_3(closes)
        ret_lag_fast_val = _ret_lag_fast(closes, config.ret_lag_fast)
        ret_lag_mid_val = _ret_lag_mid(closes, config.ret_lag_mid)
        ret_lag_slow_val = _ret_lag_slow(closes, config.ret_lag_slow)
        open_ret_val = _open_ret(open_, prev_close_)
        intraday_ret_val = _intraday_ret(close_, open_)
        open_vs_intraday_val = _open_vs_intraday(open_ret_val, intraday_ret_val)
        session_time_pos_val = _session_time_pos(bar_ts, config)

        # Renaissance Primitives (Phase 142.5 Plan 02) — temporal coordinates
        # are O(1) pure functions of bar_ts; volume structure reads the
        # precomputed series (s.*) built once above.
        hour_of_day_sin_val = _hour_of_day_sin(bar_ts)
        hour_of_day_cos_val = _hour_of_day_cos(bar_ts)
        week_of_month_sin_val = _week_of_month_sin(bar_ts)
        week_of_month_cos_val = _week_of_month_cos(bar_ts)
        day_of_month_sin_val = _day_of_month_sin(bar_ts)
        day_of_month_cos_val = _day_of_month_cos(bar_ts)
        week_of_year_sin_val = _week_of_year_sin(bar_ts)
        week_of_year_cos_val = _week_of_year_cos(bar_ts)
        month_sin_val = _month_sin(bar_ts)
        month_cos_val = _month_cos(bar_ts)

        return _build_feature_vector(
            momentum_z_fast=_series_last(s.momentum_z_fast, 0.0),
            momentum_z_mid=_series_last(s.momentum_z_mid, 0.0),
            range_position=range_position_val,
            bar_close_pos=_bar_close_pos(high_, low_, close_),
            gap_z=_series_last(s.gap_z, 0.0),
            momentum_z_slow=_series_last(s.momentum_z_slow, 0.0),
            momentum_reversal_z=_series_last(s.momentum_reversal_z, 0.0),
            informed_flow=_informed_flow(open_, close_, atr_val),
            volume_z=_series_last(s.volume_z, 0.0),
            ofi_z=_series_last(s.ofi_z, 0.0),
            ofi_div=_series_last(s.ofi_z, 0.0) - _series_last(s.momentum_z_fast, 0.0),
            cvd_slope_z=_series_last(s.cvd_slope_z, 0.0),
            cmf=_cmf(highs, lows, closes, volumes, config.cmf_period),
            rel_volume=_series_last(s.rel_volume, 1.0),
            vwap_dev_sigma=_series_last(s.vwap_dev_sigma, 0.0),
            atr_z=_series_last(s.atr_z, 0.0),
            vol_ratio=_vol_ratio(closes, config.vol_short_bars, config.vol_long_bars),
            poc_dist_atr=poc_dist_atr_val,
            va_position=va_position_val,
            sr_support_dist=sr_support_dist_val,
            sr_resist_dist=sr_resist_dist_val,
            hmm_regime_prob=cache.hmm_regime_prob,
            hmm_entropy=cache.hmm_entropy,
            hmm_duration=cache.hmm_duration,
            hurst=cache.hurst,
            shannon=cache.shannon,
            garch_ratio=cache.garch_ratio,
            hma_slope_z=cache.hma_slope_z,
            adx=cache.adx,
            aroon_fast=_aroon_osc(highs, lows, config.aroon_fast_period),
            aroon_slow=_aroon_osc(highs, lows, config.aroon_slow_period),
            rsi_fast=_series_last(s.rsi_fast, 50.0),
            rsi_mid=_series_last(s.rsi_mid, 50.0),
            rsi_slow=_series_last(s.rsi_slow, 50.0),
            cci_fast=_cci(highs, lows, closes, config.cci_fast_period),
            cci_mid=_cci(highs, lows, closes, config.cci_mid_period),
            cci_slow=_cci(highs, lows, closes, config.cci_slow_period),
            vix_z=cache.vix_z,
            flight_quality=cache.flight_quality,
            yield_slope_z=cache.yield_slope_z,
            in_ny_session=_in_ny_session(bar_ts, config),
            in_london_kz=_in_london_kz(bar_ts, config),
            in_overlap=_in_overlap(bar_ts, config),
            power_hour=_power_hour(bar_ts, config),
            opening_range=_opening_range(bar_ts, config),
            above_wk_vwap=cache.above_wk_vwap,
            dow_sin=_dow[0],
            dow_cos=_dow[1],
            month_position=_month_position(bar_ts),
            quarter_position=_quarter_position(bar_ts),
            days_to_month_end=_days_to_month_end_fraction(bar_ts),
            ctf_momentum=cache.ctf_momentum,
            ctf_vwap_align=cache.ctf_vwap_align,
            ctf_regime_align=cache.ctf_regime_align,
            amihud_illiq_z=_series_last(s.amihud_illiq_z, 0.0),
            high_52w_dist=_series_last(s.high_52w_dist, 0.0),
            ret_skew_z=_series_last(s.ret_skew_z, 0.0),
            ret_acf1_z=_series_last(s.ret_acf1_z, 0.0),
            body_ratio=body_ratio_val,
            upper_wick_ratio=upper_wick_ratio_val,
            lower_wick_ratio=lower_wick_ratio_val,
            range_vs_atr=range_vs_atr_val,
            close_vs_open_direction=close_vs_open_direction_val,
            overnight_gap=overnight_gap_val,
            overnight_gap_z=overnight_gap_z_val,
            range_efficiency=range_efficiency_val,
            ret_lag_1=ret_lag_1_val,
            ret_lag_2=ret_lag_2_val,
            ret_lag_3=ret_lag_3_val,
            ret_lag_fast=ret_lag_fast_val,
            ret_lag_mid=ret_lag_mid_val,
            ret_lag_slow=ret_lag_slow_val,
            open_ret=open_ret_val,
            intraday_ret=intraday_ret_val,
            open_vs_intraday=open_vs_intraday_val,
            session_time_pos=session_time_pos_val,
            hour_of_day_sin=hour_of_day_sin_val,
            hour_of_day_cos=hour_of_day_cos_val,
            week_of_month_sin=week_of_month_sin_val,
            week_of_month_cos=week_of_month_cos_val,
            day_of_month_sin=day_of_month_sin_val,
            day_of_month_cos=day_of_month_cos_val,
            week_of_year_sin=week_of_year_sin_val,
            week_of_year_cos=week_of_year_cos_val,
            month_sin=month_sin_val,
            month_cos=month_cos_val,
            vol_acceleration=_series_last(s.vol_acceleration, 1.0),
            dollar_vol_z=_series_last(s.dollar_vol_z, 0.0),
            vol_range_ratio=_series_last(s.vol_range_ratio, 0.0),
            vol_trend_ratio=_series_last(s.vol_trend_ratio, 1.0),
            up_vol_ratio_fast=_series_last(s.up_vol_ratio_fast, 0.5),
            up_vol_ratio_slow=_series_last(s.up_vol_ratio_slow, 0.5),
            vol_percentile=_series_last(s.vol_percentile, 0.5),
            vol_persistence=_series_last(s.vol_persistence, 0.0),
            vol_std_z=_series_last(s.vol_std_z, 0.0),
            mfi_fast=_series_last(s.mfi_fast, 50.0),
            mfi_slow=_series_last(s.mfi_slow, 50.0),
            obv_z=_series_last(s.obv_z, 0.0),
            dist_from_high_fast=_series_last(s.dist_from_high_fast, 0.0),
            dist_from_high_slow=_series_last(s.dist_from_high_slow, 0.0),
            dist_from_low_fast=_series_last(s.dist_from_low_fast, 0.0),
            dist_from_low_slow=_series_last(s.dist_from_low_slow, 0.0),
            range_pct_fast=_series_last(s.range_pct_fast, 0.0),
            range_pct_slow=_series_last(s.range_pct_slow, 0.0),
            new_high_flag=_series_last(s.new_high_flag, 0.0),
            new_low_flag=_series_last(s.new_low_flag, 0.0),
            stoch_k_fast=_series_last(s.stoch_k_fast, 0.5),
            stoch_k_slow=_series_last(s.stoch_k_slow, 0.5),
            price_percentile_fast=_series_last(s.price_percentile_fast, 0.5),
            price_percentile_slow=_series_last(s.price_percentile_slow, 0.5),
            efficiency_ratio_fast=_series_last(s.efficiency_ratio_fast, 0.0),
            efficiency_ratio_slow=_series_last(s.efficiency_ratio_slow, 0.0),
            ret_kurtosis_z_fast=_series_last(s.ret_kurtosis_z_fast, 0.0),
            ret_kurtosis_z_slow=_series_last(s.ret_kurtosis_z_slow, 0.0),
            ret_autocorr_1=_series_last(s.ret_autocorr_1, 0.0),
            ret_autocorr_5=_series_last(s.ret_autocorr_5, 0.0),
            updown_ratio_fast=_series_last(s.updown_ratio_fast, 1.0),
            updown_ratio_slow=_series_last(s.updown_ratio_slow, 1.0),
            streak_z=_series_last(s.streak_z, 0.0),
            realized_var_ratio_fast=_series_last(s.realized_var_ratio_fast, 1.0),
            realized_var_ratio_slow=_series_last(s.realized_var_ratio_slow, 1.0),
            range_to_close=_series_last(s.range_to_close, 0.0),
            true_range_pct=_series_last(s.true_range_pct, 0.0),
            vol_of_vol=_series_last(s.vol_of_vol, 0.0),
            high_low_corr=_series_last(s.high_low_corr, 0.0),
            variance_ratio_fast=_series_last(s.variance_ratio_fast, 1.0),
            variance_ratio_slow=_series_last(s.variance_ratio_slow, 1.0),
            vol_asymmetry_z=_series_last(s.vol_asymmetry_z, 0.0),
            bb_pct_b_fast=_series_last(s.bb_pct_b_fast, 0.5),
            bb_pct_b_slow=_series_last(s.bb_pct_b_slow, 0.5),
            hv_z_fast=_series_last(s.hv_z_fast, 0.0),
            hv_z_slow=_series_last(s.hv_z_slow, 0.0),
            hv_ratio=_series_last(s.hv_ratio, 1.0),
            # Renaissance Primitives (Phase 142.5 Plan 04) — alternative volatility
            # estimators + volatility dynamics. All read the precomputed series (s.*)
            # built once above; velocity primitives are the O(1) difference of the
            # current and prior-bar z-score elements (stateless, no cache dependency),
            # guaranteeing exact parity with compute_batch()'s indexing.
            parkinson_vol_z=_series_last(s.parkinson_vol_z, 0.0),
            garman_klass_vol_z=_series_last(s.garman_klass_vol_z, 0.0),
            yang_zhang_vol_z=_series_last(s.yang_zhang_vol_z, 0.0),
            parkinson_vol_velocity=(
                float(s.parkinson_vol_z[-1] - s.parkinson_vol_z[-2])
                if len(s.parkinson_vol_z) >= 2
                else 0.0
            ),
            garman_klass_vol_velocity=(
                float(s.garman_klass_vol_z[-1] - s.garman_klass_vol_z[-2])
                if len(s.garman_klass_vol_z) >= 2
                else 0.0
            ),
            yang_zhang_vol_velocity=(
                float(s.yang_zhang_vol_z[-1] - s.yang_zhang_vol_z[-2])
                if len(s.yang_zhang_vol_z) >= 2
                else 0.0
            ),
            vol_velocity_z=_series_last(s.vol_velocity_z, 0.0),
            intraday_noise_ratio=_series_last(s.intraday_noise_ratio, 1.0),
        )

    @staticmethod
    def compute_batch(
        bars: list[dict],
        symbol: str,
        tf: str,
        cache: FeatureCache,
        config: FeatureFactoryConfig,
        warm_up_bars: int = 0,
        cross_asset_by_date: dict | None = None,
        ctf_by_ts: dict | None = None,
        ctf_ts_list: list | None = None,
    ) -> list[tuple[datetime, FeatureVector]]:
        """Compute FeatureVector for every bar in bars in O(n). Returns (bar_ts, fv) pairs.

        Precomputes all series_full functions once, then loops over bars indexing series[i].
        Non-series features (cmf, cci, aroon, vol_ratio, range_position, bar_close_pos, informed_flow)
        are computed per bar with bounded windows. Cache-backed features (hmm, hurst, etc.) are
        read from cache. Calendar features computed per bar from timestamps.

        When cross_asset_by_date is provided (batch path):
          - cross-asset (vix_z, flight_quality, yield_slope_z) read from dict keyed by date
          - CTF (ctf_momentum, ctf_vwap_align, ctf_regime_align) read from ctf_by_ts via bisect
          - VP/SR (poc_dist_atr, va_position, sr_support_dist, sr_resist_dist) set to None
            (not computable from OHLCV batch; requires I3 intraday injection)
        When cross_asset_by_date is None (live path):
          - all three groups read from cache (unchanged behavior)
        """
        if len(bars) < 2:
            return []

        # Extract numpy arrays once
        opens = np.array([b["open"] for b in bars], dtype=float)
        highs = np.array([b["high"] for b in bars], dtype=float)
        lows = np.array([b["low"] for b in bars], dtype=float)
        closes = np.array([b["close"] for b in bars], dtype=float)
        volumes = np.array([b["volume"] for b in bars], dtype=float)

        s = _precompute_series(opens, highs, lows, closes, volumes, config)

        # MIN_WINDOW for non-series features (cci_slow=40, aroon_slow=26, vol_ratio=21, cmf=20, range_position=20)
        MIN_WINDOW = max(
            config.cci_slow_period,
            config.aroon_slow_period,
            config.vol_long_bars,
            config.cmf_period,
        )
        results: list[tuple[datetime, FeatureVector]] = []

        for i in range(1, len(bars)):
            # Periodically refresh regime — use hurst_window (APR: feature.hurst.window,
            # default 500) so HMM gets sufficient history. MIN_WINDOW (APR-derived, default 40) is only for
            # bounded per-bar features (CCI, Aroon, etc.) below.
            if i % config.regime_cache_refresh_bars == 0:
                regime_window_start = max(0, i - config.hurst_window)
                cache.refresh_regime(bars[regime_window_start : i + 1], config)

            # Skip warm-up
            if i < warm_up_bars:
                bar = bars[i]
                cache.advance_bar(
                    bar["ts"],
                    float(bar["high"]),
                    float(bar["low"]),
                    float(bar["close"]),
                    float(bar["volume"]),
                )
                continue

            # Build bounded window for non-series features
            window_start = max(0, i - MIN_WINDOW)
            window_bars = bars[window_start : i + 1]

            # Extract window arrays
            w_opens = np.array([b["open"] for b in window_bars], dtype=float)
            w_highs = np.array([b["high"] for b in window_bars], dtype=float)
            w_lows = np.array([b["low"] for b in window_bars], dtype=float)
            w_closes = np.array([b["close"] for b in window_bars], dtype=float)
            w_volumes = np.array([b["volume"] for b in window_bars], dtype=float)

            bar = bars[i]
            bar_ts = bar["ts"]
            open_ = float(bar["open"])
            high_ = float(bar["high"])
            low_ = float(bar["low"])
            close_ = float(bar["close"])
            vol_ = float(bar["volume"])

            # Ensure ts is timezone-aware UTC
            if isinstance(bar_ts, datetime) and bar_ts.tzinfo is None:
                bar_ts = bar_ts.replace(tzinfo=UTC)

            # Series-backed features (index into precomputed series)
            atr_val = float(s.atr_raw[i - 1]) if i - 1 < len(s.atr_raw) else 0.0
            atr_z_val = float(s.atr_z[i]) if i < len(s.atr_z) else 0.0
            gap_z_val = float(s.gap_z[i]) if i < len(s.gap_z) else 0.0
            rel_volume_val = float(s.rel_volume[i]) if i < len(s.rel_volume) else 1.0
            ofi_z_val = float(s.ofi_z[i]) if i < len(s.ofi_z) else 0.0
            cvd_slope_z_val = float(s.cvd_slope_z[i]) if i < len(s.cvd_slope_z) else 0.0
            volume_z_val = float(s.volume_z[i]) if i < len(s.volume_z) else 0.0
            momentum_z_fast_val = float(s.momentum_z_fast[i]) if i < len(s.momentum_z_fast) else 0.0
            momentum_z_mid_val = float(s.momentum_z_mid[i]) if i < len(s.momentum_z_mid) else 0.0
            momentum_z_slow_val = float(s.momentum_z_slow[i]) if i < len(s.momentum_z_slow) else 0.0
            momentum_reversal_z_val = (
                float(s.momentum_reversal_z[i]) if i < len(s.momentum_reversal_z) else 0.0
            )
            vwap_dev_sigma_val = float(s.vwap_dev_sigma[i]) if i < len(s.vwap_dev_sigma) else 0.0
            rsi_fast_val = float(s.rsi_fast[i]) if i < len(s.rsi_fast) else 50.0
            rsi_mid_val = float(s.rsi_mid[i]) if i < len(s.rsi_mid) else 50.0
            rsi_slow_val = float(s.rsi_slow[i]) if i < len(s.rsi_slow) else 50.0
            amihud_illiq_z_val = float(s.amihud_illiq_z[i]) if i < len(s.amihud_illiq_z) else 0.0
            high_52w_dist_val = float(s.high_52w_dist[i]) if i < len(s.high_52w_dist) else 0.0
            ret_skew_z_val = float(s.ret_skew_z[i]) if i < len(s.ret_skew_z) else 0.0
            ret_acf1_z_val = float(s.ret_acf1_z[i]) if i < len(s.ret_acf1_z) else 0.0

            # Non-series features (compute on bounded window)
            bar_close_pos_val = _bar_close_pos(high_, low_, close_)

            range_bars = min(config.momentum_window_mid, len(window_bars))
            range_position_val = _range_position(
                close_, w_highs[-range_bars:], w_lows[-range_bars:]
            )

            informed_flow_val = _informed_flow(open_, close_, atr_val)
            vol_ratio_val = _vol_ratio(w_closes, config.vol_short_bars, config.vol_long_bars)
            cmf_val = _cmf(w_highs, w_lows, w_closes, w_volumes, config.cmf_period)

            # Session-level (VP/SR): None in batch path; 1d defaults to neutral; else from cache
            if cross_asset_by_date is not None:
                poc_dist_atr_val = None
                va_position_val = None
                sr_support_dist_val = None
                sr_resist_dist_val = None
            elif tf == "1d":
                poc_dist_atr_val = 0.0
                va_position_val = 0.5
                sr_support_dist_val = 0.0
                sr_resist_dist_val = 0.0
            else:
                poc_dist_atr_val = cache.poc_dist_atr
                va_position_val = cache.va_position
                sr_support_dist_val = cache.sr_support_dist
                sr_resist_dist_val = cache.sr_resist_dist

            # Regime-level primitives (all from cache)
            hmm_regime_prob_val = cache.hmm_regime_prob
            hmm_entropy_val = cache.hmm_entropy
            hmm_duration_val = cache.hmm_duration
            hurst_val = cache.hurst
            shannon_val = cache.shannon
            garch_ratio_val = cache.garch_ratio
            hma_slope_z_val = cache.hma_slope_z
            adx_val = cache.adx

            # Oscillators (non-series)
            cci_fast_val = _cci(w_highs, w_lows, w_closes, config.cci_fast_period)
            cci_mid_val = _cci(w_highs, w_lows, w_closes, config.cci_mid_period)
            cci_slow_val = _cci(w_highs, w_lows, w_closes, config.cci_slow_period)

            aroon_fast_val = _aroon_osc(w_highs, w_lows, config.aroon_fast_period)
            aroon_slow_val = _aroon_osc(w_highs, w_lows, config.aroon_slow_period)

            # OFI divergence
            ofi_div_val = ofi_z_val - momentum_z_fast_val

            # Cross-asset: from pre-built causal dict (batch) or cache (live)
            if cross_asset_by_date is not None:
                _ca = cross_asset_by_date.get(bar_ts.date(), (0.0, 0.0, 0.0))
                vix_z_val, flight_quality_val, yield_slope_z_val = _ca
            else:
                vix_z_val = cache.vix_z
                flight_quality_val = cache.flight_quality
                yield_slope_z_val = cache.yield_slope_z

            # Calendar primitives
            in_ny_session_val = _in_ny_session(bar_ts, config)
            in_london_kz_val = _in_london_kz(bar_ts, config)
            in_overlap_val = _in_overlap(bar_ts, config)
            power_hour_val = _power_hour(bar_ts, config)
            opening_range_val = _opening_range(bar_ts, config)
            above_wk_vwap_val = cache.above_wk_vwap
            dow_sin_val, dow_cos_val = _dow_encoding(bar_ts)
            month_position_val = _month_position(bar_ts)
            quarter_position_val = _quarter_position(bar_ts)
            days_to_month_end_val = _days_to_month_end_fraction(bar_ts)

            # CTF: from pre-built causal dict (batch) or cache (live)
            if ctf_by_ts is not None and ctf_ts_list is not None:
                _idx = bisect.bisect_right(ctf_ts_list, bar_ts) - 1
                if _idx >= 0:
                    ctf_momentum_val, ctf_vwap_align_val, ctf_regime_align_val = ctf_by_ts[
                        ctf_ts_list[_idx]
                    ]
                else:
                    ctf_momentum_val = ctf_vwap_align_val = ctf_regime_align_val = 0.0
            else:
                ctf_momentum_val = cache.ctf_momentum
                ctf_vwap_align_val = cache.ctf_vwap_align
                ctf_regime_align_val = cache.ctf_regime_align

            # Renaissance Primitives (Phase 142.5 Plan 01). ret_lag_* index the full
            # `closes` array (view slice closes[:i+1], O(1)) rather than the bounded
            # w_closes window, since ret_lag_slow's APR window can exceed MIN_WINDOW.
            # overnight_gap_z reads the precomputed series (O(n) total, not O(n^2)).
            prev_close_ = float(closes[i - 1])
            body_ratio_val = _body_ratio(open_, high_, low_, close_)
            upper_wick_ratio_val = _upper_wick_ratio(open_, high_, low_, close_)
            lower_wick_ratio_val = _lower_wick_ratio(open_, high_, low_, close_)
            range_vs_atr_val = _range_vs_atr(high_, low_, atr_val)
            close_vs_open_direction_val = _close_vs_open_direction(open_, close_)
            overnight_gap_val = _overnight_gap(open_, prev_close_)
            overnight_gap_z_val = float(s.overnight_gap_z[i]) if i < len(s.overnight_gap_z) else 0.0
            range_efficiency_val = _range_efficiency(close_, prev_close_, high_, low_)
            ret_lag_1_val = _ret_lag_1(closes[: i + 1])
            ret_lag_2_val = _ret_lag_2(closes[: i + 1])
            ret_lag_3_val = _ret_lag_3(closes[: i + 1])
            ret_lag_fast_val = _ret_lag_fast(closes[: i + 1], config.ret_lag_fast)
            ret_lag_mid_val = _ret_lag_mid(closes[: i + 1], config.ret_lag_mid)
            ret_lag_slow_val = _ret_lag_slow(closes[: i + 1], config.ret_lag_slow)
            open_ret_val = _open_ret(open_, prev_close_)
            intraday_ret_val = _intraday_ret(close_, open_)
            open_vs_intraday_val = _open_vs_intraday(open_ret_val, intraday_ret_val)
            session_time_pos_val = _session_time_pos(bar_ts, config)

            # Renaissance Primitives (Phase 142.5 Plan 02). Temporal coordinates
            # are O(1) per bar (pure bar_ts arithmetic). Volume structure reads
            # the precomputed series (O(n) total, not per-bar O(n x window)).
            hour_of_day_sin_val = _hour_of_day_sin(bar_ts)
            hour_of_day_cos_val = _hour_of_day_cos(bar_ts)
            week_of_month_sin_val = _week_of_month_sin(bar_ts)
            week_of_month_cos_val = _week_of_month_cos(bar_ts)
            day_of_month_sin_val = _day_of_month_sin(bar_ts)
            day_of_month_cos_val = _day_of_month_cos(bar_ts)
            week_of_year_sin_val = _week_of_year_sin(bar_ts)
            week_of_year_cos_val = _week_of_year_cos(bar_ts)
            month_sin_val = _month_sin(bar_ts)
            month_cos_val = _month_cos(bar_ts)
            vol_acceleration_val = (
                float(s.vol_acceleration[i]) if i < len(s.vol_acceleration) else 1.0
            )
            dollar_vol_z_val = float(s.dollar_vol_z[i]) if i < len(s.dollar_vol_z) else 0.0
            vol_range_ratio_val = float(s.vol_range_ratio[i]) if i < len(s.vol_range_ratio) else 0.0
            vol_trend_ratio_val = float(s.vol_trend_ratio[i]) if i < len(s.vol_trend_ratio) else 1.0
            up_vol_ratio_fast_val = (
                float(s.up_vol_ratio_fast[i]) if i < len(s.up_vol_ratio_fast) else 0.5
            )
            up_vol_ratio_slow_val = (
                float(s.up_vol_ratio_slow[i]) if i < len(s.up_vol_ratio_slow) else 0.5
            )
            vol_percentile_val = float(s.vol_percentile[i]) if i < len(s.vol_percentile) else 0.5
            vol_persistence_val = float(s.vol_persistence[i]) if i < len(s.vol_persistence) else 0.0
            vol_std_z_val = float(s.vol_std_z[i]) if i < len(s.vol_std_z) else 0.0
            mfi_fast_val = float(s.mfi_fast[i]) if i < len(s.mfi_fast) else 50.0
            mfi_slow_val = float(s.mfi_slow[i]) if i < len(s.mfi_slow) else 50.0
            obv_z_val = float(s.obv_z[i]) if i < len(s.obv_z) else 0.0

            # Renaissance Primitives (Phase 142.5 Plan 05) — breakout distance.
            # All 14 fields read the precomputed series (O(n) total, not per-bar
            # O(n x window)); indexing here guarantees exact parity with compute().
            dist_from_high_fast_val = (
                float(s.dist_from_high_fast[i]) if i < len(s.dist_from_high_fast) else 0.0
            )
            dist_from_high_slow_val = (
                float(s.dist_from_high_slow[i]) if i < len(s.dist_from_high_slow) else 0.0
            )
            dist_from_low_fast_val = (
                float(s.dist_from_low_fast[i]) if i < len(s.dist_from_low_fast) else 0.0
            )
            dist_from_low_slow_val = (
                float(s.dist_from_low_slow[i]) if i < len(s.dist_from_low_slow) else 0.0
            )
            range_pct_fast_val = float(s.range_pct_fast[i]) if i < len(s.range_pct_fast) else 0.0
            range_pct_slow_val = float(s.range_pct_slow[i]) if i < len(s.range_pct_slow) else 0.0
            new_high_flag_val = float(s.new_high_flag[i]) if i < len(s.new_high_flag) else 0.0
            new_low_flag_val = float(s.new_low_flag[i]) if i < len(s.new_low_flag) else 0.0
            stoch_k_fast_val = float(s.stoch_k_fast[i]) if i < len(s.stoch_k_fast) else 0.5
            stoch_k_slow_val = float(s.stoch_k_slow[i]) if i < len(s.stoch_k_slow) else 0.5
            price_percentile_fast_val = (
                float(s.price_percentile_fast[i]) if i < len(s.price_percentile_fast) else 0.5
            )
            price_percentile_slow_val = (
                float(s.price_percentile_slow[i]) if i < len(s.price_percentile_slow) else 0.5
            )
            efficiency_ratio_fast_val = (
                float(s.efficiency_ratio_fast[i]) if i < len(s.efficiency_ratio_fast) else 0.0
            )
            efficiency_ratio_slow_val = (
                float(s.efficiency_ratio_slow[i]) if i < len(s.efficiency_ratio_slow) else 0.0
            )

            # Renaissance Primitives (Phase 142.5 Plan 03) — return distribution +
            # realized variance. All 21 fields read the precomputed series (O(n)
            # total, not per-bar O(n x window)); indexing here guarantees exact
            # parity with compute().
            ret_kurtosis_z_fast_val = (
                float(s.ret_kurtosis_z_fast[i]) if i < len(s.ret_kurtosis_z_fast) else 0.0
            )
            ret_kurtosis_z_slow_val = (
                float(s.ret_kurtosis_z_slow[i]) if i < len(s.ret_kurtosis_z_slow) else 0.0
            )
            ret_autocorr_1_val = float(s.ret_autocorr_1[i]) if i < len(s.ret_autocorr_1) else 0.0
            ret_autocorr_5_val = float(s.ret_autocorr_5[i]) if i < len(s.ret_autocorr_5) else 0.0
            updown_ratio_fast_val = (
                float(s.updown_ratio_fast[i]) if i < len(s.updown_ratio_fast) else 1.0
            )
            updown_ratio_slow_val = (
                float(s.updown_ratio_slow[i]) if i < len(s.updown_ratio_slow) else 1.0
            )
            streak_z_val = float(s.streak_z[i]) if i < len(s.streak_z) else 0.0
            realized_var_ratio_fast_val = (
                float(s.realized_var_ratio_fast[i]) if i < len(s.realized_var_ratio_fast) else 1.0
            )
            realized_var_ratio_slow_val = (
                float(s.realized_var_ratio_slow[i]) if i < len(s.realized_var_ratio_slow) else 1.0
            )
            range_to_close_val = float(s.range_to_close[i]) if i < len(s.range_to_close) else 0.0
            true_range_pct_val = float(s.true_range_pct[i]) if i < len(s.true_range_pct) else 0.0
            vol_of_vol_val = float(s.vol_of_vol[i]) if i < len(s.vol_of_vol) else 0.0
            high_low_corr_val = float(s.high_low_corr[i]) if i < len(s.high_low_corr) else 0.0
            variance_ratio_fast_val = (
                float(s.variance_ratio_fast[i]) if i < len(s.variance_ratio_fast) else 1.0
            )
            variance_ratio_slow_val = (
                float(s.variance_ratio_slow[i]) if i < len(s.variance_ratio_slow) else 1.0
            )
            vol_asymmetry_z_val = float(s.vol_asymmetry_z[i]) if i < len(s.vol_asymmetry_z) else 0.0
            bb_pct_b_fast_val = float(s.bb_pct_b_fast[i]) if i < len(s.bb_pct_b_fast) else 0.5
            bb_pct_b_slow_val = float(s.bb_pct_b_slow[i]) if i < len(s.bb_pct_b_slow) else 0.5
            hv_z_fast_val = float(s.hv_z_fast[i]) if i < len(s.hv_z_fast) else 0.0
            hv_z_slow_val = float(s.hv_z_slow[i]) if i < len(s.hv_z_slow) else 0.0
            hv_ratio_val = float(s.hv_ratio[i]) if i < len(s.hv_ratio) else 1.0

            # Renaissance Primitives (Phase 142.5 Plan 04) — alternative volatility
            # estimators + volatility dynamics. All 8 fields read the precomputed
            # series (O(n) total, not per-bar O(n x window)); velocity primitives
            # are the O(1) difference of consecutive precomputed z-score elements,
            # guaranteeing exact parity with compute().
            parkinson_vol_z_val = float(s.parkinson_vol_z[i]) if i < len(s.parkinson_vol_z) else 0.0
            garman_klass_vol_z_val = (
                float(s.garman_klass_vol_z[i]) if i < len(s.garman_klass_vol_z) else 0.0
            )
            yang_zhang_vol_z_val = (
                float(s.yang_zhang_vol_z[i]) if i < len(s.yang_zhang_vol_z) else 0.0
            )
            parkinson_vol_velocity_val = (
                float(s.parkinson_vol_z[i] - s.parkinson_vol_z[i - 1])
                if i >= 1 and i < len(s.parkinson_vol_z)
                else 0.0
            )
            garman_klass_vol_velocity_val = (
                float(s.garman_klass_vol_z[i] - s.garman_klass_vol_z[i - 1])
                if i >= 1 and i < len(s.garman_klass_vol_z)
                else 0.0
            )
            yang_zhang_vol_velocity_val = (
                float(s.yang_zhang_vol_z[i] - s.yang_zhang_vol_z[i - 1])
                if i >= 1 and i < len(s.yang_zhang_vol_z)
                else 0.0
            )
            vol_velocity_z_val = float(s.vol_velocity_z[i]) if i < len(s.vol_velocity_z) else 0.0
            intraday_noise_ratio_val = (
                float(s.intraday_noise_ratio[i]) if i < len(s.intraday_noise_ratio) else 1.0
            )

            # Build FeatureVector
            fv = _build_feature_vector(
                momentum_z_fast=momentum_z_fast_val,
                momentum_z_mid=momentum_z_mid_val,
                range_position=range_position_val,
                bar_close_pos=bar_close_pos_val,
                gap_z=gap_z_val,
                momentum_z_slow=momentum_z_slow_val,
                momentum_reversal_z=momentum_reversal_z_val,
                informed_flow=informed_flow_val,
                volume_z=volume_z_val,
                ofi_z=ofi_z_val,
                ofi_div=ofi_div_val,
                cvd_slope_z=cvd_slope_z_val,
                cmf=cmf_val,
                rel_volume=rel_volume_val,
                vwap_dev_sigma=vwap_dev_sigma_val,
                atr_z=atr_z_val,
                vol_ratio=vol_ratio_val,
                poc_dist_atr=poc_dist_atr_val,
                va_position=va_position_val,
                sr_support_dist=sr_support_dist_val,
                sr_resist_dist=sr_resist_dist_val,
                hmm_regime_prob=hmm_regime_prob_val,
                hmm_entropy=hmm_entropy_val,
                hmm_duration=hmm_duration_val,
                hurst=hurst_val,
                shannon=shannon_val,
                garch_ratio=garch_ratio_val,
                hma_slope_z=hma_slope_z_val,
                adx=adx_val,
                aroon_fast=aroon_fast_val,
                aroon_slow=aroon_slow_val,
                rsi_fast=rsi_fast_val,
                rsi_mid=rsi_mid_val,
                rsi_slow=rsi_slow_val,
                cci_fast=cci_fast_val,
                cci_mid=cci_mid_val,
                cci_slow=cci_slow_val,
                vix_z=vix_z_val,
                flight_quality=flight_quality_val,
                yield_slope_z=yield_slope_z_val,
                in_ny_session=in_ny_session_val,
                in_london_kz=in_london_kz_val,
                in_overlap=in_overlap_val,
                power_hour=power_hour_val,
                opening_range=opening_range_val,
                above_wk_vwap=above_wk_vwap_val,
                dow_sin=dow_sin_val,
                dow_cos=dow_cos_val,
                month_position=month_position_val,
                quarter_position=_quarter_position(bar_ts),
                days_to_month_end=_days_to_month_end_fraction(bar_ts),
                ctf_momentum=ctf_momentum_val,
                ctf_vwap_align=ctf_vwap_align_val,
                ctf_regime_align=ctf_regime_align_val,
                amihud_illiq_z=amihud_illiq_z_val,
                high_52w_dist=high_52w_dist_val,
                ret_skew_z=ret_skew_z_val,
                ret_acf1_z=ret_acf1_z_val,
                body_ratio=body_ratio_val,
                upper_wick_ratio=upper_wick_ratio_val,
                lower_wick_ratio=lower_wick_ratio_val,
                range_vs_atr=range_vs_atr_val,
                close_vs_open_direction=close_vs_open_direction_val,
                overnight_gap=overnight_gap_val,
                overnight_gap_z=overnight_gap_z_val,
                range_efficiency=range_efficiency_val,
                ret_lag_1=ret_lag_1_val,
                ret_lag_2=ret_lag_2_val,
                ret_lag_3=ret_lag_3_val,
                ret_lag_fast=ret_lag_fast_val,
                ret_lag_mid=ret_lag_mid_val,
                ret_lag_slow=ret_lag_slow_val,
                open_ret=open_ret_val,
                intraday_ret=intraday_ret_val,
                open_vs_intraday=open_vs_intraday_val,
                session_time_pos=session_time_pos_val,
                hour_of_day_sin=hour_of_day_sin_val,
                hour_of_day_cos=hour_of_day_cos_val,
                week_of_month_sin=week_of_month_sin_val,
                week_of_month_cos=week_of_month_cos_val,
                day_of_month_sin=day_of_month_sin_val,
                day_of_month_cos=day_of_month_cos_val,
                week_of_year_sin=week_of_year_sin_val,
                week_of_year_cos=week_of_year_cos_val,
                month_sin=month_sin_val,
                month_cos=month_cos_val,
                vol_acceleration=vol_acceleration_val,
                dollar_vol_z=dollar_vol_z_val,
                vol_range_ratio=vol_range_ratio_val,
                vol_trend_ratio=vol_trend_ratio_val,
                up_vol_ratio_fast=up_vol_ratio_fast_val,
                up_vol_ratio_slow=up_vol_ratio_slow_val,
                vol_percentile=vol_percentile_val,
                vol_persistence=vol_persistence_val,
                vol_std_z=vol_std_z_val,
                mfi_fast=mfi_fast_val,
                mfi_slow=mfi_slow_val,
                obv_z=obv_z_val,
                dist_from_high_fast=dist_from_high_fast_val,
                dist_from_high_slow=dist_from_high_slow_val,
                dist_from_low_fast=dist_from_low_fast_val,
                dist_from_low_slow=dist_from_low_slow_val,
                range_pct_fast=range_pct_fast_val,
                range_pct_slow=range_pct_slow_val,
                new_high_flag=new_high_flag_val,
                new_low_flag=new_low_flag_val,
                stoch_k_fast=stoch_k_fast_val,
                stoch_k_slow=stoch_k_slow_val,
                price_percentile_fast=price_percentile_fast_val,
                price_percentile_slow=price_percentile_slow_val,
                efficiency_ratio_fast=efficiency_ratio_fast_val,
                efficiency_ratio_slow=efficiency_ratio_slow_val,
                ret_kurtosis_z_fast=ret_kurtosis_z_fast_val,
                ret_kurtosis_z_slow=ret_kurtosis_z_slow_val,
                ret_autocorr_1=ret_autocorr_1_val,
                ret_autocorr_5=ret_autocorr_5_val,
                updown_ratio_fast=updown_ratio_fast_val,
                updown_ratio_slow=updown_ratio_slow_val,
                streak_z=streak_z_val,
                realized_var_ratio_fast=realized_var_ratio_fast_val,
                realized_var_ratio_slow=realized_var_ratio_slow_val,
                range_to_close=range_to_close_val,
                true_range_pct=true_range_pct_val,
                vol_of_vol=vol_of_vol_val,
                high_low_corr=high_low_corr_val,
                variance_ratio_fast=variance_ratio_fast_val,
                variance_ratio_slow=variance_ratio_slow_val,
                vol_asymmetry_z=vol_asymmetry_z_val,
                bb_pct_b_fast=bb_pct_b_fast_val,
                bb_pct_b_slow=bb_pct_b_slow_val,
                hv_z_fast=hv_z_fast_val,
                hv_z_slow=hv_z_slow_val,
                hv_ratio=hv_ratio_val,
                parkinson_vol_z=parkinson_vol_z_val,
                garman_klass_vol_z=garman_klass_vol_z_val,
                yang_zhang_vol_z=yang_zhang_vol_z_val,
                parkinson_vol_velocity=parkinson_vol_velocity_val,
                garman_klass_vol_velocity=garman_klass_vol_velocity_val,
                yang_zhang_vol_velocity=yang_zhang_vol_velocity_val,
                vol_velocity_z=vol_velocity_z_val,
                intraday_noise_ratio=intraday_noise_ratio_val,
            )

            results.append((bar_ts, fv))

            # Advance cache state
            cache.advance_bar(bar_ts, high_, low_, close_, vol_)

        return results


def _cold_start_vector(cache: FeatureCache, tf: str) -> FeatureVector:
    """Return a valid FeatureVector with cold-start defaults (0.0 / neutral values)."""
    if tf == "1d":
        poc_dist_atr = 0.0
        va_position = 0.5
        sr_support_dist = 0.0
        sr_resist_dist = 0.0
    else:
        poc_dist_atr = cache.poc_dist_atr
        va_position = cache.va_position
        sr_support_dist = cache.sr_support_dist
        sr_resist_dist = cache.sr_resist_dist

    return FeatureVector(
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
        poc_dist_atr=poc_dist_atr,
        va_position=va_position,
        sr_support_dist=sr_support_dist,
        sr_resist_dist=sr_resist_dist,
        hmm_regime_prob=cache.hmm_regime_prob,
        hmm_entropy=cache.hmm_entropy,
        hmm_duration=cache.hmm_duration,
        hurst=cache.hurst,
        shannon=cache.shannon,
        garch_ratio=cache.garch_ratio,
        hma_slope_z=cache.hma_slope_z,
        adx=cache.adx,
        aroon_fast=0.0,
        aroon_slow=0.0,
        rsi_fast=50.0,
        rsi_mid=50.0,
        rsi_slow=50.0,
        cci_fast=0.0,
        cci_mid=0.0,
        cci_slow=0.0,
        vix_z=cache.vix_z,
        flight_quality=cache.flight_quality,
        yield_slope_z=cache.yield_slope_z,
        in_ny_session=0.0,
        in_london_kz=0.0,
        in_overlap=0.0,
        power_hour=0.0,
        opening_range=0.0,
        above_wk_vwap=cache.above_wk_vwap,
        dow_sin=0.0,
        dow_cos=1.0,
        month_position=1.0,
        quarter_position=0.0,
        days_to_month_end=0.0,
        ctf_momentum=cache.ctf_momentum,
        ctf_vwap_align=cache.ctf_vwap_align,
        ctf_regime_align=cache.ctf_regime_align,
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
        vol_trend_ratio=0.0,
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
        new_high_flag=0.0,
        new_low_flag=0.0,
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
        momentum_rank_z=None,
        volume_rank_z=None,
        volatility_rank_z=None,
    )
