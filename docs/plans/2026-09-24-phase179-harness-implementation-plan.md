# Phase 179 walk-forward harness (build step 5) implementation plan

**Author:** Claude (Opus 5.5), 2026-09-24.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the S0-S4 walk-forward harness that turns the production ensemble method, refitted yearly on point-in-time data, into a pre-registered `SLEEVE_VERDICT` for the 13-symbol cross-asset sleeve, plus the synthetic V2/V3 calibration runs.

**Architecture:** A package under `scripts/analysis/sleeve_walk_forward/`, one module per DAG node. S0 is the only node that touches Postgres (read-only) and writes content-hashed `.npz` files; S1-S4 are pure functions over those arrays. Every statistical step calls production code (`ic_engine` cell functions, `stratum_fit`, `ensemble.shrinkage`, `portfolio.weighting`, `statistics.panel_null`); the harness adds orchestration only. S3's portfolio engine is vectorized numpy and is proven equal to a slow reference loop built directly on `weighting.py`.

**Tech stack:** Python 3.12, numpy, pandas (S0 assembly and the reference engine only), scipy, asyncpg (S0), `concurrent.futures.ProcessPoolExecutor` (S1 refits, S3 shift chunks), pytest.

**Spec:** `docs/plans/2026-09-24-phase179-sleeve-walk-forward-prereg.md` (DRAFT). Read sections 3-10, 13 and 15 before any task.

## Global constraints

- The harness never writes a production table. S0 opens its connection with `default_transaction_read_only = on` (spec 4.1).
- Bound: every S0 row has `bar_ts < alpha.validation.oos_start` (2025-12-24T05:15Z); S0 asserts it and raises otherwise (spec 5, V6).
- Refit dates: first NYSE session of each year 2011-2025, 15 refits. Training rows from 2007 on. Label exit for scale h must fall on or before the session 5 sessions before T_k (spec 6).
- 1d scales: `alpha.ic.lookahead.1d.{fast,mid,slow,extended}` = 1, 2, 5, 10, read from the S0 APR snapshot, never hardcoded.
- Composite: `alpha = X @ (w * ic_sign)`, NULL feature = 0 (spec 3).
- Execution: alpha at D's close, return `ln(open[D+2]/open[D+1])` (spec 3).
- Portfolio: arms `ic_proportional`, `vol_normalized`, `mean_variance`; gross 1; 504-session warmup; covariance admission 95% coverage; calibration 95% coverage else IC 0 (spec 3).
- Null: whole-panel circular shifts, `min_shift = 63`, all admissible shifts for the real run; Westfall-Young across the three arms (spec 7, `panel_null.py`).
- Decision: arm qualifies iff adjusted p < 0.05 and positive excess in >= 2 of 3 sub-periods (2013-2016, 2017-2020, 2021-2025); ACT needs adjusted p < 0.05/15 plus positive holdout sign (spec 8).
- Pre-registered constants live in one frozen dataclass in `config.py`; they are APR-exempt (spec 4.4). Production parameters come only from the S0 APR snapshot.
- No results are computed on real data in this build step. S0 code is built and integration-tested on a tiny slice; the real snapshot is step 6.
- Workers are compute-only and return arrays; no worker opens a DB connection (CLAUDE.md).
- Exception variable name is `error`; timestamps UTC; structlog logging via `setup_service_logging`; no per-row logging in loops.
- Commits carry no AI attribution (user global rule).

## Spec amendments this plan pins

Reading the reused code while writing this plan found four places where the pre-registration's
text doesn't match what production does. Task 0 folds these into the pre-registration (still a
DRAFT, so this is allowed and needs no methodology-ledger entry).

- **A1. All four regime groups' pooled cells are computed.** Production's meta-FDR denominator
  (`ensemble_trainer._meta_eligible`, grouped by `(feature_name, tf)` across every pooled
  regime label) and the pooled part of the BH family include the rates, commodity and fx groups'
  pooled 1d cells. S1 computes pooled 1d cells for every enabled group, routed by
  `ic_engine._build_symbol_regime_class`; only equity strata get weights. Without this the
  meta-FDR gate would be a different rule.
- **A2. Shrinkage prior scope (new deviation D7).** `ops_ic_shrinkage.compute_shrinkage_updates`
  buckets rows by `(concept group_name, regime, tf)` across per-symbol and pooled rows alike. For
  equity labels at 1d, the bucket is ~99% per-symbol rows (e.g. `high_bear`: 143,100 per-symbol
  vs 1,160 pooled). The harness computes pooled cells only, so its prior comes from pooled rows.
  Sized by gate V4b (step 6, after the 178 recompute): on production's stored rows at
  T = 2025-12-24, run selection and the stratum fit twice, once with production's `ic_shrunk`
  and once with the pooled-only prior. If any equity stratum's selected feature set differs,
  add a per-symbol 1d pass to S1 before freezing.
- **A3. Null shift span.** Section 7's "about 3,120 shifts" counted the trading span. The shifted
  object is the whole S2 alpha panel (2011-01 to 2025-12-23, about 3,750 sessions), since the
  2011-2012 warmup feeds calibration and standardization; about 3,620 admissible shifts.
- **A4. S0 also fetches sleeve closes.** The instrument covariance uses realized close-to-close
  log returns (`weighting.py` docstring); section 5 listed opens only.

Two build choices, not deviations: S3 is vectorized numpy first and numba only if the measured
per-shift cost projects past 24 hours (spec 4.3 allows the design to be revisited, never the null
thinned); instrument calibration refits every 252 sessions (the diagnostic's
`_REFIT_EVERY_BARS`, which the spec inherits by reference in section 3).

## Review focus

1. **A training row whose label exits inside the embargo.** Expected: excluded from that scale
   (`complete_mat[t, scale] = False`) and counted; V6 assert fires if any slips through. Pinned
   in Task 7.
2. **A sleeve symbol with no alpha on a day (NaN stratum or missing features).** Expected: no
   position that day, counted per year, not a zero-filled signal that the standardizer treats as
   information. Pinned in Tasks 2 and 6.
3. **A refit where an equity stratum has fewer than `min_passing_features` features.** Expected:
   stratum skipped with a reason recorded, days in that stratum get NaN alpha, never a crash and
   never a silent fallback to another stratum's weights. Pinned in Tasks 6 and 7.
4. **Any arm's null Sharpe constant across shifts (e.g. all-cash when every symbol fails
   admission).** Expected: `westfall_young_adjusted_p` raises; the harness reports FIDELITY
   BROKEN instead of a token. Pinned in Task 4.
5. **Two runs on the same inputs.** Expected: bit-identical S1 weights and S3 statistics (per-cell
   RNG seeded from refit date and cell key). Pinned in Tasks 3 and 7.

