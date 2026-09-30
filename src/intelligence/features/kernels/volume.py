"""Volume and order-flow kernels (D-25)."""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING

import numpy as np

from src.intelligence.features.contract.registry import Kernel
from src.intelligence.features.kernels._primitives import (
    ATR_RAW_PADDED,
    EPS,
    _fixed_window_zscore_series,
    _is_valid_atr,
    _k,
    _pearson_acf1,
    _percentile_rank,
    _rolling_std_series,
    _zscore_last,
    bounded_window_bars,
)
from src.intelligence.features.kernels.price import (
    _bars_since_event_series_full,
    _up_vol_body_diff,
    _vol_velocity_z_series_full,
)
from src.intelligence.utils import safe_corr

if TYPE_CHECKING:
    pass


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


def _informed_flow(open_price: float, close: float, atr: float, min_atr_pct: float) -> float:
    """Directional informed flow proxy: (close - open) / ATR.

    Returns 0.0 when atr is invalid per `_is_valid_atr` (todo 266: routed through
    the same relative floor as the 12 sibling ATR-ratio features, todo 237).
    """
    return (close - open_price) / atr if _is_valid_atr(atr, close, min_atr_pct) else 0.0


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


def _vol_acceleration(volumes: np.ndarray, eps: float = EPS) -> float:
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
    volumes: np.ndarray, highs: np.ndarray, lows: np.ndarray, window: int, eps: float = EPS
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
    volumes: np.ndarray, fast_window: int, slow_window: int, eps: float = EPS
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
    eps: float = EPS,
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
    eps: float = EPS,
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


def _vol_acceleration_series_full(volumes: np.ndarray, eps: float = EPS) -> np.ndarray:
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
    volumes: np.ndarray, highs: np.ndarray, lows: np.ndarray, window: int, eps: float = EPS
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
    volumes: np.ndarray, fast_window: int, slow_window: int, eps: float = EPS
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
    eps: float = EPS,
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
    eps: float = EPS,
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


def _price_vol_corr_series_full(
    closes: np.ndarray,
    volumes: np.ndarray,
    window: int,
    eps: float = EPS,
    abs_rets: np.ndarray | None = None,
) -> np.ndarray:
    """Rolling Pearson correlation between |log return| and volume over the
    trailing `window` bars ending at bar i, for every i. O(n x window) --
    same cost class as the pre-existing _high_low_corr_series_full; kept
    intentionally consistent with that established rolling-correlation
    pattern rather than introducing a one-off O(n) prefix-sum variant that
    would diverge from it. Degeneracy handling (near-zero variance in either
    slice -> 0.0) delegates to `safe_corr()`, the same shared helper
    _high_low_corr_series_full already uses.

    `abs_rets` may be passed in precomputed (the fast/slow calls in
    `_precompute_series` share one `abs_rets` array rather than each
    recomputing it from `closes`); if omitted it's derived here. Either way
    it's an O(n) pass, and the loop only slices bounded `window`-sized chunks
    of abs_rets/volumes per bar, so the per-bar cost is O(window), not O(i).
    """
    n = len(closes)
    result = np.zeros(n, dtype=float)
    if n < 2:
        return result
    if abs_rets is None:
        abs_rets = np.abs(np.diff(np.log(np.maximum(closes.astype(float), eps))))
    vols = volumes.astype(float)
    for i in range(n):
        if i < window:
            continue
        start = i - window
        rets_w = abs_rets[start:i]
        vol_w = vols[start + 1 : i + 1]
        if len(rets_w) < 2:
            continue
        result[i] = safe_corr(rets_w, vol_w)
    return result


# ---------------------------------------------------------------------------
# Kernels. Same conventions as kernels/price.py: series kernels call the moved bodies unchanged,
# declared memory is the sum of the window arguments along the body's chain.
# ---------------------------------------------------------------------------


def _velocity_kernel(source: str, window: str) -> Kernel:
    column = f"{source}_velocity"
    return _k(
        column,
        (column,),
        (source,),
        lambda c: getattr(c, window) + 1,
        lambda x, c: {column: _vol_velocity_z_series_full(x[source], getattr(c, window))},
    )


def _compute_volume_z(x, config):
    return {"volume_z": _volume_z_series_full(x["volume"], config.volume_zscore_window)}


def _compute_ofi_z(x, config):
    return {
        "ofi_z": _ofi_z_series_full(
            x["close"], x["high"], x["low"], x["volume"], config.ofi_zscore_window
        )
    }


def _compute_cvd_slope_z(x, config):
    return {
        "cvd_slope_z": _cvd_slope_z_series_full(
            x["close"],
            x["high"],
            x["low"],
            x["volume"],
            config.cvd_slope_bars,
            config.ofi_zscore_window,
        )
    }


def _compute_rel_volume(x, config):
    return {"rel_volume": _rel_volume_series_full(x["volume"], config.volume_zscore_window)}


def _compute_amihud(x, config):
    return {
        "amihud_illiq_z": _amihud_illiq_z_series_full(
            x["close"], x["volume"], config.amihud_zscore_window
        )
    }


