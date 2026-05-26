---
phase: 100-plugin-shared-infrastructure
plan: "04"
subsystem: intelligence-plugins
tags: [plugin-infra, incremental-state, mixin, adx, stochastic, williams-r, mfi, volume-zscore, keltner, unit-tests, replay-parity]
dependency_graph:
  requires:
    - phase: 100-02
      provides: IncrementalMixin with ATR reference implementation and mutable-in-place state contract
    - phase: 100-03
      provides: shared utility functions (wilders_update, update_ema, get_main_df) in mixins.py
  provides:
    - 6 plugins migrated to IncrementalMixin (ADX, Stochastic, WilliamsR, MFI, VolumeZscore, Keltner)
    - Replay parity tests proving compute_full(N) == seed + compute_next x N for all 6
    - Conformance tests for all 7 IncrementalMixin plugins
    - Latency benchmark showing compute_next 0.008-0.012ms per plugin
  affects:
    - src/intelligence/features/i1_indicators/adx.py
    - src/intelligence/features/i1_indicators/stochastic.py
    - src/intelligence/features/i1_indicators/williams_r.py
    - src/intelligence/features/i1_indicators/mfi.py
    - src/intelligence/trading/volume_zscore.py
    - src/intelligence/features/i1_indicators/keltner.py
    - tests/unit/intelligence/test_incremental_mixin.py
tech_stack:
  added: []
  patterns:
    - IncrementalMixin
    - Wilder-accumulator-archetype (ADX - same as ATR)
    - rolling-window-min-max-archetype (Stochastic, WilliamsR)
    - windowed-deque-archetype (MFI, VolumeZscore)
    - EMA-chain-plus-ATR-hybrid-archetype (Keltner)
key_files:
  created: []
  modified:
    - src/intelligence/features/i1_indicators/adx.py
    - src/intelligence/features/i1_indicators/stochastic.py
    - src/intelligence/features/i1_indicators/williams_r.py
    - src/intelligence/features/i1_indicators/mfi.py
    - src/intelligence/trading/volume_zscore.py
    - src/intelligence/features/i1_indicators/keltner.py
    - tests/unit/intelligence/test_incremental_mixin.py
key_decisions:
  - "N_SEED=30 for replay parity tests (not 20) -- ADX requires 29 bars minimum (max(periods)*2+1); using 30 covers all plugin min_lookback requirements cleanly"
  - "VolumeZscore _compute_full_core returns sentinel {volume_z_score: 0.0} on insufficient data (not {}) -- preserves original plugin behavior for insufficient-data case"
  - "ADX _seed_state re-runs full computation to extract Wilder accumulator values -- no coupling to _compute_full_core internals, matches ATR pattern"
  - "Stochastic _seed_state signature adapted from (frames, high, low, close, state) to (frames) -> dict -- mixin contract requires single-arg form"
metrics:
  duration_minutes: 30
  completed: "2026-05-21"
  tasks_completed: 3
  tasks_total: 3
  files_changed: 7
---

# Phase 100 Plan 04: Six Plugin IncrementalMixin Migration Summary

ADX, Stochastic, WilliamsR, MFI, VolumeZscore, and Keltner migrated to IncrementalMixin across 4 state archetypes; replay parity tests confirm compute_full(100) == seed(30) + compute_next x 70 within 1e-6; latency benchmark shows compute_next 0.008-0.012ms per plugin.

## Performance

- **Duration:** ~30 min
- **Started:** 2026-05-21T16:54:00Z
- **Completed:** 2026-05-21T16:59:00Z
- **Tasks:** 3
- **Files modified:** 7

## Accomplishments

- All 6 "easy" plugins migrated to IncrementalMixin following the ATR reference pattern
- ADX and Keltner use shared `wilders_update()` and `update_ema()` from plan 03
- MFI preserves Phase 093 correctness fix (all-positive money flow returns 100.0)
- 46 tests pass: 12 contract tests (plan 02), 28 conformance tests (7 plugins x 4 tests), 6 replay parity tests, 1 benchmark (deselected in CI with -m not benchmark)
- Latency benchmark: compute_next is 30-60x faster than compute_full per plugin (0.01ms vs 0.3-0.5ms)

## Task Commits

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Migrate ADX and Stochastic to IncrementalMixin | 81150d86 | adx.py, stochastic.py |
| 2 | Migrate WilliamsR, MFI, VolumeZscore, Keltner to IncrementalMixin | 31db24d7 | williams_r.py, mfi.py, volume_zscore.py, keltner.py |
| 3 | Add conformance, replay parity, and latency benchmark tests | a0c6582e | test_incremental_mixin.py |

## Files Created/Modified

