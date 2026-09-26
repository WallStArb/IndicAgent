"""Family 2: overnight versus intraday return decomposition (docs/plans/2026-09-25-family2-
overnight-intraday-prereg.md; Lou, Polk and Skouras 2019; Berkman et al. 2012).

Members read the session-legs panel's S1 residual returns (`legs.py`): row 0 of a session is its
overnight leg, rows 1 and 2 its intraday leg. Every member places alpha for session d on row 1
of d, formed at bar 0's close, and the target is the rest of the session.

| Member | statistic for session d | window_sessions | Sign |
|---|---|---|---|
| O1/O2 intraday_persistence | mean residual intraday return over d-w .. d-1 | 20 / 60 | +1 |
| O3/O4 overnight_to_intraday | mean residual overnight return over d-w .. d-1 | 20 / 60 | -1 |
| O5 gap_fade | residual overnight return of d | - | -1 |
| O6 gap_fade_z | O5 over the sample sd of d-w .. d-1 overnight residuals | 60 | -1 |

Signs are the members' definitions (prereg section 3), applied before the centred rank; the
book's construction direction is +1. Means and the sd need at least half the window's sessions
finite (the sd also at least 2 and a positive value). The alpha row must itself have a finite
residual.
"""

from __future__ import annotations

import dataclasses
from typing import ClassVar

import numpy as np

from src.intelligence.research.families.common import centred_rank
from src.intelligence.research.legs import LEGS, SIGNAL_LEG
from src.intelligence.research.synthetic import (
    breadth_noise,
    factor_basis,
    loading_scale_for_pr,
)


