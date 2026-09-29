"""Pooled rank IC over a (bar_ts, symbol) observation set, over `ic_math`.

Rank IC, p-values and the circular block bootstrap are `ic_math`'s; nothing is re-implemented
here. This module fixes the observation order, the stride and the mask order so a stored
`feature_ic_scores` cell can be replayed to float tolerance (186-20).
"""

from __future__ import annotations

import dataclasses

import numpy as np

from src.intelligence.measure.params import MeasureParams
from src.intelligence.measure.targets import TargetStack
from src.intelligence.statistics.ic_math import (
    _circular_block_bootstrap_ic,
    _p_values_from_ic,
    compute_ic_vectorized,
)


@dataclasses.dataclass(frozen=True)
class IcCell:
    """One pooled cell: k features against one target over one observation set."""

    features: tuple[str, ...]
    ic: np.ndarray  # [k], NaN for degenerate features and unreliable-size cells
    n_obs: np.ndarray  # [k] complete finite pairs before the stride
    n_independent: np.ndarray  # [k] complete finite pairs after the stride (ic_engine's n_valid)
    p_value: np.ndarray  # [k]
    ci_lower: np.ndarray  # [k] circular block bootstrap 95% bounds
    ci_upper: np.ndarray  # [k]
    reliable: np.ndarray  # [k] bool, finite IC on at least params.min_obs strided pairs
    n_degenerate: int
    stride: int


def observation_rows(
    features: np.ndarray, targets: np.ndarray, row_mask: np.ndarray | None = None
) -> tuple[np.ndarray, np.ndarray]:
    """Flatten [n, m, k] features and [n, m] targets in (bar_ts, symbol) row-major order:
    row r = t * m + j. `row_mask` [n, m] keeps a subset without reordering it."""
    n, m, k = features.shape
    if targets.shape != (n, m):
        raise ValueError(f"targets {targets.shape} do not match features {(n, m)}")
    x = features.reshape(n * m, k)
    y = targets.reshape(n * m)
    if row_mask is not None:
        if row_mask.shape != (n, m):
            raise ValueError(f"row_mask {row_mask.shape} does not match {(n, m)}")
        keep = row_mask.reshape(n * m)
        x, y = x[keep], y[keep]
    return x, y


