"""The lag IC term structure (glossary "IC term structure", design D2, phase 184 B4).

Per lag k = 1 .. K, IC_k is the mean over rows t of the cross-sectional Pearson correlation of
the per-row ranks of alpha[t] (average ranks over its own finite cells) with the per-row ranks
of target[t + k - 1] (average ranks over its own finite cells), taken over the names finite in
both. A row with fewer than `coverage_floor` such names contributes nothing. The target is the
one-row residual return, so lag 1 pairs alpha[t] with the return its row trades and lag k with
the return k - 1 rows later. In-session mode drops every pair whose two rows lie in different
sessions. Ranks are computed once per row per array, which is what makes K lags times S shifts
cheap; re-ranking over each pair mask would be a different, unvalidated statistic.

The joint band is the BAND_LEVEL quantile over the run's own shifts s (whole sessions, from
research.evaluate.session_shifts; the caller passes them in) of max_k |IC_k| with alpha
circularly shifted by s. The curve is read whole against that one band, so looking across K
lags costs no extra multiplicity.

This is a different object from `measure.term_structure`, which computes the proposer's IC at
cumulative horizons (returns summed over 1 .. h rows), not the IC at each lag of a one-row
return. It is a record: nothing in selection or promotion reads it.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Sequence

import numpy as np
from scipy.stats import rankdata

from src.intelligence.statistics.panel_null import shift_panel

# Definitions, not tunables (APR-exempt, RESEARCH A2): the daily curve's reach in sessions and
# the joint band's level.
K_DAILY = 60
BAND_LEVEL = 0.95


@dataclasses.dataclass(frozen=True)
class LagTermStructure:
    lags: np.ndarray  # [K] 1 .. k_max
    ic: np.ndarray  # [K] IC_k, NaN where no row qualifies
    band: float  # BAND_LEVEL quantile over shifts of max_k |IC_k|; NaN without shifts
    band_level: float
    n_shifts: int  # shifts whose curve had a finite IC (the band's sample size)
    k_max: int

    def as_record(self) -> dict:
        def num(value: float) -> float | None:
            value = float(value)
            return value if math.isfinite(value) else None

        return {
            "lags": [int(k) for k in self.lags],
            "ic": [num(v) for v in self.ic],
            "band": num(self.band),
            "band_level": float(self.band_level),
            "n_shifts": int(self.n_shifts),
            "k_max": int(self.k_max),
        }


def _row_ranks(x: np.ndarray) -> np.ndarray:
    """[n, m] average ranks per row over the row's finite cells, NaN elsewhere."""
    x = np.where(np.isfinite(x), x, np.nan)
    return rankdata(x, axis=1, nan_policy="omit")


def _check(
    alpha: np.ndarray, target: np.ndarray, coverage_floor: int, session_rows: int | None
) -> None:
    if alpha.ndim != 2 or alpha.shape != target.shape:
        raise ValueError(f"alpha {alpha.shape} and target {target.shape} must be equal 2-D")
    if coverage_floor < 2:
        raise ValueError(f"coverage_floor must be >= 2, got {coverage_floor}")
    if session_rows is not None and (session_rows < 1 or alpha.shape[0] % session_rows):
        raise ValueError(
            f"{alpha.shape[0]} rows is not a whole number of {session_rows}-row sessions"
        )


def _curve_from_ranks(
    ra: np.ndarray,
    rt: np.ndarray,
    lags: Sequence[int],
    coverage_floor: int,
    session_rows: int | None,
    in_session: bool,
) -> np.ndarray:
    n = ra.shape[0]
    out = np.full(len(lags), np.nan)
    session = np.arange(n) // session_rows if in_session else None
    for i, k in enumerate(lags):
        if k < 1:
            raise ValueError(f"lags start at 1, got {k}")
        span = k - 1
        if span >= n:
            continue
        a = ra[: n - span]
        b = rt[span:]
        both = np.isfinite(a) & np.isfinite(b)
        if in_session:
            both &= (session[: n - span] == session[span:])[:, None]
        cnt = both.sum(axis=1)
        keep = cnt >= coverage_floor
        if not keep.any():
            continue
        a, b, both, cnt = a[keep], b[keep], both[keep], cnt[keep]
        a0 = np.where(both, a, 0.0)
        b0 = np.where(both, b, 0.0)
        a_dm = np.where(both, a0 - (a0.sum(axis=1) / cnt)[:, None], 0.0)
        b_dm = np.where(both, b0 - (b0.sum(axis=1) / cnt)[:, None], 0.0)
        cov = (a_dm * b_dm).sum(axis=1)
        den = np.sqrt((a_dm * a_dm).sum(axis=1) * (b_dm * b_dm).sum(axis=1))
        with np.errstate(invalid="ignore", divide="ignore"):
            r = np.where(den > 0, cov / den, np.nan)
        if np.isfinite(r).any():
            out[i] = float(np.nanmean(r))
    return out


def lag_ic_curve(
    alpha: np.ndarray,
    target: np.ndarray,
    lags: Sequence[int],
    *,
    coverage_floor: int,
    session_rows: int | None = None,
    in_session: bool = False,
) -> np.ndarray:
    """[len(lags)] IC_k for each lag k (definition in the module docstring)."""
    _check(alpha, target, coverage_floor, session_rows)
    if in_session and session_rows is None:
        raise ValueError("in_session needs session_rows")
    return _curve_from_ranks(
        _row_ranks(alpha), _row_ranks(target), lags, coverage_floor, session_rows, in_session
    )


def lag_term_structure(
    alpha: np.ndarray,
    target: np.ndarray,
    *,
    shifts: np.ndarray,
    coverage_floor: int,
    session_rows: int = 1,
    in_session: bool = False,
    k_max: int | None = None,
) -> LagTermStructure:
    """The curve at lags 1 .. k_max with its joint band over `shifts` (rows, whole sessions).
    k_max defaults to K_DAILY on a daily clock and to session_rows - 1 in session; an intraday
    clock requires in_session."""
    _check(alpha, target, coverage_floor, session_rows)
    if session_rows > 1 and not in_session:
        raise ValueError("an intraday clock (session_rows > 1) requires in_session=True")
    if k_max is None:
        k_max = K_DAILY if session_rows == 1 else session_rows - 1
    if k_max < 1:
        raise ValueError(f"k_max must be >= 1, got {k_max}")
    lags = np.arange(1, k_max + 1)
    ra = _row_ranks(alpha)
    rt = _row_ranks(target)
    ic = _curve_from_ranks(ra, rt, lags, coverage_floor, session_rows, in_session)
    shifts = np.asarray(shifts, dtype=np.int64)
    maxima = []
    for s in shifts:
        if s % session_rows:
            raise ValueError(f"shift {int(s)} is not a whole number of {session_rows}-row sessions")
        curve = _curve_from_ranks(
            shift_panel(ra, int(s)), rt, lags, coverage_floor, session_rows, in_session
        )
        if np.isfinite(curve).any():
            maxima.append(float(np.nanmax(np.abs(curve))))
    band = float(np.quantile(maxima, BAND_LEVEL)) if maxima else float("nan")
    return LagTermStructure(
        lags=lags, ic=ic, band=band, band_level=BAND_LEVEL, n_shifts=len(maxima), k_max=k_max
    )