def _compute_vwap_dev_sigma(x, config):
    return {
        "vwap_dev_sigma": _vwap_dev_sigma_series_full(
            x["open"], x["high"], x["low"], x["close"], x["volume"]
        )
    }


def _compute_vol_acceleration(x, config):
    return {"vol_acceleration": _vol_acceleration_series_full(x["volume"])}


def _compute_dollar_vol_z(x, config):
    return {
        "dollar_vol_z": _dollar_vol_z_series_full(x["volume"], x["close"], config.dollar_vol_window)
    }


def _compute_vol_range_ratio(x, config):
    return {
        "vol_range_ratio": _vol_range_ratio_series_full(
            x["volume"], x["high"], x["low"], config.vol_range_ratio_window
        )
    }


def _compute_vol_trend_ratio(x, config):
    return {
        "vol_trend_ratio": _vol_trend_ratio_series_full(
            x["volume"], config.vol_trend_fast, config.vol_trend_slow
        )
    }


def _compute_up_vol_ratio(x, config):
    return {
        f"up_vol_ratio_{scale}": _up_vol_ratio_series_full(
            x["volume"], x["open"], x["close"], getattr(config, f"up_vol_ratio_{scale}")
        )
        for scale in ("fast", "slow")
    }


def _compute_vol_percentile(x, config):
    return {
        "vol_percentile": _vol_percentile_series_full(x["volume"], config.vol_percentile_window)
    }


def _compute_vol_persistence(x, config):
    return {
        "vol_persistence": _vol_persistence_series_full(x["volume"], config.vol_persistence_window)
    }


def _compute_vol_std_z(x, config):
    return {"vol_std_z": _vol_std_z_series_full(x["volume"], config.vol_std_window)}


def _compute_mfi(x, config):
    return {
        f"mfi_{scale}": _mfi_series_full(
            x["high"], x["low"], x["close"], x["volume"], getattr(config, f"mfi_{scale}")
        )
        for scale in ("fast", "slow")
    }


def _compute_obv_z(x, config):
    return {"obv_z": _obv_z_series_full(x["close"], x["volume"], config.obv_window)}


def _compute_price_vol_corr(x, config):
    return {
        f"price_vol_corr_{scale}": _price_vol_corr_series_full(
            x["close"], x["volume"], getattr(config, f"price_vol_corr_{scale}")
        )
        for scale in ("fast", "slow")
    }


def _compute_cmf(x, config):
    """CMF over compute_batch's bounded window: row i reads rows [max(0, i - n), i]."""
    h, lo, c, v = x["high"], x["low"], x["close"], x["volume"]
    window = bounded_window_bars(config)
    out = np.empty(len(c))
    for i in range(len(c)):
        start = max(0, i - window)
        out[i] = _cmf(
            h[start : i + 1],
            lo[start : i + 1],
            c[start : i + 1],
            v[start : i + 1],
            config.cmf_period,
        )
    return {"cmf": out}


def _compute_informed_flow(x, config):
    o, c, atr = x["open"].tolist(), x["close"].tolist(), x[ATR_RAW_PADDED].tolist()
    return {
        "informed_flow": np.array(
            [
                _informed_flow(o[i], c[i], atr[i], config.atr_normalization_min_pct)
                for i in range(len(c))
            ]
        )
    }


def _compute_vol_spike_events(x, config):
    events = x["rel_volume"] > config.vol_spike_threshold
    return {"_vol_spike_event_fast": events, "_vol_spike_event_slow": events}


def _recency_kernels() -> tuple[Kernel, ...]:
    out = []
    for scale in ("fast", "slow"):
        window = f"dist_window_{scale}"
        column = f"bars_since_vol_spike_{scale}"
        event = f"_vol_spike_event_{scale}"
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
    return tuple(out)


def _compute_flow_products(x, config):
    """Window-free products with a volume-origin parent, operand order as in compute_batch."""
    up_vol_body = np.array(
        [
            _up_vol_body_diff(a, b)
            for a, b in zip(x["up_vol_ratio_fast"].tolist(), x["body_ratio"].tolist(), strict=True)
        ]
    )
    return {
        "ofi_div": x["ofi_z"] - x["momentum_z_fast"],
        "vol_body_product": x["body_ratio"] * x["volume_z"],
        "ret_vol_product_fast": x["ret_lag_fast"] * x["volume_z"],
        "range_vol_product": x["range_vs_atr"] * x["volume_z"],
        "up_vol_body_diff": up_vol_body,
        "vol_skew_product": x["ret_skew_z"] * x["volume_z"],
        "breakout_volume_product": x["dist_from_high_fast"] * x["volume_z"],
        "illiquidity_momentum_product": x["amihud_illiq_z"] * x["momentum_z_fast"],
        "efficiency_volume_product": x["efficiency_ratio_fast"] * x["volume_z"],
    }


