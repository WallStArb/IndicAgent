"""S7: the book's combiner over a stack of member alphas (D-10, D-22; E17's owner decision).

Two combiners share one interface (Combiner): `combine(stack, target)` returns the combined
alpha, and `training_rows` is how far before a row its fit reaches (the book's memory adds it).
EqualWeight is the default for new books: a fixed, pre-registration-signed mean of the
members' per-row z-scores, nothing fitted. RidgeSpec is the walk-forward ridge below; at a
per-slot IC of 0.002 its fold estimates cost about half the book's t (todo 432), so it is a
separately counted book version, not the default.

In-fold signs (design 4.2, plan 187-09 R-187-17): an equal-weight member with no stated prior
takes its sign from a training fold. At each refit row p (the ridge's grid: refit_positions, or
anchored_refit_positions with refit_anchor) the sign is the sign of the member's fold IC, the
mean over training rows [max(0, hi - window_rows), hi), hi = p - embargo + 1, of the per-row
cross-sectional Pearson correlation between its z-score and the target, and holds for rows p up
to the next refit. The fold is trailing, not expanding (owner 2026-10-27): design 4.5 puts every
fitted part's reach into L, and an expanding fold's reach is the whole history. A zero or
undefined fold IC makes the member absent for that block, as are rows before the first refit;
without min_members an absent member makes the cell NaN (complete-case).

Walk-forward ridge:

Inputs are the factor-residualized member alphas stack[t, i, k] and the S1 residual forward
return target[t, i]. At each refit row p (refit_positions) one coefficient vector b, pooled
across names, is fitted on the stacked (row, name) observations of the training rows
[max(0, hi - window_rows), hi) with hi = p - embargo + 1: an embargo of the forward return's span
(panel.fwd_span(horizon)) sits between the last training row and p, so no target the fit sees
overlaps the first predicted row. Rows p up to the next refit are predicted with that fit.

- Refits anchor to row 0 by default. With `refit_anchor` (plan 187-09, R-187-18) they fall on
  calendar dates instead, so two panels over the same dates, or a forward run that starts on a
  later row, refit on the same sessions: the grid is every refit_rows / bars_per_session-th
  exchange session counted from the first session on or after the anchor (in both
  directions, so the anchor sets a phase, not a start), and each grid date maps to the first
  row of the first panel session on or after it. A session the panel lacks never skips a
  refit; it moves to the next panel session. The first-refit rule (a full window) is kept.
  The sessions are the exchange calendar S0's grid is checked against, never business days.

- Complete cases only (D-22): an observation enters training when the target and every member
  are finite; a prediction is NaN where any member is NaN. Nothing is filled.
- With `min_members` (design 4.1, plan 187-09) training stays complete-case, and a cell with at
  least `min_members` members present is predicted by the fold's best linear forecast from
  those members alone: b_P = solve(R_PP + penalty I, c_P) on the same standardized moments
  (R the members' correlation, c their covariance with the target), applied to z_P. Less
  information gives a smaller, not an inflated, forecast. (A rescale to the full forecast's
  spread, proposed in review, was rejected: it gives a lone member with a near-zero
  coefficient a full-size position.) Complete cells use b itself, bit for bit as without the
  field.
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
import datetime
import warnings
from typing import Protocol

import numpy as np
from numba import njit

from src.core.market_calendar import get_market_calendar

_EPS = np.finfo(np.float64).eps
# The exchange whose sessions S0's grid is checked against (snapshot._EXCHANGE, test-pinned).
_EXCHANGE = "NYSE"


class Combiner(Protocol):
    @property
    def training_rows(self) -> int: ...

    def combine(
        self, stack: np.ndarray, target: np.ndarray, *, row_session_dates: np.ndarray | None = None
    ) -> np.ndarray: ...


@dataclasses.dataclass(frozen=True)
class EqualWeight:
    """The mean over members of sign_k * z_k, z_k member k's cross-sectional z-score per row
    over the complete-case names (every member finite, as D-22); NaN elsewhere, and on a row
    with fewer than two such names or a member with zero spread. Signs are pre-registered.

    With `min_members` (design 4.1, plan 187-09) the rule is present-member: each member is
    z-scored per row over the names where it is finite (positive spread), and a cell is
    sum over the present members of sign_k * z_k / K, NaN with fewer than `min_members`
    present. Each member keeps its 1/K weight and an absent member contributes nothing, so a
    cell built from less information has a smaller forecast (closer to the median rank), the
    equal-weight analogue of the ridge's subset forecast. Averaging over the present members
    instead (design 4.1's wording) would give a lone member the full spread and push names
    with missing members to the extremes (187-09 review). A combining rule, not a fill:
    nothing is invented."""

    signs: tuple[float | None, ...]  # None: the member's sign comes from the fold (in-fold)
    min_members: int | None = None
    fold: SignFold | None = None  # required exactly when some sign is None

    def __post_init__(self) -> None:
        if not self.signs or any(s not in (-1.0, 1.0, None) for s in self.signs):
            raise ValueError(f"signs must be a non-empty tuple of +1, -1 or None: {self.signs}")
        if (self.fold is None) != (None not in self.signs):
            raise ValueError("a fold is required exactly when some sign is in-fold (None)")
        if self.min_members is not None and not 1 <= self.min_members <= len(self.signs):
            raise ValueError(f"min_members must be in 1 .. {len(self.signs)}: {self.min_members}")

    @property
    def training_rows(self) -> int:
        return 0 if self.fold is None else self.fold.window_rows + self.fold.embargo

    def _signed_scores(
        self, stack: np.ndarray, target: np.ndarray, row_session_dates: np.ndarray | None
    ) -> np.ndarray:
        """z * signs [n, m, K]: each member's signed cross-sectional z-score per cell (NaN where
        the member is absent, or on a non-complete row under the complete-case rule)."""
        # With fixed signs nothing is fitted, so there are no refits and the session dates are
        # not read; in-fold signs refit on the fold's grid (refit_anchor reads them).
        if stack.ndim != 3 or stack.shape[2] != len(self.signs):
            raise ValueError(f"stack {stack.shape} does not match {len(self.signs)} signs")
        x = stack.astype(np.float64)
        if self.min_members is None:
            complete = np.isfinite(x).all(axis=2, keepdims=True)
            x = np.where(complete, x, np.nan)
        with warnings.catch_warnings(), np.errstate(invalid="ignore", divide="ignore"):
            warnings.simplefilter("ignore", RuntimeWarning)  # empty rows stay NaN
            sd = np.nanstd(x, axis=1, keepdims=True)
            z = (x - np.nanmean(x, axis=1, keepdims=True)) / np.where(sd > 0, sd, np.nan)
            if self.fold is None:
                signs = np.asarray(self.signs)
            else:
                signs = in_fold_signs(z, target, self.signs, self.fold, row_session_dates)[:, None]
            return z * signs

    def combine(
        self, stack: np.ndarray, target: np.ndarray, *, row_session_dates: np.ndarray | None = None
    ) -> np.ndarray:
        scores = self._signed_scores(stack, target, row_session_dates)
        if self.min_members is None:
            return scores.mean(axis=2)
        with warnings.catch_warnings(), np.errstate(invalid="ignore"):
            warnings.simplefilter("ignore", RuntimeWarning)
            present = np.isfinite(scores).sum(axis=2)
            total = np.nansum(scores, axis=2) / len(self.signs)
        return np.where(present >= self.min_members, total, np.nan)

    def member_terms(
        self, stack: np.ndarray, target: np.ndarray, *, row_session_dates: np.ndarray | None = None
    ) -> np.ndarray:
        """Each member's additive term of the forecast [n, m, K]: sign_k z_k / K, so that where the
        forecast is finite its sum over members is the forecast (to rounding). NaN where the cell
        is not scored; an absent member of a scored cell contributes 0 (its 1/K share is not
        redistributed, as in combine)."""
        scores = self._signed_scores(stack, target, row_session_dates) / len(self.signs)
        if self.min_members is None:
            return scores
        present = np.isfinite(scores).sum(axis=2, keepdims=True)
        return np.where(present >= self.min_members, np.nan_to_num(scores), np.nan)


@dataclasses.dataclass(frozen=True)
class RidgeSpec:
    """Walk-forward ridge settings, all counted in panel rows (the runner converts sessions)."""

    window_rows: int
    refit_rows: int
    penalty: float
    embargo: int
    min_obs: int
    # Plan 187-09: predict on cells with at least this many members present (see
    # walk_forward_ridge); None keeps the complete-case prediction.
    min_members: int | None = None
    # Plan 187-09: refits on the exchange-session grid through this date (anchored_refit_positions);
    # None keeps row-0 anchoring.
    refit_anchor: datetime.date | None = None

    @property
    def training_rows(self) -> int:
        return self.window_rows + self.embargo

    def combine(
        self, stack: np.ndarray, target: np.ndarray, *, row_session_dates: np.ndarray | None = None
    ) -> np.ndarray:
        return walk_forward_ridge(stack, target, self, row_session_dates=row_session_dates)

    def member_terms(
        self, stack: np.ndarray, target: np.ndarray, *, row_session_dates: np.ndarray | None = None
    ) -> np.ndarray:
        """Each member's additive term z_k b_k of the forecast [n, m, K] under the fold in force;
        its sum over members is the forecast where it is finite. NaN where the cell is not
        predicted; an absent member of a predicted cell contributes 0."""
        terms = np.full(stack.shape, np.nan)
        combined = walk_forward_ridge(
            stack, target, self, row_session_dates=row_session_dates, terms_out=terms
        )
        terms[~np.isfinite(combined)] = np.nan  # an unpredicted cell has no terms
        return terms

    def terms_and_fold_weights(
        self, stack: np.ndarray, target: np.ndarray, *, row_session_dates: np.ndarray | None = None
    ) -> tuple[np.ndarray, np.ndarray]:
        """member_terms and fold_weights from one walk-forward pass (the ridge refits once)."""
        terms = np.full(stack.shape, np.nan)
        weights: list = []
        combined = walk_forward_ridge(
            stack,
            target,
            self,
            row_session_dates=row_session_dates,
            terms_out=terms,
            fold_weights_out=weights,
        )
        terms[~np.isfinite(combined)] = np.nan
        return terms, np.array(weights).reshape(len(weights), stack.shape[2])

    def fold_weights(
        self, stack: np.ndarray, target: np.ndarray, *, row_session_dates: np.ndarray | None = None
    ) -> np.ndarray:
        """The complete-member standardized weights b of every refit [F, K]."""
        weights: list = []
        walk_forward_ridge(
            stack, target, self, row_session_dates=row_session_dates, fold_weights_out=weights
        )
        return np.array(weights).reshape(len(weights), stack.shape[2])

    def __post_init__(self) -> None:
        if self.window_rows < 1 or self.refit_rows < 1 or self.embargo < 1:
            raise ValueError(f"window_rows, refit_rows and embargo must be positive: {self}")
        if not (np.isfinite(self.penalty) and self.penalty >= 0):
            raise ValueError(f"penalty must be finite and non-negative: {self}")
        if self.min_members is not None and self.min_members < 1:
            raise ValueError(f"min_members must be at least 1: {self}")


def refit_positions(n: int, spec: RidgeSpec) -> np.ndarray:
    """Refit rows: the first whose training window holds window_rows rows, then every refit_rows."""
    return np.arange(spec.window_rows + spec.embargo - 1, n, spec.refit_rows)


def exchange_sessions(first: np.datetime64, last: np.datetime64) -> np.ndarray:
    """datetime64[D], the exchange's sessions from first through last inclusive, sorted."""
    days = np.arange(first, last + np.timedelta64(1, "D"), dtype="datetime64[D]")
    calendar = get_market_calendar()
    return days[[calendar.is_trading_day(_EXCHANGE, d) for d in days.tolist()]]


