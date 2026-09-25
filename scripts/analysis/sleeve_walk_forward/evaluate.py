"""S3: the three arms on the real alpha panel and on every admissible whole-panel shift.

Pre-registration section 7. The covariance plan depends only on returns, so it is built once
and shared by the real run and every shift; everything that depends on alpha (calibration,
standardization, weights) reruns per shift inside the construction. The construction is a
parameter, (alpha, fwd_ret, plan) -> {arm: daily returns}: phase 179's calibrated arms by
default, a signal source's pinned construction otherwise (signals.SignalSource).
"""

from __future__ import annotations

import dataclasses
import functools
from collections.abc import Callable

import numpy as np
from scipy.stats import kurtosis, skew

from scripts.analysis.sleeve_walk_forward.config import HarnessConfig
from scripts.analysis.sleeve_walk_forward.portfolio import (
    CovariancePlan,
    arm_returns,
    plan_covariance,
)
from scripts.analysis.sleeve_walk_forward.sessions import sub_period_masks
from services._batch_utils import make_worker_pool
from src.intelligence.statistics.panel_null import (
    admissible_shifts,
    shift_panel,
    westfall_young_adjusted_p,
)

_SESSIONS_PER_YEAR = 252

Construction = Callable[[np.ndarray, np.ndarray, CovariancePlan], dict[str, np.ndarray]]


@dataclasses.dataclass(frozen=True)
class EvaluationResult:
    arms: tuple[str, ...]
    sharpe_obs: np.ndarray  # [J]
    sharpe_null: np.ndarray  # [K, J]
    shifts: np.ndarray  # [K]
    adjusted_p: np.ndarray  # [J]
    excess: np.ndarray  # [J], observed minus null-median Sharpe
    sub_period_excess: np.ndarray  # [J, n_sub_periods], mean daily excess return
    excess_ci: np.ndarray  # [J, 2], stationary-bootstrap 95% CI of the excess Sharpe
    # Section 11 shape measures per arm, {"observed": {...}, "null_median": {...}}. Reported
    # for sizing; decide() never reads them.
    diagnostics: dict = dataclasses.field(default_factory=dict)


def annualized_sharpe(r: np.ndarray, mask: np.ndarray) -> float:
    x = r[mask & np.isfinite(r)]
    if len(x) < 2:
        raise ValueError(f"Sharpe needs at least 2 finite returns, got {len(x)}")
    sd = float(np.std(x, ddof=1))
    if sd == 0.0:
        raise ValueError("Sharpe undefined: zero return variance")
    return float(np.mean(x)) / sd * np.sqrt(_SESSIONS_PER_YEAR)


def shape_diagnostics(r: np.ndarray) -> dict[str, float]:
    """Return-shape measures over the finite daily returns: annualized Sortino (downside
    deviation over all days, NaN with no losing day), max drawdown of the cumulative log-wealth
    path from 0, skew, excess kurtosis, and the share of positive days."""
    x = r[np.isfinite(r)]
    downside = float(np.sqrt(np.mean(np.minimum(x, 0.0) ** 2)))
    wealth = np.concatenate([[0.0], np.cumsum(x)])
    return {
        "sortino": (
            float(np.mean(x)) / downside * np.sqrt(_SESSIONS_PER_YEAR)
            if downside > 0
            else float("nan")
        ),
        "max_drawdown": float(np.max(np.maximum.accumulate(wealth) - wealth)),
        "skew": float(skew(x)),
        "excess_kurtosis": float(kurtosis(x)),
        "hit_rate": float(np.mean(x > 0)),
    }


def trade_mask(dates: np.ndarray, cfg: HarnessConfig) -> np.ndarray:
    """Sessions in the scored span: trading_start through the last sub-period's end. The panel's
    last sessions have no forward return and must not enter the Sharpe as zero-return days."""
    return (dates >= np.datetime64(cfg.trading_start)) & (
        dates <= np.datetime64(cfg.sub_periods[-1][1])
    )


