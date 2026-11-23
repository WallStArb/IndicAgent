"""Volume-shock kernels (docs/plans/2026-11-15-family10-volume-shock-prereg-draft.md, ledger E24;
Gervais, Kaniel and Mingelgrin 2001).

Pure functions over [sessions, names] arrays; no member wrapper, no `NULL_BATTERY`, no spec. The
run path reads the share volume through a `panel_source` member (`member_sources`, todo 653) and
`member_sources.orthogonalize_members` applies `residualize_rows` and `trailing_sum` below, so the
member contract still hands one array; the spec, the battery and the registration are todo 663.

V1 (`short=1`): for row d, the percentile rank of v[d] among v[d-49..d], minus 0.5, then the
cross-sectional OLS residual of that value on e[d] and abs(e[d]) with an intercept.
V2 (`short=5`): the same with m[d] = mean(v[d-4..d]) ranked among m[s], s in d-45..d (46 values),
residualized on the 5-session sum of e and its absolute value.

Percentile rank: average 0-based rank over the finite window values divided by (n - 1), so it
lies in [0, 1]; ties take the average rank. The statistic is scale free in v, so a volume rescale
(a split) or a constant basis factor per name cannot move it.

No fill: volume <= 0 or non-finite is missing (the tradeable view drops zero-volume bars), a
window reaching before the first row is not a window (NaN), a window with fewer than
`min_finite` positive volumes is NaN, a short mean needs all `short` sessions, and a row with
fewer than `min_names` finite names has no cross-section to fit (NaN). The window, short span,
`min_finite`, `min_finite_short` and `min_names` are spec fields, never defaults here.
"""

from __future__ import annotations

import numpy as np


def _positive(volume: np.ndarray) -> np.ndarray:
    v = np.asarray(volume, dtype=float)
    if v.ndim != 2:
        raise ValueError(f"volume must be [sessions, names], got shape {v.shape}")
    return np.where(np.isfinite(v) & (v > 0), v, np.nan)


def trailing_sum(x: np.ndarray, length: int) -> np.ndarray:
    """[S, m] sum of x over the `length` rows ending at each row; NaN unless all are finite."""
    if length < 1:
        raise ValueError(f"length must be >= 1, got {length}")
    out = np.zeros(x.shape)
    for lag in range(min(length, len(x))):
        out[lag:] += x[: len(x) - lag]
    out[: length - 1] = np.nan
    return out  # NaN anywhere in the span propagates through the sum


def rolling_centred_rank(x: np.ndarray, *, window: int, min_finite: int) -> np.ndarray:
    """[S, m] percentile rank of x[d] among the finite values of x[d-window+1..d], minus 0.5.
    NaN where x[d] is not finite, the window starts before row 0, or it holds fewer than
    `min_finite` finite values. The window is folded in one lag at a time."""
    if not 2 <= min_finite <= window:
        raise ValueError(f"need 2 <= min_finite <= window, got {min_finite} and {window}")
    less = np.zeros(x.shape)
    equal = np.ones(x.shape)  # the value itself
    count = np.isfinite(x).astype(float)
    with np.errstate(invalid="ignore"):
        for lag in range(1, min(window, len(x))):
            past, cur = x[: len(x) - lag], x[lag:]
            fin = np.isfinite(past)
            less[lag:] += fin & (past < cur)
            equal[lag:] += fin & (past == cur)
            count[lag:] += fin
    with np.errstate(invalid="ignore", divide="ignore"):
        rank = (less + (equal - 1.0) / 2.0) / (count - 1.0) - 0.5
    ok = np.isfinite(x) & (count >= min_finite)
    ok[: window - 1] = False
    return np.where(ok, rank, np.nan)


def volume_rank(
    volume: np.ndarray, *, window: int, short: int, min_finite: int, min_finite_short: int
) -> np.ndarray:
    """The rank value before residualization (V1 `short=1`, V2 `short=5`).

    A row is NaN unless at least `min_finite` of the `window` sessions ending at it have positive
    volume (the prereg 40-of-50 rule), the short mean is defined, and at least
    `min_finite_short` of the `window - short + 1` short means ending at it are finite (the
    rank runs over those means; for V1 they are the volumes themselves)."""
    if not 1 <= short < window:
        raise ValueError(f"need 1 <= short < window, got {short} and {window}")
    v = _positive(volume)
    base = v if short == 1 else trailing_sum(v, short) / short
    rank = rolling_centred_rank(base, window=window - short + 1, min_finite=min_finite_short)
    seen = rolling_centred_rank(v, window=window, min_finite=min_finite)
    return np.where(np.isfinite(seen), rank, np.nan)


def residualize_rows(y: np.ndarray, e: np.ndarray, *, min_names: int) -> np.ndarray:
    """[S, m] per-row OLS residual of y on (1, e, |e|) over the names with both finite. NaN
    for a name missing either, and for the whole row when fewer than `min_names` names are
    finite or the design is rank deficient."""
    if y.shape != e.shape:
        raise ValueError(f"y and e must share a shape, got {y.shape} and {e.shape}")
    out = np.full(y.shape, np.nan)
    both = np.isfinite(y) & np.isfinite(e)
    for row in np.flatnonzero(both.sum(axis=1) >= max(min_names, 4)):
        k = both[row]
        design = np.column_stack([np.ones(k.sum()), e[row, k], np.abs(e[row, k])])
        coef, _, rank, _ = np.linalg.lstsq(design, y[row, k], rcond=None)
        if rank == 3:
            out[row, k] = y[row, k] - design @ coef
    return out


def volume_shock(
    volume: np.ndarray,
    resid: np.ndarray,
    *,
    window: int,
    short: int,
    min_finite: int,
    min_finite_short: int,
    min_names: int,
) -> np.ndarray:
    """V1 (`short=1`) or V2 (`short=5`): the volume rank value orthogonalized to the same-clock
    return (the `short`-session sum of the S1 residual returns) and its absolute value."""
    if resid.shape != np.shape(volume):
        raise ValueError(
            f"resid and volume must share a shape, got {resid.shape} and {np.shape(volume)}"
        )
    value = volume_rank(
        volume,
        window=window,
        short=short,
        min_finite=min_finite,
        min_finite_short=min_finite_short,
    )
    return residualize_rows(
        value, trailing_sum(np.asarray(resid, dtype=float), short), min_names=min_names
    )