def anchored_refit_positions(row_session_dates: np.ndarray, spec: RidgeSpec) -> np.ndarray:
    """Refit rows on the calendar grid through spec.refit_anchor (see the module docstring):
    the first row of the first panel session on or after each grid session, from the first
    whose training window is full. `row_session_dates` is each row's session date, sorted,
    with the same number of rows in every session."""
    if spec.refit_anchor is None:
        raise ValueError("anchored_refit_positions needs spec.refit_anchor")
    dates = np.asarray(row_session_dates, dtype="datetime64[D]")
    if dates.size == 0:
        return np.zeros(0, dtype=np.int64)
    if np.any(dates[1:] < dates[:-1]):
        raise ValueError("row_session_dates must be sorted")
    sessions, starts, counts = np.unique(dates, return_index=True, return_counts=True)
    if np.any(counts != counts[0]):
        raise ValueError("row_session_dates must give every session the same number of rows")
    if spec.refit_rows % counts[0]:
        raise ValueError(
            f"refit_rows {spec.refit_rows} is not a whole number of sessions of {counts[0]} rows"
        )
    step = spec.refit_rows // int(counts[0])
    anchor = np.datetime64(spec.refit_anchor, "D")
    calendar = exchange_sessions(min(anchor, sessions[0]), max(anchor, sessions[-1]))
    origin = int(np.searchsorted(calendar, anchor))  # the first session on or after the anchor
    grid = calendar[origin % step :: step]
    first = np.unique(np.searchsorted(sessions, grid))  # first panel session on or after
    rows = starts[first[first < len(sessions)]]
    return rows[rows >= spec.window_rows + spec.embargo - 1].astype(np.int64)


