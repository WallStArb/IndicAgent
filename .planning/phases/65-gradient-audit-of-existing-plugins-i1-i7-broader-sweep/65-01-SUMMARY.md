---
phase: 65-gradient-audit-of-existing-plugins-i1-i7-broader-sweep
plan: 01
subsystem: testing
tags: [gradient, sigmoid, linear-ramp, binary-scanner, tdd, renaissance]

# Dependency graph
requires: []
provides:
  - gradient_utils.py with 8 canonical gradient functions (linear_ramp, threshold_decay, sigmoid_score, z_score_to_score, session_progress, hmm_regime_weight, freshness_decay, streak_score)
  - scan_binary_patterns.py scanner tool with pre-fix baseline (114 violations)
affects: [65-02, 65-03, 65-04, 65-05, all-plugin-tiers]

# Tech tracking
tech-stack:
  added: []
  patterns: [gradient-continuity-assertions, binary-pattern-scanner, tdd-red-green-refactor]

key-files:
  created:
    - src/intelligence/utils/gradient_utils.py
    - tests/unit/intelligence/test_gradient_utils.py
    - tools/scan_binary_patterns.py
    - tools/.binary_baseline.json
  modified: []

key-decisions:
  - "z_score_to_score and streak_score delegate to linear_ramp internally (DRY)"
  - "All gradient functions use pure math module, no numpy (scalar primitives)"
  - "NaN inputs to linear_ramp return out_lo (safe fallback)"
  - "hmm_regime_weight returns 0.5 neutral when HMM key is missing"
  - "Scanner allowlist covers direction encoders, crossover events, day-of-week flags, type/category fields, docstring examples"

patterns-established:
  - "Gradient continuity: mid-range inputs never produce binary {0.0, 1.0} outputs"
  - "TDD gate: RED (failing tests) -> GREEN (implementation) commits required for gradient functions"
  - "Binary scanner: regex-based pattern detection with allowlist for legitimate binary patterns"

requirements-completed: [GRAD-UTILS, GRAD-SCANNER]

# Metrics
duration: 16min
completed: 2026-04-24
---

# Phase 65 Plan 01: Gradient Utility Library + Binary Scanner Summary

**8 canonical gradient functions with full TDD tests and regex-based binary pattern scanner establishing 114-violation pre-fix baseline**

## Performance

- **Duration:** 16 min
- **Started:** 2026-04-24T07:56:04Z
- **Completed:** 2026-04-24T08:12:33Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- Created gradient_utils.py with 8 exported functions, all handling edge cases (NaN, zero, boundary clamping)
- 56 unit tests covering boundaries, midpoints, gradient continuity, and edge cases -- all passing
- Binary pattern scanner identifying 114 pre-fix violations across src/intelligence/
- Pre-fix baseline saved to tools/.binary_baseline.json for post-fix verification

## Task Commits

Each task was committed atomically:

1. **Task 1 (RED): Tests for gradient utilities** - `2a3953cc` (test)
2. **Task 1 (GREEN): Gradient utility library** - `349e71ac` (feat)
3. **Task 2: Binary pattern scanner** - `60228841` (feat)

_Note: TDD task had RED (test) and GREEN (implementation) as separate commits_

## Files Created/Modified
- `src/intelligence/utils/gradient_utils.py` - 8 canonical gradient transformation functions (linear_ramp, threshold_decay, sigmoid_score, z_score_to_score, session_progress, hmm_regime_weight, freshness_decay, streak_score)
- `tests/unit/intelligence/test_gradient_utils.py` - 56 unit tests with gradient continuity assertions
- `tools/scan_binary_patterns.py` - Regex binary pattern scanner with --baseline and --verbose flags
- `tools/.binary_baseline.json` - Pre-fix baseline: 114 violations across 32 files

## Decisions Made
- z_score_to_score and streak_score delegate to linear_ramp internally (DRY principle)
- All gradient functions use pure math module only, no numpy (scalar primitives for hot-path plugins)
- NaN inputs to linear_ramp return out_lo as safe fallback (prevents crash propagation)
- hmm_regime_weight returns 0.5 (neutral) when HMM feature key is missing
- Scanner allowlist includes direction encoders, crossover events, bullish/bearish event flags, day-of-week flags, type/category fields, and docstring examples

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed z_score_to_score mid-range test parameter**
- **Found during:** Task 1 (TDD GREEN phase)
- **Issue:** Test used z=2.5 with sigma_scale=2.0 expecting mid-range result, but abs(2.5)/2.0=1.25 > 1.0 so it correctly returns 1.0 (not mid-range)
- **Fix:** Changed test parameter to z=1.0 with sigma_scale=2.0 (actual mid-range: 0.5)
- **Files modified:** tests/unit/intelligence/test_gradient_utils.py
- **Verification:** All 56 tests pass

**2. [Rule 3 - Blocking] Scanner docstring false positives**
- **Found during:** Task 2 (scanner testing)
- **Issue:** Scanner flagged docstring examples in gradient_utils.py that describe patterns to replace (e.g. "score = 1.0 if x > threshold else 0.0")
- **Fix:** Added allowlist entries for backtick-wrapped docstring lines and "Replaces patterns" prose lines
- **Files modified:** tools/scan_binary_patterns.py
- **Verification:** Scanner no longer flags gradient_utils.py docstrings; count dropped from 122 to 114

**3. [Rule 3 - Blocking] Scanner crossover_detect false positive**
- **Found during:** Task 2 (scanner testing)
- **Issue:** Scanner flagged bullish/bearish assignments in common.py crossover_detect -- these are event flags, not scores
- **Fix:** Added bullish/bearish assignment patterns to allowlist
- **Files modified:** tools/scan_binary_patterns.py
- **Verification:** common.py crossover_detect lines no longer flagged

---

**Total deviations:** 3 auto-fixed (1 bug, 2 blocking)
**Impact on plan:** All auto-fixes necessary for correctness and scanner accuracy. No scope creep.

## Issues Encountered
None beyond the deviations documented above.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- gradient_utils.py ready for import by all plugin tiers (Plans 02-04)
- Binary baseline (114 violations) established for comparison after all waves complete
- Scanner ready for CI integration in Plan 05
- All 56 tests CI-clean, ruff-clean

## TDD Gate Compliance
- RED gate: `2a3953cc` test(65-01): add failing tests for gradient utility functions
- GREEN gate: `349e71ac` feat(65-01): implement gradient utility library with 8 canonical functions
- REFACTOR: No separate commit needed -- DRY already applied (streak_score and z_score_to_score delegate to linear_ramp)

---
*Phase: 65-gradient-audit-of-existing-plugins-i1-i7-broader-sweep*
*Completed: 2026-04-24*

## Self-Check: PASSED

All files verified present: gradient_utils.py, test_gradient_utils.py, scan_binary_patterns.py, .binary_baseline.json, SUMMARY.md
All commits verified in git log: 2a3953cc (RED), 349e71ac (GREEN), 60228841 (scanner)
