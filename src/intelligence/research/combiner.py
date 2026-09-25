"""S7: walk-forward ridge over a stack of member alphas (D-10, D-22).

Inputs are the factor-residualized member alphas stack[t, i, k] and the S1 residual forward
return target[t, i]. At each refit row p (refit_positions) one coefficient vector b, pooled
across names, is fitted on the stacked (row, name) observations of the training rows
[max(0, hi - window_rows), hi) with hi = p - embargo + 1: an embargo of the forward return's span
(panel.fwd_span(horizon)) sits between the last training row and p, so no target the fit sees
overlaps the first predicted row. Rows p up to the next refit are predicted with that fit.

- Complete cases only (D-22): an observation enters training when the target and every member
  are finite; a prediction is NaN where any member is NaN. Nothing is filled.
- Members are standardized inside each fold on the fold's training moments only (population
  mean and sd of the complete cases); the penalty acts on that standardized scale:
  b = solve(corr + penalty * I, cov(z, y)). A fold with fewer than min_obs observations, a
  member with zero training sd, or a non-finite solve predicts NaN for its block; rows before
  the first refit are NaN.
- Window, cadence and penalty come from the caller (the book spec pins them; the penalty is
  never tuned on vintage outcomes). R1 ranks the combined alpha cross-sectionally, so only the
  sign and relative size of b matter: the penalty has no leverage effect (research open
  question 6).

Moments come from per-row sums (count, sum x, sum xx', sum xy, sum y) accumulated in float64
over the rows holding at least one complete case, in chunks of refit_rows rows, then prefix
summed and differenced per fold. Compute-only numpy with no I/O, safe to run inside a
ProcessPoolExecutor worker (D-17).
"""

from __future__ import annotations

import dataclasses

import numpy as np

_EPS = np.finfo(np.float64).eps


@dataclasses.dataclass(frozen=True)
class RidgeSpec:
    """Walk-forward ridge settings, all counted in panel rows (the runner converts sessions)."""

    window_rows: int
    refit_rows: int
    penalty: float
    embargo: int
    min_obs: int

    def __post_init__(self) -> None:
        if self.window_rows < 1 or self.refit_rows < 1 or self.embargo < 1:
            raise ValueError(f"window_rows, refit_rows and embargo must be positive: {self}")
        if not (np.isfinite(self.penalty) and self.penalty >= 0):
            raise ValueError(f"penalty must be finite and non-negative: {self}")


def refit_positions(n: int, spec: RidgeSpec) -> np.ndarray:
    """Refit rows: the first whose training window holds window_rows rows, then every refit_rows."""
    return np.arange(spec.window_rows + spec.embargo - 1, n, spec.refit_rows)


def _prefix_moments(
    stack: np.ndarray, target: np.ndarray, chunk_rows: int
) -> tuple[np.ndarray, ...]:
    n, _, k = stack.shape
    ok = np.isfinite(target) & np.isfinite(stack).all(axis=2)
    rows = np.flatnonzero(ok.any(axis=1))
    count = np.zeros(n + 1)
    sx = np.zeros((n + 1, k))
    sxx = np.zeros((n + 1, k, k))
    sxy = np.zeros((n + 1, k))
    sy = np.zeros(n + 1)
    for start in range(0, rows.size, chunk_rows):
        r = rows[start : start + chunk_rows]
        w = ok[r]
        x = np.where(w[..., None], stack[r], 0).astype(np.float64)
        y = np.where(w, target[r], 0).astype(np.float64)
        out = r + 1
        count[out] = w.sum(axis=1)
        sx[out] = x.sum(axis=1)
        sxx[out] = np.matmul(x.transpose(0, 2, 1), x)
        sxy[out] = np.matmul(x.transpose(0, 2, 1), y[..., None])[..., 0]
        sy[out] = y.sum(axis=1)
    return tuple(np.cumsum(a, axis=0) for a in (count, sx, sxx, sxy, sy))


def walk_forward_ridge(stack: np.ndarray, target: np.ndarray, spec: RidgeSpec) -> np.ndarray:
    """Combined alpha [n, m] float64 from a member stack [n, m, K] and its target [n, m]."""
    if stack.ndim != 3 or target.shape != stack.shape[:2]:
        raise ValueError(f"stack {stack.shape} and target {target.shape} do not align")
    n, m, k = stack.shape
    combined = np.full((n, m), np.nan)
    positions = refit_positions(n, spec)
    if positions.size == 0:
        return combined
    count, sx, sxx, sxy, sy = _prefix_moments(stack, target, spec.refit_rows)
    # Prediction touches only rows where some name has every member finite; the rest stay NaN.
    live = np.isfinite(stack).all(axis=2).any(axis=1)
    eye = np.eye(k)
    ends = np.append(positions[1:], n)
    for p, q in zip(positions, ends, strict=True):
        hi = p - spec.embargo + 1
        lo = max(0, hi - spec.window_rows)
        c = count[hi] - count[lo]
        if c < spec.min_obs or c <= 0:
            continue
        mu = (sx[hi] - sx[lo]) / c
        cov = (sxx[hi] - sxx[lo]) / c - np.outer(mu, mu)
        diag = np.diag(cov)
        # A constant member's variance is zero only up to the rounding of the prefix difference
        # and the mean-square cancellation; anything within that bound counts as zero sd.
        rounding = _EPS * (np.abs(np.diag(sxx[hi])) + np.abs(np.diag(sxx[lo])) + c * mu * mu) / c
        if not np.all(diag > rounding):
            continue
        sd = np.sqrt(diag)
        rhs = ((sxy[hi] - sxy[lo]) / c - mu * ((sy[hi] - sy[lo]) / c)) / sd
        try:
            b = np.linalg.solve(cov / np.outer(sd, sd) + spec.penalty * eye, rhs)
        except np.linalg.LinAlgError:
            continue
        if not np.all(np.isfinite(b)):
            continue
        rows = p + np.flatnonzero(live[p:q])
        combined[rows] = (stack[rows].astype(np.float64) - mu) @ (b / sd)
    return combined