def _legs(resid: np.ndarray, bars_per_session: int) -> np.ndarray:
    if bars_per_session != LEGS:
        raise ValueError(f"family 2 members need the {LEGS}-row legs panel, got {bars_per_session}")
    n, m = resid.shape
    return resid.reshape(n // LEGS, LEGS, m)


def _prior_window(x: np.ndarray, window: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Over sessions d-window .. d-1 of x [S, m]: (count finite, sum, sum of squares), each
    [S, m], from prefix sums (index d covers sessions < d)."""
    finite = np.isfinite(x)
    zeros = np.zeros((1, x.shape[1]))
    xs = np.where(finite, x, 0.0)
    prefix = [np.concatenate([zeros, np.cumsum(a, axis=0)]) for a in (finite, xs, xs * xs)]
    lo = np.maximum(np.arange(len(x)) - window, 0)
    hi = np.arange(len(x))
    return tuple(p[hi] - p[lo] for p in prefix)


def _prior_mean(x: np.ndarray, window: int) -> np.ndarray:
    count, total, _ = _prior_window(x, window)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(count >= (window + 1) // 2, total / count, np.nan)


def _place(stat: np.ndarray, resid: np.ndarray, coverage_floor: int) -> np.ndarray:
    """stat [S, m] onto row 1 of each session, NaN where row 1's residual is missing, ranked."""
    alpha = np.full(resid.shape, np.nan)
    alpha[SIGNAL_LEG::LEGS] = stat
    alpha[~np.isfinite(resid)] = np.nan
    return centred_rank(alpha, coverage_floor=coverage_floor)


def intraday_persistence(
    resid_bar_returns: np.ndarray,
    *,
    bars_per_session: int,
    coverage_floor: int,
    window_sessions: int,
) -> np.ndarray:
    """O1/O2: +mean residual intraday return (rows 1 + 2) over the previous window sessions."""
    legs = _legs(resid_bar_returns, bars_per_session)
    intraday = legs[:, 1] + legs[:, 2]  # NaN if either leg is missing
    return _place(_prior_mean(intraday, window_sessions), resid_bar_returns, coverage_floor)


def overnight_to_intraday(
    resid_bar_returns: np.ndarray,
    *,
    bars_per_session: int,
    coverage_floor: int,
    window_sessions: int,
) -> np.ndarray:
    """O3/O4: -mean residual overnight return (row 0) over the previous window sessions."""
    legs = _legs(resid_bar_returns, bars_per_session)
    return _place(-_prior_mean(legs[:, 0], window_sessions), resid_bar_returns, coverage_floor)


def gap_fade(
    resid_bar_returns: np.ndarray, *, bars_per_session: int, coverage_floor: int
) -> np.ndarray:
    """O5: -residual overnight return of the same session (row 0 of d)."""
    legs = _legs(resid_bar_returns, bars_per_session)
    return _place(-legs[:, 0], resid_bar_returns, coverage_floor)


def gap_fade_z(
    resid_bar_returns: np.ndarray,
    *,
    bars_per_session: int,
    coverage_floor: int,
    window_sessions: int,
) -> np.ndarray:
    """O6: -(row 0 of d) over the sample sd of row 0 over the previous window sessions."""
    legs = _legs(resid_bar_returns, bars_per_session)
    gap = legs[:, 0]
    count, total, sq = _prior_window(gap, window_sessions)
    with np.errstate(invalid="ignore", divide="ignore"):
        var = (sq - total * total / count) / (count - 1)
        sd = np.sqrt(np.where(var > 0, var, np.nan))
        ok = (count >= max((window_sessions + 1) // 2, 2)) & np.isfinite(sd)
        stat = np.where(ok, -gap / sd, np.nan)
    return _place(stat, resid_bar_returns, coverage_floor)


# ---------------------------------------------------------------------------------------------
# Synthetic plant for the power check (prereg section 9, B2).
#
# Per leg, residuals with the breadth structure I + s Q Q' (synthetic.breadth_noise), scaled per
# (leg, name) by the real legs-panel residual sd, so the three legs keep their real relative
# sizes. The target is row 2 (the rest of the session) of the same session. The plant adds
# c * z[d, i] to row 2 of session d, z the per-session cross-sectional z-score of the equal-weight
# sum of three per-session z-scores built from the synthetic residuals themselves: O1's statistic
# (mean intraday residual, d-20 .. d-1), minus O3's (mean overnight residual, d-20 .. d-1), minus
# O5's (overnight residual of d). A component that is NaN for a name counts as 0. The plant is
# recursive through O1. The breadth (participation ratio) is the book spec's, measured by step
# 0's method on this universe's residual target before the check.
# ---------------------------------------------------------------------------------------------

PLANT_WINDOW_SESSIONS = 20  # prereg B2: O1 and O3 at their 20-session windows (APR-exempt)


def _xs_z(x: np.ndarray) -> np.ndarray:
    """Cross-sectional z-score of one session's values (population sd). The generator's values
    are always finite (masks apply after generation), so prereg B2's NaN-counts-as-0 rule only
    needs the zero-spread case: a constant cross-section scores 0."""
    sd = x.std()
    return (x - x.mean()) / sd if sd > 0 else np.zeros_like(x)


@dataclasses.dataclass(frozen=True, eq=False)
class LegsPlant:
    participation_ratio: float
    n_common_factors: int
    leg_sd: np.ndarray  # [3, m] real residual sd per (leg, name)
    bars_per_session: ClassVar[int] = LEGS

    def generate(
        self,
        finite_mask: np.ndarray,
        *,
        plant_coef: float,
        seed: int,
        target_mask: np.ndarray | None = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        n, m = finite_mask.shape
        if m != self.leg_sd.shape[1]:
            raise ValueError(f"mask has {m} names, the plant's scales {self.leg_sd.shape[1]}")
        n_s = n // LEGS
        rng = np.random.default_rng(seed)
        scale = loading_scale_for_pr(m, self.n_common_factors, self.participation_ratio)
        q = factor_basis(rng, m, self.n_common_factors)
        u = breadth_noise(rng, n_s * LEGS, q, scale).reshape(n_s, LEGS, m) * self.leg_sd[None]
        w = PLANT_WINDOW_SESSIONS
        need = (w + 1) // 2
        intraday_sum = np.zeros(m)
        overnight_sum = np.zeros(m)
        for d in range(n_s):
            if plant_coef and d >= need:
                lo = max(d - w, 0)
                count = d - lo
                o1 = intraday_sum / count
                o3 = overnight_sum / count
                z = _xs_z(_xs_z(o1) - _xs_z(o3) - _xs_z(u[d, 0]))
                u[d, 2] += plant_coef * z
            intraday_sum += u[d, 1] + u[d, 2]
            overnight_sum += u[d, 0]
            if d >= w:
                intraday_sum -= u[d - w, 1] + u[d - w, 2]
                overnight_sum -= u[d - w, 0]
        resid = u.reshape(n, m).copy()
        resid[~finite_mask] = np.nan
        target = np.full((n, m), np.nan)
        target[SIGNAL_LEG::LEGS] = np.where(finite_mask[2::LEGS], u[:, 2], np.nan)
        if target_mask is not None:
            target[~target_mask] = np.nan
        return resid, target


def validate_plant(power, bars_per_session: int) -> None:
    """The plant's requirements that need no data (the runner checks them before the ledger)."""
    if bars_per_session != LEGS:
        raise ValueError(
            f"family 2's plant needs the {LEGS}-row legs panel, got {bars_per_session}"
        )
    if power.plant_lags_sessions != PLANT_WINDOW_SESSIONS:
        raise ValueError(
            f"prereg B2 pins the plant window at {PLANT_WINDOW_SESSIONS} sessions; the book spec "
            f"says {power.plant_lags_sessions}"
        )


def make_plant(power, residuals, bars_per_session: int) -> LegsPlant:
    """The family's power plant: breadth and factor count from the book's power settings, leg
    scales from the real legs-panel residuals (a name with no finite residual in a leg takes
    that leg's median scale)."""
    validate_plant(power, bars_per_session)
    legs = residuals.bar.reshape(-1, LEGS, residuals.bar.shape[1])
    with np.errstate(invalid="ignore"):
        sd = np.nanstd(legs, axis=0)  # [3, m]
    fill = np.nanmedian(np.where(sd > 0, sd, np.nan), axis=1, keepdims=True)
    sd = np.where(np.isfinite(sd) & (sd > 0), sd, fill)
    return LegsPlant(
        participation_ratio=power.participation_ratio,
        n_common_factors=power.n_common_factors,
        leg_sd=sd,
    )
