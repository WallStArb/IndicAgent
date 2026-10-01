"""Pure replay core of the 186-20 parity harness.

Replays a stored POOLED cross-sectional `feature_ic_scores` cell's observation set (label bars,
peer symbols, (bar_ts, symbol) order, stride) through `measure.ic.pooled_rank_ic`, with the
table's targets and with kernel targets, and attributes every target difference to a cause.

Nothing here opens a connection or reads APR: fetchers and `MeasureParams` are injected. The
live caller is `tests/integration/test_ic_parity_replay.py`.

Mirrors `services/ic_engine.py`:

- `_compute_cross_sectional_tf` (4634): label bars from `market_regimes` (`ts <= training_window_end`),
  rows from `feature_vectors` JOIN `forward_returns` for the group's peer symbols, fetched in chunks of
  label bars and ordered `ORDER BY fv.bar_ts, fv.symbol` (chunk SQL 4902-4915).
- `_compute_one_cross_sectional_cell` (3836): stride `max(subsample_min_stride, lookahead)` over the
  flattened order (3978, 3985-3989), then `valid_mask = complete & isfinite(return)` (3995-3997).
- `_subsample_and_rank` (2062): one pooled `rankdata(axis=0)` per column, Pearson on ranks.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Callable, Sequence

import numpy as np

from src.intelligence.measure.ic import IcCell, existing_rows, observation_rows, pooled_rank_ic
from src.intelligence.measure.params import MeasureParams
from src.intelligence.statistics.ic_math import _vectorized_ic

_FLOAT32_EPS = float(np.finfo(np.float32).eps)
_EXAMPLE_CAP = 5


@dataclasses.dataclass(frozen=True)
class ObservationRows:
    """Long-form rows of one fetch chunk, or of a whole rebuilt cell (see `ObservationSet`)."""

    bar_ts: np.ndarray  # [r] datetime64[ns], naive UTC
    symbols: np.ndarray  # [r] str
    X: np.ndarray  # [r, k] feature values
    returns: np.ndarray  # [r, s] forward return per active scale (NaN for NULL)
    complete: np.ndarray  # [r, s] bool, forward_returns.complete_<scale>
    has_gap: np.ndarray  # [r] bool, forward_returns.has_gap_before_entry


ObservationSet = ObservationRows  # the concatenation of every chunk, in fetch order


def rebuild_observation_set(
    label_bars: Sequence[np.datetime64],
    peer_symbols: Sequence[str],
    fetch_chunk: Callable[[list, list[str]], ObservationRows],
    *,
    chunk_ts: int,
) -> ObservationSet:
    """The cell's rows: label bars in chunks of `chunk_ts` (ic_engine `cs_chunk_ts`), each handed to
    `fetch_chunk(ts_chunk, peer_symbols)`, concatenated in label-bar order.

    Row order inside a chunk is the fetcher's (the live fetch is `ORDER BY fv.bar_ts, fv.symbol` in
    the database collation, which is ic_engine's order and decides which rows the stride picks), so
    it is checked, not re-sorted: bar_ts must be non-decreasing. A row whose bar is not a label bar
    or whose symbol is not a peer is refused. A (bar, symbol) with no row stays missing, as in
    ic_engine's inner join."""
    labels = np.asarray(label_bars, dtype="datetime64[ns]")
    label_set = set(labels.tolist())
    peers = set(peer_symbols)
    parts: list[ObservationRows] = []
    ordered = list(labels)
    for first in range(0, len(ordered), chunk_ts):
        chunk = fetch_chunk(ordered[first : first + chunk_ts], list(peer_symbols))
        if len(chunk.bar_ts) == 0:
            continue
        if not set(chunk.bar_ts.tolist()) <= label_set:
            raise ValueError("fetched a row on a bar that is not a label bar")
        if not set(chunk.symbols.tolist()) <= peers:
            raise ValueError("fetched a row for a symbol that is not a peer")
        parts.append(chunk)
    if not parts:
        raise ValueError("no rows for any label bar")
    merged = ObservationRows(
        bar_ts=np.concatenate([p.bar_ts for p in parts]),
        symbols=np.concatenate([p.symbols for p in parts]),
        X=np.concatenate([p.X for p in parts]),
        returns=np.concatenate([p.returns for p in parts]),
        complete=np.concatenate([p.complete for p in parts]),
        has_gap=np.concatenate([p.has_gap for p in parts]),
    )
    if (np.diff(merged.bar_ts.astype(np.int64)) < 0).any():
        raise ValueError("rows are not in non-decreasing bar_ts order")
    return merged


def stride_for(horizon: int, params: MeasureParams) -> int:
    """ic_engine's `scale_stride = max(subsample_min_stride, lookahead_bars)` (3978)."""
    return max(params.min_stride, horizon)


def replay_table_targets(
    obs: ObservationSet,
    *,
    scale_idx: int,
    horizon: int,
    params: MeasureParams,
    feature_names: tuple[str, ...] | None = None,
) -> IcCell:
    """Point IC of every feature column with the table's targets: a target counts when
    `complete_<scale>` and finite (ic_engine's `valid_mask`, 3997), the stride is
    `max(min_stride, horizon)` over the flattened order and runs before the mask."""
    y = np.where(obs.complete[:, scale_idx], obs.returns[:, scale_idx], np.nan)
    return pooled_rank_ic(
        obs.X,
        y,
        stride=stride_for(horizon, params),
        params=params,
        feature_names=feature_names,
        bootstrap=False,
    )


