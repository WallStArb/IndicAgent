---
phase: 039-data-quality-db-health
plan: "02"
subsystem: database
tags: [psycopg2, signal_ledger, cis_score, data-quality, alpha-validation]

requires:
  - phase: 039-01
    provides: CIS null repair script baseline

provides:
  - CIS null repair with exit-1 completeness gate (DATA-01)
  - Alpha validation pre-check result for DerivOsc and AC Osc (DATA-02 deferred)

affects: [phase-040, phase-046, ml-training-pipeline]

tech-stack:
  added: []
  patterns:
    - "Pipeline-safe exit-1 gate: scripts that run in CI or cron must exit non-zero on incomplete repair — print-only warnings are silent failures"
    - "Completeness gate pattern: re-audit after repair, exit 1 if recoverable rows remain, exit 0 only on full success"

key-files:
  created: []
  modified:
    - production/scripts/repair_cis_nulls.py
    - tests/unit/scripts/test_repair_cis_nulls.py

key-decisions:
  - "Exit-1 gate checks recoverable_after (not total_null_after vs orphaned_ids) — orphaned rows are unrecoverable by design and must not trigger a false failure"
  - "DATA-02 deferred: cmp_DerivativeOscillator and ind_ACOscillator have 0 resolved outcomes — N >= 30 gate not met; re-check query documented for future session"

patterns-established:
  - "Completeness gate: after repair, re-audit and exit 1 if any recoverable rows still have NULL cis_score"
  - "Test pattern: TestCompletenessGate class patches connect_db + Settings + audit_null_cis + repair_recoverable to test main() exit behavior without live DB"

requirements-completed: [DATA-01]

duration: 2min
completed: "2026-03-19"
---

# Phase 039 Plan 02: CIS Null Repair Hardening + Alpha Validation Summary

**Exit-1 completeness gate added to repair_cis_nulls.py; DATA-02 deferred — 0 resolved outcomes for DerivOsc and AC Osc (N < 30 gate)**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-19T23:02:16Z
- **Completed:** 2026-03-19T23:04:30Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Replaced silent print-only verification warning with pipeline-safe `sys.exit(1)` completeness gate in `repair_cis_nulls.py`
- Added `[FAIL]` / `[PASS]` gate messages for clear operator and CI readability
- Added `TestCompletenessGate` class with two tests covering exit-1 and exit-0 paths; all 13 tests pass
- Executed alpha validation pre-check: `cmp_DerivativeOscillator` and `ind_ACOscillator` both have 0 resolved outcomes — DATA-02 deferred pending data accumulation

## Task Commits

1. **Task 1: Add exit-1 completeness gate to repair_cis_nulls.py and test** - `523f5c9` (feat)
2. **Task 2: Alpha validation pre-check (DATA-02)** - no code commit; operational query only

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `production/scripts/repair_cis_nulls.py` - Verification block replaced: recoverable_after non-empty → sys.exit(1); empty → [PASS] print and continue
- `tests/unit/scripts/test_repair_cis_nulls.py` - Added `import pytest`, imported `main`, added `TestCompletenessGate` with `test_completeness_gate_exits_1_on_remaining_recoverable` and `test_completeness_gate_exits_0_on_full_repair`

## Decisions Made

- Exit-1 gate checks `len(recoverable_after) > 0` rather than `total_null_after != len(orphaned_ids)` — the new check is semantically correct: orphaned rows are unrecoverable by design and must not trigger failure
- DATA-02 (alpha validation for bootstrap-promoted plugins) deferred pending data accumulation — no validate_alpha.py changes needed; the script's existing N >= 30 gate is correct

## DATA-02 Status: Deferred Pending Data Accumulation

**Pre-check query executed:**
```sql
SELECT setup_plugin, COUNT(*) as n
FROM signal_ledger
WHERE setup_plugin IN ('cmp_DerivativeOscillator', 'ind_ACOscillator')
  AND outcome IS NOT NULL
GROUP BY 1;
```

**Result:** 0 rows returned for both plugins. Neither has any resolved outcomes yet.

**Re-check query** (run after 30+ resolved signals accumulate):
```bash
docker exec timescaledb psql -U postgres -d indicagent -c "SELECT setup_plugin, COUNT(*) as n FROM signal_ledger WHERE setup_plugin IN ('cmp_DerivativeOscillator', 'ind_ACOscillator') AND outcome IS NOT NULL GROUP BY 1;"

# If both N >= 30:
INDICAGENT_ENV=development .venv/bin/python production/scripts/validate_alpha.py --promote cmp_DerivativeOscillator
INDICAGENT_ENV=development .venv/bin/python production/scripts/validate_alpha.py --promote ind_ACOscillator
```

DATA-02 requirement marked as deferred — no blocking issue, purely a data accumulation gate. Re-check after several days of live signal generation.

## Deviations from Plan

None — plan executed exactly as written. Exit-1 gate implemented per spec. DATA-02 correctly identified as deferred due to insufficient data (documented in plan as the expected path when N < 30).

## Issues Encountered

None.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- CIS null repair script is now pipeline-safe; can be wired to CI or cron without false negatives
- DATA-02 re-check documented with exact commands; no blocker for Phase 040
- Phase 040 (Machine Hardening) can proceed

---
*Phase: 039-data-quality-db-health*
*Completed: 2026-03-19*
