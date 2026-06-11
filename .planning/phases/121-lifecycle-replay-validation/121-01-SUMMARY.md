---
phase: 121-lifecycle-replay-validation
plan: 01
subsystem: database
tags: [signal-ledger, lifecycle-replay, historical-backfill, shadow-validation, data-quality]

# Dependency graph
requires:
  - phase: 119-framing-audit-trail
    provides: "5 new signal_ledger columns (stop_basis, stop_type_col, structural_stop_distance_atr, adaptive_buffer_mult, plugin_regime_type)"
  - phase: 112-signal-ledger-full-view
    provides: "signal_outcomes table with 9 new columns (trailing_stop_price, staleness_score, etc.)"
  - phase: 118-phase-119-shadow-plugins
    provides: "_SHADOW_VALIDATION_SETUPS frozenset (22 setups) in services/shadow_validator.py"
provides:
  - "Plugin-scoped --clean filter in historical_backfill.py scoped to _SHADOW_VALIDATION_SETUPS by default"
  - "lifecycle_replay.py v1.3: schema-aligned SELECT, no hardcoded date windows, shadow-inclusive integrity gate"
  - "phase_121_before_snapshot.py: atomic per-setup signal distribution baseline before any deletes"
  - "phase_121_orchestrate.py: single idempotent D-01 entry point with stage-based crash resume"
  - "docs/plans/phase-121-before-snapshot.json: authoritative before-baseline for Wave 2 comparison"
  - "Confirmed delete of 5,184,243 noise signals (22 shadow validation setups, before regeneration)"
affects:
  - 121-02-comparison-report
  - shadow-validator
  - wave-2-comparison

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Plugin-scoped DELETE: setup_plugin = ANY(%s) with timescaledb.max_tuples_decompressed_per_dml_transaction = 0"
    - "Stage-based orchestration JSON state for idempotent multi-hour operations"
    - "Advisory lock for snapshot atomicity (pg_try_advisory_lock same ID as lifecycle_replay)"
    - "_assert_row_types fail-fast on first batch row before bulk processing"
    - "ON CONFLICT DO NOTHING in _seed_orphan_outcomes for crash-safe re-entry"

key-files:
  created:
    - production/scripts/phase_121_before_snapshot.py
    - production/scripts/phase_121_orchestrate.py
    - docs/plans/phase-121-before-snapshot.json
  modified:
    - production/scripts/historical_backfill.py
    - production/scripts/lifecycle_replay.py

key-decisions:
  - "intelligence_features is never deleted in plugin-scoped clean — no setup_plugin column, rows shared across all 30 setups; deleting by symbol would corrupt 8 GOOD control setups"
  - "Default --clean scope is _SHADOW_VALIDATION_SETUPS frozenset (imported, never hardcoded); --setups ALL sentinel restores legacy full-symbol clean"
  - "lifecycle_replay.py _seed_orphan_outcomes has no date predicate — processes all pending signals regardless of age; makes the lifecycle replay a full-history tool"
  - "Advisory lock (_REPLAY_LOCK_ID = 20260602) shared between before_snapshot and lifecycle_replay ensures snapshot atomicity with later delete"
  - "STAGE_CLEAN subprocess buffered to memory (subprocess.PIPE) — log written after completion, not during; acceptable for a one-shot migration"

patterns-established:
  - "Plugin-scoped TimescaleDB DELETE: always set max_tuples_decompressed_per_dml_transaction = 0 before DML on compressed hypertable chunks"
  - "_assert_row_types: call on rows[0] before bulk processing loop; raise RuntimeError (not AssertionError) to propagate to JOB_COMPLETED_TOTAL failure path"
  - "Stage JSON state machine: stages_complete list + started_at + last_updated in docs/plans/ for multi-hour operations"

requirements-completed: [REPLAY-01]

# Metrics
duration: 75min (code) + D-01 sequence running async
completed: 2026-06-11
---

# Phase 121 Plan 01: Lifecycle Replay Infrastructure Redesign Summary

**Plugin-scoped clean deletes 5.18M noise signals for 22 shadow setups; lifecycle_replay.py redesigned to schema-aligned v1.3 with full-history processing; before-snapshot baseline captured atomically for Wave 2**

## Performance

- **Duration:** ~75 min (code tasks) + D-01 execution running in background process
- **Started:** 2026-06-10T23:00:00Z
- **Code complete:** 2026-06-11T00:20:00Z
- **Before-snapshot captured:** 2026-06-11T00:08:15Z
- **D-01 execution started:** 2026-06-11T00:11:00Z (PID 462899, still running at summary time)
- **Tasks:** 3 of 3 code tasks complete; D-01 sequence STAGE_CLEAN in progress
- **Files modified:** 5

