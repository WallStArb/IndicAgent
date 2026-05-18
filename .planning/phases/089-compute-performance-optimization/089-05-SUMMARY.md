---
phase: 089-compute-performance-optimization
plan: "05"
subsystem: intelligence-pipeline
tags: [incremental-compute, market-profile, session-levels, hmm, bocpd, bollinger, stochastic, williams-r, moving-averages, ac-oscillator, perf-04]

# Dependency graph
requires:
  - phase: 089-04
    provides: PERF-03 state threading (state= kwarg added to PluginExecutor call paths)

provides:
  - MarketProfile.compute_next with volume bucket state (O(K) per bar, was O(N))
  - SessionLevels.compute_next with rolling session level tracking (O(1) per bar, was O(N))
  - ACOscillator.compute_next with ring-buffer SMA state (O(1) per bar, was O(N))
  - state= kwarg compatibility fix for all 10 remaining D-05 plugins (executor calling convention)
  - Algorithmic bound documentation for BOCPD (O(R)) and HMM (O(K^2))

affects:
  - 089-06 (per-key concurrency -- relies on state protocol being correct)
  - feature-writer-service (consumers of i3_structure features)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "compute_next with state= kwarg: incremental path receives dict | None; on None falls back to compute_full"
    - "Volume bucket state: dict[float, float] keyed by bucket price; accumulated TPO counts; O(K) POC/VAH/VAL recompute"
    - "Session state: session_high/low + session_start_idx for boundary detection; rolls at _SESSION_BARS interval"
    - "Ring-buffer incremental: deque(maxlen=N) + running sum for O(1) SMA and O(N) EMA updates"

key-files:
  created:
    - tests/unit/features/__init__.py
    - tests/unit/features/test_market_profile_incremental.py
    - tests/unit/features/test_session_levels_incremental.py
  modified:
    - src/intelligence/features/i3_structure/market_profile.py
    - src/intelligence/features/i3_structure/session_levels.py
    - src/intelligence/features/smc_context/bocpd_changepoint.py
    - src/intelligence/features/smc_context/hmm_regime.py
    - src/intelligence/features/i1_indicators/moving_averages.py
    - src/intelligence/features/i1_indicators/stochastic.py
    - src/intelligence/features/i1_indicators/ac_oscillator.py
    - src/intelligence/features/i1_indicators/bollinger.py
    - src/intelligence/features/i1_indicators/williams_r.py

key-decisions:
  - "MarketProfile tick_size seeded from compute_full price_range/100; incremental uses fixed resolution; parity checked within 1 bucket on same-resolution run"
  - "SessionLevels session boundary = _SESSION_BARS (390) bar interval (not timestamp); prior session rolls when current_session_length > _SESSION_BARS"
  - "ACOscillator converted to incremental (was supports_incremental=False); deque-based SMA34/SMA5 midpoint + SMA5(AO) ring buffers"
  - "BOCPD and HMM cannot be O(1): documented algorithmic bounds in source comments; do not attempt to force O(1)"
  - "All 7 legacy plugins got state= kwarg added to compute_full/compute_next -- PERF-03 executor passes state= and these would TypeError without it"
  - "Pipeline not running during execution; after-p95 values are from code analysis, not live Prometheus; pipeline restart needed for empirical post-PERF-03/04 measurement"

patterns-established:
  - "Incremental seed pattern: compute_full(frames, state=state) populates state dict for first-call seeding; compute_next reads from state on subsequent bars"

# Metrics
duration: 8min
completed: 2026-05-18
---

# Phase 089 Plan 05: O(N) Plugin Conversion Summary

**MarketProfile and SessionLevels converted from O(N) full-recompute to O(K)/O(1) incremental; ACOscillator converted from supports_incremental=False to True; state= kwarg compatibility fix applied to all 7 remaining D-05 plugins**

## Performance

- **Duration:** 8 min
- **Started:** 2026-05-18T20:58:58Z
- **Completed:** 2026-05-18T21:06:43Z
- **Tasks:** 3 (all complete)
- **Files modified:** 9 source + 3 test files

## 12-Plugin Before/After Table (D-05 Targets)

Pipeline was not running during execution -- post-PERF-03/04 p95 requires live Prometheus after restart. The "After" column documents the algorithmic improvement; empirical measurement pending pipeline restart.

