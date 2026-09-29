"""Price dynamics kernels (D-25)."""

from __future__ import annotations

import math
from collections import deque
from typing import TYPE_CHECKING

import numpy as np

from src.intelligence.feature_cache import FeatureCache
from src.intelligence.features.kernels._primitives import (
    _atr_series_full,
    _fixed_window_zscore_series,
    _is_valid_atr,
    _is_valid_atr_series,
    _kurtosis,
    _pearson_acf1,
    _percentile_rank,
    _rolling_mean_series,
    _rolling_std_series,
    _rolling_zscore_series,
    _skewness,
    _sliding_rolling_max,
    _sliding_rolling_min,
    _zscore_last,
    bounded_window_bars,
    wilder_memory_bars,
)
from src.intelligence.features.registry import Kernel
from src.intelligence.utils import safe_corr

if TYPE_CHECKING:
    pass


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


def _range_vs_atr(high: float, low: float, atr: float, close_: float, min_atr_pct: float) -> float:
    """Bar range relative to ATR: (H - L) / ATR_N. Unbounded positive.

    Returns 0.0 when atr is invalid per `_is_valid_atr` (todo 266: routed through
    the same relative floor as the 12 sibling ATR-ratio features, todo 237).
    """
    return (high - low) / atr if _is_valid_atr(atr, close_, min_atr_pct) else 0.0


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


def _range_pct(close: float, highs: np.ndarray, lows: np.ndarray, eps: float = 1e-10) -> float:
    """Rolling range as a fraction of price: (rolling_high_N - rolling_low_N) / C.

    Unbounded non-negative. Returns 0.0 when close is near zero.
    """
    if close < eps:
        return 0.0
    return (float(np.max(highs)) - float(np.min(lows))) / close


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


def _product(a: float, b: float) -> float:
    """Pure product of two already-computed parent scalars -- no new window.
    Shared by vol_body_product, ret_vol_product_fast, range_vol_product, and
    vol_skew_product (all four were byte-identical `a * b` bodies). Unbounded,
    symmetric around 0.
    """
    return a * b


def _up_vol_body_diff(up_vol_ratio: float, body_ratio: float) -> float:
    """up_vol_body_diff = up_vol_ratio_fast - body_ratio. Pure difference of
    Plan 02's up_vol_ratio_fast (bounded [0,1]) and Plan 01's body_ratio
    (bounded [-1,1]) -- no new window. Approximately bounded [-1, 1].
    """
    return up_vol_ratio - body_ratio


def _ret_vol_ratio(ret_lag: float, atr_z: float, eps: float = 1e-10) -> float:
    """ret_vol_ratio_fast = ret_lag_fast / atr_z. Pure ratio of Plan 01's
    ret_lag_fast and baseline atr_z -- no new window. Returns 0.0 when
    abs(atr_z) < eps (epsilon guard; degenerate near-zero volatility
    z-score). Unbounded, symmetric around 0.
    """
    if abs(atr_z) < eps:
        return 0.0
    return ret_lag / atr_z


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


def _gap_z_series_full(
    opens: np.ndarray,
    closes: np.ndarray,
    atr_raw: np.ndarray,
    atr_valid: np.ndarray,
    zscore_window: int,
) -> np.ndarray:
    """Gap-z series: ATR-normalized open gap, rolling z-scored.

    `atr_raw`/`atr_valid` are the shared ATR series/validity mask already
    computed once in `_precompute_series` (todo 269 -- previously this
    function recomputed its own `_atr_series_full(highs, lows, closes,
    period)`, a redundant second computation of the exact same array since
    both used `config.adx_period`; now the same array is threaded through,
    matching the pattern `_dist_from_high_series_full`/`_dist_from_low_series_full`
    already use). `atr_valid` is aligned index-for-index with `atr_padded`/
    `closes`, so `atr_for_gap[k] == atr_padded[k+1]` and the matching slice
    is `atr_valid[1:1+gap_high]`.
    """
    n = len(closes)
    result = np.zeros(n, dtype=float)
    if n < 2:
        return result

    # ATR series (length = n-1)
    atr_core = atr_raw

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
        gap_atr_valid = atr_valid[1 : 1 + gap_high]
        gap_raw = (opens[2 : 2 + gap_high] - closes[1 : 1 + gap_high]) / np.where(
            gap_atr_valid, atr_for_gap[:gap_high], 1.0
        )
        # Z-score the gap series
        gap_z_core = _rolling_zscore_series(np.concatenate([[0.0], gap_raw]), zscore_window)
        # Build result: position 0 = 0.0, position 1 = 0.0 (no prev close), then gap_z values.
        # gap_z_core[m] scores the gap at bar m + 1 (index 0 is the leading pad), so bar k takes
        # gap_z_core[k - 1]. Writing gap_z_core[k] to bar k read bar k + 1's open into row k
        # (one-bar lookahead) and left the last row at 0.0 (186-12).
        result = np.zeros(n, dtype=float)
        if len(gap_z_core) > 2:
            result[2:] = gap_z_core[1:]

    return result