- `src/intelligence/features/i1_indicators/adx.py` - Migrated to IncrementalMixin (Wilder's accumulator archetype); uses wilders_update for smoothed_plus_dm, smoothed_minus_dm, smoothed_tr, adx (15 call sites)
- `src/intelligence/features/i1_indicators/stochastic.py` - Migrated to IncrementalMixin (rolling window min/max archetype); deque state: high_window, low_window, k_values
- `src/intelligence/features/i1_indicators/williams_r.py` - Migrated to IncrementalMixin (rolling window min/max archetype); deque state: high_window, low_window
- `src/intelligence/features/i1_indicators/mfi.py` - Migrated to IncrementalMixin (windowed money flow deque archetype); preserves Phase 093 fix; state: prev_tp, pos_mf_window, neg_mf_window
- `src/intelligence/trading/volume_zscore.py` - Migrated to IncrementalMixin (deque history archetype); _compute_full_core returns sentinel {volume_z_score: 0.0} on insufficient data
- `src/intelligence/features/i1_indicators/keltner.py` - Migrated to IncrementalMixin (EMA chain + ATR hybrid); removes _state dataclass field; uses update_ema() and wilders_update()
- `tests/unit/intelligence/test_incremental_mixin.py` - Added 3 test classes: TestMigratedPluginConformance (28 parametrized tests over 7 plugins), TestMigratedPluginReplayParity (6 parity tests), TestLatencyBenchmark

## Decisions Made

- **N_SEED=30 for replay parity tests**: ADX min requirement is `max(periods)*2+1 = 29` bars to produce output. Seeding with 20 bars returned empty dict (no state). Changed to 30 to cover all plugins cleanly.
- **VolumeZscore sentinel return**: `_compute_full_core` returns `{"volume_z_score": 0.0}` (not `{}`) on insufficient data to preserve the original plugin's behavior. This means the mixin's `if not result: return {}` guard is never triggered -- the sentinel value flows through.
- **ADX _seed_state re-runs full Wilder computation**: Consistent with ATR reference pattern. The full accumulation loop is re-executed to extract final state values rather than passing internal state between methods.
- **Stochastic _seed_state signature adapted**: Original had `(high_col, low_col, close_col, state) -> None` mutation. Mixin requires `(frames) -> dict`. Adapted to extract columns from frames and return state dict.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Increased N_SEED from 20 to 30 in replay parity tests**
- **Found during:** Task 3 (tests)
- **Issue:** ADX requires `max(periods)*2+1 = 29` minimum bars. N_SEED=20 returned empty dict with no `_state` key, causing test assertion failure.
- **Fix:** Changed `N_SEED = 20` to `N_SEED = 30` and `N_TOTAL = 50` to `N_TOTAL = 100`
- **Files modified:** tests/unit/intelligence/test_incremental_mixin.py
- **Verification:** All 6 replay parity tests pass
- **Committed in:** a0c6582e (Task 3 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - test data sizing)
**Impact on plan:** Necessary correction for ADX's higher minimum data requirement. No scope change.

## Issues Encountered

- VolumeZscore was located at `src/intelligence/trading/volume_zscore.py`, not `src/intelligence/features/trading/volume_zscore.py` as referenced in the plan. Used the actual path.
- Worktree had no `.venv` symlink -- pre-commit hook uses `${REPO_ROOT}/.venv/bin/ruff`. Created symlink to `/home/bg/dev/indicagent/.venv` to resolve.

## Verification Results

```
pytest tests/unit/intelligence/test_plugin_incremental.py -- 27 passed
pytest tests/unit/intelligence/test_incremental_mixin.py -m "not benchmark" -- 46 passed, 1 deselected

grep -c "IncrementalMixin" adx.py stochastic.py williams_r.py mfi.py volume_zscore.py keltner.py
-- each: >= 4 (import + class declaration + docstring refs)

grep -c "self._state" all 6 files -- 0 0 0 0 0 0

Latency benchmark (compute_next mean):
  ATR: 0.0084ms, ADX: 0.0124ms, Stochastic: 0.0092ms
  WilliamsR: 0.0105ms, MFI: 0.0087ms, VolumeZscore: 0.0108ms
  Keltner: 0.0082ms -- all well under 1ms threshold
```

## Next Phase Readiness

- Mixin pattern validated across 4 state archetypes (Wilder accumulator, rolling window min/max, windowed deque, EMA+ATR hybrid)
- 7 plugins on IncrementalMixin with full test coverage; regression guard in place
- Phase 100-05 (get_main_df migration) can proceed independently
- More complex plugins (RSI, MACD, Bollinger) can now be migrated using same patterns

## Self-Check: PASSED

Files exist on disk:
- src/intelligence/features/i1_indicators/adx.py -- FOUND
- src/intelligence/features/i1_indicators/stochastic.py -- FOUND
- src/intelligence/features/i1_indicators/williams_r.py -- FOUND
- src/intelligence/features/i1_indicators/mfi.py -- FOUND
- src/intelligence/trading/volume_zscore.py -- FOUND
- src/intelligence/features/i1_indicators/keltner.py -- FOUND
- tests/unit/intelligence/test_incremental_mixin.py -- FOUND

Commits present in git log:
- 81150d86 feat(100-04): migrate ADX and Stochastic plugins to IncrementalMixin -- FOUND
- 31db24d7 feat(100-04): migrate WilliamsR, MFI, VolumeZscore, Keltner to IncrementalMixin -- FOUND
- a0c6582e test(100-04): add conformance, replay parity, and latency benchmark tests -- FOUND

---
*Phase: 100-plugin-shared-infrastructure*
*Completed: 2026-05-21*
