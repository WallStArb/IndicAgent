"""Vectorized trailing-window kernel for research (184 B2a): the percentile family.

`rk_price_percentile`: weak percentile rank of the close within its trailing `window` closes
(row t included). Same statistic and arithmetic as the stored `_price_percentile_series_full`
(scipy `percentileofscore(kind="weak") / 100`, clipped to [0, 1]); here one vectorized pass
instead of one scipy call per bar. Rows before the first full window are NaN (the stored kernel
writes 0.5 there) and a window holding a NaN gives NaN; from the first full window on, on finite
inputs, it equals the stored original bit for bit in float32.

The maximum-distance and VWAP-deviation families (todos 551, 552) live in
`kernels/_windowed.py`, owned by the registry; this module composes their tables with its own
until todo 550 moves the percentile family and deletes the package.
"""

from __future__ import annotations

import re
from collections.abc import Callable

import numpy as np

from src.intelligence.features.contract.registry import Kernel
from src.intelligence.features.kernels import _windowed
from src.intelligence.features.kernels._windowed import (
    HIGH_DIST,
    VWAP_DEV,
    check_window,
    chunked,
    rolling_max_distance_kernel,
    rolling_vwap_deviation_kernel,
)

PRICE_PERCENTILE = "rk_price_percentile"

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


def _price_percentile(close: np.ndarray, window: int) -> np.ndarray:
    def reduce(hist: np.ndarray) -> np.ndarray:
        current = hist[:, -1:]
        count = np.count_nonzero(hist <= current, axis=1)
        # scipy percentileofscore(kind="weak"): count(a <= score) * (100.0 / n); then
        # _percentile_rank divides by 100 and clips. Same operations, same order.
        pct = np.clip((count * (100.0 / window)) / 100.0, 0.0, 1.0)
        return np.where(np.isnan(hist).any(axis=1), np.nan, pct)

    return chunked((np.asarray(close, dtype=float),), window, reduce)


def rolling_percentile_kernel(window: int) -> Kernel:
    w = check_window(window)
    name = f"{PRICE_PERCENTILE}_w{w}"
    return Kernel(
        name=name,
        outputs=(name,),
        inputs=("close",),
        memory=lambda config: w - 1,
        compute=lambda x, config: {name: _price_percentile(x["close"], w)},
    )


FACTORIES: dict[str, Callable[[int], Kernel]] = {
    PRICE_PERCENTILE: rolling_percentile_kernel,
    **_windowed.FACTORIES,
}

# The battery windows (184 design section 5). None equals a stored window under the APR values
# at 2026-10-27 (percentile 50 and 200, 52-week high 252; the stored VWAP deviation has no
# window). kernel_source re-checks against the provenance config on every call.
KERNELS: tuple[Kernel, ...] = (
    rolling_percentile_kernel(126),
    rolling_max_distance_kernel(126),
    rolling_vwap_deviation_kernel(20),
)
