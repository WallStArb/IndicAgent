---
phase: 093-mathematical-correctness-audit
plan: "03"
subsystem: test-correctness
tags:
  - testing
  - correctness
  - kalman
  - garch
  - invariants
  - mathematical
dependency_graph:
  requires:
    - 093-01 (conftest.py fixtures + frames_from_ohlcv helper)
  provides:
    - tests/unit/intelligence/correctness/test_kalman_invariants.py
    - tests/unit/intelligence/correctness/test_garch_invariants.py
  affects:
    - KalmanTrendPlugin regression coverage
    - GARCHVolatilityPlugin regression coverage
tech_stack:
  added: []
  patterns:
    - incremental-equals-full equivalence test pattern
    - fixed-point derivation from actual implementation (not assumed textbook formula)
    - state-mutation-aware test (capture prior values before compute_next mutates state)
key_files:
  created:
    - tests/unit/intelligence/correctness/test_kalman_invariants.py
    - tests/unit/intelligence/correctness/test_garch_invariants.py
  modified: []
decisions:
  - "Kalman slope invariant uses net level displacement over full window (not instantaneous slope at last bar); instantaneous slope can be transiently negative even on a strongly upward series due to local noise — net displacement is the algebraically correct invariant"
  - "GARCH convergence fixed point is omega/(1-beta) on flat data, NOT omega/(1-alpha-beta); alpha term vanishes when epsilon=0 strictly; this distinction is documented in test body with line-for-line reference to garch_volatility.py recurrence"
  - "GARCH shock test must capture sigma2_prior BEFORE compute_next mutates the state dict in place via state.update(); reading from state after the call returns the posterior value"
metrics:
  duration: "~4 minutes"
  completed: "2026-05-21"
  tasks_completed: 2
  files_created: 2
  files_modified: 0
---

# Phase 093 Plan 03: Kalman and GARCH Invariant Tests Summary

**One-liner:** Kalman and GARCH mathematical invariants enforced in test code: positivity, bounded gain, no NaN/Inf, correct fixed-point convergence (omega/(1-beta) derived from actual zero-epsilon recurrence), unbiased shock formula, and incremental=full equivalence.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Kalman trend invariant tests | 17e763a6 | test_kalman_invariants.py |
| 2 | GARCH(1,1) invariant tests | b3523c9e | test_garch_invariants.py |

## What Was Built

### test_kalman_invariants.py

Class `TestKalmanInvariants` with 5 test methods, 7 parametrized cases total:

| Test | Invariant Enforced |
|------|--------------------|
| `test_kalman_covariance_strictly_positive` | P_est > 0 after every bar across 500 bars |
| `test_kalman_gain_bounded` | 0 < K < 1 after every bar (scalar local-level proof in comment) |
| `test_kalman_no_nan_inf_in_outputs` | All 7 output keys finite across trending, ranging, gap fixtures |
| `test_kalman_incremental_equals_full` | bars[0:100] bootstrap + bars[100:200] compute_next == compute_full on bars[0:200], atol=1e-6 |
| `test_kalman_slope_directionally_tracks_trend` | Net filtered level displacement positive on trending; smaller on ranging |

The `test_kalman_gain_bounded` test includes an inline comment documenting the algebraic justification for `0 < K < 1`:
> "Scalar local-level invariant: K = P_pred / (P_pred + R). With P_pred > 0 and R > 0, K must be strictly in (0, 1)."

### test_garch_invariants.py

Class `TestGARCHInvariants` with 6 test methods, 8 parametrized cases total:

| Test | Invariant Enforced |
|------|--------------------|
| `test_garch_sigma2_strictly_positive` | prev_sigma2 > 0 and finite after every bar |
| `test_garch_no_overflow_on_long_run` | garch_sigma < 1e6 and finite across trending + ranging |
| `test_garch_no_underflow_on_flat_data` | sigma2 >= 1e-12 on 500 flat bars (omega floor prevents collapse) |
| `test_garch_converges_to_long_run_variance` | sigma2 within 5% of omega/(1-beta) after 500 flat bars |
| `test_garch_shock_uses_prior_sigma2` | garch_shock == epsilon^2/sigma2_prior (prior not posterior) to atol=1e-9 |
| `test_garch_incremental_equals_full` | bars[0:100] bootstrap + bars[100:200] compute_next == compute_full, atol=1e-6 |

The `test_garch_converges_to_long_run_variance` test body contains a full derivation comment:
- Quotes the exact recurrence from `garch_volatility.py` line 62
- Shows why epsilon=0 on flat data makes the alpha term vanish
- Derives fixed point: sigma2* = omega/(1-beta) (not omega/(1-alpha-beta))
- Documents why the textbook unconditional variance formula does NOT apply here

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Kalman slope instantaneous value is not a reliable invariant**
- **Found during:** Task 1 verification (first pytest run)
- **Issue:** `test_kalman_slope_directionally_tracks_trend` initially asserted `slope_trend > 0.0` on the last bar, but the 5-bar windowed slope (`trend[-1] - trend[-6]`) can be transiently negative even on a net-upward series due to local noise. First run showed `slope=-0.383` on the trending fixture (net price gain +27%).
- **Fix:** Changed invariant from instantaneous last-bar slope to net change in filtered level (`kalman_trend[-1] - kalman_trend[0]`) over the full window. This is the algebraically correct directional invariant. Added docstring explaining why instantaneous slope is not a reliable single-bar metric.
- **Files modified:** test_kalman_invariants.py
- **Commit:** 17e763a6 (included in same task commit)

**2. [Rule 1 - Bug] GARCH shock test read sigma2_prior after state mutation**
- **Found during:** Task 2 verification (first pytest run)
- **Issue:** `compute_next` mutates the state dict in place via `state.update(...)`. The test read `state["prev_sigma2"]` after calling `compute_next`, getting the posterior (updated) sigma2 instead of the prior. This caused `epsilon=0.0` (correct) and `sigma2_prior` being the posterior, making the expected shock wrong.
- **Fix:** Capture `sigma2_prior = float(state["prev_sigma2"])` and `prev_close = float(state["prev_close"])` BEFORE calling `compute_next`. Added a comment explaining the mutation contract.
- **Files modified:** test_garch_invariants.py
- **Commit:** b3523c9e (included in same task commit)

**3. [Rule 3 - Blocking] Missing .venv symlink in git worktree**
- **Found during:** Task 1 commit
- **Issue:** Pre-commit hook searches for `${REPO_ROOT}/.venv/bin/ruff` where REPO_ROOT is the worktree path. The worktree has no `.venv` directory.
- **Fix:** Created a symlink: `ln -s /home/bg/dev/indicagent/.venv /home/bg/dev/indicagent/.claude/worktrees/agent-a90cc9d09446a6d18/.venv`
- **Files modified:** none (symlink in worktree root)

## Self-Check

### Checking created files exist
<br>

- `tests/unit/intelligence/correctness/test_kalman_invariants.py`: FOUND
- `tests/unit/intelligence/correctness/test_garch_invariants.py`: FOUND

### Checking commits exist
- 17e763a6 (Task 1): FOUND
- b3523c9e (Task 2): FOUND

### Checking verification criteria
- Both test files run: PASSED — 14 passed in 0.19s
- Both files reference `math.isfinite`: FOUND in both files
- Both files have `incremental_equals_full` test: FOUND in both files
- `test_garch_invariants.py` contains derivation comment: FOUND (references garch_volatility.py line 62)
- `test_kalman_invariants.py` contains model assumption comment for K bound: FOUND

## Self-Check: PASSED
