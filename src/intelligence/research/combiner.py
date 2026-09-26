"""S7: the book's combiner over a stack of member alphas (D-10, D-22; E17's owner decision).

Two combiners share one interface (Combiner): `combine(stack, target)` returns the combined
alpha, and `training_rows` is how far before a row its fit reaches (the book's memory adds it).
EqualWeight is the default for new books: a fixed, pre-registration-signed mean of the
members' per-row z-scores, nothing fitted. RidgeSpec is the walk-forward ridge below; at a
per-slot IC of 0.002 its fold estimates cost about half the book's t (todo 432), so it is a
separately counted book version, not the default.

Walk-forward ridge:

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
by a fused per-row kernel, then prefix summed and differenced per fold. Compute-only numpy with no I/O, safe to run inside a
ProcessPoolExecutor worker (D-17).
"""

from __future__ import annotations

import dataclasses
import warnings
from typing import Protocol

import numpy as np
from numba import njit

_EPS = np.finfo(np.float64).eps


class Combiner(Protocol):
    @property
    def training_rows(self) -> int: ...

    def combine(self, stack: np.ndarray, target: np.ndarray) -> np.ndarray: ...


@dataclasses.dataclass(frozen=True)
class EqualWeight:
    """The mean over members of sign_k * z_k, z_k member k's cross-sectional z-score per row
    over the complete-case names (every member finite, as D-22); NaN elsewhere, and on a row
    with fewer than two such names or a member with zero spread. Signs are pre-registered."""

    signs: tuple[float, ...]

    def __post_init__(self) -> None:
        if not self.signs or any(s not in (-1.0, 1.0) for s in self.signs):
            raise ValueError(f"signs must be a non-empty tuple of +1 and -1, got {self.signs}")

    @property
    def training_rows(self) -> int:
        return 0

    def combine(self, stack: np.ndarray, target: np.ndarray) -> np.ndarray:
        if stack.ndim != 3 or stack.shape[2] != len(self.signs):
            raise ValueError(f"stack {stack.shape} does not match {len(self.signs)} signs")
        x = stack.astype(np.float64)
        complete = np.isfinite(x).all(axis=2, keepdims=True)
        x = np.where(complete, x, np.nan)
        with warnings.catch_warnings(), np.errstate(invalid="ignore", divide="ignore"):
            warnings.simplefilter("ignore", RuntimeWarning)  # empty rows stay NaN
            sd = np.nanstd(x, axis=1, keepdims=True)
            z = (x - np.nanmean(x, axis=1, keepdims=True)) / np.where(sd > 0, sd, np.nan)
        return (z * np.asarray(self.signs)).mean(axis=2)


@dataclasses.dataclass(frozen=True)
class RidgeSpec:
    """Walk-forward ridge settings, all counted in panel rows (the runner converts sessions)."""

    window_rows: int
    refit_rows: int
    penalty: float
    embargo: int
    min_obs: int

    @property
    def training_rows(self) -> int:
        return self.window_rows + self.embargo

    def combine(self, stack: np.ndarray, target: np.ndarray) -> np.ndarray:
        return walk_forward_ridge(stack, target, self)

    def __post_init__(self) -> None:
        if self.window_rows < 1 or self.refit_rows < 1 or self.embargo < 1:
            raise ValueError(f"window_rows, refit_rows and embargo must be positive: {self}")
        if not (np.isfinite(self.penalty) and self.penalty >= 0):
            raise ValueError(f"penalty must be finite and non-negative: {self}")


def refit_positions(n: int, spec: RidgeSpec) -> np.ndarray:
    """Refit rows: the first whose training window holds window_rows rows, then every refit_rows."""
    return np.arange(spec.window_rows + spec.embargo - 1, n, spec.refit_rows)


def _prefix_moments(stack: np.ndarray, target: np.ndarray) -> tuple[np.ndarray, ...]:
    """Prefix sums over rows of the complete-case moments (count, sum x, sum xx', sum xy,
    sum y), index r holding rows < r, plus `live` [n]: rows where some name has every member
    finite. Runs once per shift in the null and the power check, so the per-row accumulation
    is a fused kernel (float64 accumulation whatever the stack dtype)."""
    count, sx, sxx, sxy, sy, live = _row_moments_kernel(
        np.ascontiguousarray(stack), np.ascontiguousarray(target)
    )
    sums = tuple(np.cumsum(a, axis=0) for a in (count, sx, sxx, sxy, sy))
    return (*sums, live)


@njit(cache=True)
def _row_moments_kernel(stack, target):  # pragma: no cover - numba
    n, m, k = stack.shape
    count = np.zeros(n + 1)
    sx = np.zeros((n + 1, k))
    sxx = np.zeros((n + 1, k, k))
    sxy = np.zeros((n + 1, k))
    sy = np.zeros(n + 1)
    live = np.zeros(n, dtype=np.bool_)
    x = np.empty(k)
    for t in range(n):
        o = t + 1
        for i in range(m):
            complete = True
            for a in range(k):
                v = np.float64(stack[t, i, a])
                if not np.isfinite(v):
                    complete = False
                    break
                x[a] = v
            if not complete:
                continue
            live[t] = True
            y = np.float64(target[t, i])
            if not np.isfinite(y):
                continue
            count[o] += 1.0
            sy[o] += y
            for a in range(k):
                sx[o, a] += x[a]
                sxy[o, a] += x[a] * y
                for b in range(k):
                    sxx[o, a, b] += x[a] * x[b]
    return count, sx, sxx, sxy, sy, live


def walk_forward_ridge(stack: np.ndarray, target: np.ndarray, spec: RidgeSpec) -> np.ndarray:
    """Combined alpha [n, m] float64 from a member stack [n, m, K] and its target [n, m]."""
    if stack.ndim != 3 or target.shape != stack.shape[:2]:
        raise ValueError(f"stack {stack.shape} and target {target.shape} do not align")
    n, m, k = stack.shape
    combined = np.full((n, m), np.nan)
    positions = refit_positions(n, spec)
    if positions.size == 0:
        return combined
    # `live`: rows where some name has every member finite; prediction touches only those.
    count, sx, sxx, sxy, sy, live = _prefix_moments(stack, target)
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