---

## File structure

```
scripts/analysis/sleeve_walk_forward/
  __init__.py
  config.py          frozen pre-registered constants (HarnessConfig)
  sessions.py        NYSE session axis helpers: refit dates, purge cutoffs, sub-periods
  results.py         shared frozen dataclasses: Snapshot, GroupArrays, StratumWeights, RefitOutput
  snapshot.py        S0: read-only fetch -> content-hashed .npz + manifest
  refit.py           S1: one refit -> stratum weights (pure; calls production cell code)
  score.py           S2: weights + features + labels -> date x symbol alpha panel
  portfolio.py       S3 core: vectorized arm returns for one alpha panel
  evaluate.py        S3: real + shifted runs, Sharpe, WY p, excess, stability, bootstrap CI
  verdict.py         S4: decision rules -> token dict
  synthetic.py       synthetic panels for V2/V3
  run.py             CLI: --stage s0|s1|s2|s3|s4|v2|v3, content-hash file passing
tests/unit/sleeve_walk_forward/
  test_config.py test_sessions.py test_portfolio.py test_evaluate.py test_verdict.py
  test_synthetic.py test_score.py test_refit.py
tests/integration/test_sleeve_walk_forward_snapshot.py
```

Each module has one job, matching one DAG node; `portfolio.py` is split from `evaluate.py`
because it is the hot loop that runs about 3,620 times and gets its own equivalence test.

---

### Task 0: Fold amendments A1-A4 into the pre-registration

**Files:**
- Modify: `docs/plans/2026-09-24-phase179-sleeve-walk-forward-prereg.md` (sections 4.2, 5, 7, 13)

- [ ] **Step 1:** Section 4.2 reuse map, IC shrinkage row: add "Prior bucket built from the refit's pooled rows only (D7)". Pooled IC row: add "for every enabled regime group (A1); only equity strata are weighted".
- [ ] **Step 2:** Section 5: add a bullet "1d closes for the 13 sleeve symbols (covariance input)".
- [ ] **Step 3:** Section 7: replace "There are about 3,120 admissible shifts, which puts the p-value resolution near 0.0003" with "The shifted panel is the whole S2 alpha panel (2011-01 through 2025-12-23, about 3,750 sessions), since the warmup years feed calibration; about 3,620 admissible shifts, p-value resolution near 0.0003".
- [ ] **Step 4:** Section 13: add row `| D7 | IC shrinkage prior from pooled rows only | Production's bucket mixes per-symbol rows (~99% of an equity label's bucket at 1d); a per-symbol pass per refit is ~15x the IC compute | V4b: selection and weights under both priors at T = 2025-12-24; any selected-set difference adds a per-symbol pass before freezing |`. Add V4b to the section 10 table with the same text.
- [ ] **Step 5:** Commit: `git commit -m "docs(179): pre-reg amendments A1-A4 from harness planning (all-group pooled cells, D7 shrinkage prior, shift span, closes)"`

### Task 1: Package skeleton, config and calendar

**Files:**
- Create: `scripts/analysis/sleeve_walk_forward/__init__.py` (empty), `config.py`, `sessions.py`
- Test: `tests/unit/sleeve_walk_forward/__init__.py` (empty), `test_config.py`, `test_sessions.py`

**Interfaces:**
- Produces: `HarnessConfig` (frozen dataclass, fields below), `DEFAULT_CONFIG`; `refit_dates(sessions: np.ndarray, years: range) -> list[np.datetime64]`; `label_cutoff(sessions: np.ndarray, refit: np.datetime64, embargo: int) -> int` (index of the last session a label exit may fall on); `sub_period_masks(dates: np.ndarray, periods: tuple[tuple[str, str], ...]) -> list[np.ndarray]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/sleeve_walk_forward/test_config.py
import dataclasses

import pytest

from scripts.analysis.sleeve_walk_forward.config import DEFAULT_CONFIG


def test_config_is_frozen():
    with pytest.raises(dataclasses.FrozenInstanceError):
        DEFAULT_CONFIG.min_shift = 1  # type: ignore[misc]


def test_pinned_values_match_prereg():
    c = DEFAULT_CONFIG
    assert c.sleeve == ("GLD", "DBA", "DBB", "DBC", "URA", "TLT", "UUP", "VIXY", "EMLC", "HYG", "XOM", "DHI", "PGR")
    assert c.refit_years == range(2011, 2026)
    assert c.training_start == "2007-01-01"
    assert c.embargo_sessions == 5
    assert c.min_shift == 63
    assert c.warmup_sessions == 504
    assert c.calibration_refit_sessions == 252
    assert c.coverage_fraction == 0.95
    assert c.trading_start == "2013-01-01"
    assert c.sub_periods == (("2013-01-01", "2016-12-31"), ("2017-01-01", "2020-12-31"), ("2021-01-01", "2025-12-23"))
    assert c.alpha == 0.05 and c.n_tested == 15
    assert c.min_positive_sub_periods == 2
    assert c.bootstrap_mean_block == 21
    assert c.regime_group_weighted == "equity"
```

```python
# tests/unit/sleeve_walk_forward/test_sessions.py
import numpy as np
import pytest

from scripts.analysis.sleeve_walk_forward.sessions import label_cutoff, refit_dates, sub_period_masks


def _sessions(*days):
    return np.array(days, dtype="datetime64[D]")


def test_refit_dates_are_first_session_of_each_year():
    s = _sessions("2010-12-30", "2010-12-31", "2011-01-03", "2011-01-04", "2012-01-03")
    assert refit_dates(s, range(2011, 2013)) == [np.datetime64("2011-01-03"), np.datetime64("2012-01-03")]


def test_refit_dates_missing_year_raises():
    with pytest.raises(ValueError, match="2012"):
        refit_dates(_sessions("2011-01-03"), range(2011, 2013))


def test_label_cutoff_is_five_sessions_before_refit():
    s = np.arange(np.datetime64("2011-01-03"), np.datetime64("2011-01-20"))
    refit = np.datetime64("2011-01-17")
    idx = label_cutoff(s, refit, embargo=5)
    assert s[idx] == np.datetime64("2011-01-12")


def test_sub_period_masks_partition_inclusive():
    d = _sessions("2016-12-30", "2017-01-03", "2020-12-31", "2021-01-04")
    m = sub_period_masks(d, (("2013-01-01", "2016-12-31"), ("2017-01-01", "2020-12-31"), ("2021-01-01", "2025-12-23")))
    assert [x.tolist() for x in m] == [[True, False, False, False], [False, True, True, False], [False, False, False, True]]
```

- [ ] **Step 2: Run to verify failure.** `.venv/bin/pytest tests/unit/sleeve_walk_forward -q` -> collection error (module missing).

