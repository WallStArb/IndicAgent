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
