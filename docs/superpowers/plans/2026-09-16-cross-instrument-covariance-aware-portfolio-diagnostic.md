# Cross-Instrument Covariance-Aware Portfolio Diagnostic Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone, shadow-mode diagnostic script that measures whether covariance-aware
cross-instrument portfolio weighting beats naive/IC-proportional/volatility-normalized baselines, walk-
forward, for the Phase 174 cross-asset candidate list.

**Architecture:** One new script (`scripts/analysis/`), no new tables/services/Kafka topics. Pure
functions (mu calibration, covariance estimation, four weight-arm computations, exposure/turnover
diagnostics, causal regime proxy) are unit-tested directly against synthetic data; a thin I/O shell
fetches from existing tables (`market_data_ohlcv_tradeable`, `alpha_events`, `forward_returns`) and
writes a JSON report. Reuses three existing pure-function modules
(`src/intelligence/ensemble/covariance.py`, `weights.py`, `shrinkage.py`) as primitives only — not the
feature-combination wrapper (`resolve_stratum_weights`/`derive_weights`), which the spec's review found
unsound for a signed instrument book.

**Tech Stack:** Python, psycopg (sync), pandas, numpy, scipy.stats (Spearman IC), pytest.

**Spec:** `docs/superpowers/specs/2026-09-16-cross-instrument-covariance-aware-portfolio-diagnostic-design.md`

## Global Constraints

