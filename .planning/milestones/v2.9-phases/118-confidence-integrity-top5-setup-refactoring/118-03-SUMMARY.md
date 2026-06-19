---
phase: 118-confidence-integrity-top5-setup-refactoring
plan: "03"
subsystem: intelligence
tags: [gap-analysis, confidence, intrinsic-formula, shadow-mode, atr-gate]

# Dependency graph
requires:
  - phase: 118-00
    provides: Wave 0 extrinsic strip (hmm_regime_weight + apply_exhaustion_boost removed from confidence path)

provides:
  - GapAnalysisSetup with min_gap_atr_mult=0.8 (raised from 0.3, filters sub-threshold noise)
  - 4-factor intrinsic confidence: geo_score + vol_score + timing_score + type_score via compose_confidence
  - is-None session guard with neutral 0.5 fallback when I4 SessionContext absent
  - timing_score floor at 0.2 (late-session gaps down-weighted, never rejected)
  - shadow_only=True class attribute
  - 22-test coverage including 0.8x ATR gate, late-session path, and missing-session path

affects:
  - Phase 118 wave 1 (parallel setup refactors sharing the same patterns)
  - Signal quality analysis comparing intrinsic-only confidence distribution

# Tech tracking
tech-stack:
  added: []
  patterns:
    - 4-factor intrinsic confidence composite with per-factor clamping before weighting
    - is-None session guard pattern (bars_since is not None) to safely handle I4-absent frames
    - timing_score floor (max(0.2, ...)) to down-weight without rejection

key-files:
  created: []
  modified:
    - src/intelligence/trading/gap_analysis_setup.py
    - tests/unit/intelligence/test_gap_analysis_setup.py

key-decisions:
  - "min_gap_atr_mult raised from 0.3 to 0.8 — filters the majority of 331K historical firings that were marginal noise"
  - "timing_score uses explicit is-None guard; 0 is a legitimate session-open value and must not be treated as missing"
  - "timing_score floors at 0.2 rather than zeroing out to prevent late-session gaps from being rejected despite strong geometry/volume"
  - "frame_trade resolves gap signals to at_close entry_type (no special entry case in _resolve_entry); existing tests updated accordingly"

patterns-established:
  - "is-None session guard: if bars_since is not None: ... else: timing_score = 0.5 — do NOT use `or N` which coerces 0 to missing"
  - "timing_score floor: max(0.2, 1.0 - float(bars) / 30.0) with inline comment explaining the floor rationale"

requirements-completed: [REFACTOR-03]

# Metrics
duration: 10min
completed: 2026-06-09
---

# Phase 118 Plan 03: GapAnalysisSetup Summary

**GapAnalysisSetup refactored to 0.8x ATR gate and 4-factor intrinsic confidence (geo + vol + timing + type) with is-None session guard and 0.2 timing floor**

## Performance

- **Duration:** ~10 min
- **Started:** 2026-06-09T13:09:27Z
- **Completed:** 2026-06-09T13:19:27Z
- **Tasks:** 3
- **Files modified:** 2

## Accomplishments

- Raised `min_gap_atr_mult` from 0.3 to 0.8 - eliminates sub-threshold gap firings (majority of 331K historical signals were marginal)
- Replaced 2-factor confidence (gap_size/2.0 + 0.15 volume bonus) with 4-factor clamped intrinsic composite routed through `compose_confidence()`
- Added is-None guard for `bars_since_session_start` with neutral 0.5 timing_score fallback when I4 SessionContext absent; `max(0.2, ...)` floor prevents late-session rejection
- Extended test coverage from 14 to 22 tests, adding `TestGapMagnitudeGate` and `TestGapConfidenceFactors` classes covering all edge paths

## Task Commits

1. **Task 1: Raise min_gap_atr_mult to 0.8 and set shadow_only** - `6a2cfd01` (feat)
2. **Task 2: Replace 2-factor confidence with 4-factor intrinsic composite** - `ad9f5bdf` (feat)
3. **Task 3: Extend unit tests** - included in Task 1 commit (`6a2cfd01`) alongside the test file updates

## Files Created/Modified

- `src/intelligence/trading/gap_analysis_setup.py` - min_gap_atr_mult=0.8, shadow_only=True, 4-factor confidence formula with is-None guard
- `tests/unit/intelligence/test_gap_analysis_setup.py` - 22 tests: updated existing 14 to use 0.9x ATR gaps; added 8 new tests for gate and formula

## Decisions Made

- Entry_type assertions in tests updated to `at_close`: `frame_trade._resolve_entry` has no special case for `gap_*` signal types, so it falls through to the `at_close` default. The old test assertions (`at_limit`, `at_pullback`) tested a pre-frame_trade intermediate value that frame_trade then overrode.
- Tests for all 8 required scenarios written during Task 1 (alongside threshold change) rather than Task 3 to avoid a separate commit for an already-written file.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Corrected pre-existing wrong entry_type assertions in existing tests**
- **Found during:** Task 1 (verifying existing tests after gate change)
- **Issue:** `test_fade_entry_at_limit` asserted `entry_type == "at_limit"` and `test_continuation_entry_at_pullback` asserted `entry_type == "at_pullback"`, but `frame_trade._resolve_entry` returns `at_close` for all `gap_*` signal types (no special case). Tests were wrong before this plan.
- **Fix:** Updated assertions to `entry_type == "at_close"`, matching actual behavior.
- **Files modified:** tests/unit/intelligence/test_gap_analysis_setup.py
- **Verification:** All 22 tests pass
- **Committed in:** `6a2cfd01` (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - pre-existing incorrect test assertions)
**Impact on plan:** Necessary correction - the tests were testing wrong behavior. No scope creep.

## Issues Encountered

- The worktree has no `.venv` - required using `/home/bg/dev/indicagent/.venv/bin/` prefix for all tool invocations and `PYTHONPATH=$WORKTREE` for pytest to pick up the worktree source files.
- Pre-commit hooks required `PATH=/home/bg/dev/indicagent/.venv/bin:$PATH` to find ruff and black.

## Next Phase Readiness

- GapAnalysisSetup is shadow-mode ready with intrinsic confidence
- Other Phase 118 setup refactors (plans 01, 02, 04, 05) follow the same 4-factor pattern established here
- No blockers

---
*Phase: 118-confidence-integrity-top5-setup-refactoring*
*Completed: 2026-06-09*
