"""Shared rolling and ATR helpers imported by kernels and feature_factory (D-25)."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import numpy as np
from scipy import stats

from src.intelligence.features.contract.registry import Kernel

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

# Default divide-by-zero guard of the kernels' eps arguments, and the std below which a z-score is 0.
EPS = 1e-10
STD_FLOOR = 1e-8

# A Wilder recursion (ATR, RSI) forgets its seed geometrically: after `WILDER_MEMORY_HALF_LIVES *
# period` bars the seed weight is (1 - 1/period) ** (40 * period) < exp(-40), about 4e-18, below
# float64 resolution. A derived bound, not a tunable.
WILDER_MEMORY_HALF_LIVES = 40


def wilder_memory_bars(period: int) -> int:
    """Bars after which a Wilder recursion with `period` no longer depends on its seed."""
    return WILDER_MEMORY_HALF_LIVES * max(int(period), 1)


def wilder_rsi_series(closes: np.ndarray, period: int) -> np.ndarray:
    """Wilder RSI at every bar in O(n): the one implementation (kernel columns rsi_*, the live
    cache's scalar RSI and the batch CTF momentum series all call it).

    Wilder's definition: the first RSI sits at index `period` and averages the first `period`
    price changes (the SMA seed); later bars smooth with alpha = 1 / period. Bars before index
    `period` have fewer than `period` changes and stay at the 50.0 cold start, as does a flat
    window (no gains and no losses). A window with gains and no losses is 100.0.
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


def bounded_window_bars(config) -> int:
    """compute_batch's per-bar window: the longest look-back of the bounded-window scalars
    (CCI slow, Aroon slow, long volatility ratio, CMF), so each reads rows [i - n, i]."""
    return max(
        config.cci_slow_period,
        config.aroon_slow_period,
        config.vol_long_bars,
        config.cmf_period,
    )


def ts_ns_to_datetimes(ts: np.ndarray) -> list[datetime]:
    """int64 UTC nanoseconds to aware datetimes by integer arithmetic (never float seconds)."""
    return [_EPOCH + timedelta(microseconds=int(ns) // 1000) for ns in ts]


# The last unique_datetimes call: (timestamps, inverse, datetimes). The calendar and control
# kernels of one compute_kernels call all read the same `ts`, so they share one conversion.
_LAST_UNIQUE_TS: tuple[np.ndarray, np.ndarray, tuple[datetime, ...]] | None = None


def unique_datetimes(ts: np.ndarray) -> tuple[np.ndarray, tuple[datetime, ...]]:
    """(inverse, datetimes) with datetimes[inverse[i]] the UTC datetime of ts[i].

    Each distinct timestamp is converted once (ts_ns_to_datetimes, so the same integer
    arithmetic), and the result of the last call is kept and reused when the same timestamps
    come again. Every calendar value is a pure function of the timestamp, so a kernel computes
    per distinct timestamp and scatters with `inverse`.
    """
    global _LAST_UNIQUE_TS
    last = _LAST_UNIQUE_TS
    if last is not None and np.array_equal(last[0], ts):
        return last[1], last[2]
    unique, inverse = np.unique(ts, return_inverse=True)
    result = (inverse.reshape(-1), tuple(ts_ns_to_datetimes(unique)))
    _LAST_UNIQUE_TS = (np.array(ts, copy=True), *result)
    return result


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


def _cumsum_window_moments(
    arr: np.ndarray, window: int, *, squares: bool = True
) -> tuple[np.ndarray, np.ndarray | None]:
    """Trailing mean and clamped variance of every expanding-then-saturated window, by cumsums.

    Row i covers arr[max(0, i - window + 1):i + 1] (effective size min(window, i + 1)). The
    mean is (cs[i] - cs[start - 1]) / eff_w and the variance max(s2 / eff_w - mean * mean, 0.0)
    with the clamp keeping a NaN and never turning a value into NaN. Each operation is the
    IEEE operation the per-row loops this replaces performed, in the same order, so the
    results are bit-identical to them. With `squares` False only the mean is computed and the
    variance is None.
    """
    n = len(arr)
    eff_w = np.minimum(window, np.arange(1, n + 1))
    prev = np.arange(n) + 1 - eff_w - 1  # index of cs just before the window; -1 means none

    def window_sums(values: np.ndarray) -> np.ndarray:
        cs = np.cumsum(values)
        before = np.where(prev >= 0, cs[np.maximum(prev, 0)], 0.0)
        return cs - before

    with np.errstate(divide="ignore", invalid="ignore"):
        mean = window_sums(arr) / eff_w
        if not squares:
            return mean, None
        var = window_sums(arr * arr) / eff_w - mean * mean
    return mean, np.where(var < 0.0, 0.0, var)


def _rolling_zscore_series(arr: np.ndarray, window: int) -> np.ndarray:
    """Rolling z-score series matching _zscore_last semantics.

    At position i, scores arr[i] against arr[max(0, i-window+1):i+1] using the
    effective window min(window, i+1) — the series expands until it saturates at
    `window` elements. This matches _zscore_last(arr[:i+1], min(window, i+1)).

    Uses cumulative sums — O(n) total.
    Returns 0.0 where fewer than 2 samples or std < STD_FLOOR.
    """
    n = len(arr)
    out = np.zeros(n, dtype=float)
    if n < 2 or window < 2:
        return out
    mean, var = _cumsum_window_moments(arr, window)
    std = np.sqrt(var)
    with np.errstate(divide="ignore", invalid="ignore"):
        z = np.where(std > STD_FLOOR, (arr - mean) / std, 0.0)
    out[1:] = z[1:]
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


def _rolling_std_series(arr: np.ndarray, window: int) -> np.ndarray:
    """Trailing rolling std series (expanding until `window` bars, then fixed window).

    O(n) via cumulative sums. Shared building block for _vol_std_z (streaming) and
    _vol_std_z_series_full (batch).
    """
    if len(arr) == 0:
        return np.zeros(0, dtype=float)
    _, var = _cumsum_window_moments(arr, window)
    return np.sqrt(var)


def _rolling_mean_series(arr: np.ndarray, window: int) -> np.ndarray:
    """Trailing rolling mean series (expanding until `window` bars, then fixed window).

    O(n) via cumulative sums. Shared building block for the Parkinson/Garman-Klass
    alternative volatility estimators (Phase 142.5 Plan 04), which smooth their
    per-bar variance proxy over `window` bars before z-scoring.
    """
    if len(arr) == 0:
        return np.zeros(0, dtype=float)
    mean, _ = _cumsum_window_moments(arr, window, squares=False)
    return mean


def _sliding_rolling(arr: np.ndarray, window: int, reduce) -> np.ndarray:
    """result[i] == reduce(arr[max(0, i-window+1):i+1]) for every i, with reduce np.max or np.min.
    O(n) calls, vectorized over the saturated region via sliding_window_view."""
    n = len(arr)
    out = np.empty(n, dtype=float)
    if n == 0:
        return out
    expand_n = min(window - 1, n)
    for i in range(expand_n):
        out[i] = reduce(arr[: i + 1])
    if n >= window:
        windows = np.lib.stride_tricks.sliding_window_view(arr, window)
        out[window - 1 :] = reduce(windows, axis=1)
    return out


def _sliding_rolling_max(arr: np.ndarray, window: int) -> np.ndarray:
    """result[i] == max(arr[max(0, i-window+1):i+1]) for every i."""
    return _sliding_rolling(arr, window, np.max)


def _sliding_rolling_min(arr: np.ndarray, window: int) -> np.ndarray:
    """result[i] == min(arr[max(0, i-window+1):i+1]) for every i."""
    return _sliding_rolling(arr, window, np.min)


def _is_valid_atr(atr_val: float | None, close_: float, min_atr_pct: float) -> bool:
    """Shared guard for the ATR-normalized distance features consolidated onto
    it by todo 237 (session VP, S/R, swing/trend structure, fibonacci zones,
    session levels, all 6 SMC compute functions) and todo 266 (`_informed_flow`,
    `_range_vs_atr`): True iff atr_val is finite, strictly positive, AND at
    least min_atr_pct of close_ -- safe to divide a price distance by without
    exploding.

    A bare `atr_val > 0` check (this function's pre-todo-237 form) passes a
    legitimately-positive but numerically-tiny ATR -- e.g. BIL (an
    ultra-short-duration T-bill ETF) during a genuinely flat period -- and
    `(level - close_) / atr_val` then blows up to an implausible magnitude
    (confirmed live: weekly_r1_dist_atr up to 96,512) with no separate check
    ever catching it. min_atr_pct (feature.atr_normalization.min_atr_pct) is
    relative to close_, not an absolute floor, so it holds across instruments
    at any price scale.

    See `_is_valid_atr_series` for the vectorized form used by `_series_full`
    batch functions.
    """
    return (
        atr_val is not None
        and math.isfinite(atr_val)
        and atr_val > 0
        and atr_val >= min_atr_pct * abs(close_)
    )


def _is_valid_atr_series(
    atr_padded: np.ndarray, closes: np.ndarray, min_atr_pct: float
) -> np.ndarray:
    """Vectorized form of `_is_valid_atr` (todo 268): result[i] is True iff
    atr_padded[i] is finite, strictly positive, AND at least min_atr_pct of
    abs(closes[i]) -- same relative floor, applied element-wise across a full
    `_series_full` batch array instead of one scalar per call.
    """
    return np.isfinite(atr_padded) & (atr_padded > 0) & (atr_padded >= min_atr_pct * np.abs(closes))


def _zscore_last(series: np.ndarray, window: int) -> float:
    """Z-score of the last element relative to the trailing window.

    Stateless: takes full array, uses last `window` elements for mean/std,
    scores the final element. Returns 0.0 on cold start or near-zero std.
    """
    if len(series) < window:
        return 0.0
    window_data = series[-window:]
    std = float(window_data.std())
    if std < STD_FLOOR:
        return 0.0
    return float((float(series[-1]) - float(window_data.mean())) / std)


def _percentile_rank(hist: np.ndarray, current: float) -> float:
    """Percentile rank of `current` within `hist` (inclusive, "weak" semantics).

    scipy.stats.percentileofscore, bounded [0, 1].
    """
    pct = stats.percentileofscore(hist, current, kind="weak") / 100.0
    return float(np.clip(pct, 0.0, 1.0))


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


def _skewness(arr: np.ndarray) -> float:
    if len(arr) < 3:
        return 0.0
    mean = arr.mean()
    std = arr.std()
    if std < 1e-10:
        return 0.0
    result = float(np.mean(((arr - mean) / std) ** 3))
    return result if math.isfinite(result) else 0.0


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


def _k(name, outputs, inputs, memory, compute, **kw) -> Kernel:
    """Kernel with its outputs and inputs normalized to tuples."""
    return Kernel(
        name=name,
        outputs=tuple(outputs),
        inputs=tuple(inputs),
        memory=memory,
        compute=compute,
        **kw,
    )
