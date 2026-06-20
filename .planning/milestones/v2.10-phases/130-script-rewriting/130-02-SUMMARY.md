---
phase: 130-script-rewriting
plan: "02"
subsystem: persistence
tags: [repository, signal-events, 3-table-schema, backward-compat, shim]
dependency_graph:
  requires: [130-01]
  provides: [SignalEventsRepository, signal-events-write-path, backward-compat-shim]
  affects: [signal_writer, lifecycle_writer, signal_tracker, signal_auditor, api-signals, run_historical_pipeline, feature_replay]
tech_stack:
  added: []
  patterns: [asyncpg-transaction, uuid5-frame-id, jsonb-dict-passthrough, backward-compat-shim]
key_files:
  created:
    - src/persistence/repository/signal_events_repository.py
  modified:
    - src/persistence/repository/signal_ledger_repository.py
    - src/intelligence/enums/signal_status.py
    - src/intelligence/enums/__init__.py
    - src/intelligence/trading/lifecycle_tracker.py
    - src/intelligence/ml/confidence_calibrator.py
    - src/intelligence/weight_updater.py
    - src/api/routes/signals.py
    - tests/unit/persistence/test_signal_ledger_repository.py
    - tests/unit/pipeline/test_pipeline_attribution.py
    - tests/unit/intelligence/test_signal_ledger.py
    - tests/unit/services/test_lifecycle_writer.py
decisions:
  - "SignalEventsRepository targets signal_events + trade_frames + trade_executions exclusively; no signal_ledger or signal_outcomes references"
  - "signal_ledger_repository.py converted to thin re-export shim with SignalLedgerRepository = SignalEventsRepository alias"
  - "frame_id deterministic via uuid5(NAMESPACE_DNS, f'{signal_id}:{entry_type}') — idempotent across replays"
  - "LedgerEntry preserved as backward-compat dataclass shim for wave 3 callers (run_historical_pipeline, feature_replay)"
  - "Activation lifecycle fields (activated_at, activation_price, etc.) written to trade_frames.frame_details JSONB via JSONB || merge"
  - "Bootstrap query uses direct signal_events LEFT JOIN trade_frames (not signal_ledger_full view which NULLs all lifecycle fields)"
  - "concurrent_signal_count and concurrent_plugins NULL in Phase 130; v2.11 populates"
  - "Tests updated to reflect 3-table schema: removed _INSERT_SQL/_to_row() legacy assertions, added new 3-table assertions"
metrics:
  duration: "~30 minutes"
  completed: "2026-06-16"
  tasks_completed: 2
  tasks_total: 2
  files_changed: 12
---

# Phase 130 Plan 02: SignalEventsRepository — 3-Table Write Path

Single repository rewrite retargets all persistence to the 3-table signal architecture (signal_events / trade_frames / trade_executions). Frame_id deterministic via uuid5; direction text-encoded; JSONB passed as dict. All 13 importers resolve; no ImportError at pytest collection.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Create signal_events_repository.py with 3-table SQL | 54987975 | src/persistence/repository/signal_events_repository.py |
| 2 | Convert old repository file to shim and update 6 src/ importers | 38dc2176 | signal_ledger_repository.py (shim) + 6 importers + 4 test files |

## What Was Done

### Task 1: SignalEventsRepository

Created `src/persistence/repository/signal_events_repository.py` (1009 lines) with:

**Core write methods (3-table schema):**
- `insert_signal_with_frames(signal_event, trade_frames)` - atomic asyncpg transaction: one INSERT INTO signal_events + N INSERT INTO trade_frames. frame_id via uuid5(NAMESPACE_DNS, f"{signal_id}:{entry_type}"). Direction as text "long"/"short". SIGNAL_SCHEMA_VERSION constant as int (not str). concurrent_signal_count NULL (v2.11). counterfactual_pnl_r NULL (v2.11).
- `update_signal_status(signal_id, status)` - standalone UPDATE signal_events.status; idempotent, retryable.
- `update_frame_details(signal_id, meta)` - JSONB || merge on trade_frames.frame_details for activation lifecycle fields.
- `record_execution(signal_id, entry_type, ...)` - standalone INSERT into trade_executions.

**Bootstrap query:**
- `get_active_signals_for_bootstrap(pending_window_days, active_window_days)` - direct signal_events LEFT JOIN trade_frames (NOT signal_ledger_full view which returns NULL for all lifecycle fields per RESEARCH Pitfall 1). Extracts entry_zone_low/high, trailing_stop_price, chandelier_vol_source, activated_at from frame_details JSONB. Adapts target_price into `targets: [target_price]` list for evaluate_signal() compatibility.

**Backward-compat (Wave 3 transition):**
- `batch_execute(transition_type, items)` - routes activation/exit/chandelier_update/mae_mfe_update/shadow_outcome/market_resolution via update_signal_status + update_frame_details. All lifecycle state goes to trade_frames.frame_details JSONB.
- Full set of legacy method aliases (record_activation, record_zone_resolution, record_market_resolution, update_chandelier_state, etc.) delegating to update_signal_status + update_frame_details.
- `LedgerEntry` backward-compat dataclass shim (no _to_row() - plain dataclass for run_historical_pipeline and feature_replay until Wave 3).

