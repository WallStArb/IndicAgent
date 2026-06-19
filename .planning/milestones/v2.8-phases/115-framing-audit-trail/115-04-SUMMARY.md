---
phase: 115
plan: "04"
subsystem: persistence
tags:
  - signal_ledger
  - migration
  - framing-audit-trail
  - tdd
dependency_graph:
  requires:
    - 115-03  # regime_type wired to all 26 plugins
  provides:
    - signal_ledger 5 new framing audit columns
    - signal_ledger_full view updated
    - LedgerEntry 33-param _to_row()
  affects:
    - signal_writer persistence path
    - signal_ledger_full downstream analytics
tech_stack:
  added: []
  patterns:
    - TDD red-green with AttributeError confirmation
    - CREATE OR REPLACE VIEW with columns appended at end (PostgreSQL constraint)
    - asyncpg 33-param INSERT
key_files:
  created:
    - production/migrations/119_framing_audit_trail.sql
  modified:
    - src/persistence/repository/signal_ledger_repository.py
    - services/signal_writer.py
    - tests/unit/services/test_signal_writer.py
    - tests/unit/intelligence/test_signal_ledger.py
decisions:
  - "View columns appended at end (not inserted mid-list) to satisfy CREATE OR REPLACE VIEW immutability constraint"
  - "DB column named stop_type_col to avoid potential future reserved word collision; Python field remains stop_type"
metrics:
  duration: "~15 minutes"
  completed: "2026-06-05"
  tasks_completed: 2
  files_changed: 5
---

# Phase 115 Plan 04: DB Persistence — Framing Audit Trail Columns Summary

Closes the persistence gap in the framing audit trail capture chain. Five new nullable columns added to `signal_ledger` via migration 119, `signal_ledger_full` view updated, `LedgerEntry` extended to 33 parameters, and `signal_writer.py` wired to extract all five fields from the signal dict.

## What Was Built

**Migration 119** (`production/migrations/119_framing_audit_trail.sql`):
- `ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS` for 5 nullable columns:
  - `stop_basis text` — "structure_snap" | "garch_adaptive" | "atr_static"
  - `stop_type_col text` — structural level that anchored the stop
  - `structural_stop_distance_atr double precision` — ATR-normalized stop distance
  - `adaptive_buffer_mult double precision` — GARCH x Hurst multiplier at fire time
  - `plugin_regime_type text` — "trend" | "mean_reversion" | "any"
- `CREATE OR REPLACE VIEW signal_ledger_full` with 5 new columns appended at end (PostgreSQL immutability constraint)
- Migration applied successfully: `ALTER TABLE` + `CREATE VIEW` confirmed

**LedgerEntry** (`src/persistence/repository/signal_ledger_repository.py`):
- 5 new optional fields added after `feature_schema_version`, before `status`
- `_INSERT_SQL` extended: `stop_basis, stop_type_col, structural_stop_distance_atr, adaptive_buffer_mult, plugin_regime_type` at `$29-$33`
- `_to_row()` extended to 33-element tuple (was 28)

**signal_writer.py** (`services/signal_writer.py`):
- `_payload_to_ledger_entries()` extracts all 5 fields from signal dict via `sig.get()` with `None` defaults

## Test Results

```
6 new tests: TestFramingAuditFieldsInLedgerEntry — all PASS
4 updated tests: test_signal_ledger.py tuple-length assertions (28 → 33) — all PASS
Full suite: 4366 passed, 29 skipped
```

## Migration Output

```
ALTER TABLE
COMMENT (x5)
CREATE VIEW
```

View column verification (5 rows returned):
```
structural_stop_distance_atr | adaptive_buffer_mult | stop_basis | stop_type_col | plugin_regime_type
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed incorrect view CREATE OR REPLACE column order**
- **Found during:** Task 4b (applying migration)
- **Issue:** Initial migration inserted 5 new columns between `sl.pipeline_lag_ms` and `so.status` in the view SELECT list. PostgreSQL `CREATE OR REPLACE VIEW` requires new columns to be appended at end — inserting mid-list causes "cannot change name of view column" error.
- **Fix:** Appended framing audit columns at the end of the SELECT list after `so.effective_ts`, matching PostgreSQL's immutability constraint.
- **Files modified:** `production/migrations/119_framing_audit_trail.sql`
- **Commit:** d5107651

**2. [Rule 1 - Bug] Fixed test_signal_ledger.py tuple-length assertions**
- **Found during:** Task 4b (full unit suite run)
- **Issue:** 4 existing tests in `test_signal_ledger.py` asserted `len(_to_row()) == 28`; after extending to 33 elements they failed.
- **Fix:** Updated all 4 assertions to `== 33` with explanatory comments.
- **Files modified:** `tests/unit/intelligence/test_signal_ledger.py`
- **Commit:** d5107651

## Self-Check: PASSED

| Check | Result |
|-------|--------|
| `production/migrations/119_framing_audit_trail.sql` exists | FOUND |
| `src/persistence/repository/signal_ledger_repository.py` exists | FOUND |
| `services/signal_writer.py` exists | FOUND |
| `tests/unit/services/test_signal_writer.py` exists | FOUND |
| Commit d5107651 exists | FOUND |
| `_to_row()` returns 33 elements | PASSED |
| 5 view columns in `signal_ledger_full` | VERIFIED (5 rows) |
| Full unit suite | 4366 passed, 29 skipped |