- [ ] **Step 3: Implement**

```python
# scripts/analysis/sleeve_walk_forward/config.py
"""Pre-registered constants for the Phase 179 walk-forward
(docs/plans/2026-09-24-phase179-sleeve-walk-forward-prereg.md). APR-exempt: these are test
parameters fixed before any out-of-sample number exists; changing one is a methodology change."""

from __future__ import annotations

import dataclasses


@dataclasses.dataclass(frozen=True)
class HarnessConfig:
    sleeve: tuple[str, ...] = ("GLD", "DBA", "DBB", "DBC", "URA", "TLT", "UUP", "VIXY", "EMLC", "HYG", "XOM", "DHI", "PGR")
    refit_years: range = range(2011, 2026)
    training_start: str = "2007-01-01"
    embargo_sessions: int = 5
    min_shift: int = 63
    warmup_sessions: int = 504
    calibration_refit_sessions: int = 252
    coverage_fraction: float = 0.95
    trading_start: str = "2013-01-01"
    sub_periods: tuple[tuple[str, str], ...] = (
        ("2013-01-01", "2016-12-31"),
        ("2017-01-01", "2020-12-31"),
        ("2021-01-01", "2025-12-23"),
    )
    alpha: float = 0.05
    n_tested: int = 15
    min_positive_sub_periods: int = 2
    bootstrap_mean_block: int = 21
    bootstrap_reps: int = 2000
    regime_group_weighted: str = "equity"
    ic_shrinkage_k_key: str = "alpha.ic.shrinkage_k"
    mv_condition_max_key: str = "alpha.ensemble.mv_condition_max"
    ridge_epsilon_fraction: float = 0.10
    seed: int = 179


DEFAULT_CONFIG = HarnessConfig()
```

```python
# scripts/analysis/sleeve_walk_forward/sessions.py
"""Session-axis helpers. `sessions` is always the sorted NYSE session array (datetime64[D])
taken from the SPY 1d bar dates in the S0 snapshot."""

from __future__ import annotations

import numpy as np


def refit_dates(sessions: np.ndarray, years: range) -> list[np.datetime64]:
    out = []
    for year in years:
        in_year = sessions[(sessions >= np.datetime64(f"{year}-01-01")) & (sessions < np.datetime64(f"{year + 1}-01-01"))]
        if len(in_year) == 0:
            raise ValueError(f"no session in {year}")
        out.append(in_year[0])
    return out


def label_cutoff(sessions: np.ndarray, refit: np.datetime64, embargo: int) -> int:
    """Index of the last session a training label's exit may fall on: `embargo` sessions
    before the refit date."""
    pos = int(np.searchsorted(sessions, refit))
    if pos >= len(sessions) or sessions[pos] != refit:
        raise ValueError(f"refit date {refit} is not a session")
    if pos - embargo < 0:
        raise ValueError(f"refit date {refit} has fewer than {embargo} prior sessions")
    return pos - embargo


def sub_period_masks(dates: np.ndarray, periods: tuple[tuple[str, str], ...]) -> list[np.ndarray]:
    return [(dates >= np.datetime64(a)) & (dates <= np.datetime64(b)) for a, b in periods]
```

- [ ] **Step 4:** `.venv/bin/pytest tests/unit/sleeve_walk_forward -q` -> all pass.
- [ ] **Step 5:** Commit `feat(179): harness package skeleton, pinned config, session calendar helpers`.

### Task 2: Portfolio engine (S3 core) with a reference implementation

**Files:**
- Create: `scripts/analysis/sleeve_walk_forward/portfolio.py`
- Test: `tests/unit/sleeve_walk_forward/test_portfolio.py` (contains the slow reference)

**Interfaces:**
- Consumes: `weighting.instrument_covariance`, `shrink_instrument_ic`, `compute_mu`, `ic_proportional_arm`, `vol_normalized_arm`, `mean_variance_arm`; `HarnessConfig`.
- Produces:
  - `CovariancePlan` (frozen dataclass): `refit_positions: np.ndarray` (int, session index of each calibration refit), `symbol_idx: list[np.ndarray]` (admitted column indices per refit), `cov: list[np.ndarray]`, `sigma: list[np.ndarray]`, `mv_solve: list[np.ndarray | None]` (precomputed `Sigma^-1` when `mean_variance_weights` accepts it, else `None`), `mv_method: list[str]`.
  - `plan_covariance(closes: np.ndarray, cfg: HarnessConfig, mv_condition_max: float) -> CovariancePlan`: depends on returns only, computed once and shared by the real run and every shift.
  - `arm_returns(alpha: np.ndarray, fwd_ret: np.ndarray, plan: CovariancePlan, cfg: HarnessConfig, ic_shrinkage_k: float) -> dict[str, np.ndarray]`: `alpha`, `fwd_ret` are `[n_sessions, n_symbols]` float64 (NaN = no alpha / no return); returns per-arm daily gross return arrays of length `n_sessions` (NaN before the first calibration refit).

Semantics (pinned, and what the reference implements):
- Calibration refit at session index `p` for every `p >= warmup_sessions` with `(p - warmup_sessions) % calibration_refit_sessions == 0`, using data through `p - 2` (diagnostic `_EMBARGO_BARS = 2`): covariance from the trailing 504 close-to-close log returns (`instrument_covariance`, 95% coverage); per admitted symbol, raw IC = Spearman of its standardized alpha (trailing 504 through `p-2`) against `fwd_ret` over the same rows, IC 0 when paired rows cover < 95% of the 504, `n_eff` = paired count; shrink with `shrink_instrument_ic(k)`.
- Each day `d` from the first refit on: `z_i` = last value of `standardize_scores(alpha[:d+1, i] trailing 504)`; symbols with NaN alpha on `d` get `z = 0` and are counted in `no_alpha_days`. `mu = compute_mu(ic, sigma, z)`; weights per arm; return `sum_i w_i * fwd_ret[d, i]` with NaN returns counted as 0 exposure (weight dropped, reported).
- `mean_variance` uses `plan.mv_solve[k] @ mu` normalized by abs sum when not `None`, else `mean_variance_arm` with ridge fallback (identical to calling `mean_variance_arm` each day, since the condition check depends only on `cov`).

- [ ] **Step 1: Write the failing tests.** The reference is a straight loop over days calling `weighting.py` exactly as the semantics above say (pandas, slow, obviously correct):

