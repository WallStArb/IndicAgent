"""Monitoring job: per-member IC over time for frozen-book members (D-17).

The caller (186-14) supplies each member's feature grid; this module looks up no books.
"""

from __future__ import annotations

import dataclasses

import numpy as np

from src.intelligence.measure.ic import existing_rows, observation_rows, pooled_rank_ic
from src.intelligence.measure.params import MeasureParams
from src.intelligence.measure.targets import TargetStack, stride
from src.intelligence.statistics.ic_math import _hac_sharpe_nd


@dataclasses.dataclass(frozen=True)
class MemberIcSeries:
    member: str
    window_start: np.ndarray  # [W] timestamp of each window's first row
    n_sessions: np.ndarray  # [W] whole sessions in the window
    ic: np.ndarray  # [W]
    n_obs: np.ndarray  # [W] strided valid pairs
    mean_ic: float
    ic_sharpe: float  # mean / population std across windows
    ic_sharpe_hac: float  # Newey-West Bartlett, ic_math._hac_sharpe_nd
    partial_tail_sessions: int  # sessions in a trailing short window, 0 if none


def member_ic_over_time(
    feature: np.ndarray,
    member: str,
    stack: TargetStack,
    params: MeasureParams,
    *,
    present: np.ndarray,
) -> MemberIcSeries:
    """IC per window of `params.monitor_window_sessions` whole sessions, stride
    max(params.min_stride, horizon) applied inside each window, over the rows that exist
    (`present` [n, m] from `SlotMap.present`; the traded-bar mask alone would count NaN slots).
    A trailing short window is reported with its own session count, never merged into the
    previous one."""
    n, m = stack.targets.shape
    if feature.shape != (n, m):
        raise ValueError(f"feature {feature.shape} does not match the stack grid {(n, m)}")
    per_window = params.monitor_window_sessions
    n_sessions = int(stack.session[-1]) + 1 if n else 0
    valid_grid = existing_rows(stack.valid_grid(), present)
    # `session` is non-decreasing, so each window's rows are one contiguous slice: two binary
    # searches and views instead of a scan of every row per window.
    firsts = np.arange(0, n_sessions, per_window)
    lasts = np.minimum(firsts + per_window, n_sessions)
    lows, highs = (np.searchsorted(stack.session, edge) for edge in (firsts, lasts))
    starts, counts, ics, nobs = [], [], [], []
    for first, last, lo, hi in zip(firsts.tolist(), lasts.tolist(), lows.tolist(), highs.tolist()):
        X, y = observation_rows(feature[lo:hi, :, None], stack.targets[lo:hi], valid_grid[lo:hi])
        # the window IC is the only value kept, so its CI is not computed
        cell = pooled_rank_ic(X, y, stride=stride(stack, params), params=params, bootstrap=False)
        starts.append(stack.timestamps[lo])
        counts.append(last - first)
        ics.append(float(cell.ic[0]))
        nobs.append(int(cell.n_independent[0]))
    ic = np.asarray(ics, dtype=float)
    finite = ic[np.isfinite(ic)]
    if finite.size:
        mean = float(finite.mean())
        sd = float(finite.std())
        sharpe = mean / sd if sd > params.monitor_degenerate_std else 0.0
        hac = float(_hac_sharpe_nd(ic[:, None], params.hac_max_lag)[0])
    else:
        mean = sharpe = hac = float("nan")
    tail = counts[-1] if counts and counts[-1] < per_window else 0
    return MemberIcSeries(
        member=member,
        window_start=np.asarray(starts),
        n_sessions=np.asarray(counts, dtype=np.int64),
        ic=ic,
        n_obs=np.asarray(nobs, dtype=np.int64),
        mean_ic=mean,
        ic_sharpe=sharpe,
        ic_sharpe_hac=hac,
        partial_tail_sessions=tail,
    )