def _run_shifts(
    alpha: np.ndarray,
    fwd_ret: np.ndarray,
    plan: CovariancePlan,
    construction: Construction,
    arms: tuple[str, ...],
    shifts: np.ndarray,
    trade: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Compute-only worker: per shift, each arm's Sharpe and its daily returns (float32)."""
    sharpe = np.empty((len(shifts), len(arms)))
    daily = np.empty((len(shifts), len(arms), alpha.shape[0]), dtype=np.float32)
    for i, shift in enumerate(shifts):
        out = construction(shift_panel(alpha, int(shift)), fwd_ret, plan)
        for j, arm in enumerate(arms):
            sharpe[i, j] = annualized_sharpe(out[arm], trade)
            daily[i, j] = out[arm]
    return sharpe, daily


def evaluate(
    alpha: np.ndarray,
    fwd_ret: np.ndarray,
    closes: np.ndarray,
    dates: np.ndarray,
    cfg: HarnessConfig,
    *,
    mv_condition_max: float,
    ic_shrinkage_k: float,
    shifts: np.ndarray | None = None,
    workers: int = 1,
    construction: Construction | None = None,
    memory: int = 0,
) -> EvaluationResult:
    """`memory` feeds admissible_shifts when `shifts` is not given; a picklable
    `construction` (module-level function or functools.partial) replaces the calibrated arms."""
    n = alpha.shape[0]
    trade = trade_mask(dates, cfg)
    plan = plan_covariance(closes, cfg, mv_condition_max)
    if construction is None:
        construction = functools.partial(arm_returns, cfg=cfg, ic_shrinkage_k=ic_shrinkage_k)
    obs = construction(alpha, fwd_ret, plan)
    arms = tuple(obs)
    obs_daily = np.stack([obs[arm] for arm in arms])
    sharpe_obs = np.array([annualized_sharpe(r, trade) for r in obs_daily])

    if shifts is None:
        shifts = admissible_shifts(n, cfg.min_shift, memory)
    shifts = np.asarray(shifts)
    args = (alpha, fwd_ret, plan, construction, arms)
    if workers > 1:
        chunks = np.array_split(shifts, workers)
        with make_worker_pool(workers, cfg.blas_threads_per_worker) as pool:
            parts = list(pool.map(_run_shifts, *zip(*[(*args, c, trade) for c in chunks])))
        sharpe_null = np.concatenate([p[0] for p in parts])
        null_daily = np.concatenate([p[1] for p in parts])
    else:
        sharpe_null, null_daily = _run_shifts(*args, shifts, trade)

    null_median_daily = np.median(null_daily, axis=0)  # [J, n]
    excess_daily = obs_daily - null_median_daily
    sub_masks = [m & trade for m in sub_period_masks(dates, cfg.sub_periods)]
    return EvaluationResult(
        arms=arms,
        sharpe_obs=sharpe_obs,
        sharpe_null=sharpe_null,
        shifts=shifts,
        adjusted_p=westfall_young_adjusted_p(sharpe_obs, sharpe_null),
        excess=sharpe_obs - np.median(sharpe_null, axis=0),
        sub_period_excess=np.array(
            [[np.nanmean(row[m]) for m in sub_masks] for row in excess_daily]
        ),
        excess_ci=np.array(
            [
                _bootstrap_sharpe_ci(
                    row[trade], cfg.bootstrap_mean_block, cfg.bootstrap_reps, cfg.seed
                )
                for row in excess_daily
            ]
        ),
        diagnostics={
            arm: {
                "observed": shape_diagnostics(obs_daily[j][trade]),
                "null_median": shape_diagnostics(null_median_daily[j][trade]),
            }
            for j, arm in enumerate(arms)
        },
    )


def _bootstrap_sharpe_ci(x: np.ndarray, mean_block: int, reps: int, seed: int) -> np.ndarray:
    """Politis-Romano stationary bootstrap (geometric blocks, circular) 95% CI of the
    annualized Sharpe. Reported only; the permutation p decides."""
    x = x[np.isfinite(x)]
    n = len(x)
    rng = np.random.default_rng(seed)
    idx = np.empty((reps, n), dtype=np.int64)
    idx[:, 0] = rng.integers(0, n, reps)
    restart = rng.random((reps, n)) < 1.0 / mean_block
    fresh = rng.integers(0, n, (reps, n))
    for t in range(1, n):
        idx[:, t] = np.where(restart[:, t], fresh[:, t], (idx[:, t - 1] + 1) % n)
    sample = x[idx]
    sd = sample.std(axis=1, ddof=1)
    sharpe = np.where(sd > 0, sample.mean(axis=1) / np.where(sd > 0, sd, 1.0), 0.0)
    return np.percentile(sharpe * np.sqrt(_SESSIONS_PER_YEAR), [2.5, 97.5])
