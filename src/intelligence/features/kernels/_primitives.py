"""Shared rolling and ATR helpers imported by kernels and feature_factory (D-25)."""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from types import MappingProxyType
from typing import Any, NamedTuple

import numpy as np
from scipy import stats

from src.intelligence.features.contract.registry import Kernel
from src.intelligence.utils import safe_corr

# Default divide-by-zero guard of the kernels' eps arguments, and the std below which a z-score is 0.
EPS = 1e-10
STD_FLOOR = 1e-8

# A Wilder recursion (ATR, RSI) forgets its seed geometrically: after `WILDER_MEMORY_E_FOLDS *
# period` bars the seed weight is (1 - 1/period) ** (40 * period), at most exp(-40), about 4e-18.
# Float64 resolution is 2.2e-16 (exp(-37) is already below it), so 40 e-folds leave the seed
# invisible with a margin of three. A derived bound, not a tunable.
WILDER_MEMORY_E_FOLDS = 40


def wilder_memory_bars(period: int) -> int:
    """Bars after which a Wilder recursion with `period` no longer depends on its seed."""
    return WILDER_MEMORY_E_FOLDS * max(int(period), 1)


def wilder_rsi_series(closes: np.ndarray, period: int) -> np.ndarray:
    """Wilder RSI at every bar in O(n): the one implementation (kernel columns rsi_*, the live
    cache's scalar RSI and the batch CTF momentum series all call it).

    Wilder's definition: the first RSI sits at index `period` and averages the first `period`
    price changes (the SMA seed); later bars smooth with alpha = 1 / period. Bars before index
    `period` have fewer than `period` changes and are NaN, as is a seed window that has never
    moved (0/0: the ratio RSI is a function of does not exist, D1 rule 5, todo 584). A window
    with gains and no losses is a measured 100.0 (rs = inf makes the formula exactly 100.0).
    No epsilon branch: a threshold on the decaying averages would make the finite/NaN boundary
    depend on the recursion's seed age, which is unbounded memory; the plain formula is
    continuous, so a defined value never passes through a neutral branch.
    """
    n = len(closes)
    result = np.full(n, np.nan, dtype=float)
    if n < period + 1:
        return result
    deltas = np.diff(closes.astype(float))
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    alpha = 1.0 / period
    avg_gain = float(np.mean(gains[:period]))
    avg_loss = float(np.mean(losses[:period]))

    def _rsi(gain: float, loss: float) -> float:
        # The formula's exact zero-divisor cases, not an epsilon: a 0-loss window with
        # gains is the measured 100.0 (rs = inf), and 0/0 is the undefined seed (nan).
        # Python float division raises where the formula would produce these, so the
        # cases are stated rather than divided into.
        if loss == 0.0:
            return 100.0 if gain > 0.0 else math.nan
        rs = gain / loss
        return min(max(100.0 - 100.0 / (1.0 + rs), 0.0), 100.0)

    result[period] = _rsi(avg_gain, avg_loss)
    for i in range(period, len(gains)):
        avg_gain = alpha * gains[i] + (1.0 - alpha) * avg_gain
        avg_loss = alpha * losses[i] + (1.0 - alpha) * avg_loss
        result[i + 1] = _rsi(avg_gain, avg_loss)
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


def unique_datetimes(dts: np.ndarray) -> tuple[np.ndarray, tuple[datetime, ...]]:
    """(inverse, distinct) for the row-aligned `ts_dt` input: distinct[inverse[i]] is dts[i].

    Every calendar value is a pure function of the timestamp, so a kernel computes once per
    distinct datetime and scatters with `inverse`. No state survives the call.
    """
    index: dict[datetime, int] = {}
    inverse = np.fromiter((index.setdefault(d, len(index)) for d in dts), np.int64, len(dts))
    return inverse, tuple(index)


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


