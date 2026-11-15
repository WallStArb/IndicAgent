"""Trailing-window kernel families the registry owns: the maximum-distance and VWAP-deviation
statistics (todos 551 and 552, promoted from the 184 research kernels).

Each family is built per window by a factory so a spec-pinned window gets its own kernel and its
own output name (`{family}_w{window}`), and two windows never collide. The module is underscored
on purpose: `discover_kernels()` skips it, so no stored column is added; the stored
`high_52w_dist` calls `high_distance` here (one implementation of the statistic), and
`research/kernel_source.py` composes the factories into the registry it runs a spec against.

- `rk_high_dist`: (close - trailing max close) / trailing max close over `window` rows.
- `rk_vwap_dev`: (close - trailing VWAP) in units of the trailing typical-price standard
  deviation, both over the same `window` rows. The stored `vwap_dev_sigma` accumulates from the
  series start (path dependent, refused by design D7 guard 5); this one has finite memory
  `window - 1`.

Rows before the first full window are NaN, a window holding a NaN gives NaN, and a degenerate
denominator (max close, window volume or typical-price deviation at or below the floor) gives NaN
instead of a fill. Every window statistic is computed from that window's own rows (no prefix-sum
differences), so truncating the series never changes a past row and the declared memory holds
exactly (`memory_atol` 0). Compute in float64; the Kernel dtype (float32) is the persistence
dtype. None of these kernels reads its config argument.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

from src.intelligence.features.contract.registry import Kernel
from src.intelligence.features.kernels._primitives import EPS, STD_FLOOR

HIGH_DIST = "rk_high_dist"
VWAP_DEV = "rk_vwap_dev"

# Rows per chunk times window bounds the temporary [rows, window] array of a chunked pass.
# Memory hygiene only: results do not depend on it (each row's window is reduced on its own).
_CHUNK_CELLS = 4_000_000


def check_window(window: object) -> int:
    if isinstance(window, bool) or not isinstance(window, (int, np.integer)) or window < 2:
        raise ValueError(f"research kernel window must be an int >= 2, got {window!r}")
    return int(window)


def chunked(
    columns: tuple[np.ndarray, ...],
    window: int,
    reduce: Callable[..., np.ndarray],
) -> np.ndarray:
    """`reduce(*views)` over the trailing windows of each column, rows window-1..n-1, returned
    on the full length with NaN before the first full window."""
    n = len(columns[0])
    out = np.full(n, np.nan)
    if n < window:
        return out
    views = tuple(sliding_window_view(c, window) for c in columns)
    step = max(1, _CHUNK_CELLS // window)
    for lo in range(0, n - window + 1, step):
        hi = min(lo + step, n - window + 1)
        out[window - 1 + lo : window - 1 + hi] = reduce(*(v[lo:hi] for v in views))
    return out


def high_distance(close: np.ndarray, window: int) -> np.ndarray:
    """(close - trailing max close) / trailing max close, NaN before the first full window, on a
    window holding a NaN or a max below EPS."""
    c = np.asarray(close, dtype=float)

    def reduce(hist: np.ndarray) -> np.ndarray:
        rolling_max = hist.max(axis=1)
        with np.errstate(invalid="ignore", divide="ignore"):
            dist = (hist[:, -1] - rolling_max) / rolling_max
        return np.where(rolling_max >= EPS, dist, np.nan)

    return chunked((c,), window, reduce)


def vwap_deviation(
    high: np.ndarray, low: np.ndarray, close: np.ndarray, volume: np.ndarray, window: int
) -> np.ndarray:
    c = np.asarray(close, dtype=float)
    typical = (np.asarray(high, dtype=float) + np.asarray(low, dtype=float) + c) / 3.0
    v = np.asarray(volume, dtype=float)

    def reduce(tp: np.ndarray, vol: np.ndarray, cl: np.ndarray) -> np.ndarray:
        vol_sum = vol.sum(axis=1)
        sigma = tp.std(axis=1)
        with np.errstate(invalid="ignore", divide="ignore"):
            vwap = (tp * vol).sum(axis=1) / vol_sum
            dev = (cl[:, -1] - vwap) / sigma
        ok = (vol_sum > EPS) & (sigma > STD_FLOOR)
        return np.where(ok, dev, np.nan)

    return chunked((typical, v, c), window, reduce)


def rolling_max_distance_kernel(window: int) -> Kernel:
    w = check_window(window)
    name = f"{HIGH_DIST}_w{w}"
    return Kernel(
        name=name,
        outputs=(name,),
        inputs=("close",),
        memory=lambda config: w - 1,
        compute=lambda x, config: {name: high_distance(x["close"], w)},
    )


def rolling_vwap_deviation_kernel(window: int) -> Kernel:
    w = check_window(window)
    name = f"{VWAP_DEV}_w{w}"
    return Kernel(
        name=name,
        outputs=(name,),
        inputs=("high", "low", "close", "volume"),
        memory=lambda config: w - 1,
        compute=lambda x, config: {
            name: vwap_deviation(x["high"], x["low"], x["close"], x["volume"], w)
        },
    )


FACTORIES: dict[str, Callable[[int], Kernel]] = {
    HIGH_DIST: rolling_max_distance_kernel,
    VWAP_DEV: rolling_vwap_deviation_kernel,
}