def pooled_rank_ic(
    X: np.ndarray,
    y: np.ndarray,
    *,
    stride: int,
    params: MeasureParams,
    feature_names: tuple[str, ...] | None = None,
) -> IcCell:
    """Pooled Spearman IC per column of X against y, in the order ic_engine uses.

    Mirrors `services/ic_engine.py::_compute_one_cross_sectional_cell` (subsample at 3984-3990,
    valid mask at 3994-3996) and `_subsample_and_rank` (2062):

    1. Degenerate columns (std over the whole observation set below `params.degenerate_std`,
       ic_engine 2348) are dropped and counted; their IC is NaN.
    2. Stride: rows 0, stride, 2 * stride ... of the flattened order (a slice, before any mask).
    3. Valid mask: target finite and every remaining feature finite (ic_engine's row
       completeness), applied after the stride.
    4. One pooled rankdata over the masked sample per column, Pearson on ranks
       (`compute_ic_vectorized`), t-approximation p-values on n_independent, circular block
       bootstrap CI with `default_rng(params.rng_seed)`.

    `n_independent` is the strided valid count: ic_engine stores exactly that as n_independent
    (`"n_independent": int(n_valid)`, 4125). Fewer than `params.min_obs` such rows gives NaN IC.
    """
    if X.ndim != 2 or y.shape != (X.shape[0],):
        raise ValueError(f"X {X.shape} and y {y.shape} are not one row per observation")
    if stride < 1:
        raise ValueError(f"stride must be >= 1, got {stride}")
    k = X.shape[1]
    names = feature_names if feature_names is not None else tuple(f"f{j}" for j in range(k))
    if len(names) != k:
        raise ValueError(f"{len(names)} names for {k} features")
    with np.errstate(invalid="ignore"):
        std = np.nanstd(X, axis=0, dtype=np.float64) if X.shape[0] else np.full(k, np.nan)
    live = std >= params.degenerate_std  # NaN std (all-missing column) is degenerate too
    n_degenerate = int((~live).sum())

    ic = np.full(k, np.nan)
    p_value = np.full(k, np.nan)
    ci_lower = np.full(k, np.nan)
    ci_upper = np.full(k, np.nan)
    n_obs = np.zeros(k, dtype=np.int64)
    n_independent = np.zeros(k, dtype=np.int64)
    reliable = np.zeros(k, dtype=bool)

    def _complete(x: np.ndarray, target: np.ndarray) -> np.ndarray:
        return np.isfinite(target) & np.isfinite(x[:, live]).all(axis=1)

    if live.any():
        n_full = int(_complete(X, y).sum())
        Xs, ys = X[0::stride], y[0::stride]
        valid = _complete(Xs, ys)
        n_valid = int(valid.sum())
        n_obs[live] = n_full
        n_independent[live] = n_valid
        if n_valid >= params.min_obs and n_valid > 2:
            Xv, yv = Xs[valid][:, live], ys[valid]
            ic_live = compute_ic_vectorized(Xv, yv)
            lo, hi = _circular_block_bootstrap_ic(
                Xv,
                yv,
                params.bootstrap_block_size,
                params.bootstrap_resamples,
                np.random.default_rng(params.rng_seed),
            )
            ic[live] = ic_live
            p_value[live] = _p_values_from_ic(ic_live, n_valid)
            ci_lower[live], ci_upper[live] = lo, hi
            reliable[live] = np.isfinite(ic_live)
    return IcCell(
        features=names,
        ic=ic,
        n_obs=n_obs,
        n_independent=n_independent,
        p_value=p_value,
        ci_lower=ci_lower,
        ci_upper=ci_upper,
        reliable=reliable,
        n_degenerate=n_degenerate,
        stride=stride,
    )


def align_features(
    stack: TargetStack, bar_ts: np.ndarray, symbols: np.ndarray, values: np.ndarray
) -> tuple[np.ndarray, int]:
    """Scatter long-form feature rows onto the stack grid by exact (timestamp, symbol) match.

    `bar_ts` is naive UTC (bar start on intraday, the session date's 00:00 on 1d, the keys
    `build_grid` uses). Returns ([n, m, k] with NaN where no row landed, count of input rows
    matching no grid slot). A duplicate (timestamp, symbol) raises: two values for one slot
    would make the survivor arbitrary.
    """
    values = np.asarray(values, dtype=float)
    if values.ndim == 1:
        values = values[:, None]
    if not (len(bar_ts) == len(symbols) == len(values)):
        raise ValueError("bar_ts, symbols and values must have one entry per row")
    grid = np.full((len(stack.timestamps), len(stack.symbols), values.shape[1]), np.nan)
    if len(values) == 0:
        return grid, 0
    stamps = np.asarray(stack.timestamps).astype("datetime64[ns]")
    ts = np.asarray(bar_ts).astype("datetime64[ns]")
    pos = np.clip(np.searchsorted(stamps, ts), 0, len(stamps) - 1)
    ts_ok = stamps[pos] == ts
    col_of = {s: j for j, s in enumerate(stack.symbols)}
    col = np.fromiter((col_of.get(str(s), -1) for s in symbols), dtype=np.int64, count=len(symbols))
    ok = ts_ok & (col >= 0)
    rows, cols = pos[ok], col[ok]
    flat = rows.astype(np.int64) * len(stack.symbols) + cols
    if len(np.unique(flat)) != len(flat):
        raise ValueError("duplicate (timestamp, symbol) rows in the feature input")
    grid[rows, cols] = values[ok]
    return grid, int((~ok).sum())
