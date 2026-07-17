---
phase: 146-empirical-instrument-tag-calibrator-planned
plan: 03
subsystem: statistics
tags: [numpy, scipy, statsmodels, factor-loading, hac, newey-west, ols, pearson-correlation]

# Dependency graph
requires:
  - phase: 143.1 / earlier
    provides: src/intelligence/statistics/ic_math.py (Fisher-z CI, p-values, BH-FDR, HAC-Sharpe kernel, condition-number gate)
  - phase: (dual regime system work)
    provides: src/intelligence/regime_signals/breadth_vol.py (causal _compute_vix_pct_rank)
provides:
  - factor_math.py measurement kernel (standardized OLS loading, HAC-adjusted p-value, long-short spread constructor, vol_beta factor adapter)
  - Synthetic-fixture unit tests pinning correctness of all four functions
affects: [146-04 (TagCalibrator service, imports factor_math.py directly)]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Standardized loading as signed Pearson correlation (cov/(std*std)) instead of a full statsmodels.OLS solve for the univariate-regressor case"
    - "HAC inflation factor computed by reusing ic_math._hac_sharpe_nd's gamma_k/rho_k/Bartlett-weight accumulation loop pattern, applied to the demeaned elementwise product of two z-scored return series (not the Sharpe-specific function itself)"
    - "Effective-df HAC p-value: base_df / inflation, passed as explicit df to ic_math._p_values_from_ic (reused, not reimplemented)"

key-files:
  created:
    - src/intelligence/statistics/factor_math.py
    - tests/unit/test_factor_math.py
  modified: []

key-decisions:
  - "standardized_loading/loading_hac_pvalue take hac_max_lag and condition_max as plain scalar parameters rather than a duck-typed config Protocol (unlike ic_math's SharpeWindowConfig) -- each function needs at most one or two tunables, not a multi-field config object, so a Protocol class would add indirection with no real decoupling benefit over passing them directly. This deviates from 146-PATTERNS.md's suggested Protocol style but matches the plan's own literal interface signatures (loading_hac_pvalue(instrument_ret, factor_ret, hac_max_lag))."
  - "Exposed a private _loading_standard_errors(instrument_ret, factor_ret, hac_max_lag) helper (naive_se, hac_se, r, n) so the HAC-SE-inflation test can assert hac_se > naive_se directly, matching the house convention of importing underscore-prefixed helpers directly in tests (see test_ensemble_ic_math.py's _circular_shift_null/_hac_sharpe_nd imports)."
  - "loading_hac_pvalue accepts an optional extra_fitted_params: int = 0 keyword (beyond the plan's literal 3-arg signature) to let a future long-short caller reduce df for the spread construction's implicit extra fitted parameter, without changing the base call shape for the plain single-instrument-vs-single-factor case."

requirements-completed: [TAG-01]

# Metrics
duration: ~20min
completed: 2026-07-17
---

# Phase 146 Plan 03: Factor-Loading Measurement Kernel Summary

**`factor_math.py` adds standardized OLS loading (signed Pearson correlation) + Newey-West Bartlett-kernel HAC-adjusted standard error/p-value + shared long-short spread constructor + vol_beta factor adapter, reusing `ic_math`'s CI/p-value/FDR/condition-number kernel and `breadth_vol`'s causal vol proxy verbatim.**

## Performance

- **Duration:** ~20 min
- **Tasks:** 2/2 completed
- **Files modified:** 2 (both new)

## Accomplishments
- `standardized_loading(instrument_ret, factor_ret, condition_max)` -- signed Pearson correlation bounded [-1,1], with a zero-variance degenerate guard and a `check_condition_number` ill-conditioning gate (T-146-05 mitigation)
- `loading_hac_pvalue(instrument_ret, factor_ret, hac_max_lag, extra_fitted_params=0)` -- HAC-inflation-adjusted two-tailed p-value, deriving an effective df from the Newey-West Bartlett-kernel inflation factor and passing it through to `ic_math._p_values_from_ic`
- `long_short_daily_returns(long_close, short_close)` -- the one shared spread constructor for all four long-short factor series (HYG-IEF, TIP-IEF, IEF-SHY, XLE-SPY)
- `spy_realized_vol_factor(spy_close, realized_vol_window, vix_z_window)` -- thin verbatim adapter over `breadth_vol._compute_vix_pct_rank` (T-146-06 mitigation: causal-rank invariant preserved)
- Four synthetic-fixture unit tests, all CI-clean (no DB, no network)

## Task Commits

Each task was committed atomically:

1. **Task 1: factor_math.py -- loading, HAC SE/p-value, long-short constructor, vol adapter** - `948ed7ee` (feat)
2. **Task 2: test_factor_math.py -- synthetic-fixture correctness** - `1ae842a4` (test)

## Files Created/Modified
- `src/intelligence/statistics/factor_math.py` - Pure-function measurement kernel: `long_short_daily_returns`, `standardized_loading`, `_loading_standard_errors` (private), `loading_hac_pvalue`, `spy_realized_vol_factor`
- `tests/unit/test_factor_math.py` - `test_ols_loading_synthetic`, `test_hac_se_inflation`, `test_long_short_constructor`, `test_spy_realized_vol_factor_is_causal`

## Decisions Made
- Skipped the config-Protocol style suggested by 146-PATTERNS.md in favor of plain scalar parameters (`hac_max_lag`, `condition_max`) -- matches the plan's literal interface signatures and avoids unneeded indirection for functions with only 1-2 tunables. See frontmatter `key-decisions` for full rationale.
- `_loading_standard_errors` is exposed (underscore-prefixed, not in `__all__`) specifically so `test_hac_se_inflation` can assert the naive-vs-HAC SE inequality directly, matching this codebase's established test-import convention for `ic_math.py`'s own private helpers.
- Tuned `test_hac_se_inflation`'s synthetic fixture to a modest correlation coefficient (0.05x AR(1) driver instead of 0.5x) after discovering the initial fixture drove both naive and HAC p-values to float64 underflow (0.0) at n=1000, making the "HAC p-value is less significant" comparison untestable. This is a test-fixture calibration detail, not a change to the measured kernel's correctness.

## Deviations from Plan

None - plan executed exactly as written. The `_loading_standard_errors` helper and `extra_fitted_params` keyword are additive implementation details within the four required public functions' scope (Task 1's `<action>` explicitly describes reusing the HAC inflation-factor loop pattern and passing an explicit df for extra fitted parameters); no scope creep, no architectural changes, no auto-fixes of Rule 1-4 severity were needed.

## Issues Encountered
- No `.venv` present in this worktree (gitignored, per known GSD worktree limitation) -- used the main repo's `/home/bg/dev/indicagent/.venv` interpreter/tools directly (`python -m pytest`, `ruff`, `black`) since it is the same project dependency set; pre-commit hooks required `ruff`/`black` on `PATH`, resolved by prepending the main repo's `.venv/bin` to `PATH` for the commit invocations only.

## Next Phase Readiness
`factor_math.py` is ready for Plan 04's `TagCalibrator` service to import directly (`from src.intelligence.statistics.factor_math import ...`) as its thin orchestration layer's measurement kernel. No blockers.

---
*Phase: 146-empirical-instrument-tag-calibrator-planned*
*Completed: 2026-07-17*
