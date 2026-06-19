---
phase: 112-intelligence-pipeline-signal-integrity
plan: "01"
subsystem: intelligence-pipeline
tags: [contamination-boundary, schema-versioning, migrations, feature-writer, signal-ledger]
dependency_graph:
  requires: []
  provides: [PIPE-INT-01]
  affects: [intelligence_features, signal_ledger, signal_ledger_full, setup_performance, IntelligenceEvent, PluginStateManager]
tech_stack:
  added: []
  patterns: [schema-versioning, contamination-boundary, checkpoint-discard]
key_files:
  created:
    - production/migrations/110_add_feature_schema_version_to_intelligence_features.sql
    - production/migrations/111_add_feature_schema_version_to_signal_ledger.sql
    - production/migrations/112_update_signal_ledger_full_view.sql
    - production/migrations/113_reset_setup_performance_to_neutral.sql
  modified:
    - src/intelligence/schemas.py
    - src/intelligence/pipeline/state_manager.py
    - services/feature_writer.py
    - src/persistence/repository/signal_ledger_repository.py
    - services/signal_writer.py
    - tests/unit/intelligence/test_signal_ledger.py
    - tests/unit/services/test_feature_writer.py
decisions:
  - "FEATURE_SCHEMA_VERSION=2 as integer constant (not text) for efficient DB filtering"
  - "Checkpoint discard on CHECKPOINT_VERSION mismatch — cold start is the correct behavior; no migration of old state"
  - "signal_writer.py defaults to FEATURE_SCHEMA_VERSION constant (trace gap: signal_processor signals_payload does not carry feature_schema_version)"
  - "setup_performance reset: sample_size=0 for all 596 rows (spec's perf_multiplier/signal_schema_version columns do not exist)"
metrics:
  duration_minutes: 8
  completed_date: "2026-06-02"
  tasks_completed: 4
  files_modified: 7
  files_created: 4
---

# Phase 112 Plan 01: Contamination Boundary — feature_schema_version Summary

Established the forensic contamination boundary for the intelligence pipeline signal integrity fix. Every row written after this deploy is provably clean (`feature_schema_version = 2`); every pre-fix row stays NULL and is filtered out by downstream training queries.

## One-Liner

Nullable `feature_schema_version INTEGER` column on both hypertables, VIEW recreated, all writer INSERT paths stamped with constant `2`, setup_performance neutralized, checkpoint discard on version mismatch.

## Tasks Completed

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | Audit signal_ledger_full VIEW dependencies + add columns + recreate VIEW | a2fbe93d | migrations 110, 111, 112 |
| 2 | Reset contaminated setup_performance to neutral | d21b2acd | migration 113 |
| 3 | FEATURE_SCHEMA_VERSION + IntelligenceEvent field; CHECKPOINT_VERSION discard | 89ef3a41 | schemas.py, state_manager.py |
| 4 | Writer inventory + wire feature_schema_version into all INSERT paths | 84d59d31 | feature_writer.py, signal_ledger_repository.py, signal_writer.py, tests |

## signal_ledger_full Dependency Audit

**Query run:** 2026-06-02 against live DB

```sql
SELECT DISTINCT dep_schema, dep_name, dep_kind
FROM pg_depend JOIN pg_rewrite ...
WHERE referenced_class.relname = 'signal_ledger_full'
AND dependent_view.relname != 'signal_ledger_full';
```

**Result:** 0 rows — no dependent views or grants found. DROP VIEW CASCADE is safe; no objects to restore in migration 112.

## Writer INSERT Inventory — Plan 01

| File | INSERT Target | Disposition |
|------|--------------|-------------|
| `services/feature_writer.py` (line 64) | `intelligence_features` | Updated — `feature_schema_version` at `$32` in `_INSERT_FEATURE_SQL`; value sourced from `event.feature_schema_version` in `_record_to_insert_params` |
| `src/persistence/repository/signal_ledger_repository.py` (line 131) | `signal_ledger` | Updated — `feature_schema_version` at `$29` in `_INSERT_SQL`; `LedgerEntry.feature_schema_version` field added; value flows from call site |
| `services/signal_writer.py` | `signal_ledger` (via repository) | Updated — `_payload_to_ledger_entries` sets `feature_schema_version=FEATURE_SCHEMA_VERSION` constant (see Trace Gap below) |