KERNELS = (
    _k("volume_z", ("volume_z",), ("volume",), lambda c: c.volume_zscore_window, _compute_volume_z),
    _velocity_kernel("volume_z", "volume_velocity_window"),
    _k(
        "ofi_z",
        ("ofi_z",),
        ("close", "high", "low", "volume"),
        lambda c: c.ofi_zscore_window,
        _compute_ofi_z,
    ),
    _velocity_kernel("ofi_z", "ofi_velocity_window"),
    _k(
        "cvd_slope_z",
        ("cvd_slope_z",),
        ("close", "high", "low", "volume"),
        lambda c: c.cvd_slope_bars + c.ofi_zscore_window,
        _compute_cvd_slope_z,
    ),
    _velocity_kernel("cvd_slope_z", "cvd_velocity_window"),
    _k(
        "rel_volume",
        ("rel_volume",),
        ("volume",),
        lambda c: c.volume_zscore_window,
        _compute_rel_volume,
    ),
    _k(
        "amihud_illiq_z",
        ("amihud_illiq_z",),
        ("close", "volume"),
        lambda c: c.amihud_zscore_window + 1,
        _compute_amihud,
    ),
    _k(
        "vwap_dev_sigma",
        ("vwap_dev_sigma",),
        ("open", "high", "low", "close", "volume"),
        lambda c: 0,
        _compute_vwap_dev_sigma,
        path_dependent=True,
        path_dependent_reason="running VWAP and running deviation statistics accumulate from the series start",
    ),
    _velocity_kernel("vwap_dev_sigma", "vwap_velocity_window"),
    _k(
        "vol_acceleration",
        ("vol_acceleration",),
        ("volume",),
        lambda c: 1,
        _compute_vol_acceleration,
    ),
    _k(
        "dollar_vol_z",
        ("dollar_vol_z",),
        ("volume", "close"),
        lambda c: c.dollar_vol_window,
        _compute_dollar_vol_z,
    ),
    _k(
        "vol_range_ratio",
        ("vol_range_ratio",),
        ("volume", "high", "low"),
        lambda c: c.vol_range_ratio_window,
        _compute_vol_range_ratio,
    ),
    _k(
        "vol_trend_ratio",
        ("vol_trend_ratio",),
        ("volume",),
        lambda c: c.vol_trend_slow,
        _compute_vol_trend_ratio,
    ),
    _k(
        "up_vol_ratio",
        ("up_vol_ratio_fast", "up_vol_ratio_slow"),
        ("volume", "open", "close"),
        lambda c: max(c.up_vol_ratio_fast, c.up_vol_ratio_slow),
        _compute_up_vol_ratio,
    ),
    _k(
        "vol_percentile",
        ("vol_percentile",),
        ("volume",),
        lambda c: c.vol_percentile_window,
        _compute_vol_percentile,
    ),
    _k(
        "vol_persistence",
        ("vol_persistence",),
        ("volume",),
        lambda c: c.vol_persistence_window,
        _compute_vol_persistence,
    ),
    _k(
        "vol_std_z", ("vol_std_z",), ("volume",), lambda c: 2 * c.vol_std_window, _compute_vol_std_z
    ),
    _k(
        "mfi",
        ("mfi_fast", "mfi_slow"),
        ("high", "low", "close", "volume"),
        lambda c: max(c.mfi_fast, c.mfi_slow) + 1,
        _compute_mfi,
    ),
    _k("obv_z", ("obv_z",), ("close", "volume"), lambda c: c.obv_window + 1, _compute_obv_z),
    _k(
        "price_vol_corr",
        ("price_vol_corr_fast", "price_vol_corr_slow"),
        ("close", "volume"),
        lambda c: max(c.price_vol_corr_fast, c.price_vol_corr_slow) + 1,
        _compute_price_vol_corr,
    ),
    _k("cmf", ("cmf",), ("high", "low", "close", "volume"), bounded_window_bars, _compute_cmf),
    _k(
        "informed_flow",
        ("informed_flow",),
        ("open", "close", ATR_RAW_PADDED),
        lambda c: 0,
        _compute_informed_flow,
    ),
    _k(
        "vol_spike_events",
        ("_vol_spike_event_fast", "_vol_spike_event_slow"),
        ("rel_volume",),
        lambda c: 0,
        _compute_vol_spike_events,
    ),
    *_recency_kernels(),
    _k(
        "flow_products",
        (
            "ofi_div",
            "vol_body_product",
            "ret_vol_product_fast",
            "range_vol_product",
            "up_vol_body_diff",
            "vol_skew_product",
            "breakout_volume_product",
            "illiquidity_momentum_product",
            "efficiency_volume_product",
        ),
        (
            "ofi_z",
            "momentum_z_fast",
            "body_ratio",
            "volume_z",
            "ret_lag_fast",
            "range_vs_atr",
            "up_vol_ratio_fast",
            "ret_skew_z",
            "dist_from_high_fast",
            "amihud_illiq_z",
            "efficiency_ratio_fast",
        ),
        lambda c: 0,
        _compute_flow_products,
    ),
)
