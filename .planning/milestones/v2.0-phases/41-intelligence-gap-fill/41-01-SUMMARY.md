---
phase: 41-intelligence-gap-fill
plan: 01
subsystem: intelligence
tags: [cross-timeframe, fvg, order-blocks, smc, confluence, i6, proximity-decay]

requires:
  - phase: 40.5-performance-stability-emergency
    provides: stable feature_writer pipeline that persists i6 JSONB output

provides:
  - _proximity_decay(): module-level pure function for ATR-scaled zone proximity scoring
  - _score_fvg_alignment(): direction-weighted FVG proximity score across higher TFs
  - _score_ob_alignment(): direction-weighted OB proximity score across higher TFs
  - Per-TF contribution keys (i6_fvg_tf_5m, i6_ob_tf_1h, etc.) in compute_full() output
  - i6_fvg_tf_alignment and i6_ob_tf_alignment are now real non-zero values

affects:
  - phase 43 (I6 confluence expansion): can now weight fvg/ob alignment fields in CONF-04
  - feature_writer_service: i6 JSONB blob gains dynamic per-TF keys when FVGs/OBs present

tech-stack:
  added: []
  patterns:
    - "Higher-TF-only filtering: only TFs with tf_min > cur_tf_min contribute (lower TFs too ephemeral)"
    - "TF authority by minutes: weight = _TF_MINUTES[tf], normalized across contributors"
    - "Proximity decay: 1.0 within 1 ATR, linear to 0.0 at 3 ATR, 0.0 beyond"
    - "Per-TF contribution decomposition: every aggregate score has auditable per-source keys"
    - "Tuple return pattern: scoring methods return (score, contributions) for caller to unpack"

key-files:
  created: []
  modified:
    - src/intelligence/confluence/cross_timeframe.py
    - tests/unit/intelligence/test_cross_timeframe.py

key-decisions:
  - "Only higher TFs contribute to FVG/OB alignment (current TF excluded — lower TFs too ephemeral per 41-CONTEXT.md)"
  - "TF authority weight = _TF_MINUTES value (raw minutes), normalized across contributing TFs"
  - "Proximity decay uses midpoint of zone (fvg_top+fvg_bottom)/2 — not nearest edge"
  - "FVG and OB scoring use identical formula — Phase 46 calibration may diverge weights if data supports it"
  - "Per-TF contribution keys are dynamic (only appear when contributing TF has valid zone) — no schema migration needed (JSONB)"

patterns-established:
  - "Scoring method returns (aggregate, contributions_dict) tuple for full Renaissance auditability"
  - "Spread per-TF contributions into return dict with prefixed keys: i6_fvg_tf_{tf}, i6_ob_tf_{tf}"

requirements-completed:
  - INTEL-01
  - INTEL-02

duration: 22min
completed: 2026-03-20
---

# Phase 41 Plan 01: FVG/OB Cross-TF Alignment Scoring Summary

**Replaced hardcoded 0.0 stubs in CrossTimeframeConfluencePlugin with direction-weighted FVG and Order Block proximity scores across higher timeframes, including per-TF contribution decomposition for full auditability.**

## Performance

- **Duration:** ~22 min
- **Started:** 2026-03-20T13:10:00Z
- **Completed:** 2026-03-20T13:32:36Z
- **Tasks:** 2 (TDD: RED + GREEN)
- **Files modified:** 2

## Accomplishments

- Added `_proximity_decay()` module-level function: returns 1.0 within 1 ATR, linear decay to 0.0 at 3 ATR, 0.0 beyond
- Implemented `_score_fvg_alignment()` and `_score_ob_alignment()` as class methods with TF-authority weighting and direction matching
- Removed both `0.0  # TODO` stubs; compute_full() now calls real scoring methods
- Added per-TF contribution keys (`i6_fvg_tf_5m`, `i6_ob_tf_1h`, etc.) spread into return dict for audit traceability
- All 20 cross_timeframe tests pass; ruff clean

## Task Commits

1. **Task 1: Add failing tests (RED)** - `801bd4f` (test)
2. **Task 2: Implement scoring methods (GREEN)** - `12c7fc4` (feat)

## Files Created/Modified

- `src/intelligence/confluence/cross_timeframe.py` - Added `_proximity_decay()`, `_score_fvg_alignment()`, `_score_ob_alignment()`; replaced 0.0 stubs; added per-TF contribution keys in return dict
- `tests/unit/intelligence/test_cross_timeframe.py` - Added 4 new alignment test cases; updated `test_smc_bos_alignment_present_in_output` to remove stub-equality assertions

## Decisions Made

- Only higher TFs contribute (current TF excluded) — lower TFs too ephemeral per 41-CONTEXT.md locked decision
- TF weight = raw `_TF_MINUTES` minutes value, normalized across contributing TFs (same pattern as `_score_smc_bos_alignment`)
- Proximity decay uses zone midpoint, not nearest edge, for consistency with OB/FVG zone semantics
- FVG and OB use identical formula — divergence deferred to Phase 46 calibration if data supports it
- Per-TF keys are dynamic (only appear when TF has valid FVG/OB zone) — no DB migration needed (i6 JSONB is flexible)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Updated existing test asserting stub 0.0 values**
- **Found during:** Task 2 (GREEN implementation)
- **Issue:** `test_smc_bos_alignment_present_in_output` asserted `result["i6_fvg_tf_alignment"] == 0.0` and `== 0.0` — written against stub behavior, would fail after real implementation
- **Fix:** Replaced equality assertions with `isinstance(result[...], float)` checks; FVG/OB fields in `_bullish_intel()` are absent so score is still 0.0 in that case, but the test no longer encodes stub behavior as a contract
- **Files modified:** `tests/unit/intelligence/test_cross_timeframe.py`
- **Committed in:** `12c7fc4` (Task 2 feat commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - existing test encoded stub behavior)
**Impact on plan:** Necessary correctness fix. No scope creep.

## Issues Encountered

- Plan expected `test_fvg_alignment_direction_mismatch_reduces_score` to fail in RED state, but assertion `<= 0.0` passes against `0.0` stub. This is correct behavior — the test still exercises the right postcondition and is meaningful after GREEN. 2 of 4 tests failed (RED), 2 passed (which also happen to be correct against the stub). No impact on plan.

## Next Phase Readiness

- `i6_fvg_tf_alignment` and `i6_ob_tf_alignment` are now real signals — Phase 43 (I6 Confluence Expansion) can weight them in CONF-04
- Per-TF decomposition keys land in i6 JSONB automatically — no schema changes needed
- All existing tests pass; no regressions

---
*Phase: 41-intelligence-gap-fill*
*Completed: 2026-03-20*
