"""Romano-Wolf StepM selection over the selection universe (unified design 7.3.2, E18).

H0_k: series k's mean is at or below zero; the selection set is every k rejected at
family-wise error `fwer`. Every series is resampled with ONE stationary-bootstrap index draw over
the common session calendar, so their dependence is kept: ten tweaks of one book cost about one
trial, ten unrelated books about ten.

Statistic: t_k = mean_k / se_k on series k's own finite sessions, se_k its Newey-West HAC
standard error (hac.hac_mean_test, the E17 decision statistic), so differing spans, warmups and
universes do not bias the comparison. Bootstrap (default studentize="draw"): t*_k = (mean*_k -
mean_k) / se*_k, each draw centred on the sample mean and scaled by its own HAC se over the
finite sessions it lands on (Romano-Wolf's studentized form). studentize="sample" scales every
draw by the sample se instead (the SPA shortcut): through the E17 H0 battery it oversized the
slot_effects cell (74 family-wise rejections in 1,000 against a 67 bound; per-draw: 52), so it
is kept only as a documented comparison (187-05-BATTERY.md). Missing sessions are excluded,
never filled. Step-down adjusted p-values are monotone in the observed t ordering.

Pure: arrays in, result out. Parameters come from the caller (APR keys alpha.selection.stepm.*).
"""

from __future__ import annotations

import dataclasses

import numpy as np

from src.intelligence.statistics.bootstrap import stationary_bootstrap_indices
from src.intelligence.statistics.hac import hac_mean_test


@dataclasses.dataclass(frozen=True)
class StepMResult:
    t: np.ndarray  # [K] observed studentized statistic
    adjusted_p: np.ndarray  # [K] step-down family-wise adjusted p-values
    selected: np.ndarray  # [K] bool: adjusted_p <= fwer
    fwer: float
    reps: int
    block_mean: float


def stepm(
    series: np.ndarray,
    *,
    block_mean: float,
    max_horizon_sessions: int,
    reps: int,
    fwer: float,
    seed: int,
    studentize: str = "draw",
) -> StepMResult:
    """StepM over `series` [S sessions, K attempts] on one calendar (NaN where an attempt has
    no tested session). `block_mean` must exceed the longest holding horizon in the universe."""
    x = np.asarray(series, dtype=np.float64)
    if x.ndim != 2 or x.shape[1] == 0:
        raise ValueError(
            f"series must be [sessions, attempts] with at least one attempt: {x.shape}"
        )
    if not block_mean > max_horizon_sessions:
        raise ValueError(
            f"block_mean {block_mean} must exceed the longest holding horizon "
            f"{max_horizon_sessions} sessions (design 7.3.2)"
        )
    if not 0 < fwer < 1 or reps < 1:
        raise ValueError(f"need 0 < fwer < 1 and reps >= 1, got {fwer}, {reps}")
    finite = np.isfinite(x)
    tests = [hac_mean_test(x[:, k]) for k in range(x.shape[1])]
    mean = np.array([h.mean for h in tests])
    se = np.array([h.se for h in tests])
    t_obs = mean / se

    values = np.where(finite, x, 0.0)
    idx = stationary_bootstrap_indices(x.shape[0], block_mean, reps, np.random.default_rng(seed))
    if studentize not in ("draw", "sample"):
        raise ValueError(f"studentize must be 'draw' or 'sample', got {studentize!r}")
    t_star = np.empty((reps, x.shape[1]))
    if studentize == "draw":
        for b in range(reps):
            t_star[b] = [_draw_t(x[idx[b], k], mean[k]) for k in range(x.shape[1])]
        adjusted = _step_down_p(t_obs, t_star)
        return StepMResult(
            t=t_obs,
            adjusted_p=adjusted,
            selected=adjusted <= fwer,
            fwer=fwer,
            reps=reps,
            block_mean=block_mean,
        )
    for b in range(reps):
        count = finite[idx[b]].sum(axis=0)
        with np.errstate(invalid="ignore", divide="ignore"):
            boot_mean = values[idx[b]].sum(axis=0) / count
        # A draw that lands on no session of an attempt cannot show it is null: +inf counts the
        # draw as exceeding, which can only raise a p-value (see _draw_t).
        t_star[b] = np.where(count > 0, (boot_mean - mean) / se, np.inf)

    adjusted = _step_down_p(t_obs, t_star)
    return StepMResult(
        t=t_obs,
        adjusted_p=adjusted,
        selected=adjusted <= fwer,
        fwer=fwer,
        reps=reps,
        block_mean=block_mean,
    )


def _draw_t(column: np.ndarray, sample_mean: float) -> float:
    """One draw's centred t with the draw's own HAC se; +inf when the draw lands on fewer than
    two of the attempt's sessions or its long-run variance is not positive. Such a draw says
    nothing about the attempt; -inf would drop it from the max and lower every p-value it
    touches (anti-conservative for short spans), +inf counts it as an exceedance, so the error
    is conservative and the selection never gains from a short span."""
    finite = column[np.isfinite(column)]
    if len(finite) < 2:
        return np.inf
    try:
        h = hac_mean_test(finite)
    except ValueError:
        return np.inf
    return (h.mean - sample_mean) / h.se


def _step_down_p(t_obs: np.ndarray, t_star: np.ndarray) -> np.ndarray:
    """Romano-Wolf adjusted p-values: in descending order of t, the share of draws whose max
    over the still-active attempts reaches the attempt's t, made monotone. The share counts the
    observed statistic as one more draw, (k + 1) / (reps + 1), so a finite bootstrap never
    rejects more often than its nominal level."""
    order = np.argsort(-t_obs, kind="stable")
    # Max over attempts ranked at or below position j (the active set when j is tested).
    tail_max = np.maximum.accumulate(t_star[:, order[::-1]], axis=1)[:, ::-1]
    hits = (tail_max >= t_obs[order][None, :]).sum(axis=0)
    raw = (hits + 1) / (t_star.shape[0] + 1)
    adjusted = np.empty_like(raw)
    adjusted[order] = np.maximum.accumulate(raw)
    return adjusted
