"""Instrument-level portfolio weighting primitives.

Pure functions, Ring 1: no DB, no logging, no hardcoded thresholds (callers pass their own
pre-registered constants). Shared by the cross-asset covariance diagnostic
(scripts/analysis/portfolio_covariance_weighting_diagnostic.py, design
docs/superpowers/specs/2026-09-16-cross-instrument-covariance-aware-portfolio-diagnostic-design.md)
and the Phase 179 walk-forward harness
(docs/plans/2026-09-24-phase179-sleeve-walk-forward-prereg.md).

The book is signed (long/short) with gross exposure 1. mu_i = IC_shrunk_i * sigma_i * z_i:
z_i is instrument i's score standardized on its own trailing history, IC_shrunk_i its
trailing rank IC shrunk toward the leave-one-out peer mean, sigma_i from the covariance of
realized close-to-close log returns (never forward_returns, which are labels).

Deliberately not ensemble_trainer's resolve_stratum_weights/derive_weights: those zero
non-positive inputs, which would delete every short from an instrument book.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.intelligence.ensemble.covariance import compute_shrinkage_covariance
from src.intelligence.ensemble.shrinkage import leave_one_out_group_prior, shrink_ic
from src.intelligence.ensemble.weights import effective_n, mean_variance_weights
from src.intelligence.statistics.ic_math import check_condition_number


def standardize_scores(score_history: pd.Series) -> pd.Series:
    """Per-instrument time-series z-score: (score - mean) / std, using this instrument's OWN
    trailing score history. Fixes the cross-instrument score-scale mismatch the design review
    found -- different instruments' alpha_score composites have different variance (different
    active-feature counts, different feature volatility), so standardization must happen
    per-instrument, not globally across instruments.

    A zero-variance (degenerate/constant) score history returns an all-zero series rather than
    dividing by zero -- "no signal" is the correct z-score for "no variation to standardize".
    """
    std = score_history.std(ddof=0)
    if not np.isfinite(std) or std < 1e-12:
        return pd.Series(0.0, index=score_history.index)
    return (score_history - score_history.mean()) / std


def shrink_instrument_ic(ic_raw: np.ndarray, n_eff: np.ndarray, k: float) -> np.ndarray:
    """Empirical-Bayes shrink each instrument's trailing IC toward the leave-one-out
    cross-sectional mean of the other instruments in the same refit, reusing shrink_ic()/
    leave_one_out_group_prior() unchanged (src/intelligence/ensemble/shrinkage.py) rather than
    reimplementing the shrinkage math -- same reasoning as reusing compute_shrinkage_covariance.
    """
    n = len(ic_raw)
    shrunk = np.zeros(n, dtype=float)
    for i in range(n):
        prior = leave_one_out_group_prior(ic_raw, i)
        shrunk[i], _weight = shrink_ic(float(ic_raw[i]), float(n_eff[i]), prior, k)
    return shrunk


def compute_mu(ic_shrunk: np.ndarray, sigma: np.ndarray, z_latest: np.ndarray) -> np.ndarray:
    """mu_i = IC_shrunk_i * sigma_i * z_i -- the corrected Grinold-Kahn calibration (spec's
    "Critical correction... REVISED after review" section). z_latest is each instrument's
    standardized score AT the current rebalance date (the most recent value of the
    standardize_scores() series), sigma is the diagonal of the realized-return covariance matrix.
    """
    return ic_shrunk * sigma * z_latest


def log_returns(close_wide: pd.DataFrame) -> pd.DataFrame:
    """(dates x symbols) log-return frame from a (dates x symbols) close-price frame. First row
    is always dropped (no prior bar to diff against)."""
    return np.log(close_wide / close_wide.shift(1)).iloc[1:]


def instrument_covariance(
    returns: pd.DataFrame, *, min_coverage_fraction: float
) -> tuple[np.ndarray, list[str]]:
    """Ledoit-Wolf shrinkage covariance of REALIZED historical log returns over a trailing
    window (never forward_returns -- see module docstring).

    Precondition: rows are trading sessions (the caller's date axis is the exchange calendar,
    not a union of whatever timestamps each symbol happens to carry).

    Admission, all deterministic and point-in-time:
      1. a return on the window's last row (no current price means the book can't hold it,
         and keeping a stale symbol would cut the newest rows from every other symbol's fit);
      2. returns on at least min_coverage_fraction of the rows (counted on returns, so one
         missing close costs two);
      3. jointly: while the rows where every admitted symbol has a return fall below the same
         fraction, drop the lowest-coverage symbol (ties by name).
    The fit uses those complete rows. Missing returns are never filled with zero: that
    understates a new listing's variance and inflates its vol-scaled weight.

    Returns (cov, symbols) with symbols sorted and cov ordered to match; empty when nothing
    is admitted.
    """
    n_rows = len(returns)
    if n_rows == 0:
        return np.zeros((0, 0)), []
    coverage = returns.count() / n_rows
    current = returns.iloc[-1].notna()
    kept = sorted(
        sym for sym in returns.columns if current[sym] and coverage[sym] >= min_coverage_fraction
    )
    while kept and len(returns[kept].dropna()) < min_coverage_fraction * n_rows:
        kept.remove(min(kept, key=lambda sym: (coverage[sym], sym)))
    if not kept:
        return np.zeros((0, 0)), []
    cov, _shrinkage = compute_shrinkage_covariance(returns[kept].dropna().to_numpy())
    return cov, kept


def equal_weight_arm(n: int) -> np.ndarray:
    """Arm 1: naive equal-weight. No covariance adjustment, no IC weighting."""
    if n == 0:
        return np.zeros(0)
    return np.full(n, 1.0 / n)


def normalize_by_abs_sum(raw: np.ndarray) -> np.ndarray:
    total = float(np.sum(np.abs(raw)))
    if total < 1e-10:
        return np.zeros_like(raw)
    return raw / total


def ic_proportional_arm(mu: np.ndarray) -> np.ndarray:
    """Arm 2: each instrument weighted by its own calibrated mu_i, no cross-instrument
    covariance adjustment -- what's implicit in today's architecture (each instrument scored
    independently). Signed (long/short) -- normalized by sum of ABSOLUTE weights, since mu can
    be negative and a signed book's total exposure convention is gross, not net."""
    return normalize_by_abs_sum(mu)


