---
phase: 15-validated-alpha
plan: GAP-01
subsystem: intelligence
tags: [validate_alpha, bootstrap, TIER_I2, DerivativeOscillator, ACOscillator, MACDEvents]

# Dependency graph
requires:
  - phase: 15-validated-alpha/15-02
    provides: DerivativeOscillatorPlugin implementation (8 tests GREEN)
  - phase: 15-validated-alpha/15-05
    provides: ACOscillator wired to TIER_I1 (bootstrap precedent)
  - phase: 15-validated-alpha/15-04
    provides: macd_hist_accel field in MACDEventsPlugin
provides:
  - cmp_DerivativeOscillator registered in TIER_I2 (9 I2 plugins total, 92 total plugins)
  - --bootstrap flag in validate_alpha.py for data-absence exemption
  - Three bootstrap audit-trail JSON files in docs/validation/ (verdict=BOOTSTRAP)
  - Bootstrap Policy Exception documented in 15-CONTEXT.md covering ALPHA-02, ALPHA-04, ALPHA-05
affects: [15-validated-alpha, future-alpha-validation]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Bootstrap promotion policy: data-absent plugins with correct implementations get BOOTSTRAP verdict instead of blocking FAIL"
    - "--bootstrap CLI flag exits before DB connection; no TimescaleDB required for audit trail"

key-files:
  created:
    - docs/validation/2026-03-07-cmp_DerivativeOscillator-deriv_osc_cross_bullish-bootstrap.json
    - docs/validation/2026-03-07-ind_ACOscillator-ac-bootstrap.json
    - docs/validation/2026-03-07-evt_MACDEvents-macd_hist_accel-bootstrap.json
  modified:
    - production/scripts/validate_alpha.py
    - .planning/phases/15-validated-alpha/15-CONTEXT.md

key-decisions:
  - "Bootstrap policy: newly-registered plugins with zero live data get verdict=BOOTSTRAP (not FAIL) — unblocks the chicken-and-egg sequence problem"
  - "--bootstrap path exits before any psycopg2.connect call — no DB dependency for audit trail"
  - "TIER_I2 grows from 8 to 9 with cmp_DerivativeOscillator (change was committed in 4603899, tests pass)"

patterns-established:
  - "Bootstrap audit trail: verdict=BOOTSTRAP JSON written to docs/validation/ with data_absence_exemption reason and re-run instructions"

requirements-completed: [ALPHA-01, ALPHA-02, ALPHA-04, ALPHA-05]

# Metrics
duration: 15min
completed: 2026-03-07
---

# Phase 15 Plan GAP-01: Bootstrap Policy and DerivativeOscillator Registration Summary

**Bootstrap promotion policy formalised in validate_alpha.py; DerivativeOscillatorPlugin live in TIER_I2 (9 I2 plugins, 92 total); three data-absence exemption audit files covering Gaps 1/3/4**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-03-07T19:10:00Z
- **Completed:** 2026-03-07T19:25:00Z
- **Tasks:** 3 (Task 1 was pre-complete; Tasks 2-3 executed)
- **Files modified:** 4

## Accomplishments
- DerivativeOscillatorPlugin confirmed in TIER_I2 (commit 4603899 pre-committed; all 5 registration tests pass)
- `--bootstrap` flag added to validate_alpha.py — exits before any DB connection, writes verdict=BOOTSTRAP JSON with data_absence_exemption reason
- Three bootstrap audit-trail JSON files written covering Gaps 1 (DerivOsc), 3 (ACOscillator), 4 (MACD accel)
- Bootstrap Policy Exception section appended to 15-CONTEXT.md documenting ALPHA-02/04/05
- 1286 unit tests passing, 0 ruff errors

## Task Commits

1. **Task 1: Register DerivativeOscillatorPlugin in TIER_I2 and update count tests** - `4603899` (feat — pre-committed before this plan executed)
2. **Task 2: Add --bootstrap flag to validate_alpha.py, run audit records, document CONTEXT.md** - `81e601b` (feat)
3. **Task 3: Full test suite verification** - verified at `81e601b` (no separate commit needed — no file changes)

## Files Created/Modified
- `production/scripts/validate_alpha.py` — Added `--bootstrap` argparse flag + bootstrap execution path (exits before DB, writes verdict=BOOTSTRAP JSON)
- `docs/validation/2026-03-07-cmp_DerivativeOscillator-deriv_osc_cross_bullish-bootstrap.json` — Bootstrap audit trail for Gap 1 (DerivOsc)
- `docs/validation/2026-03-07-ind_ACOscillator-ac-bootstrap.json` — Bootstrap audit trail for Gap 3 (ACOscillator)
- `docs/validation/2026-03-07-evt_MACDEvents-macd_hist_accel-bootstrap.json` — Bootstrap audit trail for Gap 4 (MACD accel)
- `.planning/phases/15-validated-alpha/15-CONTEXT.md` — Bootstrap Policy Exception section appended

## Decisions Made
- Bootstrap policy resolves the chicken-and-egg problem: plugin needs live data to pass gate, but data only accumulates after registration. Exemption recorded in JSON with re-run instructions.
- `--bootstrap` path exits before psycopg2.connect — no DB dependency, so audit trail can be written even when TimescaleDB is unreachable.
- TIER_I2 count (9) and total (92) match the test assertions; no test changes were needed for Task 1 (tests had already been updated in commit 4603899).

## Deviations from Plan

None — plan executed exactly as written. Task 1 code changes were already committed in a prior session (4603899); this plan's executor verified tests pass and recorded the completion without re-doing the work.

## Issues Encountered

None.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- All four Phase 15 gap closures complete (Gaps 1, 3, 4 via bootstrap; Gap 2 in 15-GAP-02)
- Gate re-run required for ALPHA-02/04/05 after 30+ bars accumulate in intelligence_features
- Re-run commands documented in each bootstrap JSON and in 15-CONTEXT.md Bootstrap Policy Exception

---
*Phase: 15-validated-alpha*
*Completed: 2026-03-07*