def replay_kernel_targets(
    features: np.ndarray,
    targets: np.ndarray,
    valid_grid: np.ndarray,
    present: np.ndarray,
    *,
    horizon: int,
    params: MeasureParams,
    feature_names: tuple[str, ...] | None = None,
) -> IcCell:
    """Point IC with kernel targets over [n, m, k] aligned features and [n, m] targets.

    The stride runs over `existing_rows(valid_grid, present)`: the (bar_ts, symbol) rows that exist
    in feature_vectors on traded bars, which is ic_engine's row set. `present` has no default: a
    selection by traded bar alone would count empty slots in the stride."""
    row_mask = existing_rows(valid_grid, present)
    x, y = observation_rows(features, targets, row_mask)
    return pooled_rank_ic(
        x,
        y,
        stride=stride_for(horizon, params),
        params=params,
        feature_names=feature_names,
        bootstrap=False,
    )


def legacy_arithmetic_ic(
    obs: ObservationSet, *, scale_idx: int, horizon: int, params: MeasureParams
) -> np.ndarray:
    """ic_engine's own arithmetic, for attribution: features cast to float32 (the
    `Float32ChunkAccumulator`), the stride slice, one `rankdata(axis=0)` over the strided rows BEFORE
    the valid mask (`_subsample_and_rank` 2194-2196), float32 ranks, `_vectorized_ic`. Returns the
    float32 IC per column; a column with a non-finite value in the strided rows has no rank and
    returns NaN, as `rankdata` propagates it."""
    from scipy.stats import rankdata

    stride = stride_for(horizon, params)
    x = obs.X[0::stride].astype(np.float32)
    y = np.where(obs.complete[:, scale_idx], obs.returns[:, scale_idx], np.nan)[0::stride]
    valid = obs.complete[0::stride, scale_idx] & np.isfinite(y)
    ranks_x = rankdata(x, axis=0).astype(np.float32)[valid]
    ranks_y = rankdata(y[valid]).astype(np.float32)
    return _vectorized_ic(ranks_x, ranks_y)


@dataclasses.dataclass(frozen=True)
class DiffCounts:
    n_rows: int
    n_equal: int
    n_end_of_window: int
    n_gap: int
    n_other: int
    examples: dict[str, list[int]]  # cause -> up to 5 row indices


def classify_target_diffs(
    table_y: np.ndarray,
    table_complete: np.ndarray,
    kernel_y: np.ndarray,
    *,
    has_gap: np.ndarray,
    in_grid: np.ndarray,
    grid_row: np.ndarray,
    n_grid: int,
    horizon: int,
    atol: float = 1e-12,
) -> DiffCounts:
    """Attribute each row where the kernel target differs from the table target to one cause.

    A row agrees when both are missing or both finite within `atol`. Otherwise, in this order:
    `end_of_window` (the kernel leaves rows `>= n_grid - 1 - horizon` NaN, so no target reaches
    oos_start), `gap` (the table row is flagged `has_gap_before_entry`, or its bar is absent from
    the kernel grid), `other` (anything else, including a finite kernel target where the table has
    none). `grid_row` is the row's index on the kernel grid (ignored where `in_grid` is False)."""
    table_ok = table_complete & np.isfinite(table_y)
    kernel_ok = np.isfinite(kernel_y)
    both_missing = ~table_ok & ~kernel_ok
    with np.errstate(invalid="ignore"):
        same = table_ok & kernel_ok & (np.abs(table_y - kernel_y) <= atol)
    equal = both_missing | same
    differ = ~equal
    end_of_window = differ & in_grid & ~kernel_ok & table_ok & (grid_row >= n_grid - 1 - horizon)
    gap = differ & ~end_of_window & (has_gap | ~in_grid)
    other = differ & ~end_of_window & ~gap
    examples = {
        "end_of_window": np.flatnonzero(end_of_window)[:_EXAMPLE_CAP].tolist(),
        "gap": np.flatnonzero(gap)[:_EXAMPLE_CAP].tolist(),
        "other": np.flatnonzero(other)[:_EXAMPLE_CAP].tolist(),
    }
    return DiffCounts(
        n_rows=len(table_y),
        n_equal=int(equal.sum()),
        n_end_of_window=int(end_of_window.sum()),
        n_gap=int(gap.sum()),
        n_other=int(other.sum()),
        examples=examples,
    )


@dataclasses.dataclass(frozen=True)
class IcComparison:
    match: bool
    delta: float  # replayed - stored; NaN when either side is missing


def compare_point_ic(
    replayed: float | None, stored: float | None, *, tol: float = 1e-9
) -> IcComparison:
    """Both missing (NaN or None) match; one missing does not; else |replayed - stored| <= tol."""
    r_missing = replayed is None or math.isnan(replayed)
    s_missing = stored is None or math.isnan(stored)
    if r_missing and s_missing:
        return IcComparison(True, float("nan"))
    if r_missing or s_missing:
        return IcComparison(False, float("nan"))
    delta = float(replayed) - float(stored)  # type: ignore[arg-type]
    return IcComparison(abs(delta) <= tol, delta)


def float32_pipeline_tolerance(n_independent: int) -> float:
    """Error bound of a stored ic_value against a float64 replay.

    ic_engine computes `_vectorized_ic` on float32 ranks and stores the float32 result, so a stored
    value carries float32 summation error: the sums run over n terms pairwise, relative error about
    eps32 * log2(n), and the cross-sum is a signed sum so the error does not shrink with the IC.
    The bound is 2 * eps32 * ceil(log2(n)), fixed here before any live result was read."""
    return 2.0 * _FLOAT32_EPS * math.ceil(math.log2(max(n_independent, 2)))
