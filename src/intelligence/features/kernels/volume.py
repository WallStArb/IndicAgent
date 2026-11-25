"""Volume and order-flow kernels (D-25)."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import numpy as np

from src.intelligence.features.contract.registry import (
    ANCHOR_SERIES_START,
    Kernel,
    volume_basis_segment_starts,
)
from src.intelligence.features.kernels._primitives import (
    ATR_RAW_PADDED,
    EPS,
    STD_FLOOR,
    _corr_or_nan,
    _fixed_window_zscore_series,
    _is_valid_atr,
    _k,
    _pearson_acf1,
    _percentile_rank,
    _rolling_std_series,
    bounded_window_bars,
    none_mask_name,
)
from src.intelligence.features.kernels.price import (
    _bars_since_event_absent,
    _bars_since_event_series_full,
    _up_vol_body_diff,
    _vol_velocity_z_series_full,
)

if TYPE_CHECKING:
    pass


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
    closes: np.ndarray,
    volumes: np.ndarray,
    volume_basis: np.ndarray,
    zscore_window: int,
    min_valid_fraction: float,
) -> np.ndarray:
    """Amihud illiquidity z-score series (todo 555): z-score of ln(illiq[i]) over the last
    `zscore_window` bars of one volume basis, illiq[i] = |ln(C[i] / C[i-1])| / (C[i] * V[i]).

    - Scale. Raw illiq is about 1e-10 on a liquid name, below the absolute std floor, so a raw
      z-score is 0.0 almost everywhere. Amihud values are roughly log-normal and the log removes
      the price-times-volume scale, so the z-score is taken on ln(illiq).
    - Basis. Vendors count volume differently (IBKR SMART about 0.41 to 0.91 of consolidated),
      so a window spanning a basis change carries a level shift of ln(0.41..0.91). The window
      restarts where `volume_basis` changes (`volume_basis_segment_starts`) and the output is
      NaN until it is warm again: a loud gap beats a silent level shift.
    - Missing values. A zero return (no log) or a non-positive close (todo 390) gives no
      observation (a NULL volume never arrives: compute raises on it, todo 564). The z-score
      runs over the observations the window holds and is NaN when the bar's own is missing or
      the window holds fewer than ceil(min_valid_fraction * zscore_window): one missing session
      does not blank 252 rows.
    - Warm means ceil(min_valid_fraction * zscore_window) valid observations in the segment, so a
      row can emit before the full window is filled. Earlier rows, and row 0, are NaN (no_fill).

    Cumulative sums over the valid observations (missing ones enter as 0.0 and are not counted)
    give each window's moments as a difference of the sums at its ends.
    """
    n = len(closes)
    z = np.full(n, np.nan, dtype=float)
    if n < 2:
        return z
    c = np.asarray(closes, dtype=float)
    v = np.asarray(volumes, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        log_ret_abs = np.abs(np.log(c[1:] / c[:-1]))
        illiq = log_ret_abs / (c[1:] * np.maximum(v[1:], 1.0))
        obs = np.full(n, np.nan, dtype=float)
        obs[1:] = np.log(illiq)
    obs[~np.isfinite(obs)] = np.nan
    valid = ~np.isnan(obs)
    filled = np.where(valid, obs, 0.0)
    cs = np.concatenate([[0.0], np.cumsum(filled)])
    cs2 = np.concatenate([[0.0], np.cumsum(filled * filled)])
    cn = np.concatenate([[0], np.cumsum(valid)])
    rows = np.arange(n)
    start = np.maximum(rows - zscore_window + 1, volume_basis_segment_starts(volume_basis))
    count = cn[rows + 1] - cn[start]
    total = cs[rows + 1] - cs[start]
    total2 = cs2[rows + 1] - cs2[start]
    needed = max(2, math.ceil(min_valid_fraction * zscore_window))
    ok = valid & (count >= needed)
    with np.errstate(divide="ignore", invalid="ignore"):
        mean = total[ok] / count[ok]
        std = np.sqrt(np.maximum(total2[ok] / count[ok] - mean * mean, 0.0))
        z[ok] = np.where(std > STD_FLOOR, (obs[ok] - mean) / std, 0.0)
    return z


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
    NaN where the running deviation has no spread: the z-score of a zero-spread
    window is undefined (D1 rule 5, todo 584 4c), never 0.0.
    """
    n = len(closes)
    result = np.full(n, np.nan)
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
    """result[i] equals the retired per-bar _vol_acceleration at bar i. NaN at index 0 (no
    prior bar) and wherever the prior volume is near zero, matching the
    scalar's rule-5 semantics."""
    n = len(volumes)
    result = np.full(n, np.nan)
    if n < 2:
        return result
    v = volumes.astype(float)
    # rule 5: undefined where the prior volume is near zero; result is already
    # NaN there, so the masked divide never touches those entries
    np.divide(v[1:], v[:-1], out=result[1:], where=v[:-1] > eps)
    return result


