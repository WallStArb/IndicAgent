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

import calendar
import math
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np
from scipy.stats import skew as _scipy_skew

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


# ---------------------------------------------------------------------------
# Rolling z-score helper (module-level, used across primitives)
# ---------------------------------------------------------------------------


def _rolling_zscore(value: float, history: deque, window: int) -> float:
    """Compute z-score of value against rolling window history.

    Parameters
    ----------
    value: Current observation to append and score.
    history: Rolling deque (caller manages maxlen).
    window: Number of bars to use for mean/std.

    Returns
    -------
    z-score as float. Returns 0.0 when insufficient history or near-zero std.
    """
    history.append(value)
    if len(history) < window:
        return 0.0
    arr = np.array(list(history)[-window:])
    std = float(arr.std())
    if std < 1e-8:
        return 0.0
    return float((value - float(arr.mean())) / std)


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


def _gap_z(
    open_price: float,
    prev_close: float,
    atr: float,
    gap_history: deque,
    window: int,
) -> float:
    """Gap z-score: (open - prev_close) / ATR, z-scored over window.

    Returns 0.0 when ATR is zero or cold-start.
    """
    raw_gap = (open_price - prev_close) / atr if atr > 1e-10 else 0.0
    return _rolling_zscore(raw_gap, gap_history, window)


def _informed_flow(open_price: float, close: float, atr: float) -> float:
    """Directional informed flow proxy: (close - open) / ATR.

    Returns 0.0 when ATR is zero.
    """
    return (close - open_price) / atr if atr > 1e-10 else 0.0


def _ofi_z(
    high: float,
    low: float,
    close: float,
    volume: float,
    ofi_history: deque,
    window: int,
    eps: float = 1e-10,
) -> float:
    """Order flow imbalance proxy (OHLCV-only, never tick path).

    Formula: (close - low) / (high - low + eps) * volume, z-scored.
    """
    raw = (close - low) / (high - low + eps) * volume
    return _rolling_zscore(raw, ofi_history, window)


def _cvd_accumulate(
    high: float,
    low: float,
    close: float,
    volume: float,
    session_cvd: list[float],
    eps: float = 1e-10,
) -> float:
    """Accumulate one bar into session CVD using OHLCV proxy (never tick path).

    Formula: (2*close - high - low) / (high - low + eps) * volume
    Returns the new cumulative session CVD value.
    """
    raw = (2.0 * close - high - low) / (high - low + eps) * volume
    if session_cvd:
        new_val = session_cvd[-1] + raw
    else:
        new_val = raw
    session_cvd.append(new_val)
    return new_val


def _cvd_slope_z(
    session_cvd: list[float],
    cvd_history: deque,
    slope_bars: int,
    zscore_window: int,
) -> float:
    """CVD slope z-score: slope of session CVD over slope_bars, z-scored.

    Returns 0.0 on cold start.
    """
    if len(session_cvd) < slope_bars + 1:
        return 0.0
    slope = (session_cvd[-1] - session_cvd[-slope_bars - 1]) / slope_bars
    return _rolling_zscore(slope, cvd_history, zscore_window)


def _volume_z(volume: float, vol_z_history: deque, window: int) -> float:
    """Volume z-score over rolling window."""
    return _rolling_zscore(volume, vol_z_history, window)


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


def _momentum_z(
    closes: np.ndarray,
    window: int,
    zscore_history: deque,
    zscore_window: int,
) -> float:
    """Log-return velocity over window, z-scored.

    Returns 0.0 on cold start.
    """
    if len(closes) < window + 1:
        return 0.0
    log_return = math.log(max(float(closes[-1]), 1e-10) / max(float(closes[-(window + 1)]), 1e-10))
    return _rolling_zscore(log_return, zscore_history, zscore_window)


def _atr_wilder(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int) -> float:
    """ATR using Wilder's EWM smoothing. Returns 0.0 on insufficient data."""
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


def _atr_z(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    period: int,
    atr_z_history: deque,
    zscore_window: int,
) -> tuple[float, float]:
    """ATR value and its z-score.

    Returns (atr_value, atr_z_score).
    """
    atr = _atr_wilder(highs, lows, closes, period)
    z = _rolling_zscore(atr, atr_z_history, zscore_window)
    return atr, z


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


