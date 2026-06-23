---
phase: 138-ic-engine-forward-returns
plan: "07"
subsystem: testing
tags: [ic-engine, hmm, bootstrap, spearman, bh-fdr, forward-returns, unit-tests]

requires:
  - phase: 138-P6
    provides: "ic_engine.py with _circular_block_bootstrap_ic, _vectorized_ic, _POOLED_INSERT_SQL, _REGIME_INSERT_SQL; regime_writer.py with _causal_decode, _build_label_map; forward_return_writer.py"

provides:
  - "6 unit test files: vectorized IC, BH-FDR order, forward return formula, causal HMM decoding, circular block bootstrap, idempotency + regime labels"
  - "compute_ic_vectorized() public wrapper in ic_engine.py (raw inputs -> Spearman IC)"
  - "_build_label_map() refactored to accept means: np.ndarray (not GaussianHMM model)"
  - "forward_log_return() pure numpy helper in forward_return_writer.py"

affects:
  - "138-P8 corpus runs (blocked on data; these tests are the correctness anchor)"

tech-stack:
  added: []
  patterns:
    - "Pure-function extraction before testing: public compute_ic_vectorized() wraps private _vectorized_ic()"
    - "Causal vs Viterbi test: 30-bar regime-switch sequence with sharp boundary exposes lookahead"
    - "Bootstrap statistical correctness: CI shrinks with N (consistency), wider with larger block (autocorr)"

key-files:
  created:
    - tests/unit/test_ic_engine_vectorized.py
    - tests/unit/test_bh_fdr_mapping.py
    - tests/unit/test_forward_return_writer.py
    - tests/unit/test_causal_hmm_decoding.py
    - tests/unit/test_circular_block_bootstrap.py
    - tests/unit/test_ic_engine_idempotency.py
    - tests/unit/test_regime_writer.py
  modified:
    - services/ic_engine.py
    - services/regime_writer.py
    - services/forward_return_writer.py
    - tests/unit/services/test_regime_writer.py

key-decisions:
  - "_build_label_map() signature changed to accept means: np.ndarray instead of model: GaussianHMM -- more testable, still deterministic, call site passes model.means_"
  - "BH-FDR order-preservation test uses pairwise monotone check, not argsort equality -- handles cummin ties in q-values correctly"
  - "Causal vs Viterbi test uses 30-bar sequence with switch at bar 20 -- strong enough signal separation to guarantee the two decoders differ"

requirements-completed: []

duration: 25min
completed: 2026-06-23
---

# Phase 138 Plan 7: Unit Tests for IC Statistical Gates Summary

**6 pure-math unit test files anchoring Spearman IC (1e-10 vs scipy), causal HMM decoding (forward-filter != Viterbi on regime-switch data), circular block bootstrap (CI shrinks with N, wider block on AR(1)), BH-FDR order preservation, forward return formula correctness, and idempotency SQL assertions -- 5140 tests green**

## Performance

- **Duration:** 25 min
- **Started:** 2026-06-23T09:40:00Z
- **Completed:** 2026-06-23T10:05:00Z
- **Tasks:** 2
- **Files modified:** 10

## Accomplishments

- Added `compute_ic_vectorized()` public wrapper to ic_engine.py and `forward_log_return()` pure numpy helper to forward_return_writer.py to enable unit testing without DB
- Refactored `_build_label_map()` in regime_writer.py to accept `means: np.ndarray` directly (was `model: GaussianHMM`) -- updated all call sites and existing tests
- 6 new test files, 47 new test functions, all green; full unit suite remains 5140 passed, 0 failed

## Task Commits

Each task was committed atomically:

1. **Task 1: Pure-function helpers + 5 unit tests for IC math** - `5de890cb` (feat)
2. **Task 2: Idempotency + regime label unit tests** - `97d2fab9` (feat)

## Files Created/Modified