```python
# tests/unit/sleeve_walk_forward/test_portfolio.py
import numpy as np
import pandas as pd
import pytest
from scipy.stats import spearmanr

from scripts.analysis.sleeve_walk_forward.config import HarnessConfig
from scripts.analysis.sleeve_walk_forward.portfolio import arm_returns, plan_covariance
from src.intelligence.portfolio import weighting as W

CFG = HarnessConfig(warmup_sessions=60, calibration_refit_sessions=30)
MV_COND = 1000.0
K = 100.0


def _panel(seed, n=200, m=5, nan_frac=0.02):
    rng = np.random.default_rng(seed)
    closes = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, (n, m)), axis=0))
    alpha = rng.normal(size=(n, m))
    fwd = rng.normal(0, 0.01, (n, m))
    alpha[rng.random((n, m)) < nan_frac] = np.nan
    fwd[rng.random((n, m)) < nan_frac] = np.nan
    return closes, alpha, fwd


def reference(closes, alpha, fwd, cfg=CFG):
    n, m = alpha.shape
    rets = W.log_returns(pd.DataFrame(closes))
    rets.index = range(1, n)
    a = pd.DataFrame(alpha)
    out = {arm: np.full(n, np.nan) for arm in ("ic_proportional", "vol_normalized", "mean_variance")}
    state = None
    for d in range(n):
        if d >= cfg.warmup_sessions and (d - cfg.warmup_sessions) % cfg.calibration_refit_sessions == 0:
            b = d - 2
            hist = rets.loc[:b].tail(cfg.warmup_sessions)
            cov, syms = W.instrument_covariance(hist, min_coverage_fraction=cfg.coverage_fraction)
            if len(syms) >= 2:
                ic_raw, n_eff = [], []
                for s in syms:
                    z = W.standardize_scores(a[s].loc[:b].tail(cfg.warmup_sessions))
                    f = pd.Series(fwd[:, s]).loc[:b].tail(cfg.warmup_sessions)
                    p = pd.concat([z, f], axis=1).dropna()
                    ok = len(p) >= cfg.coverage_fraction * cfg.warmup_sessions
                    r = spearmanr(p.iloc[:, 0], p.iloc[:, 1])[0] if ok else 0.0
                    ic_raw.append(0.0 if not np.isfinite(r) else float(r))
                    n_eff.append(float(len(p)))
                ic = W.shrink_instrument_ic(np.array(ic_raw), np.array(n_eff), K)
                state = (cov, list(syms), ic)
        if state is None:
            continue
        cov, syms, ic = state
        sigma = np.sqrt(np.maximum(np.diag(cov), 1e-12))
        z = np.array([W.standardize_scores(a[s].loc[:d].tail(cfg.warmup_sessions)).iloc[-1] if np.isfinite(alpha[d, s]) else 0.0 for s in syms])
        mu = W.compute_mu(ic, sigma, z)
        r = np.nan_to_num(fwd[d, syms])
        out["ic_proportional"][d] = W.ic_proportional_arm(mu) @ r
        out["vol_normalized"][d] = W.vol_normalized_arm(mu, sigma) @ r
        w, _m, _c = W.mean_variance_arm(cov, mu, MV_COND, ridge_epsilon_fraction=CFG.ridge_epsilon_fraction)
        out["mean_variance"][d] = w @ r
    return out


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_engine_matches_reference(seed):
    closes, alpha, fwd = _panel(seed)
    plan = plan_covariance(closes, CFG, MV_COND)
    got = arm_returns(alpha, fwd, plan, CFG, K)
    want = reference(closes, alpha, fwd)
    for arm in want:
        np.testing.assert_allclose(got[arm], want[arm], rtol=1e-9, atol=1e-12, equal_nan=True)


def test_symbol_without_alpha_takes_no_signal_position():
    closes, alpha, fwd = _panel(3, nan_frac=0.0)
    alpha[:, 2] = np.nan
    plan = plan_covariance(closes, CFG, MV_COND)
    got = arm_returns(alpha, fwd, plan, CFG, K)
    want = reference(closes, alpha, fwd)
    np.testing.assert_allclose(got["vol_normalized"], want["vol_normalized"], rtol=1e-9, equal_nan=True)


def test_plan_is_shared_across_shifts():
    closes, alpha, fwd = _panel(4)
    plan = plan_covariance(closes, CFG, MV_COND)
    a1 = arm_returns(alpha, fwd, plan, CFG, K)
    a2 = arm_returns(np.roll(alpha, 70, axis=0), fwd, plan, CFG, K)
    assert not np.allclose(np.nan_to_num(a1["ic_proportional"]), np.nan_to_num(a2["ic_proportional"]))
```

- [ ] **Step 2:** Run -> fails on import.
- [ ] **Step 3: Implement `portfolio.py`.** Vectorize the two expensive pieces: (a) trailing standardization via cumulative sums over a 504 window per column, NaN-aware (count, sum, sum of squares of finite values; `std(ddof=0)`; zero-variance -> 0 per `standardize_scores`); the day-`d` z is `(alpha[d] - mean_d) / std_d` over the trailing window ending at `d`; (b) per-refit Spearman via `scipy.stats.rankdata` on the paired rows. Everything else is per-refit matrix work: for each refit block `[p_k, p_{k+1})`, `mu = ic * sigma * z[block][:, idx]`, arms computed row-wise with numpy (`abs().sum(axis=1)` normalization; zero-sum rows -> zero weights as `normalize_by_abs_sum`). `plan_covariance` calls `instrument_covariance` and `mean_variance_weights` once per refit and stores `Sigma^-1` or `None`. Keep the module under 200 lines; no numba.
- [ ] **Step 4:** Run the tests; all pass at `rtol=1e-9`. If the cumulative-sum standardization drifts past tolerance, recentre each window (subtract the window's first finite value) before summing; do not loosen the tolerance.
- [ ] **Step 5:** Time one call on a 3,750 x 13 panel (`python -m timeit`) and write the number in the commit body.
- [ ] **Step 6:** Commit `feat(179): vectorized portfolio engine, proven equal to a weighting.py reference loop`.

### Task 3: Evaluation (S3): real run, shift null, statistics

**Files:**
- Create: `scripts/analysis/sleeve_walk_forward/evaluate.py`
- Test: `tests/unit/sleeve_walk_forward/test_evaluate.py`

**Interfaces:**
- Consumes: `portfolio.plan_covariance`, `portfolio.arm_returns`; `panel_null.admissible_shifts`, `shift_panel`, `westfall_young_adjusted_p`; `sessions.sub_period_masks`.
- Produces:
  - `annualized_sharpe(r: np.ndarray, mask: np.ndarray) -> float` (mean/std ddof=1 over finite `r[mask]`, times sqrt(252); raises on fewer than 2 finite values or zero std).
  - `EvaluationResult` (frozen dataclass): `arms: tuple[str, ...]`, `sharpe_obs: np.ndarray [J]`, `sharpe_null: np.ndarray [K, J]`, `shifts: np.ndarray [K]`, `adjusted_p: np.ndarray [J]`, `excess: np.ndarray [J]` (obs minus null median), `sub_period_excess: np.ndarray [J, 3]` (mean daily excess return over each arm's null-median daily return, per sub-period), `excess_ci: np.ndarray [J, 2]`.
  - `evaluate(alpha, fwd_ret, closes, dates, cfg, *, mv_condition_max, ic_shrinkage_k, shifts=None, workers=1) -> EvaluationResult`. `shifts=None` means every admissible shift (the real run); V2/V3 pass a subsample. Shift chunks run in a `ProcessPoolExecutor` when `workers > 1`; the covariance plan is built once in the parent and passed to workers.
- Trading mask: `dates >= cfg.trading_start` for every Sharpe and excess figure.
- "Null-median daily return" for sub-period excess: the per-day median across shifts of each arm's daily return, then `mean(r_obs - r_null_median)` within each sub-period mask.
- Excess CI: stationary bootstrap (Politis-Romano, mean block `cfg.bootstrap_mean_block`, `cfg.bootstrap_reps` reps, seed `cfg.seed`) of the Sharpe of `r_obs - r_null_median`, 2.5/97.5 percentiles. Reported only.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/sleeve_walk_forward/test_evaluate.py
import numpy as np
import pytest

from scripts.analysis.sleeve_walk_forward.config import HarnessConfig
from scripts.analysis.sleeve_walk_forward.evaluate import annualized_sharpe, evaluate

CFG = HarnessConfig(warmup_sessions=60, calibration_refit_sessions=30, min_shift=20,
                    trading_start="2000-06-01", sub_periods=(("2000-06-01", "2000-08-31"), ("2000-09-01", "2000-10-31"), ("2000-11-01", "2001-12-31")),
                    bootstrap_reps=200)


def _inputs(seed, signal=0.0, n=300, m=5):
    rng = np.random.default_rng(seed)
    closes = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, (n, m)), axis=0))
    fwd = rng.normal(0, 0.01, (n, m))
    alpha = signal * fwd / 0.01 + rng.normal(size=(n, m))
    dates = np.arange(np.datetime64("2000-01-03"), np.datetime64("2000-01-03") + n)
    return alpha, fwd, closes, dates