## Accomplishments

- Added `--setups` plugin-scoped clean filter to `historical_backfill.py` - default scope is the `_SHADOW_VALIDATION_SETUPS` frozenset (22 setups imported from `services/shadow_validator.py`); `--setups ALL` restores legacy full-symbol clean; `intelligence_features` is never deleted under the plugin-scoped path
- Redesigned `lifecycle_replay.py` to v1.3: removed all 4 hardcoded date predicates, added 14 missing schema columns to the SELECT (5 from signal_ledger, 9 from signal_outcomes), extended `_verify_replay` with D-06 shadow integrity checks (hard-fail on `shadow_stopped_at_entry > 0` or `orphan_ledger_rows > 0`), added `_assert_row_types` fail-fast helper
- Created `phase_121_before_snapshot.py` (asyncpg oneshot) and `phase_121_orchestrate.py` (5-stage state machine with JSON crash resume)
- Captured atomic before-snapshot at `docs/plans/phase-121-before-snapshot.json`: 7,446,342 total signals across 66 setup/is_shadow combinations; 22 shadow validation setups had 5,184,243 combined signals (12,912 is_shadow=True + 5,171,331 is_shadow=False noise)
- D-01 STAGE_CLEAN confirmed deleted 5,184,243 noise signals (verified by post-delete DB counts matching expected GOOD control baseline of ~2,262,099); signal regeneration in progress via intelligence replay

## Task Commits

Each task was committed atomically:

1. **Task 1: Add --setups plugin-scoped clean filter** - `b642078d` (feat)
2. **Task 2: Redesign lifecycle_replay.py v1.3** - `890c34cd` (feat)
3. **Deviation fix: timescaledb decompression + sys.path fix** - `0a6e2756` (fix)
4. **Task 3: Create before_snapshot, orchestrate scripts, capture baseline** - `794bca8e` (feat)

## Files Created/Modified

- `production/scripts/historical_backfill.py` - Added `--setups` argparse arg; plugin-scoped DELETE path with timescaledb decompression setting; `_SHADOW_VALIDATION_SETUPS` import as default scope; `--setups ALL` sentinel for legacy full-symbol clean
- `production/scripts/lifecycle_replay.py` - v1.3: removed 4 hardcoded date predicates; added 14 SELECT columns; extended `_verify_replay` with shadow integrity checks; added `_assert_row_types` helper; updated module version docstring
- `production/scripts/phase_121_before_snapshot.py` - asyncpg oneshot: distribution-aware SQL with PERCENTILE_CONT/STDDEV/CORR; advisory lock for atomicity; exists-guard prevents overwrite; OTel oneshot exit
- `production/scripts/phase_121_orchestrate.py` - 5-stage state machine (snapshot/clean/dry_run/replay/verify); JSON state in `docs/plans/phase-121-orchestrate-state.json`; subprocess isolation for OTel lifecycle; idempotent via stage skip
- `docs/plans/phase-121-before-snapshot.json` - 66-row before-baseline captured 2026-06-11T00:08:15Z; 7,446,342 total signals; full pnl_r distribution (p05/p25/p50/p75/p95/std/n) per setup for Welch's t-test in Wave 2

## Before-Snapshot Key Numbers (Wave 2 input)

| Metric | Value |
|--------|-------|
| Captured at | 2026-06-11T00:08:15Z |
| Total signals (all setups) | 7,446,342 |
| 22 shadow validation setups combined | 5,184,243 |
| - of which is_shadow=True | 12,912 |
| - of which is_shadow=False (noise to delete) | 5,171,331 |
| GOOD control setups (12 combos, not in 22-set) | 2,262,099 |
| intelligence_features rows | preserved (not deleted) |

## D-01 Execution Status at Summary Time

The orchestration script (`phase_121_orchestrate.py`, PID 462899) is running autonomously. Status as of summary creation:

| Stage | Status |
|-------|--------|
| STAGE_SNAPSHOT | COMPLETE - before-snapshot JSON captured |
| STAGE_CLEAN | IN PROGRESS - delete confirmed, intelligence replay regenerating shadow signals |
| STAGE_DRY_RUN | pending |
| STAGE_REPLAY | pending |
| STAGE_VERIFY | pending |

**Delete confirmed:** Post-delete DB count = ~2,262,099 (matches GOOD control baseline), confirming 5,184,243 noise signals successfully deleted. `intelligence_features` preserved.

**Regeneration in progress:** At summary time, 103,386 signals regenerated so far. The orchestrate process will continue through STAGE_DRY_RUN, STAGE_REPLAY, and STAGE_VERIFY autonomously. Resume by re-running `phase_121_orchestrate.py` if it terminates unexpectedly — it is fully idempotent via stages_complete state.