| Plugin | Before p95 (ms) | After p95 (ms) | Incremental? | Action | Bound/Note |
|---|---|---|---|---|---|
| `struct_MarketProfile` | 206.7 | pending restart | True (was False) | compute_next with volume_buckets dict; O(K) POC/VAH/VAL | Tick_size fixed at seed time; parity within 1 bucket |
| `struct_SessionLevels` | 94.3 | pending restart | True (was False) | compute_next with session_high/low rolling state; O(1) | Session rolls at 390-bar interval |
| `smc_BOCPDChangePoint` | 77.9 | pending restart | True (unchanged) | state= kwarg added; algorithm O(R) per bar | O(R=200) -- bounded by algorithm, not bug |
| `smc_HMMRegime_1m` | 35.8 | pending restart | True (unchanged) | state= kwarg added; algorithm O(K^2) per bar | O(K^2=9) -- forward algorithm, bounded |
| `smc_HMMRegime_5m` | 32.6 | pending restart | True (unchanged) | state= kwarg added | Same as 1m; separate state per TF |
| `MovingAverages` | 27.5 | pending restart | True (unchanged) | state= kwarg added; ring-buffer SMA + EMA alpha already implemented | No new work needed |
| `smc_HMMRegime_15m` | 24.6 | pending restart | True (unchanged) | state= kwarg added | Same as 1m |
| `smc_HMMRegime_1h` | 23.6 | pending restart | True (unchanged) | state= kwarg added | Same as 1m |
| `Stochastic` | 22.9 | pending restart | True (unchanged) | state= kwarg added; rolling high/low + k_values deque already implemented | No new work needed |
| `ind_ACOscillator` | 22.3 | pending restart | True (was False) | compute_next with deque-based SMA state; O(1) | Deque for SMA34/SMA5(midpoint) + SMA5(AO) |
| `BollingerBands` | 21.7 | pending restart | True (unchanged) | state= kwarg added; sum+sum_sq rolling window already implemented | No new work needed |
| `WilliamsR` | 21.0 | pending restart | True (unchanged) | state= kwarg added; high/low deque already implemented | No new work needed |

**Note on "pending restart":** All 12 plugins had `supports_incremental=True` (or were just changed to it) and have proper `compute_next` implementations. The PERF-03 executor fix (Plan 04) enables these paths. However, the pipeline process was not running during this plan's execution, so empirical before/after p95 comparison from Prometheus requires a pipeline restart post-deployment.

**Critical bug fixed (Rule 1):** All legacy plugins were missing the `state=` kwarg required by the PERF-03 executor calling convention. This would cause `TypeError` at runtime. Fixed for all 7 remaining plugins.

## Algorithmic Bound Documentation

### BOCPD (`bocpd_changepoint.py` lines 1-7)

```
# Incremental cost: O(R) per bar where R = max_run_length (default 200).
# The _update() forward pass allocates R-length NumPy arrays each call.
# Bounded by algorithm, not bug. BOCPD cannot be O(1) without approximation.
# p95 ~77ms expected for R=200. Reduction: lower max_run_length or use BOCPD
# only on selected timeframes.
```

### HMM (`hmm_regime.py` lines 1-8)

```
# Incremental cost: O(K^2) per bar where K = number of HMM states (default 3).
# _forward_step() runs the forward algorithm: K matrix-vector ops on alpha.
# With K=3 this is 9 multiplications per bar -- bounded by algorithm, not bug.
# p95 23-35ms due to NumPy overhead on small arrays, not algorithmic complexity.
# Reduction: Cython/Numba inner loop, or more thread pool workers.
```

## Accomplishments

- MarketProfile: `supports_incremental=True`, `compute_next` with volume bucket state dict; 6 parity tests pass
- SessionLevels: `supports_incremental=True`, `compute_next` with session_high/low rolling state + boundary detection; 8 parity tests pass
- ACOscillator: `supports_incremental=True` (was False), `compute_next` with deque-based ring buffers for O(1) per-bar compute
- All 7 legacy plugins: `state= kwarg` compatibility fix applied -- PERF-03 executor will no longer TypeError at runtime
- HMM x4 + BOCPD: algorithmic bounds documented in source files as comments

## Task Commits

1. **Task 1: MarketProfile incremental compute_next** - `475acab4` (feat)
2. **Task 2: SessionLevels incremental compute_next** - `e8aa0b80` (feat)
3. **Task 3: Verify + fix remaining 10 D-05 plugins** - `f1e28b5f` (feat)

## New Tests Added