def test_sharpe_hand_computed():
    r = np.array([0.01, -0.01, 0.02, 0.0])
    want = r.mean() / r.std(ddof=1) * np.sqrt(252)
    assert annualized_sharpe(r, np.ones(4, bool)) == pytest.approx(want)


def test_sharpe_zero_variance_raises():
    with pytest.raises(ValueError):
        annualized_sharpe(np.zeros(5), np.ones(5, bool))


def test_real_run_uses_every_admissible_shift():
    alpha, fwd, closes, dates = _inputs(0)
    res = evaluate(alpha, fwd, closes, dates, CFG, mv_condition_max=1000.0, ic_shrinkage_k=100.0)
    assert res.shifts.tolist() == list(range(20, 300 - 20 + 1))
    assert res.sharpe_null.shape == (len(res.shifts), 3)


def test_deterministic():
    args = _inputs(1)
    a = evaluate(*args, CFG, mv_condition_max=1000.0, ic_shrinkage_k=100.0, shifts=np.arange(20, 60))
    b = evaluate(*args, CFG, mv_condition_max=1000.0, ic_shrinkage_k=100.0, shifts=np.arange(20, 60))
    np.testing.assert_array_equal(a.sharpe_null, b.sharpe_null)
    np.testing.assert_array_equal(a.excess_ci, b.excess_ci)


def test_parallel_equals_serial():
    args = _inputs(2)
    a = evaluate(*args, CFG, mv_condition_max=1000.0, ic_shrinkage_k=100.0, shifts=np.arange(20, 80))
    b = evaluate(*args, CFG, mv_condition_max=1000.0, ic_shrinkage_k=100.0, shifts=np.arange(20, 80), workers=3)
    np.testing.assert_array_equal(a.sharpe_null, b.sharpe_null)


def test_strong_signal_gets_small_p_and_positive_excess():
    res = evaluate(*_inputs(3, signal=0.5), CFG, mv_condition_max=1000.0, ic_shrinkage_k=100.0)
    assert (res.adjusted_p < 0.05).all()
    assert (res.excess > 0).all()
```

- [ ] **Step 2:** Run -> fails.
- [ ] **Step 3:** Implement `evaluate.py`: build the plan once; observed run; for each shift `k`, `arm_returns(shift_panel(alpha, k), fwd, plan, ...)`; collect `[K, J]` Sharpes and `[K, J, n]` daily returns only as a running per-day median (store `[K, n]` per arm as float32 in a memmap under the scratchpad when `K * n * J * 4` bytes exceeds 512 MB, else in RAM); WY via `westfall_young_adjusted_p`; sub-period excess; stationary bootstrap in a small private helper (no library dependency; indices by geometric block lengths with `rng = np.random.default_rng(cfg.seed)`).
- [ ] **Step 4:** Tests pass. Log (once per run, not per shift) the measured seconds per shift and the projection to the full admissible set.
- [ ] **Step 5:** Commit `feat(179): S3 evaluation, whole-panel shift null with Westfall-Young across arms`.

### Task 4: Verdict (S4)

**Files:**
- Create: `scripts/analysis/sleeve_walk_forward/verdict.py`
- Test: `tests/unit/sleeve_walk_forward/test_verdict.py`

**Interfaces:**
- Consumes: `EvaluationResult`, `HarnessConfig`.
- Produces: `decide(res: EvaluationResult, cfg: HarnessConfig, *, fidelity_ok: bool, holdout_excess: dict[str, float] | None = None) -> dict` with keys `sleeve_verdict` (`"ACT"|"PASS"|"FAIL"|None`), `fidelity` (`"OK"|"BROKEN"`), `qualifying_arms`, `act_arm`, `per_arm` (adjusted p, excess, sub-period excess, positive sub-period count, CI). `holdout_excess` is `None` before S5; then ACT candidates stay `"PASS"` with `act_pending_holdout = True`.
- Also `safe_evaluate(...)`: wraps `evaluate`; a `ValueError` from `westfall_young_adjusted_p` or `annualized_sharpe` becomes `fidelity = "BROKEN"` with the error text, never a token (Review focus 4).

- [ ] **Step 1: Write the failing tests** covering every row of spec section 8 with hand-built `EvaluationResult`s: FAIL (no arm < 0.05); FAIL (p < 0.05 but only 1 positive sub-period); PASS; ACT pending holdout (p < 0.05/15, holdout `None`) -> `PASS` with `act_pending_holdout`; ACT with positive holdout; ACT arm with negative holdout -> `PASS`; two ACT-level arms -> smallest adjusted p wins; `fidelity_ok=False` -> `sleeve_verdict None`, `fidelity "BROKEN"`; boundary p exactly 0.05 -> not qualifying (strict `<`).

```python
# tests/unit/sleeve_walk_forward/test_verdict.py (excerpt; write one test per case listed above)
import numpy as np