def _dollar_vol_z_series_full(volumes: np.ndarray, closes: np.ndarray, window: int) -> np.ndarray:
    """result[i] equals the retired per-bar _dollar_vol_z at bar i."""
    dollar_vol = volumes.astype(float) * closes.astype(float)
    return _fixed_window_zscore_series(dollar_vol, window)


def _vol_range_ratio_series_full(
    volumes: np.ndarray, highs: np.ndarray, lows: np.ndarray, window: int, eps: float = EPS
) -> np.ndarray:
    """result[i] equals the retired per-bar _vol_range_ratio at bar i. O(n) via cumsum.

    A degenerate bar (H == L) makes raw NaN; a trailing window holding one is
    NaN and recovers once the bar leaves the window (the _cumsum_window_moments
    convention: cumsums over the finite-zeroed values plus a bad-count, so one
    bad bar never poisons the rows after its window). D1 rule 5, todo 584.
    """
    n = len(volumes)
    result = np.full(n, np.nan, dtype=float)
    if n < 1:
        return result
    ranges = highs.astype(float) - lows.astype(float)
    degenerate = ranges <= eps
    safe_ranges = np.where(degenerate, 1.0, ranges)
    raw = np.where(degenerate, np.nan, volumes.astype(float) / safe_ranges)
    bad = ~np.isfinite(raw)
    good = np.where(bad, 0.0, raw)
    cs = np.cumsum(good)
    cs_bad = np.cumsum(bad.astype(float))
    for i in range(n):
        w = min(window, i + 1)
        start = i + 1 - w
        prev_cs = cs[start - 1] if start > 0 else 0.0
        prev_bad = cs_bad[start - 1] if start > 0 else 0.0
        if cs_bad[i] - prev_bad > 0.0:
            continue
        mean_raw = (cs[i] - prev_cs) / w
        if mean_raw > eps:
            result[i] = raw[i] / mean_raw
    return result


def _vol_trend_ratio_series_full(
    volumes: np.ndarray, fast_window: int, slow_window: int, eps: float = EPS
) -> np.ndarray:
    """result[i] equals the retired per-bar _vol_trend_ratio at bar i. O(n) via cumsum."""
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
        result[i] = ma_f / ma_s if ma_s > eps else np.nan
    return result


def _up_vol_ratio_series_full(
    volumes: np.ndarray,
    opens: np.ndarray,
    closes: np.ndarray,
    window: int,
    eps: float = EPS,
) -> np.ndarray:
    """result[i] equals the retired per-bar _up_vol_ratio at bar i. O(n) via cumsum."""
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
    """result[i] equals the retired per-bar _vol_percentile at bar i. O(n x window).

    NaN on cold rows and all-equal windows, matching the scalar (D1 rule 5)."""
    n = len(volumes)
    result = np.full(n, np.nan, dtype=float)
    if n < 2:
        return result
    vols = volumes.astype(float)
    for i in range(n):
        w = min(window, i + 1)
        if w < 2:
            continue
        hist = vols[i + 1 - w : i + 1]
        if float(hist.max()) - float(hist.min()) < EPS:
            continue
        result[i] = _percentile_rank(hist, float(hist[-1]))
    return result


