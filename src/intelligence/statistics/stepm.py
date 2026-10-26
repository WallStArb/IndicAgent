"""Romano-Wolf StepM selection over the selection universe (unified design 7.3.2, E18).

H0_k: series k's mean is at or below zero; the selection set is every k rejected at
family-wise error `fwer`. Every series is resampled with ONE stationary-bootstrap index draw over
the common session calendar, so their dependence is kept: ten tweaks of one book cost about one
trial, ten unrelated books about ten.

Statistic: t_k = mean_k / se_k on series k's own finite sessions, se_k its Newey-West HAC
standard error (hac.hac_mean_test, the E17 decision statistic), so differing spans, warmups and
universes do not bias the comparison. Bootstrap: t*_k = (mean*_k - mean_k) / se_k, the resampled
mean over the finite sessions the draw lands on, centred on the sample mean and scaled by the
sample se (the studentization Hansen's SPA uses; re-estimating a HAC se per draw costs reps x K
long-run variances for little change in the max-t quantiles). Missing sessions are excluded,
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
    t_star = np.empty((reps, x.shape[1]))
    for b in range(reps):
        count = finite[idx[b]].sum(axis=0)
        with np.errstate(invalid="ignore", divide="ignore"):
            boot_mean = values[idx[b]].sum(axis=0) / count
        # A draw that lands on no session of an attempt carries no evidence about it.
        t_star[b] = np.where(count > 0, (boot_mean - mean) / se, -np.inf)

    adjusted = _step_down_p(t_obs, t_star)
    return StepMResult(
        t=t_obs,
        adjusted_p=adjusted,
        selected=adjusted <= fwer,
        fwer=fwer,
        reps=reps,
        block_mean=block_mean,
    )


def _step_down_p(t_obs: np.ndarray, t_star: np.ndarray) -> np.ndarray:
    """Romano-Wolf adjusted p-values: in descending order of t, the share of draws whose max
    over the still-active attempts reaches the attempt's t, made monotone."""
    order = np.argsort(-t_obs, kind="stable")
    # Max over attempts ranked at or below position j (the active set when j is tested).
    tail_max = np.maximum.accumulate(t_star[:, order[::-1]], axis=1)[:, ::-1]
    raw = (tail_max >= t_obs[order][None, :]).mean(axis=0)
    adjusted = np.empty_like(raw)
    adjusted[order] = np.maximum.accumulate(raw)
    return adjusted
