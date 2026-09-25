"""S3 core: daily gross returns of the three signal arms for one alpha panel.

Array-first so the null can rerun it on every shifted panel. Semantics are the diagnostic's
(scripts/analysis/portfolio_covariance_weighting_diagnostic.py::run_walk_forward) on the
pre-registration's pinned values; tests/unit/sleeve_walk_forward/test_portfolio.py holds a slow
loop over src/intelligence/portfolio/weighting.py that this module must match.

- Calibration refit at session p for p >= warmup, every calibration_refit_sessions, using data
  through p - 2 (the diagnostic's _EMBARGO_BARS): instrument covariance of the trailing
  close-to-close log returns, then per admitted symbol a Spearman IC of its alpha against its
  forward return over the same trailing rows, shrunk toward the leave-one-out peer mean. The
  IC is 0 unless coverage_fraction of the window's finite-alpha days also have a finite forward
  return (todo 425, methodology-change-ledger E14: counted over the whole window, the bar was
  voided by the NaN alpha of no-weight-stratum days); small samples are left to the shrinkage,
  which scales by the paired count. A refit that admits fewer than 2 symbols keeps the previous
  refit's state.
- Each day d: z_i is alpha_i[d] standardized on its own trailing warmup window (0 when alpha is
  missing or the window has no variance), mu = IC * sigma * z, weights per arm, return
  sum_i w_i * fwd_ret[d, i] with a missing return held at 0.

The covariance, and the mean-variance solve built on it, depend only on returns, so
plan_covariance runs once and every shifted panel reuses it.

fixed_sign_returns is the construction for a signal source with a pre-registered direction
(Moskowitz, Ooi and Pedersen 2012): no fitted IC, weights direction * sign(alpha) / sigma over
the refit's admitted symbols, gross 1. The calibrated arms above learn each symbol's IC sign
from a trailing window, which for a slow signal built from the returns themselves is noisy and
biased (Stambaugh), and on synthetic trending panels shorts the trend it should ride.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from scripts.analysis.sleeve_walk_forward.config import HarnessConfig
from src.intelligence.portfolio.weighting import instrument_covariance, shrink_instrument_ic
from src.intelligence.statistics.ic_math import check_condition_number

ARMS = ("ic_proportional", "vol_normalized", "mean_variance")
FIXED_SIGN_ARM = "fixed_sign"
_EMBARGO = 2
_ZERO_SUM = 1e-10
_ZERO_STD = 1e-12


@dataclasses.dataclass(frozen=True)
class CovariancePlan:
    """Per calibration refit (None where fewer than 2 symbols were admitted)."""

    refit_positions: np.ndarray
    symbol_idx: list[np.ndarray | None]
    sigma: list[np.ndarray | None]
    # Matrix M with raw mean-variance weights = mu @ M.T (Sigma^-1, or the ridge inverse),
    # or None for the vol-normalized fallback.
    mv_matrix: list[np.ndarray | None]


def plan_covariance(
    closes: np.ndarray, cfg: HarnessConfig, mv_condition_max: float
) -> CovariancePlan:
    n = closes.shape[0]
    log_ret = np.log(closes[1:] / closes[:-1])  # row i-1 is the return into session i
    positions = np.arange(cfg.warmup_sessions, n, cfg.calibration_refit_sessions)
    symbol_idx, sigma, mv_matrix = [], [], []
    for p in positions:
        b = p - _EMBARGO
        first = max(1, b - cfg.warmup_sessions + 1)
        window = pd.DataFrame(log_ret[first - 1 : b], index=range(first, b + 1))
        cov, kept = instrument_covariance(window, min_coverage_fraction=cfg.coverage_fraction)
        if len(kept) < 2:
            symbol_idx.append(None)
            sigma.append(None)
            mv_matrix.append(None)
            continue
        symbol_idx.append(np.array(kept, dtype=int))
        sigma.append(np.sqrt(np.maximum(np.diag(cov), _ZERO_STD)))
        mv_matrix.append(_mean_variance_matrix(cov, mv_condition_max, cfg.ridge_epsilon_fraction))
    return CovariancePlan(positions, symbol_idx, sigma, mv_matrix)


def _mean_variance_matrix(
    cov: np.ndarray, condition_max: float, ridge_epsilon_fraction: float
) -> np.ndarray | None:
    """weighting.mean_variance_arm's branch, decided once: its condition checks see only cov."""
    if check_condition_number(cov, condition_max)[0]:
        return np.linalg.inv(cov)
    n = cov.shape[0]
    ridge = cov + ridge_epsilon_fraction * float(np.trace(cov)) / n * np.eye(n)
    if check_condition_number(ridge, condition_max)[0]:
        return np.linalg.inv(ridge)
    return None


def _arm_blocks(
    alpha: np.ndarray,
    fwd_ret: np.ndarray,
    plan: CovariancePlan,
    cfg: HarnessConfig,
    ic_shrinkage_k: float,
):
    """Yield (block, symbol idx, {arm: weights [block_len, len(idx)]}) per calibration segment."""
    n = alpha.shape[0]
    z = _trailing_z(alpha, cfg.warmup_sessions)
    bounds = np.append(plan.refit_positions, n)
    state = None
    for k, p in enumerate(plan.refit_positions):
        idx = plan.symbol_idx[k]
        if idx is not None:
            ic = _calibrate(alpha, fwd_ret, idx, p - _EMBARGO, cfg, ic_shrinkage_k)
            state = (idx, plan.sigma[k], ic, plan.mv_matrix[k])
        if state is None:
            continue
        idx, sig, ic, matrix = state
        block = slice(p, bounds[k + 1])
        mu = ic * sig * z[block][:, idx]
        vol = _normalize(mu / np.where(sig > _ZERO_STD, sig, np.inf) ** 2)
        mv = vol if matrix is None else _normalize(mu @ matrix.T)
        yield block, idx, {
            "ic_proportional": _normalize(mu),
            "vol_normalized": vol,
            "mean_variance": mv,
        }


