"""Pooled rank IC over a (bar_ts, symbol) observation set, over `ic_math`.

Rank IC and p-values are `ic_math`'s; the circular block bootstrap is `ic_math`'s statistic run
by the counting-rank kernel of `ic_bootstrap_jit` (`block_bootstrap_ci`). Nothing is
re-implemented here. This module fixes the observation order, the stride and the mask order so a stored
`feature_ic_scores` cell can be replayed to float tolerance (186-20).
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Sequence

import numpy as np

from src.intelligence.measure.params import MeasureParams
from src.intelligence.measure.targets import StackGrid, TargetStack
from src.intelligence.statistics.ic_bootstrap_jit import blocked_bootstrap_ics, dense_rank_inputs
from src.intelligence.statistics.ic_math import _p_values_from_ic, compute_ic_vectorized


@dataclasses.dataclass(frozen=True)
class IcCell:
    """One pooled cell: k features against one target over one observation set."""

    features: tuple[str, ...]
    ic: np.ndarray  # [k], NaN for degenerate features and unreliable-size cells
    n_obs: np.ndarray  # [k] complete finite pairs before the stride
    n_independent: np.ndarray  # [k] complete finite pairs after the stride (ic_engine's n_valid)
    p_value: np.ndarray  # [k]
    ci_lower: np.ndarray  # [k] circular block bootstrap 95% bounds, NaN when bootstrap=False
    ci_upper: np.ndarray  # [k]
    reliable: np.ndarray  # [k] bool, finite IC on at least params.min_obs strided pairs
    n_degenerate: int
    stride: int


def observation_rows(
    features: np.ndarray, targets: np.ndarray, row_mask: np.ndarray | None = None
) -> tuple[np.ndarray, np.ndarray]:
    """Flatten [n, m, k] features and [n, m] targets in (bar_ts, symbol) row-major order:
    row r = t * m + j. `row_mask` [n, m] is row existence, not completeness: it keeps the
    slots ic_engine would have a row for (traded bars, a regime's bars) without reordering,
    and it runs before `pooled_rank_ic`'s stride. Missing values are left in; the finite
    mask is applied after the stride."""
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


def existing_rows(valid_grid: np.ndarray, present: np.ndarray) -> np.ndarray:
    """[n, m] bool row existence as ic_engine has it: the bar traded (`valid_grid`) and the
    (bar_ts, symbol) has a feature row (`present`, from `SlotMap.present`). The one row
    selection every measure job hands to `observation_rows` before the stride."""
    if present.shape != valid_grid.shape or present.dtype != np.bool_:
        raise ValueError(
            f"present must be a bool array of shape {valid_grid.shape}, "
            f"got {present.dtype} {present.shape}"
        )
    return valid_grid & present


def _column_blocks(k: int):
    """(first, stop) column ranges covering k columns in about sqrt(k)-wide blocks.

    No block is a single column unless k is 1: numpy sums one column pairwise but several
    columns row by row, so a one-column block would not reproduce the whole-matrix
    `nanstd(axis=0)` bit for bit. The width bounds a block's temporaries to about
    n * sqrt(k) elements and never enters a value.
    """
    if k <= 2:
        yield 0, k
        return
    step = max(2, math.isqrt(k))
    first = 0
    while first < k:
        stop = min(first + step, k)
        if k - stop == 1:
            stop = k
        yield first, stop
        first = stop


@dataclasses.dataclass(frozen=True)
class PreparedFeatures:
    """A feature block with everything `pooled_rank_ic` derives from X alone, so a caller that
    measures the same rows against several targets (the term structure's horizons) computes the
    column std and the finite mask once and only ANDs in each target's mask."""

    X: np.ndarray  # [rows, k]
    names: tuple[str, ...]
    live: np.ndarray  # [k] bool, std at or above params.degenerate_std
    complete: np.ndarray  # [rows] bool, every live feature finite
    n_degenerate: int


def prepare_features(
    X: np.ndarray,
    params: MeasureParams,
    feature_names: tuple[str, ...] | None = None,
    *,
    complete: np.ndarray | None = None,
) -> PreparedFeatures:
    """Column std, degenerate columns and the finite-row mask of X, in column blocks.

    `complete` [rows] is the row completeness of the whole feature family (`FamilyCompleteness`):
    a row counts only when every live feature of the family is finite, exactly as ic_engine masks
    a cell over all of its features and only then works in `feature_block_columns` chunks
    (services/ic_engine.py, `valid_mask` before the block loop). Without it the mask is derived
    from this block alone, so a block's IC would depend on which other columns share it."""
    if X.ndim != 2:
        raise ValueError(f"X {X.shape} is not one row per observation")
    n, k = X.shape
    names = feature_names if feature_names is not None else tuple(f"f{j}" for j in range(k))
    if len(names) != k:
        raise ValueError(f"{len(names)} names for {k} features")
    std = np.full(k, np.nan)
    if n:
        with np.errstate(invalid="ignore"):
            for first, stop in _column_blocks(k):
                std[first:stop] = np.nanstd(X[:, first:stop], axis=0, dtype=np.float64)
    live = std >= params.degenerate_std  # NaN std (all-missing column) is degenerate too
    family_complete = complete
    live_idx = np.flatnonzero(live)
    complete = np.ones(n, dtype=bool)
    for first, stop in _column_blocks(len(live_idx)) if len(live_idx) else ():
        cols = live_idx[first:stop]
        block = X[:, first:stop] if len(live_idx) == k else X[:, cols]
        complete &= np.isfinite(block).all(axis=1)
    if family_complete is not None:
        if family_complete.shape != (n,) or family_complete.dtype != np.bool_:
            raise ValueError(f"complete must be a bool array of shape {(n,)}")
        if (family_complete & ~complete).any():
            raise ValueError("complete admits a row with a non-finite live feature in this block")
        complete = family_complete
    return PreparedFeatures(
        X=X, names=names, live=live, complete=complete, n_degenerate=int((~live).sum())
    )


class FamilyCompleteness:
    """Row completeness of a whole feature family, accumulated one block at a time.

    `add` takes a block's [rows, k] observation matrix (the rows the family is measured on, in
    the order `observation_rows` yields them); `complete` is then the AND of every block's
    live-feature finiteness, the mask ic_engine computes over all of a cell's features before it
    chunks them. Hand it to `pooled_rank_ic(complete=)` so no IC depends on the blocking."""

    def __init__(self, params: MeasureParams) -> None:
        self._params = params
        self._complete: np.ndarray | None = None

    def add(self, X: np.ndarray) -> None:
        block = prepare_features(X, self._params).complete
        self._complete = block if self._complete is None else self._complete & block

    @property
    def complete(self) -> np.ndarray:
        if self._complete is None:
            raise ValueError("FamilyCompleteness has no blocks")
        return self._complete


def merge_cells(cells: Sequence[IcCell]) -> IcCell:
    """The cells of feature blocks measured on the same rows and stride as one cell, features in
    block order; n_degenerate adds up."""
    if not cells:
        raise ValueError("no cells to merge")
    if len({c.stride for c in cells}) != 1:
        raise ValueError("cells disagree on the stride")
    return IcCell(
        features=tuple(f for c in cells for f in c.features),
        ic=np.concatenate([c.ic for c in cells]),
        n_obs=np.concatenate([c.n_obs for c in cells]),
        n_independent=np.concatenate([c.n_independent for c in cells]),
        p_value=np.concatenate([c.p_value for c in cells]),
        ci_lower=np.concatenate([c.ci_lower for c in cells]),
        ci_upper=np.concatenate([c.ci_upper for c in cells]),
        reliable=np.concatenate([c.reliable for c in cells]),
        n_degenerate=sum(c.n_degenerate for c in cells),
        stride=cells[0].stride,
    )


def pooled_rank_ic(
    X: np.ndarray,
    y: np.ndarray,
    *,
    stride: int,
    params: MeasureParams,
    feature_names: tuple[str, ...] | None = None,
    complete: np.ndarray | None = None,
    bootstrap: bool = True,
) -> IcCell:
    """Pooled Spearman IC per column of X against y, in the order ic_engine uses.

    Mirrors `services/ic_engine.py::_compute_one_cross_sectional_cell` (subsample at 3984-3990,
    valid mask at 3994-3996) and `_subsample_and_rank` (2062):

    1. Degenerate columns (std over the whole observation set below `params.degenerate_std`,
       ic_engine 2348) are dropped and counted; their IC is NaN.
    2. Stride: rows 0, stride, 2 * stride ... of the rows handed in. ic_engine's rows are the
       (bar_ts, symbol) pairs that exist in feature_vectors joined to forward_returns, so a
       caller drops slots that have no row (the stack's untraded bars, a regime's other bars)
       with `observation_rows(row_mask=...)` before this call; a slot that exists with a
       missing value stays in and is counted by the stride.
    3. Valid mask: target finite and every remaining feature finite (ic_engine's row
       completeness), applied after the stride.
    4. One pooled rankdata over the masked sample per column, Pearson on ranks
       (`compute_ic_vectorized`), t-approximation p-values on n_independent, circular block
       bootstrap CI (`block_bootstrap_ci`) with `default_rng(params.rng_seed)`.

    `n_independent` is the strided valid count: ic_engine stores exactly that as n_independent
    (`"n_independent": int(n_valid)`, 4125). Fewer than `params.min_obs` such rows gives NaN IC.

    A caller that measures a feature family in blocks passes `complete` (see `prepare_features`);
    every value is then independent of the blocking.

    `bootstrap=False` skips step 4's CI and leaves `ci_lower` and `ci_upper` NaN: ic, n_obs,
    n_independent, p_value and reliable do not depend on the CI, and every cell seeds its own
    generator, so skipping a cell's bootstrap cannot move another cell's. A caller that stores or
    reads no CI from a cell passes False; the bootstrap is the cell's whole cost.
    """
    if X.ndim != 2 or y.shape != (X.shape[0],):
        raise ValueError(f"X {X.shape} and y {y.shape} are not one row per observation")
    if stride < 1:
        raise ValueError(f"stride must be >= 1, got {stride}")
    return pooled_rank_ic_prepared(
        prepare_features(X, params, feature_names, complete=complete),
        y,
        stride=stride,
        params=params,
        bootstrap=bootstrap,
    )


def pooled_rank_ic_prepared(
    prepared: PreparedFeatures,
    y: np.ndarray,
    *,
    stride: int,
    params: MeasureParams,
    bootstrap: bool = True,
) -> IcCell:
    """`pooled_rank_ic` for a feature block prepared once; see it for the order of operations."""
    X, live, names = prepared.X, prepared.live, prepared.names
    if y.shape != (X.shape[0],):
        raise ValueError(f"X {X.shape} and y {y.shape} are not one row per observation")
    if stride < 1:
        raise ValueError(f"stride must be >= 1, got {stride}")
    k = X.shape[1]
    ic = np.full(k, np.nan)
    p_value = np.full(k, np.nan)
    ci_lower = np.full(k, np.nan)
    ci_upper = np.full(k, np.nan)
    n_obs = np.zeros(k, dtype=np.int64)
    n_independent = np.zeros(k, dtype=np.int64)
    reliable = np.zeros(k, dtype=bool)

    if live.any():
        complete = np.isfinite(y) & prepared.complete
        n_full = int(complete.sum())
        rows = np.flatnonzero(complete[0::stride]) * stride  # stride first, then the mask
        n_valid = len(rows)
        n_obs[live] = n_full
        n_independent[live] = n_valid
        if n_valid >= params.min_obs and n_valid > 2:
            Xv, yv = _live_columns(X, rows, live), y[rows]
            ic_live = compute_ic_vectorized(Xv, yv)
            ic[live] = ic_live
            p_value[live] = _p_values_from_ic(ic_live, n_valid)
            if bootstrap:
                ci_lower[live], ci_upper[live] = block_bootstrap_ci(Xv, yv, params)
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
        n_degenerate=prepared.n_degenerate,
        stride=stride,
    )


def block_bootstrap_ci(
    Xv: np.ndarray, yv: np.ndarray, params: MeasureParams
) -> tuple[np.ndarray, np.ndarray]:
    """95% circular block bootstrap bounds of the Spearman IC of each column of Xv against yv,
    the statistic of `ic_math._circular_block_bootstrap_ic` by the counting-rank kernel.

    Rows are complete and finite (the caller's valid mask). Each column and the target are dense
    ranked once; a resample's average ranks then come from counts and a prefix sum, with no sort
    (`ic_bootstrap_jit`). Centered ranks are multiples of 0.5, so their squares and products are
    multiples of 0.25 and every sum is exact in float64 while n**3 / 12 stays below 2**53 / 4
    (n below about 3.0e5): there each bound equals the scipy path bit for bit on float64 input,
    whatever the summation order. Above it both paths round, in different orders, and differ in
    the last places (about 1e-14 absolute measured at n from 4.5e5 to 2e6, todo 469); the kernel's
    own result is still the same for any thread count and slice size.

    The block starts are one stream from a fresh `default_rng(params.rng_seed)`, drawn in slices
    of `params.bootstrap_chunk_resamples` rows: a batched `integers(..., size=(B, K))` consumes
    the generator exactly as B draws of size K do (as ic_engine's blocked bootstrap relies on),
    so a slice never changes a row, and the starts matrix never exceeds one slice in memory.
    `params.bootstrap_threads` threads run the resample loop; rows are independent, so the
    thread count cannot change a value."""
    n_valid = len(yv)
    n_blocks = math.ceil(n_valid / params.bootstrap_block_size)
    offsets = np.arange(params.bootstrap_block_size)
    dense = dense_rank_inputs(Xv, yv, n_valid)
    rng = np.random.default_rng(params.rng_seed)
    resamples, chunk = params.bootstrap_resamples, params.bootstrap_chunk_resamples
    boot_ics = np.empty((resamples, Xv.shape[1]))
    for first in range(0, resamples, chunk):
        stop = min(first + chunk, resamples)
        starts = rng.integers(0, n_valid, size=(stop - first, n_blocks))
        boot_ics[first:stop] = blocked_bootstrap_ics(
            dense, starts, offsets, n_valid, params.bootstrap_threads
        )
    return np.percentile(boot_ics, 2.5, axis=0), np.percentile(boot_ics, 97.5, axis=0)


def _live_columns(X: np.ndarray, rows: np.ndarray, live: np.ndarray) -> np.ndarray:
    """X[rows][:, live] built column block by column block, without the row-selected copy of
    every column. Column-major, as numpy lays out a boolean column selection: the rank and
    Pearson sums downstream add along axis 0, and a row-major block would add in another order."""
    live_idx = np.flatnonzero(live)
    out = np.empty((len(rows), len(live_idx)), dtype=X.dtype, order="F")
    for first, stop in _column_blocks(len(live_idx)):
        out[:, first:stop] = X[np.ix_(rows, live_idx[first:stop])]
    return out


@dataclasses.dataclass(frozen=True)
class SlotMap:
    """Where long-form rows land on a stack grid: `rows[i]`, `cols[i]` for each input row with
    `ok[i]`. Built once per (bar_ts, symbols) and reused for every feature block."""

    ok: np.ndarray  # [N] bool, the row matches a grid slot
    rows: np.ndarray  # [ok.sum()] grid row index
    cols: np.ndarray  # [ok.sum()] grid column (symbol) index

    def present(self, n: int, m: int) -> np.ndarray:
        """[n, m] bool: the slots that received a row. A traded bar where one symbol has no
        feature_vectors row is a NaN slot on the grid that ic_engine has no row for; its stride
        counts only these slots. Pass it as `present` to the measure jobs."""
        out = np.zeros((n, m), dtype=bool)
        out[self.rows, self.cols] = True
        return out


def map_slots(stack: StackGrid | TargetStack, bar_ts: np.ndarray, symbols: np.ndarray) -> SlotMap:
    """Match long-form (timestamp, symbol) rows to grid slots by exact equality.

    Each distinct symbol is looked up once, not once per row. A duplicate (timestamp, symbol)
    raises: two values for one slot would make the survivor arbitrary.
    """
    if len(bar_ts) != len(symbols):
        raise ValueError("bar_ts, symbols and values must have one entry per row")
    m = len(stack.symbols)
    if len(bar_ts) == 0:
        empty = np.zeros(0, dtype=np.int64)
        return SlotMap(ok=np.zeros(0, dtype=bool), rows=empty, cols=empty)
    stamps = np.asarray(stack.timestamps).astype("datetime64[ns]")
    ts = np.asarray(bar_ts).astype("datetime64[ns]")
    pos = np.clip(np.searchsorted(stamps, ts), 0, len(stamps) - 1)
    ts_ok = stamps[pos] == ts
    col_of = {s: j for j, s in enumerate(stack.symbols)}
    labels = np.asarray(symbols)
    if labels.dtype.kind != "U":
        labels = labels.astype(str)  # str(s), as the per-row lookup did
    distinct, inverse = np.unique(labels, return_inverse=True)
    col_of_distinct = np.fromiter(
        (col_of.get(str(s), -1) for s in distinct), dtype=np.int64, count=len(distinct)
    )
    col = col_of_distinct[inverse.reshape(-1)]
    ok = ts_ok & (col >= 0)
    rows, cols = pos[ok], col[ok]
    flat = rows.astype(np.int64) * m + cols
    taken = np.zeros(len(stack.timestamps) * m, dtype=bool)
    taken[flat] = True
    if int(taken.sum()) != len(flat):
        raise ValueError("duplicate (timestamp, symbol) rows in the feature input")
    return SlotMap(ok=ok, rows=rows, cols=cols)


def scatter_features(
    stack: StackGrid | TargetStack, slots: SlotMap, values: np.ndarray
) -> tuple[np.ndarray, int]:
    """Scatter long-form `values` onto the grid through a `SlotMap`: ([n, m, k] with NaN where
    no row landed, count of input rows matching no grid slot)."""
    values = np.asarray(values, dtype=float)
    if values.ndim == 1:
        values = values[:, None]
    if len(values) != len(slots.ok):
        raise ValueError("bar_ts, symbols and values must have one entry per row")
    grid = np.full((len(stack.timestamps), len(stack.symbols), values.shape[1]), np.nan)
    if len(values):
        grid[slots.rows, slots.cols] = values[slots.ok]
    return grid, int((~slots.ok).sum())


def align_features(
    stack: StackGrid | TargetStack, bar_ts: np.ndarray, symbols: np.ndarray, values: np.ndarray
) -> tuple[np.ndarray, int]:
    """Scatter long-form feature rows onto the stack grid by exact (timestamp, symbol) match.

    `bar_ts` is naive UTC (bar start on intraday, the session date's 00:00 on 1d, the keys
    `build_grid` uses). Returns ([n, m, k] with NaN where no row landed, count of input rows
    matching no grid slot). A duplicate (timestamp, symbol) raises. A caller aligning several
    feature blocks of the same rows calls `map_slots` once and `scatter_features` per block.
    """
    values = np.asarray(values, dtype=float)
    if not (len(bar_ts) == len(symbols) == len(values)):
        raise ValueError("bar_ts, symbols and values must have one entry per row")
    return scatter_features(stack, map_slots(stack, bar_ts, symbols), values)