def vol_normalized_arm(mu: np.ndarray, sigma: np.ndarray) -> np.ndarray:
    """Arm 2b (added after design review): w_i ~ mu_i / sigma_i^2 -- the diagonal-only special
    case of mean-variance (inverse-volatility scaling, no off-diagonal correlation term).
    Isolates "just scale by volatility" from real covariance/correlation-awareness (Arm 4);
    without this arm, an apparent Arm 4 win over Arm 2 can't be attributed to correlation
    modeling instead of trivial vol scaling."""
    sigma_safe = np.where(sigma > 1e-12, sigma, np.inf)
    raw = mu / sigma_safe**2
    return normalize_by_abs_sum(raw)


def mean_variance_arm(
    cov_matrix: np.ndarray,
    mu: np.ndarray,
    condition_max: float,
    *,
    ridge_epsilon_fraction: float,
) -> tuple[np.ndarray, str, float]:
    """Arm 4: full mean-variance covariance-aware weighting -- the primitive
    mean_variance_weights() solve (Sigma^-1 . mu), NOT resolve_stratum_weights (see spec's
    Component reuse revision: that wrapper's derive_weights zeroes non-positive inputs, which
    is wrong for a signed instrument book).

    On an ill-conditioned Sigma, falls back to ridge regularization (Sigma + epsilon*I, epsilon =
    ridge_epsilon_fraction x the matrix's own average variance) and re-solves -- never
    cluster_deflate_weights/derive_weights, which are built for feature weights, not a signed
    instrument book. If even the ridge-regularized matrix is unusable, falls back
    further to vol_normalized_arm (the diagonal-only special case) rather than reimplementing
    a second, independent diagonal solve -- one source of truth for "volatility-only weighting"
    in this module. The fallback is always returned in method_used, matching ensemble_trainer.py's
    "mean_variance_fallback must never be silent" discipline -- callers are responsible for
    logging it.
    """
    raw, cond = mean_variance_weights(cov_matrix, mu, condition_max)
    if raw is not None:
        return normalize_by_abs_sum(raw), "mean_variance", cond

    n = cov_matrix.shape[0]
    epsilon = ridge_epsilon_fraction * float(np.trace(cov_matrix)) / max(n, 1)
    ridge_cov = cov_matrix + epsilon * np.eye(n)
    ridge_ok, _ridge_cond = check_condition_number(ridge_cov, condition_max)
    if ridge_ok:
        raw_ridge = np.linalg.solve(ridge_cov, mu)
        return normalize_by_abs_sum(raw_ridge), "mean_variance_ridge_fallback", cond

    sigma = np.sqrt(np.maximum(np.diag(cov_matrix), 1e-12))
    return vol_normalized_arm(mu, sigma), "mean_variance_ridge_fallback", cond


def portfolio_exposure_stats(weights: np.ndarray) -> dict[str, float]:
    """gross/net exposure, effective_n, and Herfindahl for a (possibly signed) weight vector.

    effective_n = 1/sum(w^2) is reused from the feature-combination case, but reported alongside
    gross/net exposure rather than alone -- the design review found 1/sum(w^2) misleading in
    isolation once weights are signed and non-unit-sum (Arms 3-4 can carry negative entries;
    the feature-combination case this formula was built for is always non-negative and unit-sum).
    """
    gross = float(np.sum(np.abs(weights)))
    net = float(np.sum(weights))
    herfindahl = float(np.sum(weights**2))
    return {
        "gross_exposure": gross,
        "net_exposure": net,
        "herfindahl": herfindahl,
        "effective_n": effective_n(weights),
    }