### Task 2: Shim and Importer Updates

**signal_ledger_repository.py** replaced with thin re-export shim:
- Imports all symbols from signal_events_repository via wildcard + explicit
- `SignalLedgerRepository = SignalEventsRepository` alias for lagging callers

**6 src/ importers updated** (from signal_ledger_repository to signal_events_repository):
1. `src/intelligence/enums/signal_status.py` - SignalStatus import
2. `src/intelligence/enums/__init__.py` - SignalStatus import
3. `src/intelligence/trading/lifecycle_tracker.py` - SignalStatus import
4. `src/intelligence/ml/confidence_calibrator.py` - WIN_OUTCOMES import
5. `src/intelligence/weight_updater.py` - WIN_OUTCOMES import
6. `src/api/routes/signals.py` - WIN_OUTCOMES + SignalStatus imports

**Wave 3 service importers** (signal_writer, lifecycle_writer, signal_tracker, signal_replay_auditor, run_historical_pipeline, feature_replay) preserved via shim alias until their individual plan rewrites.

**Tests updated** (Rule 1 - auto-fix: removed private SQL constant imports that no longer exist):
- `tests/unit/persistence/test_signal_ledger_repository.py` - replaced _INSERT_SQL/_to_row() tests with 3-table schema assertions
- `tests/unit/pipeline/test_pipeline_attribution.py` - removed _INSERT_SQL dependency; LedgerEntry now tested as plain dataclass
- `tests/unit/intelligence/test_signal_ledger.py` - full rewrite to SignalEventsRepository interface + 3-table SQL content assertions
- `tests/unit/services/test_lifecycle_writer.py` - batch_execute tests updated from execute_batch to execute_command per item

## Verification

- SignalEventsRepository exists with all 4 core methods: `ok`
- No INSERT/UPDATE targeting signal_outcomes or signal_ledger in new repository: `count=0 (clean)`
- Bootstrap SQL uses `FROM signal_events` JOIN, not `signal_ledger_full`: confirmed
- uuid5 present for frame_id: 5 occurrences
- Shim alias identity `SignalLedgerRepository is SignalEventsRepository`: `ok`
- All 6 src/ importers reference signal_events_repository: confirmed
- pytest tests/unit/: `4748 passed, 37 skipped`

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Test files importing private SQL constants from old repository**

- **Found during:** Task 2 — pytest collection
- **Issue:** Three test files imported private constants (`_INSERT_SQL`, `_SELECT_ACTIVE_SQL`, `_RECORD_ACTIVATION_SQL`, `_build_feature_rows`, `_INSERT_FEATURES_SQL`) and the `_to_row()` method from `signal_ledger_repository`. These are all gone from the new shim; pytest could not collect.
- **Fix:** Rewrote test assertions to target the new SignalEventsRepository interface and 3-table SQL content. Preserved test intent: method existence checks, SQL schema validation, async mock behavior verification.
- **Files modified:** `tests/unit/persistence/test_signal_ledger_repository.py`, `tests/unit/pipeline/test_pipeline_attribution.py`, `tests/unit/intelligence/test_signal_ledger.py`, `tests/unit/services/test_lifecycle_writer.py`
- **Commits:** 38dc2176 (combined with Task 2 commit)

**2. [Rule 3 - Blocking] .venv symlink missing in worktree**

- **Found during:** Task 1 commit attempt
- **Issue:** Pre-commit hook looks for `${REPO_ROOT}/.venv/bin/ruff` and `${REPO_ROOT}/.venv/bin/black` where REPO_ROOT = the worktree path. `.venv` only exists in the main repo.
- **Fix:** Symlinked `/home/bg/dev/indicagent/.venv` into the worktree path.
- **Commit:** Not a code commit; worktree setup fix.

## Self-Check

- [x] `src/persistence/repository/signal_events_repository.py` exists (1009 lines)
- [x] Contains `class SignalEventsRepository`
- [x] Contains `INSERT INTO signal_events` and `INSERT INTO trade_frames`
- [x] Contains `async with conn.transaction()` for atomic insert
- [x] Contains `FROM signal_events` in bootstrap query; does NOT contain `FROM signal_ledger_full` in bootstrap
- [x] Contains `uuid5` for frame_id generation
- [x] No `INSERT INTO signal_outcomes` or `UPDATE signal_outcomes` or `INSERT INTO signal_ledger ` (grep returns 0)
- [x] `signal_ledger_repository.py` is now a shim importing from `signal_events_repository`
- [x] `SignalLedgerRepository = SignalEventsRepository` alias present
- [x] All 6 src/ importers reference `signal_events_repository`
- [x] Commit 54987975 exists (Task 1)
- [x] Commit 38dc2176 exists (Task 2)
- [x] pytest tests/unit/ green: 4748 passed

## Self-Check: PASSED
