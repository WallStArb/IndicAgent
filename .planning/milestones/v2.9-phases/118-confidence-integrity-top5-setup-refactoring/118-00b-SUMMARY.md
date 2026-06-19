---
plan: "118-00b"
phase: "118-confidence-integrity-top5-setup-refactoring"
status: complete
completed: "2026-06-09"
subsystem: "intelligence/trading"
tags: ["confidence", "intrinsic", "composite", "contract-test", "i7"]
dependency_graph:
  requires: ["118-00"]
  provides: ["wave-0-contract-test", "intrinsic-composite-restructure"]
  affects: ["momentum_breakout", "squeeze_expansion", "trend_following", "test_i7_extrinsic_contract"]
tech_stack:
  added: []
  patterns: ["intrinsic-only composite", "factor-clamped [0,1]", "parametrized contract test"]
key_files:
  created:
    - tests/unit/intelligence/test_i7_extrinsic_contract.py
  modified:
    - src/intelligence/trading/momentum_breakout.py
    - src/intelligence/trading/squeeze_expansion.py
    - src/intelligence/trading/trend_following.py
    - tests/unit/intelligence/test_i7_exhaustion_wiring.py
decisions:
  - "FVG/OB/CHoCH/BOS structural signals kept as intrinsic confirmations for supply_demand_setup and liquidity_sweep_reclaim; contract test perturbation set scoped to CTF + exhaustion only"
  - "trend_following uses 3-factor composite (trend_conf+trend_strength+swing_pattern) since swing_pattern is available and gated upon"
  - "squeeze_expansion retains trend_regime read for supporting factors (logging only) but removed from confidence composite"
metrics:
  duration: "~20 minutes"
  completed: "2026-06-09"
  tasks: 2
  files: 4
---

# Phase 118 Plan 00b: Composite Restructure + Contract Test Summary

Restructured 3 composite-formula plugins onto intrinsic-only weighted composites and added a parametrized contract test covering the full Wave 0 blast radius (15 plugins).

## What Was Built

**Task 1 - Composite restructures:**

- `momentum_breakout`: removed `regime_score` (HMM composite factor, 15%), zone friction penalty (supply/demand zone subtractions), and `apply_exhaustion_guard`. New 3-factor intrinsic composite: `0.40 * roc_score + 0.35 * vol_score + 0.25 * break_margin`. Each factor clamped to [0,1] before weighting.

- `squeeze_expansion`: removed `regime_score` (HMM composite factor, 20%) and `apply_exhaustion_guard`. New 3-factor intrinsic composite: `0.35 * squeeze_bars_score + 0.35 * vol_expansion_score + 0.30 * momentum_score`. Each factor clamped to [0,1].

- `trend_following`: removed `trend_regime` (35%) and `ctf_score` (20%) from composite, removed zone friction penalty and `apply_exhaustion_guard`. New 3-factor intrinsic composite: `0.45 * trend_conf + 0.35 * trend_strength + 0.20 * swing_pattern`. `trend_regime` retained as gate (direction determination and entry gating) but excluded from confidence arithmetic. `ctf_score` retained for `supporting.append("cross_timeframe_aligned")` logging only.

- Removed 3 invalidated exhaustion guard tests from `test_i7_exhaustion_wiring.py` that tested now-stripped extrinsic behavior.

**Task 2 - Contract test (`test_i7_extrinsic_contract.py`):**

Three test groups:

1. `test_extrinsic_perturbation_does_not_change_confidence` - parametrized over 12 fireable Wave 0 plugins. Builds a baseline firing scenario, then perturbs with CTF+exhaustion extrinsic keys, asserts `abs(A - B) < 1e-9`. Passes for all 12 fireable plugins. 3 plugins skipped with explicit reasons (failed_breakout: requires BOS state machine; orb15/orb30: require session timing gate).

2. `test_confidence_within_bounds` - asserts returned confidence in `[0.0, 0.95]` for all 12 fireable plugins.

3. `test_extrinsic_still_captured_in_features_snapshot` - proves `ctf_score=0.8` set in features appears in `features_snapshot["ctf_score"]` via `capture_signal_features()`, confirming the capture-vs-confidence separation.

## Key Design Decision

FVG/OB/CHoCH/BOS structural SMC signals are NOT in the extrinsic perturbation set. For `supply_demand_setup` (ICT Act 1-2-3 model) and `liquidity_sweep_reclaim` (sweep quality confirmation), these are intrinsic structural confirmations that are part of the core pattern logic - not the extrinsic context signals targeted by Phase 118. Phase 118 targeted HMM weights, CTF scores, exhaustion boost/guard, and zone friction penalties.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical functionality] Removed 3 failing exhaustion guard tests**
- **Found during:** Task 1 verification
- **Issue:** `test_i7_exhaustion_wiring.py` had 3 tests for exhaustion guard behavior in momentum_breakout and trend_following that we just stripped. These were failing after the restructure.
- **Fix:** Removed the 3 test functions (`test_momentum_breakout_guard_penalty_applied_when_threshold_met`, `test_trend_following_guard_penalty_applied_when_threshold_met`, `test_trend_following_guard_suppresses_signal_when_confidence_drops_too_low`) that tested now-invalid extrinsic behavior. Consistent with how 118-00 removed 7 similar tests.
- **Files modified:** `tests/unit/intelligence/test_i7_exhaustion_wiring.py`
- **Commit:** `ebb05805`

**2. [Rule 1 - Bug] Narrowed extrinsic perturbation set in contract test**
- **Found during:** Task 2 test run
- **Issue:** Initial contract test included FVG/OB/CHoCH/BOS in the extrinsic perturbation keys. These legitimately modify confidence in supply_demand_setup (ICT model) and liquidity_sweep_reclaim (sweep quality). Test was failing for those two plugins.
- **Fix:** Removed FVG/OB/CHoCH/BOS from `_EXTRINSIC_KEYS`; added `_ZONE_PENALTY_KEYS` dict as documentation. Added explicit comment explaining the architectural distinction.
- **Files modified:** `tests/unit/intelligence/test_i7_extrinsic_contract.py`

## Self-Check: PASSED

Files verified to exist:
- `src/intelligence/trading/momentum_breakout.py`: FOUND
- `src/intelligence/trading/squeeze_expansion.py`: FOUND
- `src/intelligence/trading/trend_following.py`: FOUND
- `tests/unit/intelligence/test_i7_extrinsic_contract.py`: FOUND

Commits verified:
- `ebb05805`: FOUND (composite restructure)
- `75ba276e`: FOUND (contract test)

Invariants verified:
- compose_confidence present in all 3 restructured files: CONFIRMED
- Composite weights sum to 1.0: momentum_breakout (0.40+0.35+0.25=1.0), squeeze_expansion (0.35+0.35+0.30=1.0), trend_following (0.45+0.35+0.20=1.0): CONFIRMED
- All factors clamped to [0,1] before weighting: CONFIRMED
- Contract test: 25 passed, 3 skipped with explicit reasons: CONFIRMED

## Commits

- `ebb05805`: `refactor(118): composite restructure for momentum_breakout, squeeze_expansion, trend_following`
- `75ba276e`: `test(118): contract test — extrinsic perturbation leaves I7 confidence unchanged; extrinsic still captured`