def _vwap_dev_sigma(
    opens: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    volumes: np.ndarray,
) -> float:
    """VWAP deviation in sigma units: (close - session_vwap) / session_vwap_std.

    Uses typical price ((high+low+close)/3) for VWAP computation.
    Returns 0.0 on cold start or degenerate std.
    """
    if len(closes) < 2:
        return 0.0
    typical = (highs + lows + closes) / 3.0
    cum_tp_vol = np.cumsum(typical * volumes)
    cum_vol = np.cumsum(volumes)
    vwap_arr = np.where(cum_vol > 1e-10, cum_tp_vol / cum_vol, typical)
    vwap = float(vwap_arr[-1])
    std = float(np.std(closes - vwap_arr))
    if std < 1e-10:
        return 0.0
    return (float(closes[-1]) - vwap) / std


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


def _amihud_illiq_z(closes: np.ndarray, volumes: np.ndarray, zscore_window: int) -> float:
    """|log_return| / dollar_volume, z-scored vs rolling window.

    dollar_volume proxy: close * volume (no tick data required).
    Returns 0.0 on cold start or when all dollar volumes are zero.
    """
    if len(closes) < 2:
        return 0.0
    log_rets = np.abs(np.diff(np.log(np.maximum(closes, 1e-10))))
    dollar_vols = closes[1:] * np.maximum(volumes[1:], 1.0)
    illiq = log_rets / dollar_vols
    return _zscore_last(illiq, zscore_window)


def _high_52w_dist(closes: np.ndarray, window: int) -> float:
    """(close - rolling_max) / rolling_max: distance from the N-bar high.

    Returns 0.0 when close equals the rolling max (at the high).
    Returns negative float when below the high.
    """
    if len(closes) < 2:
        return 0.0
    w = min(window, len(closes))
    rolling_max = float(np.max(closes[-w:]))
    if rolling_max < 1e-10:
        return 0.0
    return float((float(closes[-1]) - rolling_max) / rolling_max)


def _rolling_stat_z(
    log_rets: np.ndarray,
    fn: Callable[[np.ndarray], float],
    window: int,
    zscore_window: int,
) -> float:
    """Apply fn over rolling windows of log_rets and z-score the result."""
    if len(log_rets) < window:
        return 0.0
    series = np.array(
        [fn(log_rets[max(0, i - window + 1) : i + 1]) for i in range(window - 1, len(log_rets))],
        dtype=float,
    )
    return _zscore_last(series, zscore_window)


def _ret_skew_z(closes: np.ndarray, skew_window: int, zscore_window: int) -> float:
    """Rolling return skewness, z-scored vs own history."""
    if len(closes) < skew_window + 3:
        return 0.0
    return _rolling_stat_z(
        np.diff(np.log(np.maximum(closes, 1e-10))), _skewness, skew_window, zscore_window
    )


def _ret_acf1_z(closes: np.ndarray, acf_window: int, zscore_window: int) -> float:
    """Rolling Pearson lag-1 autocorrelation of log returns, z-scored."""
    if len(closes) < acf_window + 2:
        return 0.0
    return _rolling_stat_z(
        np.diff(np.log(np.maximum(closes, 1e-10))), _pearson_acf1, acf_window, zscore_window
    )