- Long/short, not long-only (spec's recommendation for v1 — avoids needing a QP/NNLS solver).
- Sigma estimated ONLY from realized historical closes (`market_data_ohlcv_tradeable`, log returns
  `ln(close_t/close_{t-1})`) — never from `forward_returns`. These are two separate data pulls; do not
  merge them into one fetch.
- `forward_returns` used only for (a) trailing IC measurement feeding `mu_i`, and (b) scoring realized
  out-of-sample portfolio performance. Filter `return_type = 'executable_open_to_open'`, use the
  `return_fast` column (1-bar-ahead — matches this diagnostic's daily rebalance cadence), and require
  `complete_fast = true AND return_fast_suspect = false`.
- Embargo: any refit at boundary `T` uses forward-return rows with `bar_ts <= T - 2` trading days only
  (`return_fast` at bar `T` is `ln(open[T+2]/open[T+1])`, not realized until `T+1`'s open — a refit at
  `T` cannot see `T-1`'s return yet either, hence `T-2`).
- Two decoupled cadences: `_REFIT_EVERY_BARS = 252` and `_INITIAL_WARMUP_BARS = 504` (reused verbatim
  from `alpha.hmm.walk_forward.refit_every_bars.1d` / `initial_warmup_bars.1d` for consistency with the
  project's one existing walk-forward precedent, per the spec's open item). Rebalance (weight
  recomputation from that day's `alpha_score`) happens every trading day.
- Regime split on a causal proxy (trailing SPY 200-day SMA sign, 1-bar-shifted) — never
  `market_regimes`/`regime_writer.py` output, which carries todo 248's confirmed non-causal HMM
  contamination.
- Four comparison arms: equal-weight, IC-proportional, volatility-normalized (Arm 2b), full mean-
  variance. No `--gate`/pass-fail exit code — this is a measurement tool.
- All numeric thresholds are literal module-level constants, not APR keys — matches
  `universe_expansion_correlation_structure_check.py`'s (Gate A) explicit precedent: a diagnostic
  script's own methodology constants must require a code edit + reviewable diff to change, not be
  adjustable from a psql prompt, so its numbers stay comparable run-to-run.
- Exception variable name is `error` (`except Exception as error:`), never `exc` (CLAUDE.md).
- No `datetime.now()`/`datetime.utcnow()` — UTC-aware only where timestamps are constructed.

---

## File Structure

- Create: `scripts/analysis/portfolio_covariance_weighting_diagnostic.py` — pure functions (mu
  calibration, covariance, four arms, exposure/turnover, regime proxy, walk-forward orchestration) plus
  a thin I/O shell (DB fetch, argparse, `main()`), following `universe_expansion_correlation_structure_check.py`'s
  exact single-file convention (pure functions first, `# --- I/O shell ---` marker, then `main()`).
- Create: `tests/unit/scripts/test_portfolio_covariance_weighting_diagnostic.py` — one test class/section
  per pure function, plus one end-to-end synthetic smoke test of the walk-forward orchestrator.
- No existing file is modified. No migration, no new table, no APR key, no systemd unit.

---

### Task 1: Mu calibration — score standardization + IC shrinkage

**Files:**
- Create: `scripts/analysis/portfolio_covariance_weighting_diagnostic.py`
- Test: `tests/unit/scripts/test_portfolio_covariance_weighting_diagnostic.py`

**Interfaces:**
- Produces: `standardize_scores(score_history: pd.Series) -> pd.Series` — per-instrument time-series
  z-score using that instrument's own trailing-window mean/std (fixes the cross-instrument scale
  mismatch the spec review found: different instruments' `alpha_score` composites have different
  variance, so standardization must happen per-instrument, not once globally).
- Produces: `shrink_instrument_ic(ic_raw: np.ndarray, n_eff: np.ndarray, k: float) -> np.ndarray` —
  vectorized wrapper around the existing `shrink_ic`/`leave_one_out_group_prior`
  (`src/intelligence/ensemble/shrinkage.py`), shrinking each instrument's trailing IC toward the
  leave-one-out cross-sectional mean of the other instruments in the same refit.
- Produces: `compute_mu(ic_shrunk: np.ndarray, sigma: np.ndarray, z_latest: np.ndarray) -> np.ndarray` —
  `mu_i = IC_shrunk_i * sigma_i * z_i`, the corrected Grinold-Kahn form from the spec.

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for scripts/analysis/portfolio_covariance_weighting_diagnostic.py."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scripts.analysis.portfolio_covariance_weighting_diagnostic import (
    compute_mu,
    shrink_instrument_ic,
    standardize_scores,
)


def test_standardize_scores_zero_mean_unit_variance():
    s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
    z = standardize_scores(s)
    assert z.mean() == pytest.approx(0.0, abs=1e-10)
    assert z.std(ddof=0) == pytest.approx(1.0, abs=1e-10)


def test_standardize_scores_constant_series_returns_zero_not_nan():
    # A degenerate all-equal score series has zero variance -- must not divide by zero.
    s = pd.Series([2.0, 2.0, 2.0])
    z = standardize_scores(s)
    assert (z == 0.0).all()


def test_standardize_scores_removes_cross_instrument_scale_mismatch():
    # Instrument A's raw score has std 0.2, instrument B's has std 2.0 -- same underlying
    # signal shape, different scale. After standardization both must have unit variance,
    # eliminating the scale artifact the spec review flagged.
    a = pd.Series(np.array([-0.2, 0.0, 0.2]))
    b = pd.Series(np.array([-2.0, 0.0, 2.0]))
    za, zb = standardize_scores(a), standardize_scores(b)
    np.testing.assert_allclose(za.to_numpy(), zb.to_numpy())


def test_shrink_instrument_ic_shrinks_toward_leave_one_out_peer_mean():
    # Three instruments, ic_raw = [0.10, 0.20, 0.30], all n_eff=100 (default k=100 -> w=0.5).
    ic_raw = np.array([0.10, 0.20, 0.30])
    n_eff = np.array([100.0, 100.0, 100.0])
    shrunk = shrink_instrument_ic(ic_raw, n_eff, k=100.0)
    # Instrument 0's leave-one-out peer mean is (0.20+0.30)/2=0.25; w=100/(100+100)=0.5
    # shrunk[0] = 0.5*0.10 + 0.5*0.25 = 0.175
    assert shrunk[0] == pytest.approx(0.175, abs=1e-9)


def test_shrink_instrument_ic_zero_n_eff_falls_fully_to_prior():
    ic_raw = np.array([0.50, 0.10, 0.10])
    n_eff = np.array([0.0, 100.0, 100.0])
    shrunk = shrink_instrument_ic(ic_raw, n_eff, k=100.0)
    # n_eff=0 -> full shrinkage to leave-one-out prior = mean(0.10, 0.10) = 0.10, ignoring 0.50.
    assert shrunk[0] == pytest.approx(0.10, abs=1e-9)


def test_compute_mu_matches_hand_computed_formula():
    ic_shrunk = np.array([0.05, -0.02])
    sigma = np.array([0.01, 0.02])
    z_latest = np.array([1.5, -0.5])
    mu = compute_mu(ic_shrunk, sigma, z_latest)
    expected = np.array([0.05 * 0.01 * 1.5, -0.02 * 0.02 * -0.5])
    np.testing.assert_allclose(mu, expected)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/scripts/test_portfolio_covariance_weighting_diagnostic.py -v`
Expected: FAIL / collection error — `scripts/analysis/portfolio_covariance_weighting_diagnostic.py` does
not exist yet.

- [ ] **Step 3: Create the module with mu-calibration functions**

```python
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

import argparse
import json
import sys
from datetime import UTC, date, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import psycopg  # noqa: E402
import structlog  # noqa: E402
from scipy.stats import spearmanr  # noqa: E402

from src.config.settings import Settings  # noqa: E402
from src.core.service_utils import setup_service_logging  # noqa: E402
from src.intelligence.ensemble.covariance import (  # noqa: E402
    compute_shrinkage_covariance,
    covariance_to_correlation,
)
from src.intelligence.ensemble.shrinkage import (  # noqa: E402
    leave_one_out_group_prior,
    shrink_ic,
)
from src.intelligence.ensemble.weights import mean_variance_weights  # noqa: E402
from src.intelligence.statistics.ic_math import check_condition_number  # noqa: E402
from src.observability.metrics import JOB_COMPLETED_TOTAL, flush_and_shutdown_metrics  # noqa: E402

setup_service_logging("logs/portfolio_covariance_weighting_diagnostic.log")
_logger = structlog.get_logger(__name__)

_JOB_NAME = "portfolio-covariance-weighting-diagnostic"
_TIMEFRAME = "1d"
_SYMBOL_BATCH_SIZE = 25
_CORR_MIN_PERIODS = 20

# Reused verbatim from alpha.hmm.walk_forward.{refit_every_bars,initial_warmup_bars}.1d -- todo 248's
# only existing walk-forward precedent in this codebase. Not APR-backed here (see module docstring +
# Global Constraints in the plan this file was built from): a diagnostic's own methodology constants
# must require a code edit to change so its numbers stay comparable run-to-run.
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/scripts/test_portfolio_covariance_weighting_diagnostic.py -v -k "standardize_scores or shrink_instrument_ic or compute_mu"`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/analysis/portfolio_covariance_weighting_diagnostic.py tests/unit/scripts/test_portfolio_covariance_weighting_diagnostic.py
git commit -m "feat(diagnostic): mu calibration -- score standardization + IC shrinkage"
```

---

### Task 2: Realized-return instrument covariance

**Files:**
- Modify: `scripts/analysis/portfolio_covariance_weighting_diagnostic.py`
- Test: `tests/unit/scripts/test_portfolio_covariance_weighting_diagnostic.py`

**Interfaces:**
- Consumes: nothing new from Task 1.
- Produces: `log_returns(close_wide: pd.DataFrame) -> pd.DataFrame` — `(dates x symbols)` log-return
  frame from a `(dates x symbols)` close-price frame.
- Produces: `instrument_covariance(returns: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, list[str]]`
  — `(cov_matrix, corr_matrix, symbol_order)`, dropping any symbol with fewer than
  `_CORR_MIN_PERIODS` non-null observations (never silently including a near-empty column in the
  Ledoit-Wolf fit).

- [ ] **Step 1: Write the failing tests**

```python
from scripts.analysis.portfolio_covariance_weighting_diagnostic import (
    instrument_covariance,
    log_returns,
)


def test_log_returns_matches_hand_computed_values():
    close = pd.DataFrame({"A": [100.0, 110.0, 121.0]}, index=pd.date_range("2026-01-01", periods=3))
    r = log_returns(close)
    assert r.shape == (2, 1)  # first row has no prior bar
    np.testing.assert_allclose(r["A"].to_numpy(), [np.log(1.10), np.log(1.10)], atol=1e-9)


def test_instrument_covariance_shape_and_symbol_order():
    rng = np.random.default_rng(42)
    idx = pd.date_range("2026-01-01", periods=60)
    returns = pd.DataFrame(rng.normal(0, 0.01, size=(60, 3)), index=idx, columns=["A", "B", "C"])
    cov, corr, symbols = instrument_covariance(returns)
    assert cov.shape == (3, 3)
    assert corr.shape == (3, 3)
    assert symbols == ["A", "B", "C"]
    np.testing.assert_allclose(np.diag(corr), 1.0, atol=1e-9)


def test_instrument_covariance_drops_sparse_symbol():
    rng = np.random.default_rng(1)
    idx = pd.date_range("2026-01-01", periods=60)
    returns = pd.DataFrame(rng.normal(0, 0.01, size=(60, 2)), index=idx, columns=["A", "B"])
    returns["C"] = np.nan
    returns.loc[returns.index[:5], "C"] = 0.001  # only 5 obs, below _CORR_MIN_PERIODS=20
    cov, corr, symbols = instrument_covariance(returns)
    assert symbols == ["A", "B"]
    assert cov.shape == (2, 2)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/scripts/test_portfolio_covariance_weighting_diagnostic.py -v -k instrument_covariance or log_returns`
Expected: FAIL — `log_returns`/`instrument_covariance` not defined.

- [ ] **Step 3: Implement**

Add to `scripts/analysis/portfolio_covariance_weighting_diagnostic.py`, after `compute_mu`:

```python
def log_returns(close_wide: pd.DataFrame) -> pd.DataFrame:
    """(dates x symbols) log-return frame from a (dates x symbols) close-price frame. First row
    is always dropped (no prior bar to diff against)."""
    return np.log(close_wide / close_wide.shift(1)).iloc[1:]


def instrument_covariance(returns: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Ledoit-Wolf shrinkage covariance/correlation of REALIZED historical log returns (never
    forward_returns -- see module docstring). Drops any symbol with fewer than
    _CORR_MIN_PERIODS non-null observations before fitting, same reliability floor
    correlation_structure() uses in universe_expansion_correlation_structure_check.py.
    """
    counts = returns.count()
    kept = sorted(counts[counts >= _CORR_MIN_PERIODS].index.tolist())
    X = returns[kept].fillna(0.0).to_numpy()
    cov, _shrinkage = compute_shrinkage_covariance(X)
    corr = covariance_to_correlation(cov)
    return cov, corr, kept
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/scripts/test_portfolio_covariance_weighting_diagnostic.py -v -k "instrument_covariance or log_returns"`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/analysis/portfolio_covariance_weighting_diagnostic.py tests/unit/scripts/test_portfolio_covariance_weighting_diagnostic.py
git commit -m "feat(diagnostic): realized-return instrument covariance estimation"
```

---

### Task 3: Four comparison-arm weight functions

**Files:**
- Modify: `scripts/analysis/portfolio_covariance_weighting_diagnostic.py`
- Test: `tests/unit/scripts/test_portfolio_covariance_weighting_diagnostic.py`

**Interfaces:**
- Consumes: `mean_variance_weights` (from `src.intelligence.ensemble.weights`, already imported),
  `check_condition_number` (already imported).
- Produces: `equal_weight_arm(n: int) -> np.ndarray`
- Produces: `ic_proportional_arm(mu: np.ndarray) -> np.ndarray`
- Produces: `vol_normalized_arm(mu: np.ndarray, sigma: np.ndarray) -> np.ndarray`
- Produces: `mean_variance_arm(cov_matrix: np.ndarray, mu: np.ndarray, condition_max: float) ->
  tuple[np.ndarray, str, float]` — `(weights, method_used, condition_number)`, `method_used` in
  `{"mean_variance", "mean_variance_ridge_fallback"}`.

- [ ] **Step 1: Write the failing tests**

```python
from scripts.analysis.portfolio_covariance_weighting_diagnostic import (
    equal_weight_arm,
    ic_proportional_arm,
    mean_variance_arm,
    vol_normalized_arm,
)


def test_equal_weight_arm_sums_to_one_and_is_uniform():
    w = equal_weight_arm(4)
    assert w.shape == (4,)
    np.testing.assert_allclose(w, [0.25, 0.25, 0.25, 0.25])


def test_ic_proportional_arm_normalizes_by_sum_of_absolute_values():
    mu = np.array([0.02, -0.01, 0.01])
    w = ic_proportional_arm(mu)
    np.testing.assert_allclose(w, mu / 0.04)
    assert np.sum(np.abs(w)) == pytest.approx(1.0)


def test_ic_proportional_arm_all_zero_mu_returns_zero_vector():
    w = ic_proportional_arm(np.zeros(3))
    np.testing.assert_allclose(w, np.zeros(3))


def test_vol_normalized_arm_divides_by_variance_not_std():
    mu = np.array([0.02, 0.02])
    sigma = np.array([0.01, 0.02])
    w = vol_normalized_arm(mu, sigma)
    raw = mu / sigma**2  # [200.0, 50.0]
    expected = raw / np.sum(np.abs(raw))
    np.testing.assert_allclose(w, expected)


def test_mean_variance_arm_well_conditioned_uses_direct_solve():
    cov = np.array([[0.0004, 0.0001], [0.0001, 0.0009]])
    mu = np.array([0.01, -0.01])
    w, method, cond = mean_variance_arm(cov, mu, condition_max=1000.0)
    assert method == "mean_variance"
    assert np.isfinite(cond)
    np.testing.assert_allclose(np.sum(np.abs(w)), 1.0)


def test_mean_variance_arm_ill_conditioned_falls_back_to_ridge_and_logs_loud():
    # Near-singular covariance (two nearly-identical rows) -- condition number gate should trip.
    cov = np.array([[1.0, 0.999999999], [0.999999999, 1.0]])
    mu = np.array([0.01, 0.01])
    w, method, cond = mean_variance_arm(cov, mu, condition_max=10.0)
    assert method == "mean_variance_ridge_fallback"
    np.testing.assert_allclose(np.sum(np.abs(w)), 1.0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/scripts/test_portfolio_covariance_weighting_diagnostic.py -v -k arm`
Expected: FAIL — functions not defined.

- [ ] **Step 3: Implement**

Add to `scripts/analysis/portfolio_covariance_weighting_diagnostic.py`, after `instrument_covariance`:

```python
def equal_weight_arm(n: int) -> np.ndarray:
    """Arm 1: naive equal-weight. No covariance adjustment, no IC weighting."""
    if n == 0:
        return np.zeros(0)
    return np.full(n, 1.0 / n)


def _normalize_by_abs_sum(raw: np.ndarray) -> np.ndarray:
    total = float(np.sum(np.abs(raw)))
    if total < 1e-10:
        return np.zeros_like(raw)
    return raw / total


def ic_proportional_arm(mu: np.ndarray) -> np.ndarray:
    """Arm 2: each instrument weighted by its own calibrated mu_i, no cross-instrument
    covariance adjustment -- what's implicit in today's architecture (each instrument scored
    independently). Signed (long/short) -- normalized by sum of ABSOLUTE weights, since mu can
    be negative and a signed book's total exposure convention is gross, not net."""
    return _normalize_by_abs_sum(mu)


def vol_normalized_arm(mu: np.ndarray, sigma: np.ndarray) -> np.ndarray:
    """Arm 2b (added after design review): w_i ~ mu_i / sigma_i^2 -- the diagonal-only special
    case of mean-variance (inverse-volatility scaling, no off-diagonal correlation term).
    Isolates "just scale by volatility" from real covariance/correlation-awareness (Arm 4);
    without this arm, an apparent Arm 4 win over Arm 2 can't be attributed to correlation
    modeling instead of trivial vol scaling."""
    sigma_safe = np.where(sigma > 1e-12, sigma, np.inf)
    raw = mu / sigma_safe**2
    return _normalize_by_abs_sum(raw)


def mean_variance_arm(
    cov_matrix: np.ndarray, mu: np.ndarray, condition_max: float
) -> tuple[np.ndarray, str, float]:
    """Arm 4: full mean-variance covariance-aware weighting -- the primitive
    mean_variance_weights() solve (Sigma^-1 . mu), NOT resolve_stratum_weights (see spec's
    Component reuse revision: that wrapper's derive_weights zeroes non-positive inputs, which
    is wrong for a signed instrument book).

    On an ill-conditioned Sigma, falls back to ridge regularization (Sigma + epsilon*I, epsilon
    scaled to 10% of the matrix's own average variance) and re-solves -- never
    cluster_deflate_weights/derive_weights, which assume a feature-staleness input this
    diagnostic doesn't have. The fallback is always returned in method_used, matching
    ensemble_trainer.py's "mean_variance_fallback must never be silent" discipline -- callers
    (the walk-forward orchestrator, Task 7) are responsible for logging it.
    """
    raw, cond = mean_variance_weights(cov_matrix, mu, condition_max)
    if raw is not None:
        return _normalize_by_abs_sum(raw), "mean_variance", cond

    n = cov_matrix.shape[0]
    epsilon = _RIDGE_EPSILON_FRACTION * float(np.trace(cov_matrix)) / max(n, 1)
    ridge_cov = cov_matrix + epsilon * np.eye(n)
    ridge_ok, ridge_cond = check_condition_number(ridge_cov, condition_max)
    if ridge_ok:
        raw_ridge = np.linalg.solve(ridge_cov, mu)
    else:
        # Even the ridge-regularized matrix is unusable -- fall back further to the diagonal
        # (volatility-only) solve rather than emit an unstable result.
        raw_ridge = mu / np.maximum(np.diag(cov_matrix), 1e-12)
    return _normalize_by_abs_sum(raw_ridge), "mean_variance_ridge_fallback", cond
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/scripts/test_portfolio_covariance_weighting_diagnostic.py -v -k arm`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/analysis/portfolio_covariance_weighting_diagnostic.py tests/unit/scripts/test_portfolio_covariance_weighting_diagnostic.py
git commit -m "feat(diagnostic): four comparison-arm weight functions"
```

---

### Task 4: Portfolio exposure diagnostics and turnover

**Files:**
- Modify: `scripts/analysis/portfolio_covariance_weighting_diagnostic.py`
- Test: `tests/unit/scripts/test_portfolio_covariance_weighting_diagnostic.py`

**Interfaces:**
- Produces: `portfolio_exposure_stats(weights: np.ndarray) -> dict[str, float]` — keys
  `gross_exposure`, `net_exposure`, `effective_n`, `herfindahl`.
- Produces: `l1_turnover(w_prev: np.ndarray, w_curr: np.ndarray) -> float`.

- [ ] **Step 1: Write the failing tests**

```python
from scripts.analysis.portfolio_covariance_weighting_diagnostic import (
    l1_turnover,
    portfolio_exposure_stats,
)


def test_portfolio_exposure_stats_long_short_book():
    w = np.array([0.5, -0.3, 0.2])
    stats = portfolio_exposure_stats(w)
    assert stats["gross_exposure"] == pytest.approx(1.0)
    assert stats["net_exposure"] == pytest.approx(0.4)
    assert stats["herfindahl"] == pytest.approx(0.5**2 + 0.3**2 + 0.2**2)
    assert stats["effective_n"] == pytest.approx(1.0 / (0.5**2 + 0.3**2 + 0.2**2))


def test_portfolio_exposure_stats_all_zero_weights_no_divide_by_zero():
    stats = portfolio_exposure_stats(np.zeros(3))
    assert stats["gross_exposure"] == 0.0
    assert stats["net_exposure"] == 0.0
    assert stats["effective_n"] == 0.0


def test_l1_turnover_matches_hand_computed_sum():
    w_prev = np.array([0.5, 0.5, 0.0])
    w_curr = np.array([0.2, 0.3, 0.5])
    assert l1_turnover(w_prev, w_curr) == pytest.approx(0.3 + 0.2 + 0.5)


def test_l1_turnover_no_change_is_zero():
    w = np.array([0.3, 0.7])
    assert l1_turnover(w, w) == pytest.approx(0.0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/scripts/test_portfolio_covariance_weighting_diagnostic.py -v -k "exposure_stats or l1_turnover"`
Expected: FAIL — functions not defined.

- [ ] **Step 3: Implement**

Add to `scripts/analysis/portfolio_covariance_weighting_diagnostic.py`, after `mean_variance_arm`:

```python
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
    effective_n = 0.0 if herfindahl < 1e-12 else 1.0 / herfindahl
    return {
        "gross_exposure": gross,
        "net_exposure": net,
        "herfindahl": herfindahl,
        "effective_n": effective_n,
    }


def l1_turnover(w_prev: np.ndarray, w_curr: np.ndarray) -> float:
    """sum(|w_t - w_{t-1}|) -- L1 turnover between two consecutive rebalance weight vectors.
    Reported per arm per rebalance (Output section, spec) so a mean-variance arm's tendency to
    churn on small mu/Sigma shifts is visible, not hidden behind a gross-return-only report."""
    return float(np.sum(np.abs(w_curr - w_prev)))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/scripts/test_portfolio_covariance_weighting_diagnostic.py -v -k "exposure_stats or l1_turnover"`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/analysis/portfolio_covariance_weighting_diagnostic.py tests/unit/scripts/test_portfolio_covariance_weighting_diagnostic.py
git commit -m "feat(diagnostic): portfolio exposure stats and L1 turnover"
```

---

### Task 5: Causal regime proxy

**Files:**
- Modify: `scripts/analysis/portfolio_covariance_weighting_diagnostic.py`
- Test: `tests/unit/scripts/test_portfolio_covariance_weighting_diagnostic.py`

**Interfaces:**
- Produces: `causal_regime_labels(spy_close: pd.Series, window: int = _REGIME_SMA_WINDOW) ->
  pd.Series` — per-date `"bull"`/`"bear"` label, `NaN` (as `None`) where the trailing window isn't
  yet full.

- [ ] **Step 1: Write the failing tests**

```python
from scripts.analysis.portfolio_covariance_weighting_diagnostic import causal_regime_labels


def test_causal_regime_labels_bull_when_price_above_trailing_sma():
    # Strictly increasing series: every post-warmup point sits above its own trailing SMA.
    idx = pd.date_range("2026-01-01", periods=10)
    close = pd.Series(np.arange(1.0, 11.0), index=idx)
    labels = causal_regime_labels(close, window=5)
    # First 5 (warmup) are None; from index 5 on, price > trailing SMA -> "bull".
    assert labels.iloc[:5].isna().all()
    assert (labels.iloc[5:] == "bull").all()


def test_causal_regime_labels_bear_when_price_below_trailing_sma():
    idx = pd.date_range("2026-01-01", periods=10)
    close = pd.Series(np.arange(10.0, 0.0, -1.0), index=idx)
    labels = causal_regime_labels(close, window=5)
    assert (labels.iloc[5:] == "bear").all()


def test_causal_regime_labels_never_uses_same_bar_close():
    # A single-bar spike at t should not change t's OWN label -- the label at t is derived from
    # the SMA of bars strictly before t (1-bar shift), so it must be knowable before t's close
    # prints. Verify by comparing to a manually shifted SMA.
    idx = pd.date_range("2026-01-01", periods=8)
    close = pd.Series([1, 2, 3, 4, 5, 100, 7, 8], index=idx, dtype=float)
    labels = causal_regime_labels(close, window=3)
    manual_sma = close.rolling(3).mean().shift(1)
    expected = np.where(close > manual_sma, "bull", "bear")
    expected_masked = pd.Series(expected, index=idx).where(manual_sma.notna())
    pd.testing.assert_series_equal(labels, expected_masked, check_names=False)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/scripts/test_portfolio_covariance_weighting_diagnostic.py -v -k causal_regime_labels`
Expected: FAIL — function not defined.

- [ ] **Step 3: Implement**

Add to `scripts/analysis/portfolio_covariance_weighting_diagnostic.py`, after `l1_turnover`:

```python
def causal_regime_labels(spy_close: pd.Series, window: int = _REGIME_SMA_WINDOW) -> pd.Series:
    """Causal bull/bear regime proxy: trailing SMA of SPY close, SHIFTED one bar so today's
    label never depends on today's own close (avoids same-bar lookahead entirely, by
    construction -- no walk-forward loop needed for this proxy, unlike Sigma/IC).

    Used instead of market_regimes/regime_writer.py's HMM labels, which carry a confirmed
    non-causal contamination (full-series fit; walk-forward fix exists but is disabled -- todo
    248). Cheap, causal by construction, avoids inheriting that unresolved bug rather than just
    disclosing it (spec's Method section, "Regime split on a causal proxy").

    Returns NaN for any date before the trailing window is full.
    """
    trailing_sma = spy_close.rolling(window).mean().shift(1)
    label = pd.Series(np.where(spy_close > trailing_sma, "bull", "bear"), index=spy_close.index)
    return label.where(trailing_sma.notna())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/scripts/test_portfolio_covariance_weighting_diagnostic.py -v -k causal_regime_labels`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/analysis/portfolio_covariance_weighting_diagnostic.py tests/unit/scripts/test_portfolio_covariance_weighting_diagnostic.py
git commit -m "feat(diagnostic): causal SPY-SMA regime proxy"
```

---

### Task 6: Walk-forward orchestration

**Files:**
- Modify: `scripts/analysis/portfolio_covariance_weighting_diagnostic.py`
- Test: `tests/unit/scripts/test_portfolio_covariance_weighting_diagnostic.py`

**Interfaces:**
- Consumes: every pure function from Tasks 1-5 (`standardize_scores`, `shrink_instrument_ic`,
  `compute_mu`, `log_returns`, `instrument_covariance`, all four arm functions,
  `portfolio_exposure_stats`, `l1_turnover`, `causal_regime_labels`).
- Produces: `run_walk_forward(close_wide: pd.DataFrame, alpha_wide: pd.DataFrame, fwd_return_wide:
  pd.DataFrame, cost_hurdle_wide: pd.DataFrame, spy_close: pd.Series) -> dict[str, Any]` — the full
  report structure (per Output section of the spec), taking already-fetched, already-aligned
  `(dates x symbols)` frames — no DB access in this function, so it's fully unit-testable against
  synthetic data. `cost_hurdle_wide` supplies the per-instrument cost proxy (`alpha_events.cost_hurdle`)
  needed for cost-adjusted net return — required by the spec's Output section ("gross and cost-adjusted
  net return per arm"), missed in the first draft of this plan and added here during self-review.

- [ ] **Step 1: Write the failing test (synthetic end-to-end)**

```python
from scripts.analysis.portfolio_covariance_weighting_diagnostic import run_walk_forward


def _synthetic_inputs(n_days: int = 520, n_symbols: int = 4, seed: int = 7):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n_days, freq="B")
    symbols = [f"SYM{i}" for i in range(n_symbols)]

    log_ret = rng.normal(0.0002, 0.01, size=(n_days, n_symbols))
    close = pd.DataFrame(
        100.0 * np.exp(np.cumsum(log_ret, axis=0)), index=idx, columns=symbols
    )
    alpha = pd.DataFrame(rng.normal(0.0, 1.0, size=(n_days, n_symbols)), index=idx, columns=symbols)
    # forward_returns.return_fast at bar t approximates the next bar's log return -- synthetic
    # stand-in consistent with "1-bar-ahead executable return" for this smoke test.
    fwd = pd.DataFrame(log_ret, index=idx, columns=symbols).shift(-1)
    # cost_hurdle: constant small per-instrument friction proxy, mirroring alpha_events.cost_hurdle.
    cost_hurdle = pd.DataFrame(0.0005, index=idx, columns=symbols)
    spy = pd.Series(100.0 * np.exp(np.cumsum(rng.normal(0.0002, 0.008, n_days))), index=idx)
    return close, alpha, fwd, cost_hurdle, spy


def test_run_walk_forward_smoke_produces_all_four_arms_and_diagnostics():
    close, alpha, fwd, cost_hurdle, spy = _synthetic_inputs()
    report = run_walk_forward(close, alpha, fwd, cost_hurdle, spy)

    assert set(report["arms"].keys()) == {
        "equal_weight",
        "ic_proportional",
        "vol_normalized",
        "mean_variance",
    }
    for arm_name, arm_report in report["arms"].items():
        assert "rebalance_steps" in arm_report
        assert len(arm_report["rebalance_steps"]) > 0
        first_step = arm_report["rebalance_steps"][0]
        assert set(first_step.keys()) >= {
            "date",
            "weights",
            "gross_exposure",
            "net_exposure",
            "effective_n",
            "turnover",
            "realized_return",
            "cost",
            "net_realized_return",
        }
        assert "aggregate" in arm_report
        assert "unconditional" in arm_report["aggregate"]
        assert "mean_net_realized_return" in arm_report["aggregate"]["unconditional"]
        assert "bull" in arm_report["aggregate"] or "bear" in arm_report["aggregate"]

    assert report["mean_variance_fallback_count"] >= 0
    assert report["n_rebalance_steps"] == len(report["arms"]["equal_weight"]["rebalance_steps"])


def test_run_walk_forward_cost_reduces_net_return_below_gross():
    # With a strictly positive cost_hurdle and nonzero turnover, net_realized_return must never
    # exceed gross realized_return for any step -- cost only ever subtracts.
    close, alpha, fwd, cost_hurdle, spy = _synthetic_inputs()
    report = run_walk_forward(close, alpha, fwd, cost_hurdle, spy)
    for arm_report in report["arms"].values():
        for step in arm_report["rebalance_steps"]:
            assert step["net_realized_return"] <= step["realized_return"] + 1e-12
            assert step["cost"] >= 0.0


def test_run_walk_forward_never_uses_embargoed_forward_return():
    # Regression guard for the embargo requirement: construct a fwd_return frame where the
    # LAST two rows are populated with an extreme outlier value that must never influence any
    # refit's IC calibration if the embargo is respected (those two rows fall inside the
    # embargo window relative to the final refit boundary).
    close, alpha, fwd, cost_hurdle, spy = _synthetic_inputs(n_days=520)
    fwd_poisoned = fwd.copy()
    fwd_poisoned.iloc[-2:] = 999.0  # would blow up IC/mu if leaked into calibration
    report_clean = run_walk_forward(close, alpha, fwd, cost_hurdle, spy)
    report_poisoned = run_walk_forward(close, alpha, fwd_poisoned, cost_hurdle, spy)
    # The LAST refit's calibration (ic_shrunk logged per refit) must be identical between the
    # two runs -- the poisoned rows fall inside the embargo window and must never be read.
    last_refit_clean = report_clean["refits"][-1]["ic_shrunk"]
    last_refit_poisoned = report_poisoned["refits"][-1]["ic_shrunk"]
    np.testing.assert_allclose(last_refit_clean, last_refit_poisoned)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/scripts/test_portfolio_covariance_weighting_diagnostic.py -v -k run_walk_forward`
Expected: FAIL — function not defined.

- [ ] **Step 3: Implement**

Add to `scripts/analysis/portfolio_covariance_weighting_diagnostic.py`, after `causal_regime_labels`:

```python
_ARM_FUNCS = ("equal_weight", "ic_proportional", "vol_normalized", "mean_variance")


def run_walk_forward(
    close_wide: pd.DataFrame,
    alpha_wide: pd.DataFrame,
    fwd_return_wide: pd.DataFrame,
    cost_hurdle_wide: pd.DataFrame,
    spy_close: pd.Series,
) -> dict[str, Any]:
    """Full walk-forward diagnostic over already-fetched, already-aligned (dates x symbols)
    frames -- no DB access here, so this is directly unit-testable against synthetic data.

    Two decoupled cadences (spec's Method section):
    - Sigma/IC refit every _REFIT_EVERY_BARS trading days, using data through the embargo
      boundary (current index position - _EMBARGO_BARS) only.
    - Weight recomputation from that day's alpha_score every trading day, using the most
      recent refit's Sigma/IC_shrunk.

    Returns the full report dict: per-arm rebalance-step history, per-arm aggregate stats
    (unconditional + causal regime split), and refit-level diagnostics (condition number,
    fallback flag, ic_shrunk -- so a caller can audit exactly what each refit saw).
    """
    dates = close_wide.index
    symbols = sorted(close_wide.columns.tolist())
    returns = log_returns(close_wide[symbols])
    regime_labels = causal_regime_labels(spy_close)

    weights_by_arm: dict[str, list[np.ndarray]] = {a: [] for a in _ARM_FUNCS}
    prev_weights: dict[str, np.ndarray | None] = {a: None for a in _ARM_FUNCS}
    steps_by_arm: dict[str, list[dict[str, Any]]] = {a: [] for a in _ARM_FUNCS}
    refits: list[dict[str, Any]] = []
    fallback_count = 0

    current_cov: np.ndarray | None = None
    current_corr_symbols: list[str] | None = None
    current_ic_shrunk: dict[str, float] | None = None
    last_refit_pos = -_REFIT_EVERY_BARS  # force a refit on the first eligible day

    for pos, rebal_date in enumerate(dates):
        if pos < _INITIAL_WARMUP_BARS:
            continue

        if pos - last_refit_pos >= _REFIT_EVERY_BARS:
            embargo_boundary = pos - _EMBARGO_BARS
            hist_returns = returns.loc[returns.index <= dates[embargo_boundary]].tail(
                _INITIAL_WARMUP_BARS
            )
            cov, _corr, cov_symbols = instrument_covariance(hist_returns)
            if len(cov_symbols) < 2:
                continue

            ic_shrunk_vals: dict[str, float] = {}
            ic_raw_list = []
            n_eff_list = []
            for sym in cov_symbols:
                z_hist = standardize_scores(
                    alpha_wide[sym].loc[alpha_wide.index <= dates[embargo_boundary]].tail(
                        _INITIAL_WARMUP_BARS
                    )
                )
                fwd_hist = fwd_return_wide[sym].loc[
                    fwd_return_wide.index <= dates[embargo_boundary]
                ].tail(_INITIAL_WARMUP_BARS)
                paired = pd.concat([z_hist, fwd_hist], axis=1, keys=["z", "fwd"]).dropna()
                if len(paired) >= _CORR_MIN_PERIODS:
                    ic_raw, _p = spearmanr(paired["z"], paired["fwd"])
                    ic_raw = 0.0 if not np.isfinite(ic_raw) else float(ic_raw)
                else:
                    ic_raw = 0.0
                ic_raw_list.append(ic_raw)
                n_eff_list.append(float(len(paired)))

            ic_shrunk_arr = shrink_instrument_ic(
                np.array(ic_raw_list), np.array(n_eff_list), _IC_SHRINKAGE_K
            )
            ic_shrunk_vals = dict(zip(cov_symbols, ic_shrunk_arr.tolist(), strict=True))

            current_cov, current_corr_symbols, current_ic_shrunk = cov, cov_symbols, ic_shrunk_vals
            last_refit_pos = pos
            refits.append(
                {
                    "refit_date": str(rebal_date.date()),
                    "symbols": cov_symbols,
                    "ic_shrunk": ic_shrunk_arr.tolist(),
                }
            )

        if current_cov is None or current_corr_symbols is None:
            continue

        active_symbols = current_corr_symbols
        sigma = np.sqrt(np.maximum(np.diag(current_cov), 1e-12))
        z_today = np.array(
            [
                standardize_scores(
                    alpha_wide[sym].loc[alpha_wide.index <= rebal_date].tail(_INITIAL_WARMUP_BARS)
                ).iloc[-1]
                if rebal_date in alpha_wide.index and pd.notna(alpha_wide.loc[rebal_date, sym])
                else 0.0
                for sym in active_symbols
            ]
        )
        ic_shrunk_today = np.array([current_ic_shrunk[sym] for sym in active_symbols])
        mu = compute_mu(ic_shrunk_today, sigma, z_today)

        realized = fwd_return_wide.reindex([rebal_date])[active_symbols].iloc[0].fillna(0.0).to_numpy()
        cost_hurdle_today = (
            cost_hurdle_wide.reindex([rebal_date])[active_symbols].iloc[0].fillna(0.0).to_numpy()
        )
        regime = regime_labels.get(rebal_date)

        for arm in _ARM_FUNCS:
            if arm == "equal_weight":
                w = equal_weight_arm(len(active_symbols))
            elif arm == "ic_proportional":
                w = ic_proportional_arm(mu)
            elif arm == "vol_normalized":
                w = vol_normalized_arm(mu, sigma)
            else:
                w, method, _cond = mean_variance_arm(current_cov, mu, _MV_CONDITION_MAX)
                if method == "mean_variance_ridge_fallback":
                    fallback_count += 1
                    _logger.warning(
                        "portfolio_covariance_weighting_diagnostic.mean_variance_fallback",
                        date=str(rebal_date.date()),
                    )

            prev = prev_weights[arm]
            per_instrument_turnover = (
                np.zeros_like(w) if prev is None else np.abs(w - prev)
            )
            turnover = float(np.sum(per_instrument_turnover))
            # Cost model: each instrument's own cost_hurdle applied to the size of its OWN
            # rebalance trade (spec's Output section: "using alpha_events' existing cost_hurdle
            # as the per-instrument cost proxy"), summed to one scalar cost for the step.
            cost = float(np.sum(per_instrument_turnover * cost_hurdle_today))
            prev_weights[arm] = w
            weights_by_arm[arm].append(w)

            exposure = portfolio_exposure_stats(w)
            gross_return = float(np.dot(w, realized))
            steps_by_arm[arm].append(
                {
                    "date": str(rebal_date.date()),
                    "regime": regime,
                    "weights": dict(zip(active_symbols, w.tolist(), strict=True)),
                    "turnover": turnover,
                    "cost": cost,
                    "realized_return": gross_return,
                    "net_realized_return": gross_return - cost,
                    **exposure,
                }
            )

    arms_report: dict[str, Any] = {}
    for arm in _ARM_FUNCS:
        steps = steps_by_arm[arm]
        arms_report[arm] = {
            "rebalance_steps": steps,
            "aggregate": _aggregate_arm(steps),
        }

    return {
        "arms": arms_report,
        "refits": refits,
        "mean_variance_fallback_count": fallback_count,
        "n_rebalance_steps": len(steps_by_arm["equal_weight"]),
    }


def _aggregate_arm(steps: list[dict[str, Any]]) -> dict[str, Any]:
    """Unconditional + causal-regime-split aggregate stats for one arm's rebalance history."""

    def _summary(subset: list[dict[str, Any]]) -> dict[str, float]:
        if not subset:
            return {
                "n": 0,
                "mean_realized_return": 0.0,
                "mean_net_realized_return": 0.0,
                "mean_cost": 0.0,
                "mean_turnover": 0.0,
                "mean_effective_n": 0.0,
            }
        returns = np.array([s["realized_return"] for s in subset])
        net_returns = np.array([s["net_realized_return"] for s in subset])
        costs = np.array([s["cost"] for s in subset])
        turnovers = np.array([s["turnover"] for s in subset])
        eff_n = np.array([s["effective_n"] for s in subset])
        return {
            "n": len(subset),
            "mean_realized_return": float(returns.mean()),
            "mean_net_realized_return": float(net_returns.mean()),
            "mean_cost": float(costs.mean()),
            "mean_turnover": float(turnovers.mean()),
            "mean_effective_n": float(eff_n.mean()),
        }

    out = {"unconditional": _summary(steps)}
    for label in ("bull", "bear"):
        out[label] = _summary([s for s in steps if s["regime"] == label])
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/scripts/test_portfolio_covariance_weighting_diagnostic.py -v -k run_walk_forward`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/analysis/portfolio_covariance_weighting_diagnostic.py tests/unit/scripts/test_portfolio_covariance_weighting_diagnostic.py
git commit -m "feat(diagnostic): walk-forward orchestration tying all arms together"
```

---

### Task 7: Data loading I/O helpers

**Files:**
- Modify: `scripts/analysis/portfolio_covariance_weighting_diagnostic.py`
- Test: `tests/unit/scripts/test_portfolio_covariance_weighting_diagnostic.py`

**Interfaces:**
- Produces: `_fetch_daily_closes(conn: psycopg.Connection, symbols: list[str], start: str, end_exclusive:
  str) -> pd.DataFrame` — `(dates x symbols)`, from `market_data_ohlcv_tradeable`.
- Produces: `_fetch_alpha_scores(conn: psycopg.Connection, symbols: list[str], tf: str, weight_version:
  str, start: str, end_exclusive: str) -> pd.DataFrame` — `(dates x symbols)`, from `alpha_events`.
- Produces: `_fetch_forward_returns(conn: psycopg.Connection, symbols: list[str], tf: str, start: str,
  end_exclusive: str) -> pd.DataFrame` — `(dates x symbols)` of `return_fast`, filtered
  `return_type='executable_open_to_open' AND complete_fast AND NOT return_fast_suspect`.
- Produces: `_fetch_cost_hurdle(conn: psycopg.Connection, symbols: list[str], tf: str,
  weight_version: str, start: str, end_exclusive: str) -> pd.DataFrame` — `(dates x symbols)` of
  `alpha_events.cost_hurdle`, the per-instrument cost proxy required by the spec's Output section for
  cost-adjusted net return.
- Produces: `_apply_coverage_filter(close_wide: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]` —
  drops any symbol below `_MIN_COVERAGE`, logged not silent (matches Gate A's pattern exactly).

This task has no pure-function unit test of its own (it's a thin DB I/O shell, matching Gate A's own
convention of leaving `_fetch_daily_closes` etc. untested directly and instead exercised via `main()`);
it is verified in Task 8 by running the script end-to-end against the live DB.

- [ ] **Step 1: Implement**

Add to `scripts/analysis/portfolio_covariance_weighting_diagnostic.py`, after `run_walk_forward` /
`_aggregate_arm`, before the `main()` section:

```python
# ---------------------------------------------------------------------------
# I/O shell -- DB fetch, coverage filter, CLI, main().
# ---------------------------------------------------------------------------


def _batched(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _fetch_daily_closes(
    conn: psycopg.Connection, symbols: list[str], start: str, end_exclusive: str
) -> pd.DataFrame:
    """(date x symbol) wide frame of daily closes from market_data_ohlcv_tradeable -- never the
    raw market_data_ohlcv table (~82% synthetic-fill/flat-carry-forward placeholder bars
    intraday). Matches universe_expansion_correlation_structure_check.py's _fetch_daily_closes."""
    frames: list[pd.DataFrame] = []
    for batch in _batched(symbols, _SYMBOL_BATCH_SIZE):
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT timestamp, symbol, close
                FROM market_data_ohlcv_tradeable
                WHERE timeframe = %(timeframe)s AND symbol = ANY(%(symbols)s)
                  AND timestamp >= %(start)s AND timestamp < %(end_exclusive)s
                """,
                {"timeframe": _TIMEFRAME, "symbols": batch, "start": start, "end_exclusive": end_exclusive},
            )
            rows = cur.fetchall()
        if rows:
            frames.append(pd.DataFrame(rows, columns=["timestamp", "symbol", "close"]))
    if not frames:
        return pd.DataFrame()
    long = pd.concat(frames, ignore_index=True)
    long["timestamp"] = pd.to_datetime(long["timestamp"], utc=True)
    return long.pivot(index="timestamp", columns="symbol", values="close").sort_index()


def _fetch_alpha_scores(
    conn: psycopg.Connection,
    symbols: list[str],
    tf: str,
    weight_version: str,
    start: str,
    end_exclusive: str,
) -> pd.DataFrame:
    """(date x symbol) wide frame of alpha_events.alpha_score -- already signed (positive=long,
    negative=short per alpha_publisher.py's own direction derivation), so no separate
    direction-sign combination is needed."""
    frames: list[pd.DataFrame] = []
    for batch in _batched(symbols, _SYMBOL_BATCH_SIZE):
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT bar_ts, symbol, alpha_score
                FROM alpha_events
                WHERE tf = %(tf)s AND weight_version = %(weight_version)s
                  AND symbol = ANY(%(symbols)s)
                  AND bar_ts >= %(start)s AND bar_ts < %(end_exclusive)s
                """,
                {
                    "tf": tf,
                    "weight_version": weight_version,
                    "symbols": batch,
                    "start": start,
                    "end_exclusive": end_exclusive,
                },
            )
            rows = cur.fetchall()
        if rows:
            frames.append(pd.DataFrame(rows, columns=["bar_ts", "symbol", "alpha_score"]))
    if not frames:
        return pd.DataFrame()
    long = pd.concat(frames, ignore_index=True)
    long["bar_ts"] = pd.to_datetime(long["bar_ts"], utc=True)
    return long.pivot(index="bar_ts", columns="symbol", values="alpha_score").sort_index()


def _fetch_forward_returns(
    conn: psycopg.Connection, symbols: list[str], tf: str, start: str, end_exclusive: str
) -> pd.DataFrame:
    """(date x symbol) wide frame of forward_returns.return_fast, filtered to
    return_type='executable_open_to_open' (CLAUDE.md Invariant 1) AND complete_fast AND NOT
    return_fast_suspect. return_fast (1-bar-ahead) matches this diagnostic's daily rebalance
    cadence -- Codex's "covariance horizon alignment" review finding, resolved by picking the
    horizon that matches the rebalance cadence rather than leaving it unspecified."""
    frames: list[pd.DataFrame] = []
    for batch in _batched(symbols, _SYMBOL_BATCH_SIZE):
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT bar_ts, symbol, return_fast
                FROM forward_returns
                WHERE tf = %(tf)s AND symbol = ANY(%(symbols)s)
                  AND return_type = 'executable_open_to_open'
                  AND complete_fast AND NOT return_fast_suspect
                  AND bar_ts >= %(start)s AND bar_ts < %(end_exclusive)s
                """,
                {"tf": tf, "symbols": batch, "start": start, "end_exclusive": end_exclusive},
            )
            rows = cur.fetchall()
        if rows:
            frames.append(pd.DataFrame(rows, columns=["bar_ts", "symbol", "return_fast"]))
    if not frames:
        return pd.DataFrame()
    long = pd.concat(frames, ignore_index=True)
    long["bar_ts"] = pd.to_datetime(long["bar_ts"], utc=True)
    return long.pivot(index="bar_ts", columns="symbol", values="return_fast").sort_index()


def _fetch_cost_hurdle(
    conn: psycopg.Connection,
    symbols: list[str],
    tf: str,
    weight_version: str,
    start: str,
    end_exclusive: str,
) -> pd.DataFrame:
    """(date x symbol) wide frame of alpha_events.cost_hurdle -- the per-instrument cost proxy
    used by run_walk_forward's cost-adjusted net-return calculation (spec's Output section)."""
    frames: list[pd.DataFrame] = []
    for batch in _batched(symbols, _SYMBOL_BATCH_SIZE):
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT bar_ts, symbol, cost_hurdle
                FROM alpha_events
                WHERE tf = %(tf)s AND weight_version = %(weight_version)s
                  AND symbol = ANY(%(symbols)s)
                  AND bar_ts >= %(start)s AND bar_ts < %(end_exclusive)s
                """,
                {
                    "tf": tf,
                    "weight_version": weight_version,
                    "symbols": batch,
                    "start": start,
                    "end_exclusive": end_exclusive,
                },
            )
            rows = cur.fetchall()
        if rows:
            frames.append(pd.DataFrame(rows, columns=["bar_ts", "symbol", "cost_hurdle"]))
    if not frames:
        return pd.DataFrame()
    long = pd.concat(frames, ignore_index=True)
    long["bar_ts"] = pd.to_datetime(long["bar_ts"], utc=True)
    return long.pivot(index="bar_ts", columns="symbol", values="cost_hurdle").sort_index()


def _apply_coverage_filter(close_wide: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Drop any symbol below _MIN_COVERAGE non-null fraction, logged not silent -- identical
    reasoning and threshold to universe_expansion_correlation_structure_check.py's
    _apply_coverage_filter, so this diagnostic's own dropped-symbol behavior is comparable."""
    coverage = close_wide.notna().mean()
    keep = coverage[coverage >= _MIN_COVERAGE].index.tolist()
    dropped = sorted(set(close_wide.columns) - set(keep))
    return close_wide[sorted(keep)], dropped
```

- [ ] **Step 2: Commit**

```bash
git add scripts/analysis/portfolio_covariance_weighting_diagnostic.py
git commit -m "feat(diagnostic): DB fetch helpers for closes, alpha scores, forward returns"
```

---

### Task 8: CLI, JSON report, main()

**Files:**
- Modify: `scripts/analysis/portfolio_covariance_weighting_diagnostic.py`
- Test: `tests/unit/scripts/test_portfolio_covariance_weighting_diagnostic.py`

**Interfaces:**
- Produces: `main(argv: list[str] | None = None) -> int` — argparse + DB connect + fetch + call
  `run_walk_forward` + write JSON + exit code (0 success, 1 error; no gate).

- [ ] **Step 1: Write the failing test (argparse wiring only, no live DB)**

```python
from scripts.analysis.portfolio_covariance_weighting_diagnostic import main


def test_main_requires_symbols_argument():
    with pytest.raises(SystemExit) as exc_info:
        main([])
    assert exc_info.value.code == 2  # argparse's own usage-error exit code
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/scripts/test_portfolio_covariance_weighting_diagnostic.py -v -k test_main_requires_symbols_argument`
Expected: FAIL — `main` not defined.

- [ ] **Step 3: Implement**

Add to `scripts/analysis/portfolio_covariance_weighting_diagnostic.py`, at the end (after
`_apply_coverage_filter`):

```python
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Shadow-mode diagnostic: does cross-instrument covariance-aware portfolio weighting "
            "beat naive/IC-proportional/volatility-normalized baselines, walk-forward? Measurement "
            "tool only -- no --gate, no pass/fail exit code. Exit codes: 0=ran, 1=error."
        ),
    )
    parser.add_argument("--symbols", required=True, help="Comma-separated symbol list.")
    parser.add_argument("--tf", default=_TIMEFRAME)
    parser.add_argument("--weight-version", required=True, help="alpha_events.weight_version to read.")
    parser.add_argument("--start", default="2018-01-01", help="Window start (inclusive).")
    parser.add_argument("--end", default="2026-09-02", help="Window end (inclusive).")
    parser.add_argument("--regime-factor-symbol", default="SPY")
    parser.add_argument("--json-out", type=Path, help="Write the full result structure as JSON.")
    args = parser.parse_args(argv)

    status = "success"
    try:
        symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
        settings = Settings()
        conn = psycopg.connect(settings.database_url)
        conn.autocommit = True
        try:
            end_exclusive = (date.fromisoformat(args.end) + timedelta(days=1)).isoformat()

            close_wide = _fetch_daily_closes(conn, symbols, args.start, end_exclusive)
            if close_wide.empty:
                print("FAILED: no daily bars found for the requested symbols/window.", file=sys.stderr)
                status = "failure"
                return 1
            close_filtered, dropped = _apply_coverage_filter(close_wide)
            _logger.info(
                "portfolio_covariance_weighting_diagnostic.coverage_filter",
                n_population=len(symbols),
                n_retained=close_filtered.shape[1],
                dropped_symbols=dropped,
            )
            retained_symbols = sorted(close_filtered.columns.tolist())

            alpha_wide = _fetch_alpha_scores(
                conn, retained_symbols, args.tf, args.weight_version, args.start, end_exclusive
            )
            fwd_wide = _fetch_forward_returns(conn, retained_symbols, args.tf, args.start, end_exclusive)
            cost_hurdle_wide = _fetch_cost_hurdle(
                conn, retained_symbols, args.tf, args.weight_version, args.start, end_exclusive
            )
            spy_close_wide = _fetch_daily_closes(conn, [args.regime_factor_symbol], args.start, end_exclusive)
            if spy_close_wide.empty:
                print(f"FAILED: no bars for regime-factor symbol {args.regime_factor_symbol}.", file=sys.stderr)
                status = "failure"
                return 1
            spy_close = spy_close_wide[args.regime_factor_symbol]

            report = run_walk_forward(close_filtered, alpha_wide, fwd_wide, cost_hurdle_wide, spy_close)
            report["cohort"] = {
                "n_population": len(symbols),
                "n_retained": len(retained_symbols),
                "dropped_symbols": dropped,
                "retained_symbols": retained_symbols,
            }
            report["window"] = {"start": args.start, "end": args.end}
            report["caveats"] = [
                "Universe membership conditioned on Gate B passing over this same measurement "
                "period is itself a selection effect -- these numbers are conditional on the "
                "Gate-B-selected universe, not evidence this method would discover these "
                "instruments from an unfiltered pool.",
                "IC is measured as Spearman rank correlation, used as a linear mu-scaling "
                "coefficient -- a heuristic, not an exact Pearson-slope calibration.",
                "Sample size at this instrument count is likely powered for a directional read "
                "only, not a p<0.05 verdict.",
            ]

            print(
                f"Rebalance steps: {report['n_rebalance_steps']}, "
                f"mean_variance ridge-fallback count: {report['mean_variance_fallback_count']}"
            )
            for arm, arm_report in report["arms"].items():
                agg = arm_report["aggregate"]["unconditional"]
                print(
                    f"  {arm}: n={agg['n']} mean_realized_return={agg['mean_realized_return']:.6f} "
                    f"mean_net_realized_return={agg['mean_net_realized_return']:.6f} "
                    f"mean_turnover={agg['mean_turnover']:.4f} mean_effective_n={agg['mean_effective_n']:.2f}"
                )

            if args.json_out:
                args.json_out.write_text(json.dumps(report, indent=2, default=str))

            return 0
        finally:
            conn.close()
    except Exception as error:
        status = "failure"
        _logger.error("portfolio_covariance_weighting_diagnostic.failed", error=str(error))
        print(f"FAILED: {error}", file=sys.stderr)
        return 1
    finally:
        JOB_COMPLETED_TOTAL.add(1, {"job": _JOB_NAME, "status": status})
        flush_and_shutdown_metrics()


if __name__ == "__main__":
    from src.observability.otel import OTelInitError, init_otel_providers

    try:
        init_otel_providers(_JOB_NAME)
    except OTelInitError as error:
        print(f"[warn] OTel init failed -- metrics disabled: {error}")
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/scripts/test_portfolio_covariance_weighting_diagnostic.py -v -k test_main_requires_symbols_argument`
Expected: PASS

- [ ] **Step 5: Run the full test suite for this file**

Run: `.venv/bin/pytest tests/unit/scripts/test_portfolio_covariance_weighting_diagnostic.py -v`
Expected: PASS (all tests from Tasks 1-8)

- [ ] **Step 6: Lint and format**

Run: `.venv/bin/ruff check scripts/analysis/portfolio_covariance_weighting_diagnostic.py tests/unit/scripts/test_portfolio_covariance_weighting_diagnostic.py --fix && .venv/bin/black scripts/analysis/portfolio_covariance_weighting_diagnostic.py tests/unit/scripts/test_portfolio_covariance_weighting_diagnostic.py`
Expected: clean, no errors.

- [ ] **Step 7: Commit**

```bash
git add scripts/analysis/portfolio_covariance_weighting_diagnostic.py tests/unit/scripts/test_portfolio_covariance_weighting_diagnostic.py
git commit -m "feat(diagnostic): CLI, JSON report, main() entrypoint"
```

---

### Task 9: Full unit suite + self-review pass

**Files:**
- Modify (if gaps found): `scripts/analysis/portfolio_covariance_weighting_diagnostic.py`,
  `tests/unit/scripts/test_portfolio_covariance_weighting_diagnostic.py`

- [ ] **Step 1: Run the complete project unit suite to confirm no regressions**

Run: `.venv/bin/pytest tests/unit/ -q`
Expected: all green, including the new file's ~25 tests.

- [ ] **Step 2: Re-read the spec's Method/Output/Comparison-arms sections against the implementation**

Confirm each spec requirement maps to code:
- Two distinct return series never conflated: `log_returns`/`instrument_covariance` only ever
  consume `close_wide`; `fwd_return_wide` only ever feeds `_fetch_forward_returns` →
  `run_walk_forward`'s IC/scoring paths. Grep to confirm no cross-contamination:
  `grep -n "fwd_return_wide\|fwd_wide" scripts/analysis/portfolio_covariance_weighting_diagnostic.py`
  — every hit should be in `_fetch_forward_returns`, `run_walk_forward`'s IC-measurement and
  `realized` scoring lines, `main()`'s fetch/pass-through, and the test file. None should appear
  inside `log_returns`/`instrument_covariance`.
- Embargo enforced: `run_walk_forward`'s refit block always slices via
  `dates[pos - _EMBARGO_BARS]` (`embargo_boundary`), never `dates[pos]` directly, for both the
  covariance history slice and the IC-measurement history slice.
- Four arms present in every report: `_ARM_FUNCS` tuple length 4, `run_walk_forward`'s per-step
  loop iterates all of them unconditionally.
- Turnover, cost, and gross/net exposure reported per step, not just gross return: confirm
  `steps_by_arm[...].append({...})` includes `turnover`, `cost`, `realized_return`,
  `net_realized_return`, `gross_exposure`, `net_exposure`, `effective_n` — all seven keys, per the
  Output section's explicit "gross and cost-adjusted net return" requirement (`alpha_events.cost_hurdle`
  as the per-instrument cost proxy — fetched via `_fetch_cost_hurdle`, threaded through
  `run_walk_forward`'s `cost_hurdle_wide` parameter).
- Regime split uses the causal proxy, not `market_regimes`: `grep -n "market_regimes"
  scripts/analysis/portfolio_covariance_weighting_diagnostic.py` must return zero hits.
- No `--gate` flag: `grep -n "add_argument.*gate" scripts/analysis/portfolio_covariance_weighting_diagnostic.py`
  must return zero hits.
- Gate-B selection-lookahead caveat surfaces in the report: confirm `report["caveats"]` in
  `main()` includes it (already written in Task 8 — verify it wasn't dropped).

If any gap is found, fix it inline now rather than filing a follow-up — this is the plan's own
self-review loop, matching writing-plans' "Self-Review" step.

- [ ] **Step 3: Commit any fixes found during self-review**

```bash
git add scripts/analysis/portfolio_covariance_weighting_diagnostic.py tests/unit/scripts/test_portfolio_covariance_weighting_diagnostic.py
git commit -m "fix(diagnostic): self-review fixes against spec"
```

(Skip this step if the self-review found no gaps.)

---

## Prerequisites before this script produces real numbers

This plan builds and unit-tests the diagnostic against synthetic data only — per the spec, Gate A
(`scripts/analysis/universe_expansion_correlation_structure_check.py --symbols GLD,DBA,DBB,DBC,URA,TLT,UUP,VIXY,EMLC,HYG,XOM,DHI,PGR --gate`)
and Gate B (per-instrument IC via `ic_engine`) must both run first, and `alpha_events` must have a
populated `weight_version` for the 13-symbol candidate list, before `main()` can be run against the
live DB and produce a real report. Building/testing this script does not depend on either gate having
passed.
