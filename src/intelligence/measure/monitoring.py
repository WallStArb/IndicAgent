"""Monitoring job: per-member IC over time for frozen-book members (D-17).

The caller (186-14) supplies each member's feature grid; this module looks up no books.
"""

from __future__ import annotations

import dataclasses

import numpy as np

from src.intelligence.measure.ic import existing_rows, observation_rows, pooled_rank_ic
from src.intelligence.measure.params import MeasureParams
from src.intelligence.measure.targets import TargetStack, stride


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


def _hac_sharpe_gapped(ic: np.ndarray, max_lag: int) -> float:
    """Newey-West Bartlett IC Sharpe over a time-indexed window series that may hold NaN.

    ic_math._hac_sharpe_nd assumes adjacent rows are adjacent windows; dropping NaN windows
    first would pair windows that are not lag-k apart. Mean and variance use the finite
    windows; the lag-k autocovariance averages demeaned products over the pairs (t, t + k)
    that are both finite in the original series (none: rho_k = 0). Identical to
    _hac_sharpe_nd on a series without NaN."""
    ok = np.isfinite(ic)
    finite = ic[ok]
    n = finite.size
    mean = finite.mean()
    var0 = ((finite - mean) ** 2).mean()
    inflation = 1.0
    if max_lag > 0 and n >= max_lag + 2:
        demeaned = np.where(ok, ic - mean, 0.0)
        for k in range(1, max_lag + 1):
            pair = ok[k:] & ok[:-k]
            if not pair.any():
                continue
            gamma_k = (demeaned[k:][pair] * demeaned[:-k][pair]).mean()
            rho_k = gamma_k / var0 if var0 > 1e-12 else 0.0
            inflation += 2.0 * (1.0 - k / (max_lag + 1)) * rho_k
        inflation = max(inflation, 1.0)  # can't be more precise than i.i.d.
    hac_std = np.sqrt(var0 * inflation)
    return float(mean / hac_std) if hac_std > 1e-10 else 0.0


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
        cell = pooled_rank_ic(X, y, stride=stride(stack, params), params=params)
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
        hac = _hac_sharpe_gapped(ic, params.hac_max_lag)
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
