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
        # ATR series computation
        atr_series = _atr_series_full(highs, lows, closes, config.adx_period)
        atr_val = float(atr_series[-1]) if len(atr_series) > 0 else 0.0
        # ATR z-score: pad with 0.0, then z-score the series
        atr_padded = np.concatenate([[0.0], atr_series])
        atr_z_series = _rolling_zscore_series(atr_padded, config.momentum_zscore_window)
        atr_z_val = float(atr_z_series[-1]) if len(atr_z_series) > 0 else 0.0

        # --- Bar-level primitives ---
        bar_close_pos_val = _bar_close_pos(high_, low_, close_)

        range_bars = min(config.momentum_window_mid, len(bars))
        range_position_val = _range_position(
            close_,
            highs[-range_bars:],
            lows[-range_bars:],
        )

        # rel_volume: vol_ / mean(volumes over volume_zscore_window)
        rel_volume_series = _rel_volume_series_full(volumes, config.volume_zscore_window)
        rel_volume_val = float(rel_volume_series[-1]) if len(rel_volume_series) > 0 else 1.0

        prev_close = float(closes[-2])
        # gap_z: (open - prev_close) / atr, z-scored over momentum_zscore_window
        gap_z_series = _gap_z_series_full(
            opens, highs, lows, closes, config.adx_period, config.momentum_zscore_window
        )
        gap_z_val = float(gap_z_series[-1]) if len(gap_z_series) > 0 else 0.0

        informed_flow_val = _informed_flow(open_, close_, atr_val)

        # ofi_z: OHLCV proxy, z-scored over ofi_zscore_window
        ofi_z_series = _ofi_z_series_full(closes, highs, lows, volumes, config.ofi_zscore_window)
        ofi_z_val = float(ofi_z_series[-1]) if len(ofi_z_series) > 0 else 0.0

        # cvd_slope_z: cumulative CVD slope over slope_bars, z-scored
        cvd_slope_z_series = _cvd_slope_z_series_full(
            closes, highs, lows, volumes, config.cvd_slope_bars, config.ofi_zscore_window
        )
        cvd_slope_z_val = float(cvd_slope_z_series[-1]) if len(cvd_slope_z_series) > 0 else 0.0

        # volume_z: rolling z-score of volume
        volume_z_series = _volume_z_series_full(volumes, config.volume_zscore_window)
        volume_z_val = float(volume_z_series[-1]) if len(volume_z_series) > 0 else 0.0

        vol_ratio_val = _vol_ratio(closes, config.vol_short_bars, config.vol_long_bars)

        # momentum_z_fast: log-return velocity over momentum_window_fast, z-scored
        momentum_z_fast_series = _momentum_z_series_full(
            closes, config.momentum_window_fast, config.momentum_zscore_window
        )
        momentum_z_fast_val = (
            float(momentum_z_fast_series[-1]) if len(momentum_z_fast_series) > 0 else 0.0
        )

        # momentum_z_mid: log-return velocity over momentum_window_mid, z-scored
        momentum_z_mid_series = _momentum_z_series_full(
            closes, config.momentum_window_mid, config.momentum_zscore_window
        )
        momentum_z_mid_val = (
            float(momentum_z_mid_series[-1]) if len(momentum_z_mid_series) > 0 else 0.0
        )

        # momentum_z_slow: log-return velocity over momentum_window_slow, z-scored
        momentum_z_slow_series = _momentum_z_series_full(
            closes, config.momentum_window_slow, config.momentum_zscore_window
        )
        momentum_z_slow_val = (
            float(momentum_z_slow_series[-1]) if len(momentum_z_slow_series) > 0 else 0.0
        )

        # momentum_reversal_z: 1-bar log return z-scored over fast zscore window
        momentum_reversal_z_series = _momentum_reversal_z_series_full(
            closes, config.momentum_zscore_window
        )
        momentum_reversal_z_val = (
            float(momentum_reversal_z_series[-1]) if len(momentum_reversal_z_series) > 0 else 0.0
        )

        cmf_val = _cmf(highs, lows, closes, volumes, config.cmf_period)

        # vwap_dev_sigma
        vwap_dev_sigma_series = _vwap_dev_sigma_series_full(opens, highs, lows, closes, volumes)
        vwap_dev_sigma_val = (
            float(vwap_dev_sigma_series[-1]) if len(vwap_dev_sigma_series) > 0 else 0.0
        )

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
        rsi_fast_series = _rsi_series_full(closes, config.rsi_fast_period)
        rsi_fast_val = float(rsi_fast_series[-1]) if len(rsi_fast_series) > 0 else 50.0

        rsi_mid_series = _rsi_series_full(closes, config.rsi_mid_period)
        rsi_mid_val = float(rsi_mid_series[-1]) if len(rsi_mid_series) > 0 else 50.0

        rsi_slow_series = _rsi_series_full(closes, config.rsi_slow_period)
        rsi_slow_val = float(rsi_slow_series[-1]) if len(rsi_slow_series) > 0 else 50.0
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
        amihud_illiq_z_series = _amihud_illiq_z_series_full(
            closes, volumes, config.amihud_zscore_window
        )
        amihud_illiq_z_val = (
            float(amihud_illiq_z_series[-1]) if len(amihud_illiq_z_series) > 0 else 0.0
        )

        high_52w_dist_series = _high_52w_dist_series_full(closes, config.high_52w_window)
        high_52w_dist_val = (
            float(high_52w_dist_series[-1]) if len(high_52w_dist_series) > 0 else 0.0
        )

        ret_skew_z_series = _ret_skew_z_series_full(
            closes, config.ret_skew_window, config.ret_skew_zscore_window
        )
        ret_skew_z_val = float(ret_skew_z_series[-1]) if len(ret_skew_z_series) > 0 else 0.0

        ret_acf1_z_series = _ret_acf1_z_series_full(
            closes, config.ret_acf_window, config.ret_acf_zscore_window
        )
        ret_acf1_z_val = float(ret_acf1_z_series[-1]) if len(ret_acf1_z_series) > 0 else 0.0

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

    @staticmethod
    def compute_batch(
        bars: list[dict],
        symbol: str,
        tf: str,
        cache: FeatureCache,
        config: FeatureFactoryConfig,
        warm_up_bars: int = 0,
    ) -> list[tuple[datetime, FeatureVector]]:
        """Compute FeatureVector for every bar in bars in O(n). Returns (bar_ts, fv) pairs.

        Precomputes all series_full functions once, then loops over bars indexing series[i].
        Non-series features (cmf, cci, aroon, vol_ratio, range_position, bar_close_pos, informed_flow)
        are computed per bar with bounded windows. Cache-backed features (hmm, hurst, etc.) are
        read from cache. Calendar features computed per bar from timestamps.
        """
        if len(bars) < 2:
            return []

        # Extract numpy arrays once
        opens = np.array([b["open"] for b in bars], dtype=float)
        highs = np.array([b["high"] for b in bars], dtype=float)
        lows = np.array([b["low"] for b in bars], dtype=float)
        closes = np.array([b["close"] for b in bars], dtype=float)
        volumes = np.array([b["volume"] for b in bars], dtype=float)

        # Precompute all series — call each _*_series_full once
        atr_series = _atr_series_full(highs, lows, closes, config.adx_period)
        atr_padded = np.concatenate([[0.0], atr_series])  # length = n
        atr_z_series = _rolling_zscore_series(atr_padded, config.momentum_zscore_window)

        gap_z_series = _gap_z_series_full(
            opens, highs, lows, closes, config.adx_period, config.momentum_zscore_window
        )
        rel_volume_series = _rel_volume_series_full(volumes, config.volume_zscore_window)
        ofi_z_series = _ofi_z_series_full(closes, highs, lows, volumes, config.ofi_zscore_window)
        cvd_slope_z_series = _cvd_slope_z_series_full(
            closes, highs, lows, volumes, config.cvd_slope_bars, config.ofi_zscore_window
        )
        volume_z_series = _volume_z_series_full(volumes, config.volume_zscore_window)

        momentum_z_fast_series = _momentum_z_series_full(
            closes, config.momentum_window_fast, config.momentum_zscore_window
        )
        momentum_z_mid_series = _momentum_z_series_full(
            closes, config.momentum_window_mid, config.momentum_zscore_window
        )
        momentum_z_slow_series = _momentum_z_series_full(
            closes, config.momentum_window_slow, config.momentum_zscore_window
        )
        momentum_reversal_z_series = _momentum_reversal_z_series_full(
            closes, config.momentum_zscore_window
        )

        vwap_dev_sigma_series = _vwap_dev_sigma_series_full(opens, highs, lows, closes, volumes)

        rsi_fast_series = _rsi_series_full(closes, config.rsi_fast_period)
        rsi_mid_series = _rsi_series_full(closes, config.rsi_mid_period)
        rsi_slow_series = _rsi_series_full(closes, config.rsi_slow_period)

        amihud_illiq_z_series = _amihud_illiq_z_series_full(
            closes, volumes, config.amihud_zscore_window
        )
        high_52w_dist_series = _high_52w_dist_series_full(closes, config.high_52w_window)
        ret_skew_z_series = _ret_skew_z_series_full(
            closes, config.ret_skew_window, config.ret_skew_zscore_window
        )
        ret_acf1_z_series = _ret_acf1_z_series_full(
            closes, config.ret_acf_window, config.ret_acf_zscore_window
        )

        # MIN_WINDOW for non-series features (cci_slow=40, aroon_slow=26, vol_ratio=21, cmf=20, range_position=20)
        MIN_WINDOW = 50
        results: list[tuple[datetime, FeatureVector]] = []

        for i in range(1, len(bars)):
            # Periodically refresh regime
            if i % config.regime_cache_refresh_bars == 0:
                window_start = max(0, i - MIN_WINDOW)
                cache.refresh_regime(bars[window_start : i + 1], config)

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
            atr_val = float(atr_series[i - 1]) if i - 1 < len(atr_series) else 0.0
            atr_z_val = float(atr_z_series[i]) if i < len(atr_z_series) else 0.0

            gap_z_val = float(gap_z_series[i]) if i < len(gap_z_series) else 0.0
            rel_volume_val = float(rel_volume_series[i]) if i < len(rel_volume_series) else 1.0
            ofi_z_val = float(ofi_z_series[i]) if i < len(ofi_z_series) else 0.0
            cvd_slope_z_val = float(cvd_slope_z_series[i]) if i < len(cvd_slope_z_series) else 0.0
            volume_z_val = float(volume_z_series[i]) if i < len(volume_z_series) else 0.0

            momentum_z_fast_val = (
                float(momentum_z_fast_series[i]) if i < len(momentum_z_fast_series) else 0.0
            )
            momentum_z_mid_val = (
                float(momentum_z_mid_series[i]) if i < len(momentum_z_mid_series) else 0.0
            )
            momentum_z_slow_val = (
                float(momentum_z_slow_series[i]) if i < len(momentum_z_slow_series) else 0.0
            )
            momentum_reversal_z_val = (
                float(momentum_reversal_z_series[i]) if i < len(momentum_reversal_z_series) else 0.0
            )

            vwap_dev_sigma_val = (
                float(vwap_dev_sigma_series[i]) if i < len(vwap_dev_sigma_series) else 0.0
            )

            rsi_fast_val = float(rsi_fast_series[i]) if i < len(rsi_fast_series) else 50.0
            rsi_mid_val = float(rsi_mid_series[i]) if i < len(rsi_mid_series) else 50.0
            rsi_slow_val = float(rsi_slow_series[i]) if i < len(rsi_slow_series) else 50.0

            amihud_illiq_z_val = (
                float(amihud_illiq_z_series[i]) if i < len(amihud_illiq_z_series) else 0.0
            )
            high_52w_dist_val = (
                float(high_52w_dist_series[i]) if i < len(high_52w_dist_series) else 0.0
            )
            ret_skew_z_val = float(ret_skew_z_series[i]) if i < len(ret_skew_z_series) else 0.0
            ret_acf1_z_val = float(ret_acf1_z_series[i]) if i < len(ret_acf1_z_series) else 0.0

            # Non-series features (compute on bounded window)
            bar_close_pos_val = _bar_close_pos(high_, low_, close_)

            range_bars = min(config.momentum_window_mid, len(window_bars))
            range_position_val = _range_position(
                close_, w_highs[-range_bars:], w_lows[-range_bars:]
            )

            informed_flow_val = _informed_flow(open_, close_, atr_val)
            vol_ratio_val = _vol_ratio(w_closes, config.vol_short_bars, config.vol_long_bars)
            cmf_val = _cmf(w_highs, w_lows, w_closes, w_volumes, config.cmf_period)

            # Session-level primitives (from cache; 1d TF defaults to neutral)
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

            # Cross-asset primitives (all from cache)
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

            _month_in_q = (bar_ts.month - 1) % 3
            _day_in_q = _month_in_q * 30 + bar_ts.day
            quarter_position_val = min(1.0, _day_in_q / _QUARTER_LENGTH_DAYS)

            _days_in_month = calendar.monthrange(bar_ts.year, bar_ts.month)[1]
            _days_remaining = _days_in_month - bar_ts.day
            days_to_month_end_val = _days_remaining / _days_in_month

            # Cross-timeframe primitives (from cache)
            ctf_momentum_val = cache.ctf_momentum
            ctf_vwap_align_val = cache.ctf_vwap_align
            ctf_regime_align_val = cache.ctf_regime_align

            # Guard function
            def _guard(v: float, fallback: float = 0.0) -> float:
                return v if math.isfinite(v) else fallback

            # Build FeatureVector
            fv = FeatureVector(
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
        momentum_rank_z=None,
        volume_rank_z=None,
        volatility_rank_z=None,
    )
