---
phase: 124
plan: "03"
subsystem: intelligence/trading
tags: [i7-plugin, ofi-continuation, structural-rewrite, signal-quality, acceleration-detection]
dependency_graph:
  requires: [124-01]
  provides: [ofi_continuation structural trigger, EWMA acceleration detection, volume spike trigger]
  affects: [signal_events.setup_plugin=trad_OFIContinuation]
tech_stack:
  added: []
  patterns: [OFIContinuationState dataclass, deque EWMA buffer, deduplicate_event trigger]
key_files:
  created: []
  modified:
    - src/intelligence/trading/ofi_continuation.py
    - tests/unit/intelligence/test_ofi_continuation.py
decisions:
  - OFI streak demoted to context filter; acceleration/thrust event is the trigger (aligns with D-02 in 124-CONTEXT.md)
  - deduplicate_event(direction) replaces onset_guard -- fires per structural thrust, not per streak crossing
  - EWMA acceleration threshold = mag_floor * 0.10 (second derivative must exceed 10% of floor to avoid noise)
  - Volume spike threshold = 2.0x average (vol_ratio from volume_sma_20 feature)
  - EWMA buffer only accumulates on bars that pass the magnitude gate (noise suppression)
metrics:
  duration: ~30m
  completed: "2026-06-14T23:04:25Z"
  tasks: 5
  files: 2
---

# Phase 124 Plan 03: OFIContinuation Structural Rewrite Summary

OFIContinuation rewritten to fire on EWMA acceleration (second derivative) or volume spike thrust on top of sustained OFI flow; OFI streak demoted to context filter only.

## What Was Built

### OFIContinuationState Dataclass (Task 1)

Added `OFIContinuationState` with `ewma_buffer: deque(maxlen=20)` and `last_acceleration_bar: int | None`. Factory method `_get_ofi_state(symbol, tf)` provides lazy per-(symbol, tf) isolation. `_accel_state: dict[str, OFIContinuationState]` field on the plugin.

### EWMA Acceleration Detection (Task 2)

Second derivative of `ofi_ewma_20` computed from the buffer:
- `acceleration = (buf[-1] - buf[-2]) - (buf[-2] - buf[-3])`
- Directional alignment required: acceleration must point the same direction as current flow
- Threshold: `abs(acceleration) >= mag_threshold * 0.10` (10% of per-instrument floor)
- Buffer must have `>= 5` entries before acceleration is computable

### Volume Spike as Alternative Trigger (Task 3)

`vol_ratio = current_vol / vol_sma_20` where `vol_sma_20` comes from I1 features. If `vol_ratio >= 2.0`, volume spike confirmed. OR logic: `acceleration_confirmed OR volume_spike` to qualify as a structural thrust bar.

### Gate Reordering (Task 4)

Gate order in `compute_full()`:
1. Magnitude gate FIRST -- `abs(ofi_ewma_20) < mag_threshold` rejects noise
2. Update EWMA buffer (after magnitude gate -- noise bars excluded from history)
3. Structural trigger SECOND -- acceleration OR volume spike required
4. Context filter THIRD -- `count >= min_bars` (streak still needed as precondition)
5. ATR + trade frame viability
6. `deduplicate_event(direction)` SIXTH -- replaces `onset_guard`

`onset_guard` fully removed. `deduplicate_event` fires once per structural event per direction, allows re-fire after `_DEDUP_MIN_BARS` active-condition calls.

### Unit Tests (Task 5)

Complete rewrite of `tests/unit/intelligence/test_ofi_continuation.py`:

- `test_streak_only_no_signal`: constant EWMA (zero second derivative) + no volume spike -> zero signals even after 25 bars. Verifies the fundamental invariant.
- `test_streak_with_acceleration_fires_once`: builds streak via 15 stable bars, then delivers increasing-delta sequence (step_increment = 125 for ES, threshold = 50). Fires on acceleration bar.
- `test_volume_spike_fires_once`: builds streak via 11 stable bars at vol_sma=1000, then 15 bars at vol=2500 (2.5x). Fires exactly once; `deduplicate_event` suppresses same-direction re-fire.
- `test_separate_symbols_have_independent_state`: ES calls do not populate NQ EWMA buffer.
- Helper `_fire_via_acceleration()`: calibrates step_increment to `floor * 0.25` (2.5x the threshold) to produce reliable acceleration irrespective of per-instrument floor.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] EWMA buffer only populated after magnitude gate**

- **Found during:** Task 2 implementation review
- **Issue:** Plan said "Update EWMA buffer: state = self._get_ofi_state(symbol, tf); if ofi_ewma: state.ewma_buffer.append(float(ofi_ewma))" but placing this before the magnitude gate would fill the buffer with sub-floor noise values, contaminating the second derivative calculation with bars that shouldn't count.
- **Fix:** Buffer update placed after magnitude gate -- only valid-magnitude bars accumulate.
- **Files modified:** src/intelligence/trading/ofi_continuation.py
- **Commit:** c1d01abd

**2. [Rule 1 - Bug] Existing tests broken by structural rewrite**

- **Found during:** Task 5 verification
- **Issue:** All existing `TestOnsetBehavior` tests used constant EWMA which produces zero acceleration; with the new trigger model, these tests would either all fail or silently pass for wrong reasons.
- **Fix:** Complete test infrastructure rewrite. Added `_fire_via_acceleration()` with calibrated step_increment. `TestOnsetBehavior` renamed to `TestStructuralTrigger` with semantically correct tests. `_make_frames()` extended with `volume` and `vol_sma_20` parameters.
- **Files modified:** tests/unit/intelligence/test_ofi_continuation.py
- **Commit:** 2c65da88

**3. [Rule 1 - Bug] NQ acceleration test required calibrated step_increment**

- **Found during:** Task 5 test run
- **Issue:** NQ floor = 200, threshold = 20. Initial `_fire_via_acceleration` used `step_increment = ofi_ewma_20_final * 0.05` which gave acceleration < threshold for small final values.
- **Fix:** `step_increment = floor * 0.25` -- always 2.5x the threshold regardless of final EWMA value.
- **Files modified:** tests/unit/intelligence/test_ofi_continuation.py
- **Commit:** 2c65da88

## Self-Check: PASSED

- FOUND: src/intelligence/trading/ofi_continuation.py
- FOUND: tests/unit/intelligence/test_ofi_continuation.py
- FOUND: feat commit c1d01abd (OFIContinuation structural rewrite)
- FOUND: test commit 2c65da88 (test rewrite)
- 19/19 unit tests pass