def _skewness(arr: np.ndarray) -> float:
    """Fisher's skewness via scipy. Returns 0.0 on < 3 elements or zero std."""
    if len(arr) < 3:
        return 0.0
    result = float(_scipy_skew(arr))
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

        # Extract arrays for vectorized computation (full history)
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
        vol_ = float(last["volume"])
        bar_ts = last["ts"]

        # Ensure ts is timezone-aware UTC
        if isinstance(bar_ts, datetime) and bar_ts.tzinfo is None:
            bar_ts = bar_ts.replace(tzinfo=UTC)

        # --- ATR (needed by gap_z and informed_flow) ---
        atr_val = _atr_wilder(highs, lows, closes, config.adx_period)

        # ATR z-score: compute ATR for each suffix, then z-score the series
        zw = config.momentum_zscore_window
        atr_series = np.array(
            [
                _atr_wilder(highs[: i + 1], lows[: i + 1], closes[: i + 1], config.adx_period)
                for i in range(max(0, len(closes) - zw - 1), len(closes))
            ],
            dtype=float,
        )
        atr_z_val = _zscore_last(atr_series, min(zw, len(atr_series)))

        # --- Bar-level primitives ---
        bar_close_pos_val = _bar_close_pos(high_, low_, close_)

        range_bars = min(config.momentum_window_mid, len(bars))
        range_position_val = _range_position(
            close_,
            highs[-range_bars:],
            lows[-range_bars:],
        )

        # rel_volume: vol_ / mean(volumes over volume_zscore_window)
        vol_window = min(config.volume_zscore_window, len(volumes))
        mean_vol = float(np.mean(volumes[-vol_window:]))
        rel_volume_val = vol_ / mean_vol if mean_vol > 1e-10 else 1.0

        prev_close = float(closes[-2])
        # gap_z: (open - prev_close) / atr, z-scored over momentum_zscore_window
        gap_raw_series = np.array(
            [
                (float(bars[i]["open"]) - float(bars[i - 1]["close"]))
                / (_atr_wilder(highs[:i], lows[:i], closes[:i], config.adx_period) or 1.0)
                for i in range(max(1, len(bars) - zw), len(bars))
            ],
            dtype=float,
        )
        gap_z_val = _zscore_last(gap_raw_series, min(zw, len(gap_raw_series)))

        informed_flow_val = _informed_flow(open_, close_, atr_val)

        # ofi_z: OHLCV proxy, z-scored over ofi_zscore_window
        ofi_raw = (closes - lows) / (highs - lows + 1e-10) * volumes
        ofi_z_val = _zscore_last(ofi_raw, config.ofi_zscore_window)

        # cvd_slope_z: cumulative CVD slope over slope_bars, z-scored
        cvd_raw = (2.0 * closes - highs - lows) / (highs - lows + 1e-10) * volumes
        cum_cvd = np.cumsum(cvd_raw)
        slope_bars = config.cvd_slope_bars
        if len(cum_cvd) > slope_bars:
            cvd_slopes = np.array(
                [
                    (cum_cvd[i] - cum_cvd[i - slope_bars]) / slope_bars
                    for i in range(slope_bars, len(cum_cvd))
                ],
                dtype=float,
            )
            cvd_slope_z_val = _zscore_last(cvd_slopes, config.ofi_zscore_window)
        else:
            cvd_slope_z_val = 0.0

        # volume_z: rolling z-score of volume
        volume_z_val = _zscore_last(volumes, config.volume_zscore_window)

        vol_ratio_val = _vol_ratio(closes, config.vol_short_bars, config.vol_long_bars)

        # momentum_z_fast: log-return velocity over momentum_window_fast, z-scored
        wf = config.momentum_window_fast
        if len(closes) > wf:
            mom_fast_series = np.log(
                np.maximum(closes[wf:], 1e-10) / np.maximum(closes[:-wf], 1e-10)
            )
            momentum_z_fast_val = _zscore_last(mom_fast_series, config.momentum_zscore_window)
        else:
            momentum_z_fast_val = 0.0

        # momentum_z_mid: log-return velocity over momentum_window_mid, z-scored
        wm = config.momentum_window_mid
        if len(closes) > wm:
            mom_mid_series = np.log(
                np.maximum(closes[wm:], 1e-10) / np.maximum(closes[:-wm], 1e-10)
            )
            momentum_z_mid_val = _zscore_last(mom_mid_series, config.momentum_zscore_window)
        else:
            momentum_z_mid_val = 0.0

        # momentum_z_slow: log-return velocity over momentum_window_slow, z-scored
        wslow = config.momentum_window_slow
        if len(closes) > wslow:
            mom_slow_series = np.log(
                np.maximum(closes[wslow:], 1e-10) / np.maximum(closes[:-wslow], 1e-10)
            )
            momentum_z_slow_val = _zscore_last(mom_slow_series, config.momentum_zscore_window)
        else:
            momentum_z_slow_val = 0.0

        # momentum_reversal_z: 1-bar log return z-scored over fast zscore window
        reversal_raw = np.diff(np.log(np.maximum(closes, 1e-10)))
        reversal_window = min(config.momentum_zscore_window, len(reversal_raw))
        momentum_reversal_z_val = (
            _zscore_last(reversal_raw, reversal_window)
            if len(reversal_raw) >= reversal_window
            else 0.0
        )

        cmf_val = _cmf(highs, lows, closes, volumes, config.cmf_period)

        vwap_dev_sigma_val = _vwap_dev_sigma(opens, highs, lows, closes, volumes)

        # --- Session-level primitives (from cache; 1d TF defaults to neutral) ---
        if tf == "1d":
            poc_dist_atr_val = 0.0
            va_position_val = 0.5
            sr_support_dist_val = 0.0
            sr_resist_dist_val = 0.0
        else:
            poc_dist_atr_val = cache.poc_dist_atr
            va_position_val = cache.va_position
            sr_support_dist_val = cache.sr_support_dist
            sr_resist_dist_val = cache.sr_resist_dist

        # --- Regime-level primitives (all from cache — refreshed by caller) ---
        hmm_regime_prob_val = cache.hmm_regime_prob
        hmm_entropy_val = cache.hmm_entropy
        hmm_duration_val = cache.hmm_duration
        hurst_val = cache.hurst
        shannon_val = cache.shannon
        garch_ratio_val = cache.garch_ratio
        hma_slope_z_val = cache.hma_slope_z
        adx_val = cache.adx

        # --- Oscillators (shared deltas across RSI periods) ---
        _close_deltas = np.diff(closes.astype(float))
        _rsi_gains = np.where(_close_deltas > 0, _close_deltas, 0.0)
        _rsi_losses = np.where(_close_deltas < 0, -_close_deltas, 0.0)
        rsi_fast_val = (
            _rsi_wilder(_rsi_gains, _rsi_losses, config.rsi_fast_period)
            if len(closes) >= config.rsi_fast_period + 1
            else 50.0
        )
        rsi_mid_val = (
            _rsi_wilder(_rsi_gains, _rsi_losses, config.rsi_mid_period)
            if len(closes) >= config.rsi_mid_period + 1
            else 50.0
        )
        rsi_slow_val = (
            _rsi_wilder(_rsi_gains, _rsi_losses, config.rsi_slow_period)
            if len(closes) >= config.rsi_slow_period + 1
            else 50.0
        )
        cci_fast_val = _cci(highs, lows, closes, config.cci_fast_period)
        cci_mid_val = _cci(highs, lows, closes, config.cci_mid_period)
        cci_slow_val = _cci(highs, lows, closes, config.cci_slow_period)

        # --- Trend freshness ---
        aroon_fast_val = _aroon_osc(highs, lows, config.aroon_fast_period)
        aroon_slow_val = _aroon_osc(highs, lows, config.aroon_slow_period)

        # --- OFI divergence ---
        ofi_div_val = ofi_z_val - momentum_z_fast_val

        # --- Cross-asset primitives (all from cache — populated by update_cross_asset) ---
        vix_z_val = cache.vix_z
        flight_quality_val = cache.flight_quality
        yield_slope_z_val = cache.yield_slope_z

        # --- Calendar primitives ---
        in_ny_session_val = _in_ny_session(bar_ts, config)
        in_london_kz_val = _in_london_kz(bar_ts, config)
        in_overlap_val = _in_overlap(bar_ts, config)
        power_hour_val = _power_hour(bar_ts, config)
        opening_range_val = _opening_range(bar_ts, config)
        above_wk_vwap_val = cache.above_wk_vwap
        dow_sin_val, dow_cos_val = _dow_encoding(bar_ts)
        month_position_val = _month_position(bar_ts)

        # quarter_position: position within calendar quarter [0, 1]
        # month_in_quarter = 0, 1, or 2; day_in_quarter is approximate
        _month_in_q = (bar_ts.month - 1) % 3  # 0, 1, 2
        _day_in_q = _month_in_q * 30 + bar_ts.day
        quarter_position_val = min(1.0, _day_in_q / _QUARTER_LENGTH_DAYS)

        # days_to_month_end: normalized days remaining to month end [0, 1]
        _days_in_month = calendar.monthrange(bar_ts.year, bar_ts.month)[1]
        _days_remaining = _days_in_month - bar_ts.day
        days_to_month_end_val = _days_remaining / _days_in_month

        # --- Cross-timeframe primitives (from cache — populated when HTF bar arrives) ---
        ctf_momentum_val = cache.ctf_momentum
        ctf_vwap_align_val = cache.ctf_vwap_align
        ctf_regime_align_val = cache.ctf_regime_align

        # --- Statistical / liquidity ---
        amihud_illiq_z_val = _amihud_illiq_z(closes, volumes, config.amihud_zscore_window)
        high_52w_dist_val = _high_52w_dist(closes, config.high_52w_window)
        ret_skew_z_val = _ret_skew_z(closes, config.ret_skew_window, config.ret_skew_zscore_window)
        ret_acf1_z_val = _ret_acf1_z(closes, config.ret_acf_window, config.ret_acf_zscore_window)

        # Guard: replace any NaN/inf with 0.0 (cold-start safety)
        def _guard(v: float, fallback: float = 0.0) -> float:
            return v if math.isfinite(v) else fallback

        return FeatureVector(
            # Momentum (7)
            momentum_z_fast=_guard(momentum_z_fast_val),
            momentum_z_mid=_guard(momentum_z_mid_val),
            range_position=_guard(range_position_val, 0.5),
            bar_close_pos=_guard(bar_close_pos_val, 0.5),
            gap_z=_guard(gap_z_val),
            momentum_z_slow=_guard(momentum_z_slow_val),
            momentum_reversal_z=_guard(momentum_reversal_z_val),
            # Volume and order flow (8)
            informed_flow=_guard(informed_flow_val),
            volume_z=_guard(volume_z_val),
            ofi_z=_guard(ofi_z_val),
            ofi_div=_guard(ofi_div_val),
            cvd_slope_z=_guard(cvd_slope_z_val),
            cmf=_guard(cmf_val),
            rel_volume=_guard(rel_volume_val, 1.0),
            vwap_dev_sigma=_guard(vwap_dev_sigma_val),
            # Volatility (2)
            atr_z=_guard(atr_z_val),
            vol_ratio=_guard(vol_ratio_val, 1.0),
            # Session-level (4)
            poc_dist_atr=_guard(poc_dist_atr_val),
            va_position=_guard(va_position_val, 0.5),
            sr_support_dist=_guard(sr_support_dist_val),
            sr_resist_dist=_guard(sr_resist_dist_val),
            # Regime-level (11)
            hmm_regime_prob=_guard(hmm_regime_prob_val),
            hmm_entropy=_guard(hmm_entropy_val),
            hmm_duration=_guard(hmm_duration_val),
            hurst=_guard(hurst_val, 0.5),
            shannon=_guard(shannon_val, 1.0),
            garch_ratio=_guard(garch_ratio_val, 1.0),
            hma_slope_z=_guard(hma_slope_z_val),
            adx=_guard(adx_val),
            aroon_fast=_guard(aroon_fast_val),
            aroon_slow=_guard(aroon_slow_val),
            # Oscillators (6)
            rsi_fast=_guard(rsi_fast_val, 50.0),
            rsi_mid=_guard(rsi_mid_val, 50.0),
            rsi_slow=_guard(rsi_slow_val, 50.0),
            cci_fast=_guard(cci_fast_val),
            cci_mid=_guard(cci_mid_val),
            cci_slow=_guard(cci_slow_val),
            # Cross-asset (3)
            vix_z=_guard(vix_z_val),
            flight_quality=_guard(flight_quality_val),
            yield_slope_z=_guard(yield_slope_z_val),
            # Calendar (11)
            in_ny_session=in_ny_session_val,
            in_london_kz=in_london_kz_val,
            in_overlap=in_overlap_val,
            power_hour=power_hour_val,
            opening_range=opening_range_val,
            above_wk_vwap=above_wk_vwap_val,
            dow_sin=dow_sin_val,
            dow_cos=dow_cos_val,
            month_position=month_position_val,
            quarter_position=_guard(quarter_position_val, 0.0),
            days_to_month_end=_guard(days_to_month_end_val, 0.0),
            # Cross-timeframe (3)
            ctf_momentum=_guard(ctf_momentum_val),
            ctf_vwap_align=_guard(ctf_vwap_align_val),
            ctf_regime_align=_guard(ctf_regime_align_val),
            # Statistical / liquidity (4)
            amihud_illiq_z=_guard(amihud_illiq_z_val),
            high_52w_dist=_guard(high_52w_dist_val),
            ret_skew_z=_guard(ret_skew_z_val),
            ret_acf1_z=_guard(ret_acf1_z_val),
            # Cross-sectional (3, nullable — populated by Phase 139)
            momentum_rank_z=None,
            volume_rank_z=None,
            volatility_rank_z=None,
        )


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
        momentum_rank_z=None,
        volume_rank_z=None,
        volatility_rank_z=None,
    )