def _trailing_window_sums(values: np.ndarray, window: int) -> np.ndarray:
    """Sum of every expanding-then-saturated trailing window, each window added left to right.

    Row i is the sum of values[max(0, i - window + 1):i + 1]. A difference of prefix sums
    (cs[i] - cs[i - window]) loses digits to the size of the whole series' running total, so
    its error grows with series length (SPY 5m, 400k rows: up to 3,834 float32 ulps in the
    rolling vol z-scores, todo 584 G4-a). Here a window's sum depends only on that window's own
    values, in one fixed order, so a recompute over any suffix that holds the window returns the
    identical bits; the cost is O(n * window) vector additions.
    """
    if window < 1:
        raise ValueError(f"window must be at least 1, got {window}")
    values = np.asarray(values, dtype=float)  # one precision for the head and the saturated rows
    n = len(values)
    out = np.empty(n, dtype=float)
    head = min(window - 1, n)
    if head > 0:
        out[:head] = np.cumsum(values[:head])
    if n >= window:
        saturated = n - window + 1
        acc = np.array(values[:saturated], dtype=float)
        for k in range(1, window):
            acc += values[k : k + saturated]
        out[window - 1 :] = acc
    return out


def _cumsum_window_moments(
    arr: np.ndarray, window: int, *, squares: bool = True
) -> tuple[np.ndarray, np.ndarray | None]:
    """Trailing mean and clamped variance of every expanding-then-saturated window, from exact
    per-window sums (`_trailing_window_sums`).

    Row i covers arr[max(0, i - window + 1):i + 1] (effective size min(window, i + 1)). The
    mean is the window sum / eff_w and the variance max(s2 / eff_w - mean * mean, 0.0)
    with the clamp keeping a NaN and never turning a value into NaN. Each window is added left
    to right, as the per-row loops this replaces did, so the results are bit-identical to them
    and do not depend on the series length. With `squares` False only the mean is computed and the
    variance is None.

    A window holding a NaN or inf defines nothing: its mean and variance are NaN (D1 rule 5,
    todo 584), and windows entirely past the bad value recover. The sums run over the
    NaN-zeroed array with a cumsum of the bad-count, so one bad value never poisons the rows
    after its window (a plain cumsum would carry the NaN to the end of the series).
    """
    n = len(arr)
    eff_w = np.minimum(window, np.arange(1, n + 1))
    bad = ~np.isfinite(arr)
    good = np.where(bad, 0.0, arr)

    def window_sums(values: np.ndarray) -> np.ndarray:
        return _trailing_window_sums(values, window)

    def window_bad_count(flags: np.ndarray) -> np.ndarray:
        # 0/1 counts are exactly representable, so a prefix-sum difference is exact here
        cs = np.cumsum(flags, dtype=np.int64)
        lag = np.concatenate((np.zeros(min(window, n), dtype=np.int64), cs[: max(n - window, 0)]))
        return cs - lag

    with np.errstate(divide="ignore", invalid="ignore"):
        has_bad = window_bad_count(bad) > 0
        mean = window_sums(good) / eff_w
        mean[has_bad] = np.nan
        if not squares:
            return mean, None
        # mean is already NaN in a bad window, so var is too; the clamp preserves NaN.
        var = window_sums(good * good) / eff_w - mean * mean
        var = np.where(var < 0.0, 0.0, var)
    return mean, var


def _rolling_zscore_series(arr: np.ndarray, window: int) -> np.ndarray:
    """Rolling z-score series matching _zscore_last semantics.

    At position i, scores arr[i] against arr[max(0, i-window+1):i+1] using the
    effective window min(window, i+1) — the series expands until it saturates at
    `window` elements. This matches _zscore_last(arr[:i+1], min(window, i+1)).

    Uses exact per-window sums — O(n * window) total.
    NaN where fewer than 2 samples or std <= STD_FLOOR: the z-score of a window
    that does not spread is undefined (D1 rule 5, todo 584), never a 0.0 fill.
    """
    n = len(arr)
    if n == 0:
        return np.zeros(0, dtype=float)
    if window < 2:
        return np.full(n, np.nan)
    mean, var = _cumsum_window_moments(arr, window)
    std = np.sqrt(var)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(std > STD_FLOOR, (arr - mean) / std, np.nan)


