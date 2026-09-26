"""Family 1: cross-sectional intraday periodicity (docs/plans/2026-09-25-family1-intraday-
periodicity-prereg.md; Heston, Korajczyk and Sadka 2010).

A name's residual return in a half-hour slot predicts its residual return in the same slot on
following days, relative to other names. Direction +1 (continuation) for every member.

| Member | alpha before slot j of session d | window_sessions |
|---|---|---|
| P1 same_slot_lag1 | slot j residual return on d-1 | 1 |
| P2 same_slot_mean5 | mean over d-5 .. d-1 | 5 |
| P3 same_slot_mean20 | mean over d-20 .. d-1 | 20 |
| P4 same_slot_mean40 | mean over d-40 .. d-1 | 40 |

Slot j of a session covers bars 2j and 2j+1; its residual return is their sum, NaN if either
is missing. Alpha for slot j of session d sits at the last bar before the slot (row
d * bars_per_session + 2j - 1; slot 0 at the previous session's last bar, entering at the
open), built from past sessions' slot j returns only. A mean needs at least half the window's
days finite. Then the centred rank with the coverage floor. Window, floor and bars per
session come from the spec.
"""

from __future__ import annotations

import dataclasses
import math

import numpy as np

from src.intelligence.research.families.common import centred_rank
from src.intelligence.research.synthetic import factor_basis, loading_scale_for_pr

# Bars per half-hour slot on the 15m grid: the member's definition, not a tunable (APR-exempt).
SLOT_BARS = 2


def slot_returns(resid_bar_returns: np.ndarray, *, bars_per_session: int) -> np.ndarray:
    """[S, J, m] half-hour slot residual returns, J = bars_per_session // 2."""
    if bars_per_session % SLOT_BARS:
        raise ValueError(f"bars_per_session must be even, got {bars_per_session}")
    n, m = resid_bar_returns.shape
    bars = resid_bar_returns.reshape(
        n // bars_per_session, bars_per_session // SLOT_BARS, SLOT_BARS, m
    )
    return bars.sum(axis=2)  # NaN propagates: a slot with a missing bar is NaN


def place_slot_alpha(slot_alpha: np.ndarray, *, bars_per_session: int, n_rows: int) -> np.ndarray:
    """[n, m] with slot j of session d at row d * bars_per_session + 2j - 1 and NaN elsewhere.
    slot_alpha is [S + 1, J, m]; index S is the session after the panel, whose slot 0 lands on
    the panel's last row. Rows outside [0, n_rows) are dropped."""
    s1, j_n, m = slot_alpha.shape
    rows = (
        np.arange(s1)[:, None] * bars_per_session + SLOT_BARS * np.arange(j_n)[None, :] - 1
    ).ravel()
    flat = slot_alpha.reshape(s1 * j_n, m)
    keep = (rows >= 0) & (rows < n_rows)
    out = np.full((n_rows, m), np.nan)
    out[rows[keep]] = flat[keep]
    return out


def same_slot_mean(
    resid_bar_returns: np.ndarray,
    *,
    bars_per_session: int,
    coverage_floor: int,
    window_sessions: int,
) -> np.ndarray:
    """P1-P4: mean of each name's slot j residual returns over the previous window_sessions
    sessions (at least half of them finite), placed before slot j, centred-ranked per row."""
    slots = slot_returns(resid_bar_returns, bars_per_session=bars_per_session)  # [S, J, m]
    finite = np.isfinite(slots)
    # Prefix sums over sessions: index k holds the total over sessions < k, so the window for
    # session d (sessions d - w .. d - 1) is prefix[d] - prefix[max(d - w, 0)], d = 0 .. S.
    zeros = np.zeros((1, *slots.shape[1:]))
    total = np.concatenate([zeros, np.cumsum(np.where(finite, slots, 0.0), axis=0)])
    count = np.concatenate([zeros, np.cumsum(finite, axis=0)])
    lo = np.maximum(np.arange(len(total)) - window_sessions, 0)
    win_total = total - total[lo]
    win_count = count - count[lo]
    need = (window_sessions + 1) // 2
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.where(win_count >= need, win_total / win_count, np.nan)
    alpha = place_slot_alpha(mean, bars_per_session=bars_per_session, n_rows=len(resid_bar_returns))
    # The signal bar must itself have a residual: a bar with no close gives no position.
    alpha[~np.isfinite(resid_bar_returns)] = np.nan
    return centred_rank(alpha, coverage_floor=coverage_floor)