@dataclasses.dataclass(frozen=True)
class SignFold:
    """In-fold sign settings in panel rows (the runner converts sessions): the trailing window,
    the refit cadence, the embargo (fwd_span(horizon)) and the optional calendar anchor, read
    by the same refit grid as the ridge's."""

    window_rows: int
    refit_rows: int
    embargo: int
    refit_anchor: datetime.date | None = None

    def __post_init__(self) -> None:
        if self.window_rows < 1 or self.refit_rows < 1 or self.embargo < 1:
            raise ValueError(f"SignFold rows must be positive: {self}")


def _refit_grid(n: int, spec: RidgeSpec | SignFold, row_session_dates: np.ndarray | None):
    """The refit rows of a fitted part: row-0 anchored, or on the calendar grid with
    spec.refit_anchor (which needs each row's session date)."""
    if spec.refit_anchor is None:
        return refit_positions(n, spec)  # type: ignore[arg-type]  # same three fields
    if row_session_dates is None:
        raise ValueError("an anchored refit (refit_anchor) needs row_session_dates")
    if len(row_session_dates) != n:
        raise ValueError(f"{len(row_session_dates)} row_session_dates for {n} rows")
    return anchored_refit_positions(row_session_dates, spec)  # type: ignore[arg-type]


def _row_correlation(z: np.ndarray, y: np.ndarray) -> np.ndarray:
    """[n] per-row Pearson correlation of z [n, m] and y [n, m] over the names where both are
    finite; NaN with fewer than two such names or no spread in either."""
    both = np.isfinite(z) & np.isfinite(y)
    count = both.sum(axis=1)
    zc = np.where(both, z, 0.0)
    yc = np.where(both, y, 0.0)
    with np.errstate(invalid="ignore", divide="ignore"):
        zm = zc.sum(axis=1) / count
        ym = yc.sum(axis=1) / count
        dz = np.where(both, z - zm[:, None], 0.0)
        dy = np.where(both, y - ym[:, None], 0.0)
        szz = (dz * dz).sum(axis=1)
        syy = (dy * dy).sum(axis=1)
        corr = (dz * dy).sum(axis=1) / np.sqrt(szz * syy)
    return np.where((count >= 2) & (szz > 0) & (syy > 0), corr, np.nan)