### Value Sources

- **feature_writer.py**: `event.feature_schema_version` — directly from the deserialized `IntelligenceEvent`. Since `IntelligenceEvent.feature_schema_version` defaults to `FEATURE_SCHEMA_VERSION = 2`, all post-deploy events carry `2`.
- **signal_ledger_repository.py**: value comes from the `LedgerEntry` object at the call site. `signal_writer.py` constructs `LedgerEntry` with `feature_schema_version=FEATURE_SCHEMA_VERSION` constant (see Trace Gap).
- **signal_writer.py**: Defaults to `FEATURE_SCHEMA_VERSION` constant — see Trace Gap below.

### Trace Gap: signal_writer.py

**Found during Task 4 inventory.** The signal pipeline's `signal_processor.py::prepare_signals_or_dlq()` builds the `signals_payload` dict (published to `topic_intelligence_i7_signals`) without a `feature_schema_version` field. `signal_writer.py` consumes this payload and constructs `LedgerEntry` objects. Since the field is absent from the payload, it cannot be sourced from the originating `IntelligenceEvent`.

**Resolution for Plan 01:** `signal_writer.py` defaults to `FEATURE_SCHEMA_VERSION` constant at the `LedgerEntry` construction site. This is correct: all post-deploy signals written by `signal_writer` will be stamped `2`, making the contamination boundary effective.

**Follow-up (Plan 02 or separate):** Thread `feature_schema_version` through `SignalProcessorResult.signals_payload` so the value is traceable end-to-end from `IntelligenceEvent` rather than defaulted at write time. Low priority — constant default achieves the same boundary effect.

## Deviations from Plan

### Auto-fixed Issues

None — plan executed as specified.

### Spec Deviations (documented, not code bugs)

**1. [Rule 2 - Spec Adaptation] setup_performance migration — perf_multiplier/signal_schema_version columns do not exist**

- **Found during:** Task 2 — pre-execution column verification
- **Spec reference:** Migration 113 spec referenced `WHERE signal_schema_version < $new_version` and `perf_multiplier` column
- **Reality:** `setup_performance` has columns: `setup_plugin, win_rate, avg_pnl_r, sample_size, sharpe_ratio, timeframe, regime, updated_at, direction, symbol`. Neither `perf_multiplier` nor `signal_schema_version` exist.
- **Equivalent neutralization:** Reset `sample_size = 0` for all 596 rows. `perf_multiplier` is computed at runtime by `run_setup_performance_update()` with `WHERE sample_size >= 30`. Sample count `0` removes every row from eligibility; computed multiplier defaults to `1.0`.
- **Files modified:** `production/migrations/113_reset_setup_performance_to_neutral.sql`
- **Commit:** d21b2acd

**2. [Documentation] .venv symlink required for pre-commit hooks in worktree**

- Worktree's `git rev-parse --show-toplevel` returns worktree path, not main repo path. Pre-commit hook looks for `.venv` at `$REPO_ROOT/.venv`. Created symlink `worktree-root/.venv -> /home/bg/dev/indicagent/.venv` to allow hooks to pass.
- Not a code change; operational note for future worktree executions.

## Verification Results

- `intelligence_features.feature_schema_version` — nullable INTEGER column present, 0 non-NULL rows (no backfill)
- `signal_ledger.feature_schema_version` — nullable INTEGER column present
- `signal_ledger_full` VIEW exposes `feature_schema_version` column
- `setup_performance` — 0 rows with `sample_size >= 30` (596 rows reset)
- `FEATURE_SCHEMA_VERSION = 2` constant in `src/intelligence/schemas.py`
- `IntelligenceEvent.feature_schema_version` field defaults to `FEATURE_SCHEMA_VERSION`
- `CHECKPOINT_VERSION = 2` in `state_manager.py`; discard-on-mismatch logic active; save path writes `CHECKPOINT_VERSION`
- All 4080 unit tests green

## Self-Check: PASSED

All created files confirmed present on disk. All task commits found in git log:
- a2fbe93d — Task 1: migrations 110, 111, 112
- d21b2acd — Task 2: migration 113
- 89ef3a41 — Task 3: schemas.py, state_manager.py
- 84d59d31 — Task 4: feature_writer.py, signal_ledger_repository.py, signal_writer.py, tests