**Wave 2 prerequisite:** Wave 2 (`121-02`) must verify `phase-121-orchestrate-state.json` shows all 5 stages complete and `STAGE_VERIFY` passed before computing the comparison report.

## Decisions Made

- Plugin-scoped DELETE uses `setup_plugin = ANY(%s)` not `is_shadow = true` - both shadow=True and shadow=False rows for the 22 setup names are deleted, because the non-shadow rows (5.17M) are the "noise signals" generated under broken code that was active before the setups were placed in shadow mode
- `timescaledb.max_tuples_decompressed_per_dml_transaction = 0` is required before any DML on compressed TimescaleDB hypertable chunks - without it, deletes spanning many compressed chunks fail with "tuple decompression limit exceeded"
- `services/` must be added to `sys.path` before `from services.shadow_validator import _SHADOW_VALIDATION_SETUPS` because `historical_backfill.py` imports `_path_bootstrap` transitively via the shadow_validator module
- Advisory lock ID 20260602 shared between `before_snapshot` and `lifecycle_replay` prevents a snapshot during an active replay that is mid-delete - snapshot and delete are mutually exclusive

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] TimescaleDB decompression limit exceeded on DELETE**
- **Found during:** Task 3 (D-01 execution, STAGE_CLEAN)
- **Issue:** `DELETE FROM signal_outcomes WHERE signal_id IN (SELECT ... FROM signal_ledger WHERE setup_plugin = ANY(%s))` raised `psycopg2.errors.ConfigurationLimitExceeded: tuple decompression limit exceeded` - compressed TimescaleDB chunks have a default limit of 1000 decompressed tuples per DML transaction
- **Fix:** Added `cur.execute("SET timescaledb.max_tuples_decompressed_per_dml_transaction = 0")` immediately before both DELETE statements in the plugin-scoped clean path to remove the limit for the session
- **Files modified:** `production/scripts/historical_backfill.py`
- **Verification:** Delete executed successfully; post-delete count matched expected baseline
- **Committed in:** `0a6e2756` (fix commit)

**2. [Rule 3 - Blocking] ModuleNotFoundError: `_path_bootstrap` not found when importing `shadow_validator`**
- **Found during:** Task 3 (D-01 execution, STAGE_CLEAN)
- **Issue:** `from services.shadow_validator import _SHADOW_VALIDATION_SETUPS` raised `ModuleNotFoundError: No module named '_path_bootstrap'` because `shadow_validator.py` imports `_path_bootstrap` from the same `services/` directory, which requires `services/` to be in `sys.path`
- **Fix:** Added `services/` directory to `sys.path` before the import: `_services_dir = str(project_root / "services"); if _services_dir not in _sys.path: _sys.path.insert(0, _services_dir)` - placed inside the import block since it only runs at clean time
- **Files modified:** `production/scripts/historical_backfill.py`
- **Verification:** Import succeeded; shadow validator loaded correctly with 22 setups
- **Committed in:** `0a6e2756` (combined with fix 1)

---

**Total deviations:** 2 auto-fixed (both Rule 3 - blocking issues discovered during execution)
**Impact on plan:** Both fixes required for the D-01 sequence to run. No scope creep; both are runtime environment issues, not design changes.

## Issues Encountered

- Pre-commit hook initially failed because `.venv` symlink was missing in the worktree directory. Fixed by creating symlink: `ln -s /home/bg/dev/indicagent/.venv /home/bg/dev/indicagent/.claude/worktrees/agent-a01bc20d16d69781f/.venv`
- Before-snapshot SQL had `so.was_selected` which does not exist (was_selected is in signal_ledger, not signal_outcomes). Fixed to `sl.was_selected`. Caught immediately on first test run.

## Next Phase Readiness

Wave 2 (`121-02-PLAN.md`) is ready to proceed ONCE the orchestrate process completes all 5 stages. Prerequisites for Wave 2:
1. `phase-121-orchestrate-state.json` shows `stages_complete: ["snapshot", "clean", "dry_run", "replay", "verify"]`
2. STAGE_VERIFY passed (no stopped_at_entry in shadow signals, no orphan ledger rows)
3. `docs/plans/phase-121-before-snapshot.json` present (already captured)

The before-snapshot JSON is the primary Wave 2 input. All 66 rows have full pnl_r distribution data (p05/p25/p50/p75/p95, std, n) enabling Welch's t-test comparison.

Re-run orchestration if needed: `.venv/bin/python production/scripts/phase_121_orchestrate.py` (idempotent, resumes from last completed stage).

---
*Phase: 121-lifecycle-replay-validation*
*Completed: 2026-06-11*
