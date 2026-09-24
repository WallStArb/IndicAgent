"""S3: the three arms on the real alpha panel and on every admissible whole-panel shift.

Pre-registration section 7. The covariance plan depends only on returns, so it is built once
and shared by the real run and every shift; everything that depends on alpha (calibration,
standardization, weights) reruns per shift inside portfolio.arm_returns.
"""

from __future__ import annotations

import dataclasses
from concurrent.futures import ProcessPoolExecutor

import numpy as np

from scripts.analysis.sleeve_walk_forward.config import HarnessConfig
from scripts.analysis.sleeve_walk_forward.portfolio import (
    ARMS,
    CovariancePlan,
    arm_returns,
    plan_covariance,
)
from scripts.analysis.sleeve_walk_forward.sessions import sub_period_masks
from src.intelligence.statistics.panel_null import (
    admissible_shifts,
    shift_panel,
    westfall_young_adjusted_p,
)

_SESSIONS_PER_YEAR = 252


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


def annualized_sharpe(r: np.ndarray, mask: np.ndarray) -> float:
    x = r[mask & np.isfinite(r)]
    if len(x) < 2:
        raise ValueError(f"Sharpe needs at least 2 finite returns, got {len(x)}")
    sd = float(np.std(x, ddof=1))
    if sd == 0.0:
        raise ValueError("Sharpe undefined: zero return variance")
    return float(np.mean(x)) / sd * np.sqrt(_SESSIONS_PER_YEAR)


def _run_shifts(
    alpha: np.ndarray,
    fwd_ret: np.ndarray,
    plan: CovariancePlan,
    cfg: HarnessConfig,
    k: float,
    shifts: np.ndarray,
    trade: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Compute-only worker: per shift, each arm's Sharpe and its daily returns (float32)."""
    sharpe = np.empty((len(shifts), len(ARMS)))
    daily = np.empty((len(shifts), len(ARMS), alpha.shape[0]), dtype=np.float32)
    for i, shift in enumerate(shifts):
        out = arm_returns(shift_panel(alpha, int(shift)), fwd_ret, plan, cfg, k)
        for j, arm in enumerate(ARMS):
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
) -> EvaluationResult:
    n = alpha.shape[0]
    trade = dates >= np.datetime64(cfg.trading_start)
    plan = plan_covariance(closes, cfg, mv_condition_max)
    obs = arm_returns(alpha, fwd_ret, plan, cfg, ic_shrinkage_k)
    obs_daily = np.stack([obs[arm] for arm in ARMS])
    sharpe_obs = np.array([annualized_sharpe(r, trade) for r in obs_daily])

    shifts = admissible_shifts(n, cfg.min_shift) if shifts is None else np.asarray(shifts)
    args = (alpha, fwd_ret, plan, cfg, ic_shrinkage_k)
    if workers > 1:
        chunks = np.array_split(shifts, workers)
        with ProcessPoolExecutor(max_workers=workers) as pool:
            parts = list(pool.map(_run_shifts, *zip(*[(*args, c, trade) for c in chunks])))
        sharpe_null = np.concatenate([p[0] for p in parts])
        null_daily = np.concatenate([p[1] for p in parts])
    else:
        sharpe_null, null_daily = _run_shifts(*args, shifts, trade)

    null_median_daily = np.median(null_daily, axis=0)  # [J, n]
    excess_daily = obs_daily - null_median_daily
    sub_masks = [m & trade for m in sub_period_masks(dates, cfg.sub_periods)]
    return EvaluationResult(
        arms=ARMS,
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