def _bars_since_rolling_extreme_series_full(
    values: np.ndarray, window: int, mode: str
) -> np.ndarray:
    """result[i] == bars elapsed since the maximum (mode="max") or minimum
    (mode="min") of values[max(0, i-window+1):i+1] was last attained, as a
    float in [0, window-1]. result[i] == 0.0 means the extreme is the current
    bar. O(n) total via a monotonic deque of indices (each index enters and
    leaves the deque at most once); on ties, the most recent occurrence is
    treated as the current extreme.
    """
    n = len(values)
    out = np.zeros(n, dtype=float)
    if n == 0:
        return out
    dq: deque[int] = deque()
    for i in range(n):
        v = values[i]
        if mode == "max":
            while dq and values[dq[-1]] <= v:
                dq.pop()
        else:  # "min"
            while dq and values[dq[-1]] >= v:
                dq.pop()
        dq.append(i)
        while dq[0] <= i - window:
            dq.popleft()
        out[i] = float(i - dq[0])
    return out


def _bars_since_event_series_full(events: np.ndarray, window: int) -> np.ndarray:
    """result[i] == bars elapsed since the most recent True in
    events[max(0, i-window+1):i+1], as a float in [0, window-1].
    result[i] == 0.0 means events[i] is True. When no event occurred inside
    the trailing window, saturates to float(window-1) -- NOT 0.0 (which would
    falsely assert "an event just happened") and NOT NaN. O(n) total via a
    deque of True-event indices (each index enters and leaves at most once).
    """
    n = len(events)
    out = np.full(n, float(window - 1), dtype=float)
    if n == 0:
        return out
    dq: deque[int] = deque()
    for i in range(n):
        if events[i]:
            dq.append(i)
        while dq and dq[0] <= i - window:
            dq.popleft()
        out[i] = float(i - dq[-1]) if dq else float(window - 1)
    return out


def _dist_from_high_series_full(
    closes: np.ndarray,
    highs: np.ndarray,
    atr_padded: np.ndarray,
    atr_valid: np.ndarray,
    window: int,
) -> np.ndarray:
    """result[i] == streaming distance from the rolling high, ATR-normalized,
    at bar i. `atr_valid` is the precomputed `_is_valid_atr_series` mask
    (todo 268: hoisted by the caller and shared across all 4
    dist_from_high/low_fast/slow calls rather than recomputed per call)."""
    rolling_high = _sliding_rolling_max(highs, window)
    safe_atr = np.where(atr_valid, atr_padded, 1.0)
    raw = (rolling_high - closes.astype(float)) / safe_atr
    return np.where(atr_valid, raw, 0.0)


def _dist_from_low_series_full(
    closes: np.ndarray, lows: np.ndarray, atr_padded: np.ndarray, atr_valid: np.ndarray, window: int
) -> np.ndarray:
    """result[i] == streaming distance from the rolling low, ATR-normalized,
    at bar i. `atr_valid` is the precomputed `_is_valid_atr_series` mask
    (todo 268: hoisted by the caller and shared across all 4
    dist_from_high/low_fast/slow calls rather than recomputed per call)."""
    rolling_low = _sliding_rolling_min(lows, window)
    safe_atr = np.where(atr_valid, atr_padded, 1.0)
    raw = (closes.astype(float) - rolling_low) / safe_atr
    return np.where(atr_valid, raw, 0.0)


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


def _ret_autocorr_series_full(closes: np.ndarray, lag: int, use_abs: bool = False) -> np.ndarray:
    """Expanding-window lag-k Pearson autocorrelation of log returns, computed
    over ALL available history up to each bar. result[i] == streaming
    _ret_autocorr(closes[:i+1], lag). O(n) total via incremental running sums
    (one new pair added per bar, no window to re-sum).

    use_abs=True (Phase 151 Plan 03, todo 180): computes the identical
    construction over |log returns| instead of signed log returns --
    volatility-clustering (return-MAGNITUDE autocorrelation) rather than the
    directional autocorrelation the default (use_abs=False) callers
    (ret_autocorr_1/ret_autocorr_5) measure. Existing use_abs=False callers
    are byte-identical to the pre-refactor behavior.
    """
    n = len(closes)
    result = np.zeros(n, dtype=float)
    if n < 2:
        return result
    log_rets = np.diff(np.log(np.maximum(closes.astype(float), 1e-10)))
    if use_abs:
        log_rets = np.abs(log_rets)
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
    """result[i] == streaming safe_corr(H, L) over the trailing (expanding
    until saturated) `window` bars ending at bar i. O(n x window).
    """
    n = len(highs)
    result = np.zeros(n, dtype=float)
    h = highs.astype(float)
    lo = lows.astype(float)
    for i in range(n):
        w = min(window, i + 1)
        start = i + 1 - w
        result[i] = safe_corr(h[start : i + 1], lo[start : i + 1])
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
    k*var(open-to-close), k ~= 0.34, definitional). O(n) via the same
    cumsum-based rolling-variance building block _rolling_std_series already
    provides (var = std^2) -- both series share its expanding-until-window
    trailing semantics, so this is an exact, not approximate, replacement
    for a naive per-bar np.var(window_slice) loop.
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
    var_overnight = _rolling_std_series(overnight, window) ** 2
    var_o2c = _rolling_std_series(o2c, window) ** 2
    yz = var_overnight + k * var_o2c
    return _fixed_window_zscore_series(yz, zscore_window)