from scripts.analysis.sleeve_walk_forward.config import DEFAULT_CONFIG
from scripts.analysis.sleeve_walk_forward.evaluate import EvaluationResult
from scripts.analysis.sleeve_walk_forward.verdict import decide

ARMS = ("ic_proportional", "vol_normalized", "mean_variance")


def _res(p, sub):
    j = len(ARMS)
    return EvaluationResult(arms=ARMS, sharpe_obs=np.ones(j), sharpe_null=np.zeros((10, j)), shifts=np.arange(10),
                            adjusted_p=np.array(p), excess=np.ones(j), sub_period_excess=np.array(sub), excess_ci=np.zeros((j, 2)))


def test_pass_needs_two_positive_sub_periods():
    r = _res([0.01, 0.2, 0.2], [[1, -1, -1], [1, 1, 1], [1, 1, 1]])
    assert decide(r, DEFAULT_CONFIG, fidelity_ok=True)["sleeve_verdict"] == "FAIL"


def test_negative_holdout_downgrades_act_to_pass():
    r = _res([0.001, 0.2, 0.2], [[1, 1, -1], [1, 1, 1], [1, 1, 1]])
    out = decide(r, DEFAULT_CONFIG, fidelity_ok=True, holdout_excess={"ic_proportional": -0.1})
    assert out["sleeve_verdict"] == "PASS" and out["act_arm"] is None