- `tests/unit/test_ic_engine_vectorized.py` - 6 tests: vectorized IC matches scipy.spearmanr to 1e-10 for all features
- `tests/unit/test_bh_fdr_mapping.py` - 6 tests: BH-FDR output length, order preservation, monotone q with sorted p
- `tests/unit/test_forward_return_writer.py` - 7 tests: ln(open[T+N+1]/open[T+1]) formula, no lookahead, NaN for last n rows
- `tests/unit/test_causal_hmm_decoding.py` - 5 tests: forward-filter != full-sequence Viterbi on 30-bar regime-switch sequence
- `tests/unit/test_circular_block_bootstrap.py` - 4 tests: CI shrinks with N (n=100 vs n=500), wider CI with block_size=50 vs 5 on AR(1) phi=0.7, circular wrap no IndexError, determinism
- `tests/unit/test_ic_engine_idempotency.py` - 9 tests: skip-set dedup logic, ON CONFLICT DO NOTHING in both INSERT SQL constants, is_pooled key separation
- `tests/unit/test_regime_writer.py` - 10 tests: label assignment with known means [-0.5, +0.5, 0.0], no integer-string labels, 4-component ranging count
- `services/ic_engine.py` - added `compute_ic_vectorized()` public wrapper (accepts raw inputs, ranks internally)
- `services/regime_writer.py` - refactored `_build_label_map(means: np.ndarray)` from `_build_label_map(model: GaussianHMM, n_components)`
- `services/forward_return_writer.py` - added `forward_log_return()` pure numpy helper + `import numpy as np`
- `tests/unit/services/test_regime_writer.py` - updated 6 `_build_label_map(model, n_components)` call sites to `_build_label_map(model.means_)`

## Decisions Made

- `_build_label_map()` signature change to `means: np.ndarray`: the old `(model, n_components)` signature required a fitted `GaussianHMM` in tests (heavyweight); accepting `np.ndarray` directly allows pure-numpy unit tests with known means like `[-0.5, +0.5, 0.0]`. Semantics are identical -- call site passes `model.means_`.
- BH-FDR test uses pairwise monotone check (not argsort equality): statsmodels enforces monotone q-values via cummin, which can cause ties between consecutive q-values that make argsort index ordering fragile. The pairwise check `p[i] < p[j] => q[i] <= q[j]` is the correct mathematical statement.
- Causal vs Viterbi test uses 30-bar sequence with switch at bar 20 and seed=42: the signal separation (positive returns vs strongly negative) is strong enough that the causal forward filter and Viterbi reliably produce different outputs. Verified empirically before writing the assertion.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed BH-FDR test assertion (argsort equality -> pairwise monotone)**
- **Found during:** Task 1 (test_bh_fdr_mapping.py)
- **Issue:** `test_bh_fdr_index_correspondence` used `np.argsort(pvals) == np.argsort(q)` which fails because BH cummin creates tied q-values that can sort in any order
- **Fix:** Replaced with pairwise check: for all (i,j) pairs, `p[i] < p[j] => q[i] <= q[j]`
- **Files modified:** tests/unit/test_bh_fdr_mapping.py
- **Committed in:** 5de890cb (Task 1 commit)

**2. [Rule 1 - Bug] Fixed NameError in test_forward_log_return_last_n_rows_are_nan**
- **Found during:** Task 1 (test_forward_return_writer.py)
- **Issue:** Used `n` instead of `n_lookahead` variable name in nan_region slice
- **Fix:** Corrected to `result[m - n_lookahead - 1:]`
- **Files modified:** tests/unit/test_forward_return_writer.py
- **Committed in:** 5de890cb (Task 1 commit)

---

**Total deviations:** 2 auto-fixed (both Rule 1 bugs found during test runs)
**Impact on plan:** Both fixes were test-logic corrections, not implementation changes. No scope creep.

## Issues Encountered

None beyond the two auto-fixed test bugs above.

## Next Phase Readiness

- P8 (IC discovery report + corpus runs) is blocked on data: `feature_ic_scores` requires a full `backfill_feature_factory` + `regime_writer` + `forward_return_writer` + `ic_engine` run over the 58-ETF corpus
- All mathematical correctness gates are now locked by these 6 test files
- Full unit suite: 5140 passed, 41 skipped, 0 failed

---
*Phase: 138-ic-engine-forward-returns*
*Completed: 2026-06-23*
