---
plan: 141-P2
phase: "141"
title: "HMM Numba JIT"
subsystem: intelligence
tags: [hmm, numba, jit, performance, regime_writer]
requires: [141-P0]
provides: [alpha_pass_jit, hmm_jit_precompile]
affects: [services/regime_writer.py, src/intelligence/hmm_jit.py]
tech_stack_added: [numba>=0.65.0]
tech_stack_patterns: [numba-njit-cache, main-process-jit-warmup]
key_files_created:
  - src/intelligence/hmm_jit.py
  - tests/unit/intelligence/test_hmm_jit.py
key_files_modified:
  - services/regime_writer.py
  - requirements.txt
decisions:
  - "Explicit scalar loops in njit: numba 0.65.1 does not support .max(axis=0) or np.sum(..., axis=0) on 2-D arrays in nopython mode; replaced with explicit i/j loops for log-sum-exp"
  - "Takes log_A not transmat_: caller computes log(max(transmat_, 1e-300)) once per symbol outside JIT boundary, avoids redundant computation inside the LLVM-compiled t-loop"
  - "Main-process pre-compile with dummy (10, n_components) input before ProcessPoolExecutor; no initializer= argument; workers load cache read-only — single-writer pattern eliminates __pycache__ race under both fork and spawn start methods"
  - "Ring 1 placement: src/intelligence/hmm_jit.py has no DB imports, no Ring 2 imports, no asyncio"
metrics:
  duration_minutes: 15
  tasks_completed: 3
  tasks_total: 3
  files_changed: 4
  completed_date: "2026-06-29"
---

# Phase 141 Plan P2: HMM Numba JIT Summary

Numba JIT forward filter for the HMM alpha-pass t-loop in regime_writer, with pre-compiled cache loading in all worker subprocesses via a single main-process warmup.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| P2-T1 | Write failing tests for alpha_pass_jit | 9450a6c5 | tests/unit/intelligence/test_hmm_jit.py, requirements.txt |
| P2-T2 | Implement src/intelligence/hmm_jit.py | 269ad5f3 | src/intelligence/hmm_jit.py |
| P2-T3 | Wire alpha_pass_jit into regime_writer | c4ab422f | services/regime_writer.py |

## What Was Built

`src/intelligence/hmm_jit.py` exports `alpha_pass_jit` decorated with `@numba.njit(cache=True)`. The function is a numerically identical replacement for `_alpha_pass` in `regime_writer.py`, differing only in its interface: it takes `log_A` (pre-computed `log(max(transmat_, 1e-300))`) instead of raw `transmat_`, moving the log-max computation outside the JIT boundary to the Python call site where it executes once per symbol.

The call site in `_causal_decode` was updated:
- Before: `_alpha_pass(log_emit, model.transmat_, pi0)`
- After: `log_A = np.log(np.maximum(model.transmat_, 1e-300)); _alpha_pass_jit(log_emit, log_A, pi0)`

The main-process pre-compile block runs before `ProcessPoolExecutor` spawns any workers, using a dummy `(10, n_components)` input. With `cache=True`, Numba writes the compiled artifact to `__pycache__` once; all worker subprocesses then load it read-only on first use. No `initializer=` argument is needed.

## Test Coverage

5 tests in `tests/unit/intelligence/test_hmm_jit.py`, all green:
- `test_jit_states_match_reference` - states array-equal to Python `_alpha_pass_ref` for same inputs
- `test_jit_alpha_history_matches_reference` - alpha_history within rtol=1e-10
- `test_alpha_rows_sum_to_one` - each row sums to 1.0 within atol=1e-10
- `test_diag_cov_path_identity` - JIT matches reference when log_emit from diag-covariance HMM
- `test_full_cov_path_identity` - JIT matches reference when log_emit from full-covariance HMM

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Numba njit does not support .max(axis=0) on 2-D arrays**
- **Found during:** Task P2-T2, first test run
- **Issue:** `log_trans.max(axis=0)` and `np.sum(np.exp(log_trans - max_lt), axis=0)` raise TypingError in numba 0.65.1 nopython mode — the `axis` kwarg is not supported for 2-D array reductions
- **Fix:** Replaced with explicit `for i in range(K): for j in range(K):` loops implementing log-sum-exp; semantically identical, LLVM-compiled so no performance penalty
- **Files modified:** src/intelligence/hmm_jit.py
- **Commit:** 269ad5f3

**2. [Rule 3 - Blocking] Missing .venv symlink and logs/ directory in worktree**
- **Found during:** Task P2-T1, first commit attempt
- **Issue:** Pre-commit hook looks for `${REPO_ROOT}/.venv/bin/ruff` where REPO_ROOT is the worktree root; worktree had no .venv and no logs/ directory
- **Fix:** Created `logs/` dir and symlinked `.venv` -> `/home/bg/dev/indicagent/.venv`
- **Commit:** Infrastructure fix, not code commit

## Pre-existing Test Failures (Not Caused by P2)

The following tests fail on `main` before P2 and remain unchanged:
- `test_causal_hmm_decoding.py` (5 tests): call `_causal_decode(obs, means, covars, A, K)` with 5 arguments — stale tests from before `_causal_decode` was aliased to `_alpha_pass(log_emit, A, pi0)`
- `test_regime_writer.py::test_causal_decode_vectorized_matches_original`: same stale 5-arg call
- `test_alpha_publisher.py` and `test_ic_engine_compute_split.py`: unrelated pre-existing failures

Total pre-P2 failures: 45. Post-P2: 45 (unchanged). The 5 new hmm_jit tests are all green.

## Performance Impact

Target: 20+ hour regime_writer full 58-symbol corpus run reduced to ~30 min via LLVM native speed. The t-loop (previously pure Python) is the sole bottleneck; vectorized numpy in `_log_emit_full` and `_log_emit_diag` is unaffected (those functions use try/except which is incompatible with nopython mode).

## Known Stubs

None.

## Threat Flags

None — no new network endpoints, auth paths, or trust-boundary crossings introduced.

## Self-Check

- [x] `src/intelligence/hmm_jit.py` exists: confirmed
- [x] `tests/unit/intelligence/test_hmm_jit.py` exists: confirmed
- [x] Commits 9450a6c5, 269ad5f3, c4ab422f exist in git log
- [x] `numba>=0.65.0` line in requirements.txt (non-comment): confirmed
- [x] `from src.intelligence.hmm_jit import alpha_pass_jit as _alpha_pass_jit` in regime_writer.py: confirmed
- [x] JIT pre-compile block before ProcessPoolExecutor (no initializer=): confirmed
- [x] `log_A = np.log(np.maximum(model.transmat_, 1e-300))` at call site: confirmed
- [x] All 5 hmm_jit tests PASS: confirmed (1.72s, cache hit on second run)

## Self-Check: PASSED