```

- [ ] **Step 2-4:** Fail, implement (pure, ~60 lines), pass.
- [ ] **Step 5:** Commit `feat(179): S4 decision rules as pinned in pre-reg section 8`.

### Task 5: Synthetic panels and the V2/V3 runners

**Files:**
- Create: `scripts/analysis/sleeve_walk_forward/synthetic.py`
- Test: `tests/unit/sleeve_walk_forward/test_synthetic.py`

**Interfaces:**
- Produces: `synthetic_panel(seed: int, *, n: int, m: int, signal_ic: float, alpha_ar1: float, drift_sd: float, corr: float) -> tuple[alpha, fwd_ret, closes, dates]`: returns `r = drift_i + L @ eps` (equicorrelated `corr`, daily vol 1%, per-asset drift drawn once from `N(0, drift_sd)`), closes from cumulated `r`, `fwd_ret[d] = r[d+2]` (execution convention), and alpha an AR(1) (`alpha_ar1`) noise process plus `signal_ic`-scaled standardized `fwd_ret`. `n = 3750, m = 13` for V2/V3.
  - `run_v2(seeds: range, n_shifts: int, workers: int) -> dict` and `run_v3(target_irs: tuple[float, ...], seeds: range, n_shifts: int, workers: int) -> dict`: per seed, a random subsample of `n_shifts` admissible shifts (`np.random.default_rng(seed)`), `evaluate` + `decide(fidelity_ok=True)`; return the PASS rate and its binomial 95% CI. V3 first calibrates `signal_ic` per target IR by bisection on the mean realized excess IR of `vol_normalized` over 20 seeds, and reports the calibrated IC with the result.
- Persistent alpha (`alpha_ar1 = 0.98`) and nonzero drift (`drift_sd = 0.0003`) are on by default in V2: the null must stay calibrated when the signal is slow and assets drift (spec 1's drift argument), which is the case a naive shuffle null gets wrong.

- [ ] **Step 1: Failing tests:** shapes and dtypes; `fwd_ret[d] == r[d+2]` exactly; same seed -> identical arrays; with `signal_ic = 0`, a 10-seed x 49-shift smoke run of `run_v2` returns a PASS rate in [0, 0.5] (smoke only; the real V2 is 200 seeds and runs from `run.py`); with `signal_ic = 0.3`, the 10-seed smoke PASS rate is at least 0.8.
- [ ] **Step 2-4:** Fail, implement, pass. Mark the two smoke tests `@pytest.mark.slow` only if they exceed 30 s together.
- [ ] **Step 5:** Commit `feat(179): synthetic panels and V2/V3 runners`.

### Task 6: Scoring (S2)

**Files:**
- Create: `scripts/analysis/sleeve_walk_forward/results.py`, `scripts/analysis/sleeve_walk_forward/score.py`
- Test: `tests/unit/sleeve_walk_forward/test_score.py`

**Interfaces:**
- Produces in `results.py` (frozen dataclasses, no logic, used by Tasks 6-9):
  - `StratumWeights`: `feature_names: list[str]`, `weights: np.ndarray`, `ic_signs: np.ndarray`, `method_used: str`, `effective_n: float`.
  - `RefitOutput`: `refit_date: np.datetime64`, `strata: dict[str, StratumWeights]` (equity label -> weights), `skipped: dict[str, str]` (label -> reason), `ic_rows: list[dict]`, `n_embargo_excluded: int`.
  - `GroupArrays`: one regime group's 1d rows sorted `(bar_ts, symbol)`: `symbols: np.ndarray`, `bar_ts: np.ndarray` (datetime64[D]), `session_idx: np.ndarray` (int), `X: np.ndarray` float32 `[rows, len(_FEATURE_NAMES)]`, `returns: np.ndarray [rows, 4]`, `complete: np.ndarray bool [rows, 4]`, `labels: np.ndarray` (the group's `market_regimes` label per row, "" if none).
  - `Snapshot`: `sessions`, `groups: dict[str, GroupArrays]`, `all_1d: GroupArrays` (every 1d symbol, equity labels, for the trainer's stratum `X`), `sleeve_features: np.ndarray [n_sessions, n_sleeve, n_features]`, `sleeve_opens`, `sleeve_closes` `[n_sessions, n_sleeve]`, `equity_labels: np.ndarray [n_sessions]`, `broadcast_mask: np.ndarray bool`, `feature_to_group: dict[str, str]`, `apr: dict[str, str]`, `manifest: dict`.
- Consumes: `StratumWeights`, `RefitOutput` (above), sleeve feature arrays from `Snapshot`.
- Produces: `score_panel(refits: list[RefitOutput], features: np.ndarray [n_sessions, n_sleeve, n_all_features], feature_index: dict[str, int], labels: np.ndarray [n_sessions] (equity regime label or ""), sessions: np.ndarray, refit_dates: list[np.datetime64], end: np.datetime64) -> tuple[np.ndarray, dict]` returning the `[n_sessions, n_sleeve]` alpha panel (NaN where no stratum weights, no label, or the symbol has no feature row that day) and counts: NaN days per year per reason (`no_label`, `no_stratum_weights`, `no_feature_row`).
- Composite exactly as the trainer: `X` with NULL -> 0, `alpha = X @ (weights * ic_signs)`.

- [ ] **Step 1: Failing tests:** hand-built 2-refit, 2-stratum case with known weights gives hand-computed alpha; a day in `[T_k, T_{k+1})` uses refit k, never k+1; a stratum missing in refit k gives NaN plus `no_stratum_weights`; NULL feature counts as 0 but a missing feature row gives NaN (`no_feature_row`); no day before the first refit date is scored (V6 assert raises if the caller passes one).
- [ ] **Step 2-4:** Fail, implement, pass.
- [ ] **Step 5:** Commit `feat(179): S2 scoring with per-reason no-alpha counts`.

### Task 7: Refit (S1)

**Files:**
- Create: `scripts/analysis/sleeve_walk_forward/refit.py`
- Test: `tests/unit/sleeve_walk_forward/test_refit.py`

**Interfaces:**
- Consumes (production, imported never copied): `services.ic_engine`: `ICEngineConfig.from_apr`, `_compute_one_cross_sectional_cell`, `_compute_one_broadcast_cell`, `_mark_cluster_representatives`, `_derive_worker_rng_seed`, `_FEATURE_NAMES`; `src.intelligence.statistics.ic_math.apply_bh_fdr`; `scripts.ops.alpha.ops_ic_shrinkage.compute_shrinkage_updates`; `services.ensemble_trainer`: `EnsembleConfig.from_apr`, `_meta_eligible`, `_eligibility_where` (tests only), `_resolve_ic_input_column`; `services._batch_utils._resolve_per_tf`; `stratum_fit.select_stratum`, `fit_stratum_weights`.
- Produces:
  - `training_arrays(snapshot_group: GroupArrays, cutoffs: dict[int, int]) -> tuple[X_raw, returns_mat, complete_mat, bar_ts]`: rows with `bar_ts` in `[training_start, T_k)`, sorted `(bar_ts, symbol)` like `chunk_sql`; `complete_mat[:, j]` set False where scale j's exit session index `t + h_j + 1 > cutoff`; the h=1 cutoff also trims rows (spec 6).
  - `eligible(row: dict, sign_symmetric: bool) -> bool`: Python mirror of `_eligibility_where(...)[1]` (full clause, `passes_fdr` included) with `_base` variant for meta-FDR.
  - Returns `results.RefitOutput` (Task 6).
  - `run_refit(snapshot: Snapshot, refit_date: np.datetime64, cfg: HarnessConfig, excluded: frozenset[str]) -> RefitOutput`. Steps, in production order:
    1. For every enabled regime group (A1) and each of its 1d labels present before T_k: build the cell arrays for that label's sessions, call `_compute_one_cross_sectional_cell` with `broadcast_mask` = production broadcast flags OR `excluded`, then `_compute_one_broadcast_cell` with the production broadcast mask minus `excluded`. RNG per cell: `np.random.default_rng(_derive_worker_rng_seed(f"{refit_date}|{group}|{label}", config.bootstrap_seed))`. `training_window_end` = the session at the h=1 cutoff.
    2. `_mark_cluster_representatives` over all rows, then one `apply_bh_fdr` over the collected representative p-values at `alpha.ic.fdr_alpha` (D1), writing `bh_adjusted_p`/`passes_fdr` onto the representatives.
    3. Shrinkage: `compute_shrinkage_updates(reliable rows, feature_to_group, k)` over this refit's rows (D7), applied onto `ic_shrunk`/`shrinkage_weight`.
    4. Meta-FDR: build `fdr_pass_rows` (per feature at tf 1d: pass rate over rows passing the base clause), `_meta_eligible(...)`.
    5. For each equity label: rows passing `eligible(..., full)`, in the meta-eligible set, not in `excluded`, with `ic_shrunk` not NULL when `ic_input` is `ic_shrunk`; `select_stratum`; fetch that label's `X` over all 1d symbols' snapshot rows in the label (trainer's `fv_rows` query: every symbol, joined to equity labels) and `fit_stratum_weights`; skip with reason on `min_features`, `missing_cols`, `n_fit_rows < 2`, or zero weight sum, exactly as `_process_stratum`.
    6. V6 asserts: no row in any cell has `bar_ts >= T_k`; every `complete` label's exit index <= its cutoff.

- [ ] **Step 1: Failing tests** (tiny synthetic snapshot: 12 symbols, 2 groups, 3 labels, 600 sessions, 6 real features plus the canaries; build `ICEngineConfig.from_apr` from a fixture APR dict copied from the live `alpha.ic.*` keys, with bootstrap sizes reduced through the same APR keys):
  - `test_embargo_excludes_late_labels`: a row 3 sessions before `T_k` has `complete` False for h=1 (exit t+2 > cutoff) and all longer scales; `n_embargo_excluded` counts it.
  - `test_eligible_matches_production_sql`: 200 random rows through `eligible` and through production's `_eligibility_where` string executed by `sqlite3` on an in-memory table with the same columns; results identical, for both `sign_symmetric` values.
  - `test_planted_feature_is_selected`: a feature with a planted monotone relation to `return_fast` in one equity label is selected and gets positive weight; pure-noise features mostly don't.
  - `test_refit_is_deterministic`: two `run_refit` calls give identical `ic_rows` and weights.
  - `test_excluded_feature_never_weighted`: a planted feature in `excluded` emits no row and no weight.
  - `test_stratum_skip_reasons`: a label with one surviving feature returns `skipped[label] == "min_features"`.
  - `test_fit_uses_rows_before_window_end_only`: rows after `training_window_end` in a label's `X` don't change the weights (409 behavior via `fit_stratum_weights`).
- [ ] **Step 2-4:** Fail, implement, pass. If a private ic_engine function needs a symbol this plan doesn't list, import it and record it in the module docstring's import list (debt owned by todo 214), never copy code.
- [ ] **Step 5:** Commit `feat(179): S1 refit driving production IC, FDR, shrinkage and stratum-fit code`.

### Task 8: Snapshot (S0)

**Files:**
- Create: `scripts/analysis/sleeve_walk_forward/snapshot.py`
- Test: `tests/integration/test_sleeve_walk_forward_snapshot.py`

**Interfaces:**
- Produces (returns `results.Snapshot`, Task 6): `async build_snapshot(dsn: str, out_dir: Path, *, symbols: list[str] | None = None, start: str, end_exclusive: str) -> Path` writing `snapshot_<sha256>.npz` plus `manifest_<sha256>.json`, and `load_snapshot(path) -> Snapshot` (memory-mapped arrays). Contents: per 1d symbol, `bar_ts`, float32 feature matrix in `_FEATURE_NAMES` order (NULL -> NaN), forward returns + complete flags for the four 1d scales (`return_type = 'executable_open_to_open'`); `market_regimes` 1d labels per group; `instrument_tags` for routing; concept_registry broadcast flags and `group_name`s; the full `config_state` as the APR snapshot (its own hash); sleeve 1d opens and closes from `market_data_ohlcv_tradeable`; the session axis (union of universe 1d feature-row dates; SPY-only dropped 2 real sessions, see pre-reg 12.1 V4). Column dtypes from `conn.prepare(sql).get_attributes()`, never inferred (CLAUDE.md). Bare `asyncpg.connect()` calls `_setup_codecs(conn)` before any jsonb read.
- Connection: `server_settings={"default_transaction_read_only": "on"}`. Assert `max(bar_ts) < oos_start` across every fetched table; raise otherwise.

- [ ] **Step 1: Failing integration test** (runs against the live DB, read-only, 2 symbols x 2 months in 2019): snapshot builds; hash is stable across two builds; a write attempted on the snapshot's connection raises `ReadOnlySQLTransactionError`; `end_exclusive` past `oos_start` raises before fetching.
- [ ] **Step 2-4:** Fail, implement, pass: `.venv/bin/pytest tests/integration/test_sleeve_walk_forward_snapshot.py -q`.
- [ ] **Step 5:** Commit `feat(179): S0 read-only content-hashed snapshot`.

### Task 9: CLI and stage wiring

**Files:**
- Create: `scripts/analysis/sleeve_walk_forward/run.py`
- Test: extend `test_verdict.py` with one end-to-end test that runs S1-S4 on the Task 7 fixture snapshot through `run.main([...])` in a temp dir.

**Interfaces:**
- `run.py --stage {s0,s1,s2,s3,s4,v2,v3} --in <hash> --out-dir <dir> [--workers N]`. Each stage reads its parent's hashed file, writes its own `<stage>_<sha256>.npz|json`, and prints the hash. S1 runs refits in a `ProcessPoolExecutor` (compute-only workers returning `RefitOutput`). `setup_service_logging("logs/sleeve_walk_forward.log")`; oneshot `job_completed_total{job="sleeve-walk-forward", status}` at exit (D-06). S4 writes only the result JSON in this step; the ledger row and concept_registry row are written in build step 8.
- A stage refuses to run on a parent artifact whose recorded code commit differs from `git rev-parse HEAD` unless `--allow-code-drift` is passed (prevents mixing stages across code versions after the freeze).

- [ ] **Steps 1-4:** Failing end-to-end test, implement, pass, full unit suite green (`.venv/bin/pytest tests/unit/ -q`).
- [ ] **Step 5:** Commit `feat(179): harness CLI with content-hashed stage artifacts`.

### Task 10: Done-coding SOP and handoff to step 6

- [ ] `/simplify` over the package, then `/code-review`; fix findings.
- [ ] `.venv/bin/pytest tests/unit/ -q` green; ruff and black clean.
- [ ] Merge `--ff-only` to main, push.
- [ ] After the 178 recompute finishes (check `ps aux | grep ic_engine` shows nothing): run `run.py --stage v2` (200 seeds x 199 shifts) and `--stage v3` (IR 0.6 and 0.8, 200 seeds each); record PASS rates, CIs and measured seconds per shift in the pre-reg section 12 addendum draft. V2 outside 5% +/- 3.1%, or V3 below 50% at IR 0.8, stops the phase for a design revisit (spec 10).
- [x] (plan: `docs/plans/2026-09-24-phase179-diagnostics-plan.md`) Section 11 diagnostics (net-of-cost with todo 393's fix, per-year/per-symbol/per-stratum excess, equal-weight and static-tilt references, uniform-weight and production-pool variants, feature decay, no-weight days) are reported-only and land as a follow-up plan before the freeze (step 7); none of them feeds the token.
- [ ] Update the 179 memory and pre-reg build order: step 5 done, next step 6 (HMM audit, deprecated-feature decision, S0 snapshot, V4, V4b, V5).

## Execution record (2026-09-24)

Tasks 0-9 built on `feat/179-harness`, `/simplify` and a fresh-context final review applied
(no Critical; 2 Important fixed with failing-first tests: the V6 embargo assert now checks label
exit sessions, and the stage drift key covers the harness's own sources and records the git
commit). Harness suite 60 tests; full unit suite green. Measured: 49.5 ms per shift, full null
about 3 minutes single-core.

Rulings taken during the build: `calendar.py` renamed `sessions.py` (stdlib shadowing); a failed
calibration refit keeps the prior state until the next scheduled refit; calibration Spearman on
raw alpha (rank-invariant to standardization); null daily returns held in RAM (163 MB);
synthetic runs pin k = 100 and mv_condition_max = 1000; V3's planted effect is the mean
vol_normalized excess Sharpe; no edits to `ic_engine.py`/`_batch_utils.py` while a recompute is
live (harness imports their private hooks, todo 214 debt); `Snapshot.apr` holds
(value, value_type); live-DB test in `tests/live/`; snapshot as a directory of memory-mapped
`.npy`; `oos_start` read separately (no `config_schema` row); stage artifacts are pickles with
`code_key`, `git_commit`, `git_dirty`; s1 requires `--excluded-file`, s4 requires `--fidelity`.
Process slip: `refit.py` was written before its tests; mutation checks (embargo off-by-one,
dropped earnings-season clause) were caught by the tests written after.

### Before the freeze (step 7), from the final review's minor findings

- [x] Bound the S3 trade mask by the last sub-period end (the last two sessions' NaN forward
      returns currently enter the Sharpe as zero-return days).
- [x] Count whole rows dropped at the h=1 cutoff in `n_embargo_excluded`.
- [x] Runtime assert in `score.py`: no scored day before its refit date.
- [x] `_LABELS_SQL`: assert one label per (group, day).
- [x] `load_snapshot`: re-verify the directory hash (at least in s1).
- [x] Pin in the addendum: the BH family excludes production's 1d POOLED `earnings_season`
      cells; V6 wording (section 10 vs section 6); `n_rows_off_session` count (pre-reg 12.1).
- [x] Hygiene: read `fdr_alpha` from `ICEngineConfig`; hoist `group.X[keep]` out of the label loop.
- [x] Section 11 shape diagnostics per arm (Sortino, max drawdown, skew, excess kurtosis, hit
      rate), real run and null median, in the S3 payload; reported only, never read by `decide`.