def in_fold_signs(
    z: np.ndarray,
    target: np.ndarray,
    signs: tuple[float | None, ...],
    fold: SignFold,
    row_session_dates: np.ndarray | None,
) -> np.ndarray:
    """[n, K] sign per row and member: fixed signs as given, in-fold (None) ones the sign of
    the fold IC (see the module docstring) on rows p up to the next refit, NaN before the
    first refit or where the fold IC is zero or undefined. z is the members' z-scores [n, m, K]."""
    n = z.shape[0]
    out = np.tile(np.asarray([np.nan if s is None else s for s in signs]), (n, 1))
    positions = _refit_grid(n, fold, row_session_dates)
    if positions.size == 0:  # no full window: every in-fold member is absent
        return out
    ends = np.append(positions[1:], n)
    for k in (k for k, s in enumerate(signs) if s is None):
        ic = _row_correlation(z[:, :, k], target)
        for p, q in zip(positions, ends, strict=True):
            hi = p - fold.embargo + 1
            window = ic[max(0, hi - fold.window_rows) : hi]
            window = window[np.isfinite(window)]
            # Summed over the window itself, not differenced prefix sums, so a zero fold IC is
            # exactly zero (absent) and the sign never depends on history before the window.
            mean = window.mean() if window.size else np.nan
            out[p:q, k] = np.sign(mean) if np.isfinite(mean) and mean != 0 else np.nan
    return out


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


