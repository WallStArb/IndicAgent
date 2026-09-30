"""Inputs for the daily-grid kernels (186-15).

`cross_asset_daily` and `factor_beta_daily` run on a daily reference grid: one row per date. On
an intraday row grid several rows share a date, and a builder keyed by date would see the later
rows of the same date, so the causality probe runs these kernels on this grid instead. Not a
test module.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np

from tests.unit.intelligence import kernel_parity_reference as ref

DAILY_GRID_KERNELS = frozenset({"cross_asset_daily", "factor_beta_daily"})
_CLOSE_COLUMNS = (
    "ref_spy_close",
    "ref_tlt_close",
    "ref_shy_close",
    "ref_tip_close",
    "ref_hyg_close",
    "ref_lqd_close",
    "ref_sym_close",
)


def daily_grid_inputs(n: int, seed: int = 21) -> dict[str, np.ndarray]:
    """n consecutive calendar dates, seven positive random-walk closes and the symbol."""
    rng = np.random.default_rng(seed)
    start = datetime(2015, 1, 5, tzinfo=UTC)
    ts = np.array(
        [ref.dt_to_ns(start + timedelta(days=i)) for i in range(n)],
        dtype=np.int64,
    )
    inputs: dict[str, np.ndarray] = {"ts": ts, "symbol": np.array(["QQQ"] * n, dtype=object)}
    for name in _CLOSE_COLUMNS:
        inputs[name] = np.cumprod(1.0 + rng.normal(0.0, 0.01, n)) * 100.0
    return inputs


def intraday_kernels(kernels) -> tuple:
    return tuple(k for k in kernels if k.name not in DAILY_GRID_KERNELS)


def daily_grid_kernels(kernels) -> tuple:
    return tuple(k for k in kernels if k.name in DAILY_GRID_KERNELS)
