"""Monitoring job: per-member IC over time for frozen-book members (D-17).

The caller (186-14) supplies each member's feature grid; this module looks up no books.
"""

from __future__ import annotations

import dataclasses

import numpy as np

from src.intelligence.measure.ic import observation_rows, pooled_rank_ic
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
    feature: np.ndarray, member: str, stack: TargetStack, params: MeasureParams
) -> MemberIcSeries:
    """IC per window of `params.monitor_window_sessions` whole sessions, stride
    max(params.min_stride, horizon) applied inside each window. A trailing short window is
    reported with its own session count, never merged into the previous one."""
    n, m = stack.targets.shape
    if feature.shape != (n, m):
        raise ValueError(f"feature {feature.shape} does not match the stack grid {(n, m)}")
    per_window = params.monitor_window_sessions
    n_sessions = int(stack.session[-1]) + 1 if n else 0
    valid_grid = stack.valid_grid()
    starts, counts, ics, nobs = [], [], [], []
    for first in range(0, n_sessions, per_window):
        last = min(first + per_window, n_sessions)
        rows = np.flatnonzero((stack.session >= first) & (stack.session < last))
        mask = valid_grid[rows]
        X, y = observation_rows(feature[rows][:, :, None], stack.targets[rows], mask)
        cell = pooled_rank_ic(X, y, stride=stride(stack, params), params=params)
        starts.append(stack.timestamps[rows[0]])
        counts.append(last - first)
        ics.append(float(cell.ic[0]))
        nobs.append(int(cell.n_independent[0]))
    ic = np.asarray(ics, dtype=float)
    finite = ic[np.isfinite(ic)]
    if finite.size:
        mean = float(finite.mean())
        sd = float(finite.std())
        sharpe = mean / sd if sd > 1e-10 else 0.0
        hac = float(_hac_sharpe_nd(finite[:, None], params.hac_max_lag)[0])
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