def walk_forward_ridge(
    stack: np.ndarray,
    target: np.ndarray,
    spec: RidgeSpec,
    *,
    row_session_dates: np.ndarray | None = None,
    terms_out: np.ndarray | None = None,
    fold_weights_out: list | None = None,
) -> np.ndarray:
    """Combined alpha [n, m] float64 from a member stack [n, m, K] and its target [n, m].
    `row_session_dates` [n] (each row's session date) is required with spec.refit_anchor and
    not read without it. `terms_out` [n, m, K] (NaN-filled by the caller) receives each member's
    additive term z_k b_k of every predicted cell, and `fold_weights_out` the fitted standardized
    weight vector b of each refit (plan 187-14); neither changes the returned alpha."""
    if stack.ndim != 3 or target.shape != stack.shape[:2]:
        raise ValueError(f"stack {stack.shape} and target {target.shape} do not align")
    n, m, k = stack.shape
    combined = np.full((n, m), np.nan)
    positions = _refit_grid(n, spec, row_session_dates)
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
        if terms_out is not None:
            terms_out[rows] = (stack[rows].astype(np.float64) - mu) / sd * b
        if fold_weights_out is not None:
            fold_weights_out.append(b.copy())
        if spec.min_members is not None:
            corr = cov / np.outer(sd, sd)
            _subset_forecast(combined, stack, p, q, mu, sd, corr, rhs, spec, terms_out)
    return combined


def _subset_forecast(
    combined: np.ndarray,
    stack: np.ndarray,
    p: int,
    q: int,
    mu: np.ndarray,
    sd: np.ndarray,
    corr: np.ndarray,
    rhs: np.ndarray,
    spec: RidgeSpec,
    terms_out: np.ndarray | None = None,
) -> None:
    """Fill rows p..q-1's incomplete cells with at least min_members present: one small ridge
    solve per missing-member pattern on the fold's standardized moments (see the module
    docstring). Complete cells are left as predicted."""
    if stack.shape[2] < spec.min_members:
        raise ValueError(f"min_members {spec.min_members} exceeds the {stack.shape[2]} members")
    z = (stack[p:q].astype(np.float64) - mu) / sd
    present = np.isfinite(z)
    count = present.sum(axis=2)
    partial = (count >= spec.min_members) & (count < z.shape[2])
    if not partial.any():
        return
    patterns, inverse = np.unique(present[partial], axis=0, return_inverse=True)
    cells = np.argwhere(partial)
    block = combined[p:q]
    for j, pattern in enumerate(patterns):
        k = np.flatnonzero(pattern)
        try:
            b = np.linalg.solve(corr[np.ix_(k, k)] + spec.penalty * np.eye(len(k)), rhs[k])
        except np.linalg.LinAlgError:
            continue
        r, i = cells[inverse.ravel() == j].T
        block[r, i] = z[r, i][:, k] @ b
        if terms_out is not None:
            terms_out[p + r, i] = 0.0  # absent members contribute nothing
            terms_out[p + r[:, None], i[:, None], k[None, :]] = z[r, i][:, k] * b