def _fixed_window_zscore_series(arr: np.ndarray, window: int) -> np.ndarray:
    """Rolling z-score series matching streaming `_zscore_last(arr, window)`.

    `_rolling_zscore_series` expands the window until it saturates; the streaming
    `_zscore_last` instead returns NaN until `window` samples exist. This forces
    that fixed-window cold start as NaN (D1 rule 5, todo 584).
    """
    z = _rolling_zscore_series(arr, window)
    z[: window - 1] = np.nan
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
    scores the final element. NaN on a history shorter than the window and on a
    window that does not spread (D1 rules 1 and 5, todo 584), never a 0.0 fill.
    """
    if len(series) < window:
        return math.nan
    window_data = series[-window:]
    std = float(window_data.std())
    if std < STD_FLOOR:
        return math.nan
    return float((float(series[-1]) - float(window_data.mean())) / std)


def _z_or_nan(history: deque, window: int) -> float:
    """Z-score of the newest value against the last `window` values: NaN while the history is
    shorter than the window and NaN on a zero-spread window (D1 rules 1 and 5, todo 584), never a
    0.0 fill. `_zscore_last` is the one implementation of the arithmetic."""
    return _zscore_last(np.asarray(history, dtype=float), window)


def _corr_or_nan(x: np.ndarray, y: np.ndarray, window: int) -> float:
    """Pearson correlation over the last `window` pairs: NaN until `window` pairs exist and NaN
    when either side has no spread (D1 rule 5), never `safe_corr`'s 0.0 for a degenerate input."""
    if len(x) < window or len(y) < window:
        return math.nan
    x, y = x[-window:], y[-window:]
    if float(x.std()) < STD_FLOOR or float(y.std()) < STD_FLOOR:
        return math.nan
    return safe_corr(x, y)


def _percentile_rank(hist: np.ndarray, current: float) -> float:
    """Percentile rank of `current` within `hist` (inclusive, "weak" semantics).

    scipy.stats.percentileofscore, bounded [0, 1].
    """
    pct = stats.percentileofscore(hist, current, kind="weak") / 100.0
    return float(np.clip(pct, 0.0, 1.0))


def _pearson_acf1(arr: np.ndarray) -> float:
    """Pearson lag-1 autocorrelation. NaN if std < 1e-10 or len < 2: the
    autocorrelation of a zero-spread window is undefined (D1 rule 5, todo 584 4c)."""
    if len(arr) < 2:
        return math.nan
    x = arr[:-1] - arr[:-1].mean()
    y = arr[1:] - arr[1:].mean()
    denom = float(np.sqrt(np.dot(x, x) * np.dot(y, y)))
    if denom < 1e-10:
        return math.nan
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


# The ATR series every windowed kernel reads: Wilder ATR padded with 0.0 at row 0 so it aligns with
# the bars (price.py produces it; volume, vp_sr and smc read it).
ATR_RAW_PADDED = "_atr_raw_padded"


def window_start(i: int, lookback: int) -> int:
    """First row of the causal window of `lookback` bars ending at row i: `max(0, i - lookback + 1)`."""
    return max(0, i - lookback + 1)


def none_mask_name(key: str) -> str:
    """Name of the intermediate output that marks rows where `key` is None (not a number)."""
    return f"_{key}_is_none"


def nullable_keys(fallback: Mapping[str, Any]) -> frozenset[str]:
    """Keys a helper may return None for: the keys its fallback dict holds as None."""
    return frozenset(key for key, value in fallback.items() if value is None)