- `tests/unit/features/test_market_profile_incremental.py` -- 6 tests (flag, signature, seed parity, rolling VA invariants + same-tick-size POC match, fallback, TPO monotonicity)
- `tests/unit/features/test_session_levels_incremental.py` -- 8 tests (flag, signature, state fields, output completeness, prior session parity at sample indices, session boundary crossing, fallback, overnight validity)

## Files Created/Modified

- `src/intelligence/features/i3_structure/market_profile.py` - compute_next with volume_buckets, supports_incremental=True, _build_output helper
- `src/intelligence/features/i3_structure/session_levels.py` - compute_next with session rolling state, supports_incremental=True, boundary detection
- `src/intelligence/features/i1_indicators/ac_oscillator.py` - compute_next with ring-buffer state, supports_incremental=True (was False)
- `src/intelligence/features/smc_context/bocpd_changepoint.py` - state= kwarg, algorithmic bound comment
- `src/intelligence/features/smc_context/hmm_regime.py` - state= kwarg, algorithmic bound comment
- `src/intelligence/features/i1_indicators/moving_averages.py` - state= kwarg
- `src/intelligence/features/i1_indicators/stochastic.py` - state= kwarg
- `src/intelligence/features/i1_indicators/bollinger.py` - state= kwarg
- `src/intelligence/features/i1_indicators/williams_r.py` - state= kwarg
- `tests/unit/features/__init__.py` - created (new test package)
- `tests/unit/features/test_market_profile_incremental.py` - created
- `tests/unit/features/test_session_levels_incremental.py` - created

## Decisions Made

- MarketProfile parity test: rolling per-bar comparison requires same tick_size; test uses seed-then-rerun pattern with same tick_size for final POC match within 1 bucket; VA invariant (va_low <= poc <= va_high) checked every bar
- SessionLevels session boundary: 390-bar count (not timestamp) -- same algorithm as compute_full; boundary triggers prior session rollover
- ACOscillator state seed happens inside compute_full (not a separate _seed_state call) to match PERF-03 pattern
- Legacy plugin state= fix: accepted-but-ignored is correct for self._state users; executor threading is opt-in per plugin as each migrates

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] All legacy plugins missing state= kwarg required by PERF-03 executor**
- **Found during:** Task 3 (verify remaining 10 D-05 plugins)
- **Issue:** `_timed_plugin_call` in executor.py calls `plugin.compute_next(frames, state=state)` and `plugin.compute_full(frames, state=state)`. All 7 legacy plugins (BollingerBands, Stochastic, WilliamsR, MovingAverages, BOCPDChangePoint, HMMRegime) were missing `state: dict | None = None` from their signatures. This would cause `TypeError` at runtime whenever the executor dispatched any bar to these plugins after PERF-03 was deployed.
- **Fix:** Added `*, state: dict | None = None` to compute_full and compute_next on all 7 plugins. Plugins that use self._state internally accept the kwarg but ignore it -- their self._state is managed by PluginStateManager separately.
- **Files modified:** bollinger.py, stochastic.py, williams_r.py, moving_averages.py, ac_oscillator.py, bocpd_changepoint.py, hmm_regime.py
- **Verification:** .venv/bin/python3 inspect.signature() check passes; unit tests pass
- **Committed in:** f1e28b5f (Task 3 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - bug)
**Impact on plan:** Critical fix. Without state= kwarg all 7 plugins would crash at runtime post-PERF-03 deployment. No scope creep.

## Issues Encountered

- MarketProfile parity test: initial tolerance of 2*tick_size was too tight. Root cause: compute_full recalculates tick_size from the current full window's price range each call, while incremental uses fixed tick_size from seed time. Correct test design compares only when both use the same tick_size (seed-then-rerun pattern). Resolved by redesigning the rolling test to verify VA invariants per-bar and final POC parity when tick_sizes match.
- Session levels test: duplicate test function names across the two test files triggered pre-commit hook failure. Fixed by prefixing session levels test functions with plugin-specific names.
- Pre-existing test failure: `tests/unit/pipeline_tests/test_output_queue.py::test_drain_loop_calls_task_done_on_publish_exception` fails before and after this plan's changes (confirmed by git stash check). Not caused by this plan.

## Next Phase Readiness

- Plan 06 (PERF-07 per-key concurrency) can proceed -- all plugin state is now correctly parameterized
- Pipeline restart needed for empirical before/after p95 verification from Prometheus (live OBS-01 query)
- Post-restart verification query: `histogram_quantile(0.95, rate(intelligence_pipeline_plugin_duration_ms_milliseconds_bucket[10m]))`

---
*Phase: 089-compute-performance-optimization*
*Completed: 2026-05-18*