# ---------------------------------------------------------------------------------------------
# Synthetic plant for the power check (D-19, D-20; moved from synthetic.py unchanged, so its
# random draws and outputs are bit-identical to what book_v1's power check used).
#
# u[d, j, i] = e[d, j, i] + c * mean_{l=1..L} u[d - l, j, i]: flat persistence of a name's own
# slot-j residual over the last L sessions, cross-sectionally demeaned per slot (HKS shape). It
# lives at the slot level, so members built from bars see exactly what was planted. Each slot
# splits into its two bars with an independent split whose bars sum to the slot return.
# Idiosyncratic slot variance is 1: ranks, R1 weights and Sharpe ratios are scale free.
# ---------------------------------------------------------------------------------------------

_BAR_SPLIT_SD = 0.5  # sd of the within-slot split, in units of the slot's idiosyncratic sd


@dataclasses.dataclass(frozen=True)
class SameSlotPlant:
    bars_per_session: int
    participation_ratio: float
    n_common_factors: int
    plant_lags_sessions: int

    def _slot_residuals(self, n_sessions: int, n_names: int, plant_coef: float, rng) -> np.ndarray:
        """u [S, J, m]: demeaned slot residuals with the planted same-slot persistence."""
        j_n, m, k, lags = (
            self.bars_per_session // SLOT_BARS,
            n_names,
            self.n_common_factors,
            self.plant_lags_sessions,
        )
        scale = loading_scale_for_pr(m, k, self.participation_ratio)
        q = factor_basis(rng, m, k)
        u = np.empty((n_sessions, j_n, m))
        window = np.zeros((lags, j_n, m))  # ring buffer of the last `lags` sessions
        running = np.zeros((j_n, m))
        for d in range(n_sessions):
            e = (
                rng.standard_normal((j_n, m))
                + math.sqrt(scale) * rng.standard_normal((j_n, k)) @ q.T
            )
            e -= e.mean(axis=1, keepdims=True)
            u[d] = e + plant_coef * running / lags
            slot = d % lags
            running += u[d] - window[slot]
            window[slot] = u[d]
        return u

    def generate(
        self,
        finite_mask: np.ndarray,
        *,
        plant_coef: float,
        seed: int,
        target_mask: np.ndarray | None = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        """(resid_bar [n, m], target [n, m]): bar residuals whose slot pairs sum to u, and the
        target u[d, j] at slot j's placement row (the bar before the slot), NaN elsewhere and
        wherever a bar of the slot is masked. `target_mask`, when given, also blanks the target
        wherever the real residual target is missing, so replicates see the real test's pattern."""
        bps = self.bars_per_session
        n, m = finite_mask.shape
        n_sessions, j_n = n // bps, bps // SLOT_BARS
        rng = np.random.default_rng(seed)
        u = self._slot_residuals(n_sessions, m, plant_coef, rng)
        first = u / SLOT_BARS + _BAR_SPLIT_SD * rng.standard_normal(u.shape)
        bars = np.stack([first, u - first], axis=2)  # [S, J, 2, m]
        resid_bar = bars.reshape(n, m)
        resid_bar[~finite_mask] = np.nan

        slot_ok = finite_mask.reshape(n_sessions, j_n, SLOT_BARS, m).all(axis=2)
        rows = (
            np.arange(n_sessions)[:, None] * bps + SLOT_BARS * np.arange(j_n)[None, :] - 1
        ).ravel()
        values = np.where(slot_ok, u, np.nan).reshape(-1, m)
        keep = rows >= 0
        target = np.full((n, m), np.nan)
        target[rows[keep]] = values[keep]
        if target_mask is not None:
            target[~target_mask] = np.nan
        return resid_bar, target


def validate_plant(power, bars_per_session: int) -> None:
    """The plant's requirements that need no data (the runner checks them before the ledger):
    whole half-hour slots."""
    if bars_per_session % SLOT_BARS:
        raise ValueError(
            f"the same-slot plant needs whole {SLOT_BARS}-bar slots, got {bars_per_session}"
        )


def make_plant(power, _residuals, bars_per_session: int) -> SameSlotPlant:
    """The family's power plant from a book's pinned power settings. The real residuals are
    unused: this plant needs only their masks, which the power check passes separately."""
    return SameSlotPlant(
        bars_per_session=bars_per_session,
        participation_ratio=power.participation_ratio,
        n_common_factors=power.n_common_factors,
        plant_lags_sessions=power.plant_lags_sessions,
    )