def undefined_on(tf: str | Sequence[str], outputs: Sequence[str]) -> dict[str, frozenset[str]]:
    """A `Kernel.not_applicable` declaration: every output in `outputs` is undefined on `tf` (one
    timeframe, or several)."""
    tfs = frozenset((tf,) if isinstance(tf, str) else tf)
    return {name: tfs for name in outputs}


class KeyGroup(NamedTuple):
    """The keys one row helper returns, which of them may be None, and the keys it hands on as
    in-memory intermediates under another name (`names`: key -> registered output name).

    One spec feeds both sides of a kernel: `outputs` is what the Kernel registers and `columns`
    runs `row_dict_columns` with the same keys, so the two cannot drift. `public_keys` are the
    keys a caller of the kernel reads back (intermediates excluded).
    """

    keys: tuple[str, ...]
    nullable: frozenset[str] = frozenset()
    names: Mapping[str, str] = MappingProxyType({})

    @classmethod
    def from_fallback(
        cls, fallback: Mapping[str, Any], names: Mapping[str, str] | None = None
    ) -> KeyGroup:
        """Keys in the fallback dict's order; nullable where the fallback holds None."""
        return cls(tuple(fallback), nullable_keys(fallback), MappingProxyType(dict(names or {})))

    @classmethod
    def concat(cls, *groups: KeyGroup) -> KeyGroup:
        """One group from several computed by one kernel (no renames)."""
        return cls(
            tuple(key for group in groups for key in group.keys),
            frozenset().union(*(group.nullable for group in groups)),
        )

    @property
    def public_keys(self) -> tuple[str, ...]:
        return tuple(key for key in self.keys if key not in self.names)

    @property
    def outputs(self) -> tuple[str, ...]:
        """Registered output names: each key (renamed if an intermediate), then the none-masks."""
        return row_dict_outputs(self.keys, self.nullable, self.names)

    def columns(self, n: int, row_fn: Callable[[int], Mapping[str, Any]]) -> dict[str, np.ndarray]:
        return row_dict_columns(n, self.keys, self.nullable, row_fn, self.names)


def row_dict_outputs(
    keys: Sequence[str], nullable: frozenset[str], output_names: Mapping[str, str] | None = None
) -> tuple[str, ...]:
    """The column names `row_dict_columns(n, keys, nullable, ..., output_names)` returns."""
    names = output_names or {}
    return (
        *(names.get(key, key) for key in keys),
        *(none_mask_name(key) for key in keys if key in nullable),
    )


def row_dict_columns(
    n: int,
    keys: Sequence[str],
    nullable: frozenset[str],
    row_fn: Callable[[int], Mapping[str, Any]],
    output_names: Mapping[str, str] | None = None,
) -> dict[str, np.ndarray]:
    """Run `row_fn(i)` for rows 1..n-1 and collect each key as a float64 column.

    Row 0 is NaN (the batch loop never emits it). A value of None in a `nullable` key is NaN in
    the column and 1.0 in the `none_mask_name(key)` column (0.0 where a number was returned), so
    a None and a non-finite float stay distinguishable for a caller that maps them differently.
    A None in a key not declared nullable raises: a silent NaN would be a wrong answer.
    `output_names` renames a key to its registered output (intermediates start with "_").
    """
    names = output_names or {}
    columns = {key: np.full(n, np.nan) for key in keys}
    masks = {key: np.full(n, np.nan) for key in keys if key in nullable}
    for i in range(1, n):
        row = row_fn(i)
        for key in keys:
            value = row[key]
            if value is None:
                if key not in masks:
                    raise ValueError(f"row {i}: {key!r} is None but is not declared nullable")
                masks[key][i] = 1.0
            else:
                columns[key][i] = value
                if key in masks:
                    masks[key][i] = 0.0
    out = {names.get(key, key): col for key, col in columns.items()}
    out.update({none_mask_name(key): mask for key, mask in masks.items()})
    return out


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
