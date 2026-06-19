---
phase: 120-shadow-mode-validation
plan: "02"
subsystem: shadow-governance
tags: [shadow-auditor, demotion, shadow-registry, otel, SoC]

# Dependency graph
requires:
  - phase: 120-shadow-mode-validation-plan-01
    provides: shadow_validator.py handles all promotion logic

provides:
  - "shadow_auditor.py reduced to demotion-only (promotion path fully removed)"
  - "SoC split enforced: demotion=30-min auditor, promotion=weekly validator"

affects:
  - 120-shadow-mode-validation
  - shadow-registry governance

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Surgical file reduction: remove promotion path without touching demotion body"
    - "Test file update: remove tests for removed functions, update swarm-skip test to new demotion-only contract"

key-files:
  created: []
  modified:
    - services/shadow_auditor.py
    - tests/unit/services/test_shadow_auditor.py

key-decisions:
  - "SoC split: shadow_auditor.py is now demotion-only; shadow_validator.py owns all promotion decisions (D-01)"
  - "bootstrap_ci_lower retained in shadow_auditor.py - used by _check_demotion (line 102)"
  - "8 promotion-exclusive OTel metrics removed from imports; demotion metrics unaffected"

patterns-established:
  - "Promotion tests removed when promotion path is deleted; demotion tests kept and updated to reflect new if-not-shadow logic"

requirements-completed: [SHADOW-01]

# Metrics
duration: 5min
completed: 2026-06-10
---

# Phase 120 Plan 02: Shadow Auditor Demotion-Only Summary

**Surgically removed _check_promotion() and all 13 promotion-exclusive symbols from shadow_auditor.py, leaving a clean demotion-only service (SoC split D-01)**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-06-10T20:26:33Z
- **Completed:** 2026-06-10T20:31:00Z
- **Tasks:** 1
- **Files modified:** 2

## Accomplishments

- Deleted `_check_promotion()` (140 lines) from shadow_auditor.py
- Removed all 8 promotion-exclusive OTel metric imports; kept `JOB_COMPLETED_TOTAL` and `flush_and_shutdown_metrics`
- Removed promotion-exclusive pure functions `_should_promote` and `_tail_risk_blocks_promotion`
- Removed promotion-exclusive module constants `_WIN_OUTCOMES`, `TAIL_GATE_MIN_SKEWNESS`, `TAIL_GATE_MIN_RECOVERY`
- Updated `_run_audit` call site: replaced `if is_shadow: promote else demote` with `if not is_shadow: demote`
- Updated test file: removed 15 promotion tests, updated swarm-skip test to assert demotion-only path, fixed ruff unused import warnings

## Task Commits

1. **Task 1: Remove promotion path from shadow_auditor.py** - `a88474d5` (feat)

**Plan metadata:** (SUMMARY commit follows)

## Files Created/Modified

- `services/shadow_auditor.py` - Reduced from 359 lines to 181 lines; demotion-only, zero promotion symbols remaining
- `tests/unit/services/test_shadow_auditor.py` - 8 tests retained (all demotion-path); 15 promotion tests removed; swarm-skip test updated to `is_shadow=False` contract

## Decisions Made

- `bootstrap_ci_lower` import retained - confirmed used by `_check_demotion` (line 102 of resulting file), not promotion-exclusive
- Test file updated in same commit - removing functions requires removing tests that test those functions (Rule 3: blocking issue)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Updated test_shadow_auditor.py to remove references to deleted symbols**
- **Found during:** Task 1 (after editing shadow_auditor.py, running tests)
- **Issue:** test file imported `TAIL_GATE_MIN_RECOVERY`, `TAIL_GATE_MIN_SKEWNESS`, `_check_promotion`, `_should_promote`, `_tail_risk_blocks_promotion` - all removed from shadow_auditor.py. Caused `ImportError` at pytest collection.
- **Fix:** Removed 15 promotion tests and all imports of removed symbols. Updated `test_run_audit_skips_swarm_agent_rows` to remove `_check_promotion` patch and assert demotion-only behavior (i7_plugin with `is_shadow=False` triggers `_check_demotion`). Fixed ruff unused-import warnings via `ruff --fix`.
- **Files modified:** `tests/unit/services/test_shadow_auditor.py`
- **Verification:** `pytest tests/unit/services/test_shadow_auditor.py` - 8 passed
- **Committed in:** `a88474d5` (same task commit)

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** Necessary - removing tested functions requires removing the tests. Demotion tests retained and passing. No scope creep.

## Issues Encountered

- Pre-commit hook failed first attempt: worktree lacks `.venv` symlink, so hook couldn't find `ruff`/`black`. Fixed by creating `.venv` symlink pointing to main repo venv. Second commit succeeded.

## Self-Check

Files exist:
- `services/shadow_auditor.py` - present, 181 lines
- `tests/unit/services/test_shadow_auditor.py` - present, 8 tests passing

Commits:
- `a88474d5` - feat(120-02): reduce shadow_auditor to demotion-only

Symbol verification (all removed):
- `_check_promotion`, `_should_promote`, `_tail_risk_blocks_promotion` - absent
- `_WIN_OUTCOMES`, `TAIL_GATE_MIN_SKEWNESS`, `TAIL_GATE_MIN_RECOVERY` - absent
- All 8 SHADOW_* promotion metrics - absent

Retained:
- `bootstrap_ci_lower` - present (import + usage in _check_demotion)
- `_check_demotion` - present and unchanged

## Self-Check: PASSED

## Next Phase Readiness

- Plan 03 (DB migration 120: `signal_ledger_shadow` view) can proceed independently
- Plan 04 (systemd timer + service units) can proceed independently
- shadow_auditor.py demotion path is unchanged and operational

---
*Phase: 120-shadow-mode-validation*
*Completed: 2026-06-10*
