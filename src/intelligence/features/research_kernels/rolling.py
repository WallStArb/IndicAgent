"""Vectorized trailing-window kernels for research (184 B2a, B2c).

Three families, each built per window by a factory so a spec-pinned window gets its own kernel
and its own output name (`{family}_w{window}`), and two windows never collide:

- `rk_price_percentile`: weak percentile rank of the close within its trailing `window` closes
  (row t included). Same statistic and arithmetic as the stored `_price_percentile_series_full`
  (scipy `percentileofscore(kind="weak") / 100`, clipped to [0, 1]); here one vectorized pass
  instead of one scipy call per bar.
- `rk_high_dist`: (close - trailing max close) / trailing max close over `window` rows. Same
  formula as the stored `_high_52w_dist_series_full`, without its O(n x window) loop.
- `rk_vwap_dev`: (close - trailing VWAP) in units of the trailing typical-price standard
  deviation, both over the same `window` rows. The stored `vwap_dev_sigma` accumulates from
  the series start (path dependent); this one has finite memory `window - 1`.

Differences from the stored originals, all by design: rows before the first full window are NaN
(the stored kernels write 0.5 and 0.0 there), a window holding a NaN gives NaN, and a degenerate
denominator (max close, window volume or typical-price deviation at or below the floor) gives
NaN instead of a fill. From the first full window on, on finite inputs, the first two equal the
stored originals bit for bit in float32.

Every window statistic is computed from that window's own rows (no prefix-sum differences), so
truncating the series never changes a past row and the declared memory holds exactly
(`memory_atol` 0). Compute in float64; the Kernel dtype (float32) is the persistence dtype.
None of these kernels reads its config argument (`CONFIG_FREE_KERNELS`).
"""

from __future__ import annotations

import re
from collections.abc import Callable

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

from src.intelligence.features.contract.registry import Kernel
from src.intelligence.features.kernels._primitives import EPS, STD_FLOOR

PRICE_PERCENTILE = "rk_price_percentile"
HIGH_DIST = "rk_high_dist"
VWAP_DEV = "rk_vwap_dev"

# Families whose compute and memory never read the config argument.
CONFIG_FREE_KERNELS: frozenset[str] = frozenset({PRICE_PERCENTILE, HIGH_DIST, VWAP_DEV})

# Stored feature columns computing the same statistic as a research family (184-REVIEWS row 10:
# research serves only a window no stored column carries). kernel_source refuses a research
# window equal to one of these columns' windows under the provenance config.
STORED_EQUIVALENTS: dict[str, tuple[str, ...]] = {
    PRICE_PERCENTILE: ("price_percentile_fast", "price_percentile_slow"),
    HIGH_DIST: ("high_52w_dist",),
    # The stored vwap_dev_sigma is cumulative from the series start and uses the deviation's
    # own running std: a different statistic, so no stored window can collide.
    VWAP_DEV: (),
}

# The FeatureFactoryConfig field holding each stored equivalent's window.
STORED_WINDOW_FIELD: dict[str, str] = {
    "price_percentile_fast": "percentile_window_fast",
    "price_percentile_slow": "percentile_window_slow",
    "high_52w_dist": "high_52w_window",
}

_NAME = re.compile(r"^(rk_[a-z_]+?)_w(\d+)$")

# Rows per chunk times window bounds the temporary [rows, window] array of a chunked pass.
# Memory hygiene only: results do not depend on it (each row's window is reduced on its own).
_CHUNK_CELLS = 4_000_000


def family_of(name: str) -> str | None:
    """The research family of a kernel or output name (`rk_high_dist_w126` -> `rk_high_dist`),
    or None when the name is not a research kernel's."""
    match = _NAME.match(name)
    if match is None or match.group(1) not in FACTORIES:
        return None
    return match.group(1)


def window_of(name: str) -> int | None:
    match = _NAME.match(name)
    return int(match.group(2)) if match is not None and family_of(name) is not None else None


def _check_window(window: object) -> int:
    if isinstance(window, bool) or not isinstance(window, (int, np.integer)) or window < 2:
        raise ValueError(f"research kernel window must be an int >= 2, got {window!r}")
    return int(window)


def _chunked(
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


def _price_percentile(close: np.ndarray, window: int) -> np.ndarray:
    def reduce(hist: np.ndarray) -> np.ndarray:
        current = hist[:, -1:]
        count = np.count_nonzero(hist <= current, axis=1)
        # scipy percentileofscore(kind="weak"): count(a <= score) * (100.0 / n); then
        # _percentile_rank divides by 100 and clips. Same operations, same order.
        pct = np.clip((count * (100.0 / window)) / 100.0, 0.0, 1.0)
        return np.where(np.isnan(hist).any(axis=1), np.nan, pct)

    return _chunked((np.asarray(close, dtype=float),), window, reduce)


def _high_dist(close: np.ndarray, window: int) -> np.ndarray:
    c = np.asarray(close, dtype=float)

    def reduce(hist: np.ndarray) -> np.ndarray:
        rolling_max = hist.max(axis=1)
        with np.errstate(invalid="ignore", divide="ignore"):
            dist = (hist[:, -1] - rolling_max) / rolling_max
        return np.where(rolling_max >= EPS, dist, np.nan)

    return _chunked((c,), window, reduce)


def _vwap_dev(
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

    return _chunked((typical, v, c), window, reduce)


def rolling_percentile_kernel(window: int) -> Kernel:
    w = _check_window(window)
    name = f"{PRICE_PERCENTILE}_w{w}"
    return Kernel(
        name=name,
        outputs=(name,),
        inputs=("close",),
        memory=lambda config: w - 1,
        compute=lambda x, config: {name: _price_percentile(x["close"], w)},
    )


def rolling_max_distance_kernel(window: int) -> Kernel:
    w = _check_window(window)
    name = f"{HIGH_DIST}_w{w}"
    return Kernel(
        name=name,
        outputs=(name,),
        inputs=("close",),
        memory=lambda config: w - 1,
        compute=lambda x, config: {name: _high_dist(x["close"], w)},
    )


def rolling_vwap_deviation_kernel(window: int) -> Kernel:
    w = _check_window(window)
    name = f"{VWAP_DEV}_w{w}"
    return Kernel(
        name=name,
        outputs=(name,),
        inputs=("high", "low", "close", "volume"),
        memory=lambda config: w - 1,
        compute=lambda x, config: {
            name: _vwap_dev(x["high"], x["low"], x["close"], x["volume"], w)
        },
    )


FACTORIES: dict[str, Callable[[int], Kernel]] = {
    PRICE_PERCENTILE: rolling_percentile_kernel,
    HIGH_DIST: rolling_max_distance_kernel,
    VWAP_DEV: rolling_vwap_deviation_kernel,
}

# The battery windows (184 design section 5). None equals a stored window under the APR values
# at 2026-10-27 (percentile 50 and 200, 52-week high 252; the stored VWAP deviation has no
# window). kernel_source re-checks against the provenance config on every call.
KERNELS: tuple[Kernel, ...] = (
    rolling_percentile_kernel(126),
    rolling_max_distance_kernel(126),
    rolling_vwap_deviation_kernel(20),
)