def _vol_velocity_z_series_full(series: np.ndarray, window: int) -> np.ndarray:
    """z-score of the rolling velocity (first difference) of `series` over
    `window`. result[i] == streaming velocity-of-series at bar i. Fully
    vectorized O(n).

    Generic over the input array (Phase 151 Plan 01 Task 2): originally
    written for atr_z (-> vol_velocity_z) but the same construction is
    reused byte-identically for momentum_z_fast/mid/slow (->
    momentum_z_velocity_fast/mid/slow) and vwap_dev_sigma (->
    vwap_dev_sigma_velocity).
    """
    n = len(series)
    if n < 2:
        return np.zeros(n, dtype=float)
    velocity = np.diff(series.astype(float))
    padded = np.concatenate([[0.0], velocity])
    return _fixed_window_zscore_series(padded, window)


def _intraday_noise_ratio_series_full(
    closes: np.ndarray, session_bars: int, eps: float = 1e-10
) -> np.ndarray:
    """result[i] == the intraday noise ratio (sum(|log_ret|) / |net log_ret|)
    over the trailing `session_bars` bars ending at bar i. O(n) via cumsum of
    |log_ret| and log_ret over a fixed `session_bars` window. Stays 0.0 until
    i >= session_bars (insufficient-history guard); 1.0 when net progress is
    at or near zero (no dominant direction).
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
# Kernels. A name beginning with "_" is an intermediate, not a FeatureVector column.
# Series kernels call the moved `_*_series_full` bodies unchanged. Declared memory is the sum of
# the window arguments along the body's chain; memory_check proves it (see the tolerance table
# in the 186-12 summary). Cumsum-based rolling statistics and Wilder recursions differ from a
# sliced recompute in the last bits, which is what `memory_atol` covers where it is non-zero.
# ---------------------------------------------------------------------------

_EPS = 1e-10


def _k(name, outputs, inputs, memory, compute, **kw) -> Kernel:
    return Kernel(
        name=name,
        outputs=tuple(outputs),
        inputs=tuple(inputs),
        memory=memory,
        compute=compute,
        **kw,
    )


def _fast_mid_slow(template: str) -> tuple[tuple[str, str], ...]:
    return tuple((scale, template.format(scale=scale)) for scale in ("fast", "mid", "slow"))


# --- ATR chain -----------------------------------------------------------------------------


def _compute_atr(x, config):
    atr_raw = _atr_series_full(x["high"], x["low"], x["close"], config.adx_period)
    return {"_atr_raw_padded": np.concatenate([[0.0], atr_raw])}


def _compute_atr_valid(x, config):
    return {
        "_atr_valid": _is_valid_atr_series(
            x["_atr_raw_padded"], x["close"], config.atr_normalization_min_pct
        )
    }


def _compute_atr_z(x, config):
    return {"atr_z": _rolling_zscore_series(x["_atr_raw_padded"], config.momentum_zscore_window)}


def _compute_gap_z(x, config):
    return {
        "gap_z": _gap_z_series_full(
            x["open"],
            x["close"],
            x["_atr_raw_padded"][1:],
            x["_atr_valid"],
            config.momentum_zscore_window,
        )
    }


# --- momentum, reversal, RSI ---------------------------------------------------------------


def _momentum_kernels() -> tuple[Kernel, ...]:
    out = []
    for scale, column in _fast_mid_slow("momentum_z_{scale}"):
        window = f"momentum_window_{scale}"
        out.append(
            _k(
                column,
                (column,),
                ("close",),
                lambda c, w=window: getattr(c, w) + c.momentum_zscore_window,
                lambda x, c, w=window, col=column: {
                    col: _momentum_z_series_full(
                        x["close"], getattr(c, w), c.momentum_zscore_window
                    )
                },
            )
        )
        velocity = f"momentum_z_velocity_{scale}"
        out.append(
            _k(
                velocity,
                (velocity,),
                (column,),
                lambda c: c.momentum_velocity_window + 1,
                lambda x, c, col=column, vel=velocity: {
                    vel: _vol_velocity_z_series_full(x[col], c.momentum_velocity_window)
                },
            )
        )
    return tuple(out)


def _rsi_kernels() -> tuple[Kernel, ...]:
    out = []
    for scale, column in _fast_mid_slow("rsi_{scale}"):
        period = f"rsi_{scale}_period"
        out.append(
            _k(
                column,
                (column,),
                ("close",),
                lambda c, p=period: wilder_memory_bars(getattr(c, p)) + getattr(c, p),
                lambda x, c, p=period, col=column: {
                    col: _rsi_series_full(x["close"], getattr(c, p))
                },
            )
        )
        velocity = f"rsi_velocity_{scale}"
        out.append(
            _k(
                velocity,
                (velocity,),
                (column,),
                lambda c: c.rsi_velocity_window + 1,
                lambda x, c, col=column, vel=velocity: {
                    vel: _vol_velocity_z_series_full(x[col], c.rsi_velocity_window)
                },
            )
        )
    return tuple(out)


# --- return statistics ---------------------------------------------------------------------


def _compute_ret_skew_z(x, config):
    return {
        "ret_skew_z": _ret_skew_z_series_full(
            x["close"], config.ret_skew_window, config.ret_skew_zscore_window
        )
    }


def _compute_ret_acf1_z(x, config):
    return {
        "ret_acf1_z": _ret_acf1_z_series_full(
            x["close"], config.ret_acf_window, config.ret_acf_zscore_window
        )
    }


def _compute_overnight_gap_z(x, config):
    return {
        "overnight_gap_z": _overnight_gap_z_series_full(
            x["open"], x["close"], config.overnight_gap_window
        )
    }


def _compute_high_52w_dist(x, config):
    return {"high_52w_dist": _high_52w_dist_series_full(x["close"], config.high_52w_window)}


def _compute_momentum_reversal_z(x, config):
    return {
        "momentum_reversal_z": _momentum_reversal_z_series_full(
            x["close"], config.momentum_zscore_window
        )
    }


def _compute_ret_kurtosis(x, config):
    return {
        f"ret_kurtosis_z_{scale}": _ret_kurtosis_z_series_full(
            x["close"], getattr(config, f"ret_kurtosis_{scale}"), config.ret_kurtosis_zscore_window
        )
        for scale in ("fast", "slow")
    }


def _compute_ret_autocorr(x, config):
    return {
        "ret_autocorr_1": _ret_autocorr_series_full(x["close"], 1),
        "ret_autocorr_5": _ret_autocorr_series_full(x["close"], 5),
    }


def _compute_abs_ret_autocorr(x, config):
    return {"abs_ret_autocorr_1": _ret_autocorr_series_full(x["close"], 1, use_abs=True)}


def _compute_streak_z(x, config):
    return {"streak_z": _streak_z_series_full(x["close"], config.streak_window)}


def _compute_vol_asymmetry_z(x, config):
    return {
        "vol_asymmetry_z": _vol_asymmetry_z_series_full(x["close"], config.vol_asymmetry_window)
    }


def _compute_intraday_noise_ratio(x, config):
    return {
        "intraday_noise_ratio": _intraday_noise_ratio_series_full(
            x["close"], config.intraday_noise_window
        )
    }


def _compute_high_low_corr(x, config):
    return {
        "high_low_corr": _high_low_corr_series_full(
            x["high"], x["low"], config.high_low_corr_window
        )
    }


def _scaled_series_kernel(name, template, inputs, memory_of, compute_of):
    """One kernel per fast/slow scale: name `{template}_{scale}`; `memory_of(config, scale)`
    and `compute_of(x, config, scale)` are the scale-specific memory and array."""
    out = []
    for scale in ("fast", "slow"):
        column = template.format(scale=scale)
        out.append(
            _k(
                column,
                (column,),
                inputs,
                lambda c, s=scale: memory_of(c, s),
                lambda x, c, s=scale, col=column: {col: compute_of(x, c, s)},
            )
        )
    return tuple(out)


_BREAKOUT_KERNELS = (
    *_scaled_series_kernel(
        "dist_from_high",
        "dist_from_high_{scale}",
        ("close", "high", "_atr_raw_padded", "_atr_valid"),
        lambda c, s: getattr(c, f"dist_window_{s}"),
        lambda x, c, s: _dist_from_high_series_full(
            x["close"],
            x["high"],
            x["_atr_raw_padded"],
            x["_atr_valid"],
            getattr(c, f"dist_window_{s}"),
        ),
    ),
    *_scaled_series_kernel(
        "dist_from_low",
        "dist_from_low_{scale}",
        ("close", "low", "_atr_raw_padded", "_atr_valid"),
        lambda c, s: getattr(c, f"dist_window_{s}"),
        lambda x, c, s: _dist_from_low_series_full(
            x["close"],
            x["low"],
            x["_atr_raw_padded"],
            x["_atr_valid"],
            getattr(c, f"dist_window_{s}"),
        ),
    ),
    *_scaled_series_kernel(
        "range_pct",
        "range_pct_{scale}",
        ("close", "high", "low"),
        lambda c, s: getattr(c, f"range_window_{s}"),
        lambda x, c, s: _range_pct_series_full(
            x["close"], x["high"], x["low"], getattr(c, f"range_window_{s}")
        ),
    ),
    *_scaled_series_kernel(
        "stoch_k",
        "stoch_k_{scale}",
        ("close", "high", "low"),
        lambda c, s: getattr(c, f"stoch_window_{s}"),
        lambda x, c, s: _stoch_k_series_full(
            x["close"], x["high"], x["low"], getattr(c, f"stoch_window_{s}")
        ),
    ),
    *_scaled_series_kernel(
        "price_percentile",
        "price_percentile_{scale}",
        ("close",),
        lambda c, s: getattr(c, f"percentile_window_{s}"),
        lambda x, c, s: _price_percentile_series_full(
            x["close"], getattr(c, f"percentile_window_{s}")
        ),
    ),
    *_scaled_series_kernel(
        "efficiency_ratio",
        "efficiency_ratio_{scale}",
        ("close",),
        lambda c, s: getattr(c, f"efficiency_window_{s}") + 1,
        lambda x, c, s: _efficiency_ratio_series_full(
            x["close"], getattr(c, f"efficiency_window_{s}")
        ),
    ),
    *_scaled_series_kernel(
        "updown_ratio",
        "updown_ratio_{scale}",
        ("close",),
        lambda c, s: getattr(c, f"updown_ratio_{s}") + 1,
        lambda x, c, s: _updown_ratio_series_full(x["close"], getattr(c, f"updown_ratio_{s}")),
    ),
    *_scaled_series_kernel(
        "realized_var_ratio",
        "realized_var_ratio_{scale}",
        ("close",),
        lambda c, s: c.realized_var_slow + 1,
        lambda x, c, s: _realized_var_ratio_series_full(
            x["close"], c.realized_var_fast, c.realized_var_slow
        ),
    ),
    *_scaled_series_kernel(
        "bb_pct_b",
        "bb_pct_b_{scale}",
        ("close",),
        lambda c, s: getattr(c, f"bb_pct_b_{s}"),
        lambda x, c, s: _bb_pct_b_series_full(x["close"], getattr(c, f"bb_pct_b_{s}")),
    ),
    *_scaled_series_kernel(
        "hv_z",
        "hv_z_{scale}",
        ("close",),
        lambda c, s: 2 * getattr(c, f"hv_{s}") + 1,
        lambda x, c, s: _hv_z_series_full(x["close"], getattr(c, f"hv_{s}")),
    ),
)


def _compute_variance_ratio(x, config):
    return {
        f"variance_ratio_{scale}": _variance_ratio_series_full(
            x["close"], getattr(config, f"variance_ratio_{scale}")
        )
        for scale in ("fast", "slow")
    }


def _compute_hv_ratio(x, config):
    return {"hv_ratio": _hv_ratio_series_full(x["close"], config.hv_fast, config.hv_ratio_window)}


def _compute_parkinson(x, config):
    return {
        "parkinson_vol_z": _parkinson_vol_z_series_full(
            x["high"], x["low"], config.parkinson_vol_window, config.parkinson_vol_zscore_window
        )
    }


def _compute_garman_klass(x, config):
    return {
        "garman_klass_vol_z": _garman_klass_vol_z_series_full(
            x["open"],
            x["high"],
            x["low"],
            x["close"],
            config.garman_klass_vol_window,
            config.garman_klass_vol_zscore_window,
        )
    }


def _compute_yang_zhang(x, config):
    return {
        "yang_zhang_vol_z": _yang_zhang_vol_z_series_full(
            x["open"],
            x["close"],
            config.yang_zhang_vol_window,
            config.yang_zhang_vol_zscore_window,
        )
    }


def _compute_vol_of_vol(x, config):
    return {"vol_of_vol": _vol_of_vol_series_full(x["atr_z"], config.vol_of_vol_window)}


def _compute_vol_velocity_z(x, config):
    return {"vol_velocity_z": _vol_velocity_z_series_full(x["atr_z"], config.vol_velocity_window)}


def _compute_range_to_close(x, config):
    return {"range_to_close": _range_to_close_series_full(x["high"], x["low"], x["close"])}


def _compute_true_range_pct(x, config):
    return {"true_range_pct": _true_range_pct_series_full(x["high"], x["low"], x["close"])}


def _compute_vol_velocity_diffs(x, config):
    """Row-to-row difference of the three volatility z-scores (row 0 has no previous row)."""
    out = {}
    for name, source in (
        ("parkinson_vol_velocity", "parkinson_vol_z"),
        ("garman_klass_vol_velocity", "garman_klass_vol_z"),
        ("yang_zhang_vol_velocity", "yang_zhang_vol_z"),
    ):
        z = x[source]
        diff = np.zeros(len(z))
        diff[1:] = z[1:] - z[:-1]
        out[name] = diff
    return out


# --- recency and event masks ---------------------------------------------------------------


def _compute_abs_log_ret(x, config):
    log_ret = np.abs(np.diff(np.log(np.maximum(x["close"].astype(float), _EPS))))
    return {"_abs_log_ret": np.concatenate([[0.0], log_ret])}


def _recency_kernels() -> tuple[Kernel, ...]:
    out = []
    for scale in ("fast", "slow"):
        window = f"dist_window_{scale}"
        for label, source, mode in (("high", "high", "max"), ("low", "low", "min")):
            column = f"bars_since_{label}_{scale}"
            out.append(
                _k(
                    column,
                    (column,),
                    (source,),
                    lambda c, w=window: getattr(c, w),
                    lambda x, c, w=window, s=source, m=mode, col=column: {
                        col: _bars_since_rolling_extreme_series_full(x[s], getattr(c, w), m)
                    },
                )
            )
        event = f"_extreme_move_event_{scale}"
        out.append(
            _k(
                event,
                (event,),
                ("_abs_log_ret",),
                lambda c, w=window: getattr(c, w),
                lambda x, c, w=window, ev=event: {
                    ev: x["_abs_log_ret"]
                    > c.extreme_move_sigma_threshold
                    * _rolling_std_series(x["_abs_log_ret"], getattr(c, w))
                },
            )
        )
        column = f"bars_since_extreme_move_{scale}"
        out.append(
            _k(
                column,
                (column,),
                (event,),
                lambda c, w=window: getattr(c, w),
                lambda x, c, w=window, ev=event, col=column: {
                    col: _bars_since_event_series_full(x[ev], getattr(c, w))
                },
            )
        )
    for label, source, mode in (("52w_high", "high", "max"), ("52w_low", "low", "min")):
        column = f"bars_since_{label}"
        out.append(
            _k(
                column,
                (column,),
                (source,),
                lambda c: c.high_52w_window,
                lambda x, c, s=source, m=mode, col=column: {
                    col: _bars_since_rolling_extreme_series_full(x[s], c.high_52w_window, m)
                },
            )
        )
    return tuple(out)


# --- per-bar scalars -----------------------------------------------------------------------


def _compute_bar_shape(x, config):
    o, h, lo, c = (x[f].tolist() for f in ("open", "high", "low", "close"))
    n = len(c)
    out = {
        name: np.empty(n)
        for name in (
            "bar_close_pos",
            "body_ratio",
            "upper_wick_ratio",
            "lower_wick_ratio",
            "close_vs_open_direction",
        )
    }
    for i in range(n):
        out["bar_close_pos"][i] = _bar_close_pos(h[i], lo[i], c[i])
        out["body_ratio"][i] = _body_ratio(o[i], h[i], lo[i], c[i])
        out["upper_wick_ratio"][i] = _upper_wick_ratio(o[i], h[i], lo[i], c[i])
        out["lower_wick_ratio"][i] = _lower_wick_ratio(o[i], h[i], lo[i], c[i])
        out["close_vs_open_direction"][i] = _close_vs_open_direction(o[i], c[i])
    return out


def _compute_range_vs_atr(x, config):
    h, lo, c = (x[f].tolist() for f in ("high", "low", "close"))
    atr = x["_atr_raw_padded"].tolist()
    return {
        "range_vs_atr": np.array(
            [
                _range_vs_atr(h[i], lo[i], atr[i], c[i], config.atr_normalization_min_pct)
                for i in range(len(c))
            ]
        )
    }


def _compute_prev_close_scalars(x, config):
    """Scalars pairing a bar with the previous close; row 0 has none and is NaN."""
    o, h, lo, c = (x[f].tolist() for f in ("open", "high", "low", "close"))
    n = len(c)
    names = ("overnight_gap", "range_efficiency", "open_ret", "intraday_ret", "open_vs_intraday")
    out = {name: np.full(n, np.nan) for name in names}
    for i in range(1, n):
        prev = c[i - 1]
        out["overnight_gap"][i] = _overnight_gap(o[i], prev)
        out["range_efficiency"][i] = _range_efficiency(c[i], prev, h[i], lo[i])
        open_ret = _open_ret(o[i], prev)
        intraday = _intraday_ret(c[i], o[i])
        out["open_ret"][i] = open_ret
        out["intraday_ret"][i] = intraday
        out["open_vs_intraday"][i] = _open_vs_intraday(open_ret, intraday)
    return out


def _ret_lag_kernels() -> tuple[Kernel, ...]:
    out = [
        _k(
            "ret_lag_short",
            ("ret_lag_1", "ret_lag_2", "ret_lag_3"),
            ("close",),
            lambda c: 3,
            lambda x, c: {
                "ret_lag_1": np.array(
                    [_ret_lag_1(x["close"][: i + 1]) for i in range(len(x["close"]))]
                ),
                "ret_lag_2": np.array(
                    [_ret_lag_2(x["close"][: i + 1]) for i in range(len(x["close"]))]
                ),
                "ret_lag_3": np.array(
                    [_ret_lag_3(x["close"][: i + 1]) for i in range(len(x["close"]))]
                ),
            },
        )
    ]
    for scale, fn in (("fast", _ret_lag_fast), ("mid", _ret_lag_mid), ("slow", _ret_lag_slow)):
        window = f"ret_lag_{scale}"
        column = window
        out.append(
            _k(
                column,
                (column,),
                ("close",),
                lambda c, w=window: getattr(c, w),
                lambda x, c, w=window, f=fn, col=column: {
                    col: np.array(
                        [f(x["close"][: i + 1], getattr(c, w)) for i in range(len(x["close"]))]
                    )
                },
            )
        )
    return tuple(out)


def _compute_bounded_window_scalars(x, config):
    """range_position, vol_ratio, CCI and Aroon over compute_batch's bounded window.

    Row i reads rows [max(0, i - n), i] with n = bounded_window_bars(config), so memory is n.
    """
    h, lo, c = x["high"], x["low"], x["close"]
    n_rows = len(c)
    window = bounded_window_bars(config)
    names = (
        "range_position",
        "vol_ratio",
        "cci_fast",
        "cci_mid",
        "cci_slow",
        "aroon_fast",
        "aroon_slow",
    )
    out = {name: np.empty(n_rows) for name in names}
    for i in range(n_rows):
        start = max(0, i - window)
        w_h, w_l, w_c = h[start : i + 1], lo[start : i + 1], c[start : i + 1]
        range_bars = min(config.momentum_window_mid, i + 1 - start)
        out["range_position"][i] = _range_position(
            float(c[i]), w_h[-range_bars:], w_l[-range_bars:]
        )
        out["vol_ratio"][i] = _vol_ratio(w_c, config.vol_short_bars, config.vol_long_bars)
        out["cci_fast"][i] = _cci(w_h, w_l, w_c, config.cci_fast_period)
        out["cci_mid"][i] = _cci(w_h, w_l, w_c, config.cci_mid_period)
        out["cci_slow"][i] = _cci(w_h, w_l, w_c, config.cci_slow_period)
        out["aroon_fast"][i] = _aroon_osc(w_h, w_l, config.aroon_fast_period)
        out["aroon_slow"][i] = _aroon_osc(w_h, w_l, config.aroon_slow_period)
    return out


def _compute_ret_vol_ratio_fast(x, config):
    lag, atr_z = x["ret_lag_fast"].tolist(), x["atr_z"].tolist()
    return {
        "ret_vol_ratio_fast": np.array(
            [_ret_vol_ratio(a, b) for a, b in zip(lag, atr_z, strict=True)]
        )
    }


def _compute_price_only_products(x, config):
    """Window-free products of price-origin parents, in the operand order compute_batch uses."""
    return {
        "momentum_vol_regime_product": x["momentum_z_fast"] * x["hv_ratio"],
        "quarter_momentum_product": x["quarter_position"] * x["momentum_z_fast"],
        "variance_ratio_momentum_product": x["variance_ratio_fast"] * x["momentum_z_fast"],
    }


def _compute_cache_products(x, config):
    """Products of the cache-backed bar statistics (adx, hurst) with the momentum columns."""
    return {
        "momentum_trend_product": x["momentum_z_fast"] * x["adx"],
        "reversion_hurst_product": x["momentum_reversal_z"] * x["hurst"],
    }


# --- bar statistics ------------------------------------------------------------------------

_BAR_STATISTICS = ("hurst", "shannon", "garch_ratio", "hma_slope_z", "adx")


def _compute_bar_statistics_refresh(x, config):
    """Replay of FeatureCache.refresh_regime at compute_batch's cadence on a fresh cache.

    The cache refreshes at rows i >= 1 with i % regime_cache_refresh_bars == 0 on bars
    [max(0, i - hurst_window), i], then the loop reads the five values at that same row; row 0
    holds the cache's initial values.
    """
    o, h, lo, c, v = (x[f].tolist() for f in ("open", "high", "low", "close", "volume"))
    bars = [
        {"open": o[i], "high": h[i], "low": lo[i], "close": c[i], "volume": v[i]}
        for i in range(len(c))
    ]
    cache = FeatureCache()
    out = {name: np.empty(len(bars)) for name in _BAR_STATISTICS}
    for i in range(len(bars)):
        if i >= 1 and i % config.regime_cache_refresh_bars == 0:
            cache.refresh_regime(bars[max(0, i - config.hurst_window) : i + 1], config)
        for name in _BAR_STATISTICS:
            out[name][i] = getattr(cache, name)
    return out


def _bounded_memory(config) -> int:
    return bounded_window_bars(config)


KERNELS = (
    _k(
        "atr_wilder",
        ("_atr_raw_padded",),
        ("high", "low", "close"),
        lambda c: wilder_memory_bars(c.adx_period),
        _compute_atr,
    ),
    _k("atr_valid", ("_atr_valid",), ("_atr_raw_padded", "close"), lambda c: 0, _compute_atr_valid),
    _k(
        "atr_z",
        ("atr_z",),
        ("_atr_raw_padded",),
        lambda c: c.momentum_zscore_window,
        _compute_atr_z,
    ),
    _k(
        "gap_z",
        ("gap_z",),
        ("open", "close", "_atr_raw_padded", "_atr_valid"),
        lambda c: c.momentum_zscore_window + 2,
        _compute_gap_z,
    ),
    *_momentum_kernels(),
    _k(
        "momentum_reversal_z",
        ("momentum_reversal_z",),
        ("close",),
        lambda c: c.momentum_zscore_window + 1,
        _compute_momentum_reversal_z,
    ),
    *_rsi_kernels(),
    _k(
        "ret_skew_z",
        ("ret_skew_z",),
        ("close",),
        lambda c: c.ret_skew_window + c.ret_skew_zscore_window + 1,
        _compute_ret_skew_z,
    ),
    _k(
        "ret_acf1_z",
        ("ret_acf1_z",),
        ("close",),
        lambda c: c.ret_acf_window + c.ret_acf_zscore_window + 1,
        _compute_ret_acf1_z,
    ),
    _k(
        "overnight_gap_z",
        ("overnight_gap_z",),
        ("open", "close"),
        lambda c: c.overnight_gap_window + 1,
        _compute_overnight_gap_z,
    ),
    _k(
        "high_52w_dist",
        ("high_52w_dist",),
        ("close",),
        lambda c: c.high_52w_window,
        _compute_high_52w_dist,
    ),
    _k(
        "ret_kurtosis_z",
        ("ret_kurtosis_z_fast", "ret_kurtosis_z_slow"),
        ("close",),
        lambda c: c.ret_kurtosis_slow + c.ret_kurtosis_zscore_window + 1,
        _compute_ret_kurtosis,
    ),
    _k(
        "ret_autocorr",
        ("ret_autocorr_1", "ret_autocorr_5"),
        ("close",),
        lambda c: 0,
        _compute_ret_autocorr,
        path_dependent=True,
        path_dependent_reason="expanding-window autocorrelation over all history since the series start",
    ),
    _k(
        "abs_ret_autocorr",
        ("abs_ret_autocorr_1",),
        ("close",),
        lambda c: 0,
        _compute_abs_ret_autocorr,
        path_dependent=True,
        path_dependent_reason="expanding-window autocorrelation over all history since the series start",
    ),
    _k(
        "streak_z",
        ("streak_z",),
        ("close",),
        lambda c: 0,
        _compute_streak_z,
        path_dependent=True,
        path_dependent_reason="the signed streak length is unbounded, so no finite window reproduces it",
    ),
    _k(
        "vol_asymmetry_z",
        ("vol_asymmetry_z",),
        ("close",),
        lambda c: 2 * c.vol_asymmetry_window + 1,
        _compute_vol_asymmetry_z,
    ),
    _k(
        "intraday_noise_ratio",
        ("intraday_noise_ratio",),
        ("close",),
        lambda c: c.intraday_noise_window + 1,
        _compute_intraday_noise_ratio,
    ),
    _k(
        "high_low_corr",
        ("high_low_corr",),
        ("high", "low"),
        lambda c: c.high_low_corr_window,
        _compute_high_low_corr,
    ),
    _k(
        "variance_ratio",
        ("variance_ratio_fast", "variance_ratio_slow"),
        ("close",),
        lambda c: 0,
        _compute_variance_ratio,
        path_dependent=True,
        path_dependent_reason="full-sample Lo-MacKinlay estimator over all history since the series start",
    ),
    *_BREAKOUT_KERNELS,
    _k(
        "hv_ratio",
        ("hv_ratio",),
        ("close",),
        lambda c: c.hv_fast + c.hv_ratio_window + 1,
        _compute_hv_ratio,
    ),
    _k(
        "parkinson_vol_z",
        ("parkinson_vol_z",),
        ("high", "low"),
        lambda c: c.parkinson_vol_window + c.parkinson_vol_zscore_window,
        _compute_parkinson,
    ),
    _k(
        "garman_klass_vol_z",
        ("garman_klass_vol_z",),
        ("open", "high", "low", "close"),
        lambda c: c.garman_klass_vol_window + c.garman_klass_vol_zscore_window,
        _compute_garman_klass,
    ),
    _k(
        "yang_zhang_vol_z",
        ("yang_zhang_vol_z",),
        ("open", "close"),
        lambda c: c.yang_zhang_vol_window + c.yang_zhang_vol_zscore_window + 1,
        _compute_yang_zhang,
    ),
    _k(
        "vol_velocity_diffs",
        ("parkinson_vol_velocity", "garman_klass_vol_velocity", "yang_zhang_vol_velocity"),
        ("parkinson_vol_z", "garman_klass_vol_z", "yang_zhang_vol_z"),
        lambda c: 1,
        _compute_vol_velocity_diffs,
    ),
    _k(
        "vol_of_vol",
        ("vol_of_vol",),
        ("atr_z",),
        lambda c: 2 * c.vol_of_vol_window,
        _compute_vol_of_vol,
    ),
    _k(
        "vol_velocity_z",
        ("vol_velocity_z",),
        ("atr_z",),
        lambda c: c.vol_velocity_window + 1,
        _compute_vol_velocity_z,
    ),
    _k(
        "range_to_close",
        ("range_to_close",),
        ("high", "low", "close"),
        lambda c: 0,
        _compute_range_to_close,
    ),
    _k(
        "true_range_pct",
        ("true_range_pct",),
        ("high", "low", "close"),
        lambda c: 1,
        _compute_true_range_pct,
    ),
    _k("abs_log_ret", ("_abs_log_ret",), ("close",), lambda c: 1, _compute_abs_log_ret),
    *_recency_kernels(),
    _k(
        "bar_shape",
        (
            "bar_close_pos",
            "body_ratio",
            "upper_wick_ratio",
            "lower_wick_ratio",
            "close_vs_open_direction",
        ),
        ("open", "high", "low", "close"),
        lambda c: 0,
        _compute_bar_shape,
    ),
    _k(
        "range_vs_atr",
        ("range_vs_atr",),
        ("high", "low", "close", "_atr_raw_padded"),
        lambda c: 0,
        _compute_range_vs_atr,
    ),
    _k(
        "prev_close_scalars",
        ("overnight_gap", "range_efficiency", "open_ret", "intraday_ret", "open_vs_intraday"),
        ("open", "high", "low", "close"),
        lambda c: 1,
        _compute_prev_close_scalars,
    ),
    *_ret_lag_kernels(),
    _k(
        "bounded_window_scalars",
        (
            "range_position",
            "vol_ratio",
            "cci_fast",
            "cci_mid",
            "cci_slow",
            "aroon_fast",
            "aroon_slow",
        ),
        ("high", "low", "close"),
        _bounded_memory,
        _compute_bounded_window_scalars,
    ),
    _k(
        "ret_vol_ratio_fast",
        ("ret_vol_ratio_fast",),
        ("ret_lag_fast", "atr_z"),
        lambda c: 0,
        _compute_ret_vol_ratio_fast,
    ),
    _k(
        "bar_statistics_refresh",
        _BAR_STATISTICS,
        ("open", "high", "low", "close", "volume"),
        lambda c: 0,
        _compute_bar_statistics_refresh,
        path_dependent=True,
        path_dependent_reason="refresh cadence counts from row 0 and the hma slope history accumulates across refreshes",
    ),
    _k(
        "price_only_products",
        (
            "momentum_vol_regime_product",
            "quarter_momentum_product",
            "variance_ratio_momentum_product",
        ),
        ("momentum_z_fast", "hv_ratio", "quarter_position", "variance_ratio_fast"),
        lambda c: 0,
        _compute_price_only_products,
    ),
    _k(
        "cache_products",
        ("momentum_trend_product", "reversion_hurst_product"),
        ("momentum_z_fast", "adx", "momentum_reversal_z", "hurst"),
        lambda c: 0,
        _compute_cache_products,
    ),
)