def _vol_persistence_series_full(volumes: np.ndarray, window: int) -> np.ndarray:
    """result[i] equals the retired per-bar _vol_persistence at bar i. O(n x window)."""
    n = len(volumes)
    result = np.full(n, np.nan)
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
    """result[i] equals the retired per-bar _vol_std_z at bar i. O(n) total."""
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
    """result[i] equals the retired per-bar _mfi at bar i. O(n) via cumsum (rising-flag is
    fixed per bar regardless of window; only the rolling sums need cumsum).
    Cold rows and zero-flow windows are NaN, matching the scalar (D1 rule 5,
    todo 584).
    """
    n = len(closes)
    result = np.full(n, np.nan, dtype=float)
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
    """result[i] equals the retired per-bar _obv_z at bar i. Index 0 padded with 0.0 (cold start)."""
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
    slice -> NaN, D1 rule 5) delegates to `_corr_or_nan()`, the same shared
    helper _high_low_corr_series_full uses.

    `abs_rets` may be passed in precomputed (the fast/slow calls in
    `_precompute_series` share one `abs_rets` array rather than each
    recomputing it from `closes`); if omitted it's derived here. Either way
    it's an O(n) pass, and the loop only slices bounded `window`-sized chunks
    of abs_rets/volumes per bar, so the per-bar cost is O(window), not O(i).
    """
    n = len(closes)
    result = np.full(n, np.nan)
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
        result[i] = _corr_or_nan(rets_w, vol_w, window)
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
            x["close"],
            x["volume"],
            x["volume_basis"],
            config.amihud_zscore_window,
            config.amihud_min_valid_fraction,
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
    ratio = _vol_range_ratio_series_full(
        x["volume"], x["high"], x["low"], config.vol_range_ratio_window
    )
    return {
        "vol_range_ratio": ratio,
        none_mask_name("vol_range_ratio"): np.isnan(ratio).astype(np.float64),
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
    """CMF over the bounded window: row i reads rows [max(0, i - n), i]."""
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
    rel = x["rel_volume"]
    # float 1.0/0.0 with NaN where rel_volume is NaN: a masked volume row must read as unknown,
    # not as "no spike", and the volume guard can only mask float outputs (todo 560)
    events = np.where(np.isnan(rel), np.nan, (rel > config.vol_spike_threshold).astype(float))
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
                (column, none_mask_name(column)),
                (event,),
                lambda c, w=window: getattr(c, w),
                lambda x, c, w=window, ev=event, col=column: {
                    # raw float events (1.0/0.0/NaN): the helper reads a NaN
                    # row as unknown, not as "no spike" (todo 560, 584 4b-2)
                    col: _bars_since_event_series_full(x[ev], getattr(c, w)),
                    none_mask_name(col): _bars_since_event_absent(x[ev], getattr(c, w)),
                },
                # the event: a volume spike inside the window (none mask = no event)
                object_dependent=frozenset({column}),
            )
        )
    return tuple(out)


def _compute_flow_products(x, config):
    """Window-free products with a volume-origin parent, operand order fixed by the kernel contract."""
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
        zero_is_state=frozenset({"rel_volume"}),
    ),
    _k(
        "amihud_illiq_z",
        ("amihud_illiq_z",),
        ("close", "volume", "volume_basis"),
        lambda c: c.amihud_zscore_window + 1,
        _compute_amihud,
        volume_basis_safe=True,
    ),
    _k(
        "vwap_dev_sigma",
        ("vwap_dev_sigma",),
        ("open", "high", "low", "close", "volume"),
        lambda c: 0,
        _compute_vwap_dev_sigma,
        path_dependent=True,
        path_dependent_reason="running VWAP and running deviation statistics accumulate from the series start",
        memory_anchor=ANCHOR_SERIES_START,
        # _vwap_dev_sigma_series_full: the running deviation std needs two rows to spread
        definition=lambda c, tf: 1,
    ),
    _velocity_kernel("vwap_dev_sigma", "vwap_velocity_window"),
    _k(
        "vol_acceleration",
        ("vol_acceleration",),
        ("volume",),
        lambda c: 1,
        _compute_vol_acceleration,
        zero_is_state=frozenset({"vol_acceleration"}),
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
        ("vol_range_ratio", none_mask_name("vol_range_ratio")),
        ("volume", "high", "low"),
        lambda c: c.vol_range_ratio_window,
        _compute_vol_range_ratio,
        # the object: a trailing window with no bar of zero range (high equal to low), where the
        # ratio is NaN by D1 rule 5 (todo 652 R5); none mask = NaN
        object_dependent=frozenset({"vol_range_ratio"}),
    ),
    _k(
        "vol_trend_ratio",
        ("vol_trend_ratio",),
        ("volume",),
        lambda c: c.vol_trend_slow,
        _compute_vol_trend_ratio,
        zero_is_state=frozenset({"vol_trend_ratio"}),
    ),
    _k(
        "up_vol_ratio",
        ("up_vol_ratio_fast", "up_vol_ratio_slow"),
        ("volume", "open", "close"),
        lambda c: max(c.up_vol_ratio_fast, c.up_vol_ratio_slow),
        _compute_up_vol_ratio,
        zero_is_state=frozenset({"up_vol_ratio_fast", "up_vol_ratio_slow"}),
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
        zero_is_state=frozenset({"mfi_fast", "mfi_slow"}),
    ),
    _k("obv_z", ("obv_z",), ("close", "volume"), lambda c: c.obv_window + 1, _compute_obv_z),
    _k(
        "price_vol_corr",
        ("price_vol_corr_fast", "price_vol_corr_slow"),
        ("close", "volume"),
        lambda c: max(c.price_vol_corr_fast, c.price_vol_corr_slow) + 1,
        _compute_price_vol_corr,
    ),
    _k(
        "cmf",
        ("cmf",),
        ("high", "low", "close", "volume"),
        bounded_window_bars,
        _compute_cmf,
        zero_is_state=frozenset({"cmf"}),
    ),
    _k(
        "informed_flow",
        ("informed_flow",),
        ("open", "close", ATR_RAW_PADDED),
        lambda c: 0,
        _compute_informed_flow,
        zero_is_state=frozenset({"informed_flow"}),
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
            "efficiency_ratio_fast",
        ),
        lambda c: 0,
        _compute_flow_products,
        # a doji (open equal to close) has body_ratio 0, so the product is a measured 0.0; a
        # zero-range bar makes body_ratio, and so the product, NaN (todo 652 R2)
        zero_is_state=frozenset({"vol_body_product"}),
        degenerate_input_state=frozenset({"vol_body_product"}),
    ),
    # Its own kernel: amihud_illiq_z handles a basis change itself (volume_basis_safe), so the
    # volume guard must not mask this product with the other flow products' volume inputs.
    _k(
        "illiquidity_momentum_product",
        ("illiquidity_momentum_product",),
        ("amihud_illiq_z", "momentum_z_fast"),
        lambda c: 0,
        lambda x, c: {"illiquidity_momentum_product": x["amihud_illiq_z"] * x["momentum_z_fast"]},
    ),
)
