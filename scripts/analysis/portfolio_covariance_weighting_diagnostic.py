#!/usr/bin/env python3
"""
portfolio_covariance_weighting_diagnostic.py -- shadow-mode diagnostic for whether cross-instrument
covariance-aware portfolio weighting beats naive/IC-proportional/volatility-normalized baselines.

See docs/superpowers/specs/2026-09-16-cross-instrument-covariance-aware-portfolio-diagnostic-design.md
for the full design, including why resolve_stratum_weights/derive_weights are NOT reused (they zero
non-positive inputs, which is wrong for a signed instrument book -- confirmed against the actual code
during design review) and why Sigma is estimated from realized historical returns, never forward_returns.

Method (must match the spec exactly -- do not "fix" any of this without updating the spec first):
- mu_i = IC_shrunk_i * sigma_i * z_i, where z_i is instrument i's OWN trailing score history
  standardized to zero mean / unit variance (fixes cross-instrument score-scale mismatch), IC_shrunk_i
  is instrument i's trailing rank-IC shrunk via empirical-Bayes toward the leave-one-out peer mean, and
  sigma_i is the diagonal of the realized-return covariance matrix.
- Sigma: Ledoit-Wolf shrinkage covariance of REALIZED historical log returns
  (ln(close_t/close_{t-1})) -- never forward_returns, which are targets/labels, not observations.
- Embargo: any refit at boundary T uses forward-return rows with bar_ts <= T - 2 trading days only.
- Two decoupled cadences: covariance/IC refit every _REFIT_EVERY_BARS trading days (coarse), weight
  recomputation from that day's alpha_score every trading day (fine).
- Four comparison arms: equal-weight, IC-proportional, volatility-normalized (diagonal-Sigma special
  case), full mean-variance (off-diagonal Sigma).
- No --gate: this is a measurement tool, not a promotion gate.

Exit-code contract: 0 = ran successfully. 1 = the script errored (DB connection failure, unhandled
exception, bad arguments). No gate exit code (2) -- see spec's "Output" section.

Usage:
    .venv/bin/python scripts/analysis/portfolio_covariance_weighting_diagnostic.py \\
        --symbols GLD,DBA,DBB,DBC,URA,TLT,UUP,VIXY,EMLC,HYG,XOM,DHI,PGR \\
        --weight-version v1 --json-out /var/tmp/portfolio_covariance_diagnostic.json
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import structlog  # noqa: E402

from src.core.service_utils import setup_service_logging  # noqa: E402
from src.intelligence.ensemble.shrinkage import (  # noqa: E402
    leave_one_out_group_prior,
    shrink_ic,
)

setup_service_logging("logs/portfolio_covariance_weighting_diagnostic.log")
_logger = structlog.get_logger(__name__)

_JOB_NAME = "portfolio-covariance-weighting-diagnostic"
_TIMEFRAME = "1d"
_SYMBOL_BATCH_SIZE = 25
_CORR_MIN_PERIODS = 20

# Reused verbatim from alpha.hmm.walk_forward.{refit_every_bars,initial_warmup_bars}.1d -- todo 248's
# only existing walk-forward precedent in this codebase. Not APR-backed here (see module docstring):
# a diagnostic's own methodology constants must require a code edit to change so its numbers stay
# comparable run-to-run.
_REFIT_EVERY_BARS = 252
_INITIAL_WARMUP_BARS = 504

# executable_open_to_open at bar T is ln(open[T+2]/open[T+1]) -- not realized until T+1's open. A
# refit at boundary T must only see forward-return rows through T-2.
_EMBARGO_BARS = 2

# Matches universe_expansion_correlation_structure_check.py's _MIN_DAILY_COVERAGE -- same reasoning.
_MIN_COVERAGE = 0.95

# Matches alpha.ensemble.mv_condition_max's live default (1000) -- hardcoded per this module's own
# non-APR methodology-constant convention (see docstring), not because it disagrees with that key.
_MV_CONDITION_MAX = 1000.0

# Matches alpha.ic.shrinkage_k's live default (100).
_IC_SHRINKAGE_K = 100.0

# Ridge fallback for an ill-conditioned instrument covariance: Sigma + epsilon * I, epsilon scaled to
# 10% of the matrix's own average variance (trace/n) so the ridge term is meaningful regardless of the
# instruments' absolute return-variance scale.
_RIDGE_EPSILON_FRACTION = 0.10

# Causal regime proxy: trailing SPY SMA window, shifted 1 bar so today's regime label never uses
# today's own close.
_REGIME_SMA_WINDOW = 200


# ---------------------------------------------------------------------------
# Pure functions -- no I/O, no logging. Unit-tested directly against synthetic data in
# tests/unit/scripts/test_portfolio_covariance_weighting_diagnostic.py.
# ---------------------------------------------------------------------------


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