def arm_returns(
    alpha: np.ndarray,
    fwd_ret: np.ndarray,
    plan: CovariancePlan,
    cfg: HarnessConfig,
    ic_shrinkage_k: float,
) -> dict[str, np.ndarray]:
    out = {arm: np.full(alpha.shape[0], np.nan) for arm in ARMS}
    for block, idx, weights in _arm_blocks(alpha, fwd_ret, plan, cfg, ic_shrinkage_k):
        r = np.nan_to_num(fwd_ret[block][:, idx])
        for arm, w in weights.items():
            out[arm][block] = (w * r).sum(axis=1)
    return out


def arm_weights(
    alpha: np.ndarray,
    fwd_ret: np.ndarray,
    plan: CovariancePlan,
    cfg: HarnessConfig,
    ic_shrinkage_k: float,
) -> dict[str, np.ndarray]:
    """Each arm's daily weights over the full sleeve, [n, n_sleeve], NaN before the first
    calibration and 0 for symbols outside a segment's admitted set. Section 11 diagnostics only
    (turnover, costs, per-symbol contribution); never read by `decide`."""
    out = {arm: np.full(alpha.shape, np.nan) for arm in ARMS}
    for block, idx, weights in _arm_blocks(alpha, fwd_ret, plan, cfg, ic_shrinkage_k):
        for arm, w in weights.items():
            full = np.zeros((w.shape[0], alpha.shape[1]))
            full[:, idx] = w
            out[arm][block] = full
    return out


def fixed_sign_returns(
    alpha: np.ndarray, fwd_ret: np.ndarray, plan: CovariancePlan, *, direction: float
) -> dict[str, np.ndarray]:
    n = alpha.shape[0]
    out = np.full(n, np.nan)
    bounds = np.append(plan.refit_positions, n)
    state = None
    for k, p in enumerate(plan.refit_positions):
        if plan.symbol_idx[k] is not None:
            state = (plan.symbol_idx[k], plan.sigma[k])
        if state is None:
            continue
        idx, sig = state
        block = slice(p, bounds[k + 1])
        raw = direction * np.sign(np.nan_to_num(alpha[block][:, idx])) / sig
        out[block] = (_normalize(raw) * np.nan_to_num(fwd_ret[block][:, idx])).sum(axis=1)
    return {FIXED_SIGN_ARM: out}


def _normalize(raw: np.ndarray) -> np.ndarray:
    """Row-wise weighting.normalize_by_abs_sum."""
    total = np.abs(raw).sum(axis=1, keepdims=True)
    return np.where(total < _ZERO_SUM, 0.0, raw / np.where(total < _ZERO_SUM, 1.0, total))


def _trailing_z(alpha: np.ndarray, window: int) -> np.ndarray:
    """z[d, i] = weighting.standardize_scores(alpha[d-window+1 : d+1, i]).iloc[-1], or 0 when
    alpha[d, i] is missing. Rolling sums are taken about each column's mean to limit
    cancellation in the variance."""
    finite = np.isfinite(alpha)
    center = np.zeros(alpha.shape[1])
    has_data = finite.any(axis=0)
    center[has_data] = np.nanmean(alpha[:, has_data], axis=0)
    x = np.where(finite, alpha - center, 0.0)
    count, s1, s2 = (_window_sum(v, window) for v in (finite.astype(float), x, x * x))
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = s1 / count
        std = np.sqrt(np.maximum(s2 / count - mean**2, 0.0))
        z = (x - mean) / std
    return np.where(finite & (count > 0) & (std >= _ZERO_STD), z, 0.0)


def _window_sum(values: np.ndarray, window: int) -> np.ndarray:
    csum = np.cumsum(values, axis=0)
    out = csum.copy()
    out[window:] -= csum[:-window]
    return out


def _calibrate(
    alpha: np.ndarray,
    fwd_ret: np.ndarray,
    idx: np.ndarray,
    through: int,
    cfg: HarnessConfig,
    k: float,
) -> np.ndarray:
    rows = slice(max(0, through - cfg.warmup_sessions + 1), through + 1)
    ic_raw = np.zeros(len(idx))
    n_eff = np.zeros(len(idx))
    for j, s in enumerate(idx):
        a, f = alpha[rows, s], fwd_ret[rows, s]
        fa = np.isfinite(a)
        if fa.sum() < 2 or np.std(a[fa]) < _ZERO_STD:
            # standardize_scores returns zeros over the whole window: constant z, IC 0.
            n_eff[j] = np.isfinite(f).sum()
            continue
        paired = fa & np.isfinite(f)
        n_eff[j] = paired.sum()
        if n_eff[j] >= 2 and n_eff[j] >= cfg.coverage_fraction * fa.sum():
            rho = spearmanr(a[paired], f[paired])[0]
            ic_raw[j] = float(rho) if np.isfinite(rho) else 0.0
    return shrink_instrument_ic(ic_raw, n_eff, k)
