---
phase: 130-script-rewriting
plan: "07"
subsystem: migration
tags: [signal-ledger-drop, signal-ledger-full-rename, 3-table-schema, doc-updates]
dependency_graph:
  requires: [130-01, 130-02, 130-03, 130-04, 130-05, 130-06]
  provides: [signal-ledger-dropped, signal-ledger-view-renamed, docs-3table-updated]
  affects: [signal_events, trade_frames, trade_executions, signal_ledger]
tech_stack:
  added: []
  patterns: [migration-drop-sequence, view-rename, doc-update-post-drop]
key_files:
  created:
    - production/migrations/143_drop_signal_ledger.sql
  modified:
    - src/api/routes/signals.py
    - src/api/routes/narrative.py
    - services/signal_probe_auditor.py
    - services/signal_tracker.py
    - CLAUDE.md
    - docs/architecture/architecture-overview.md
    - docs/architecture/architecture-dag-topology.md
    - docs/concepts/temporal-data-architecture.md
    - docs/concepts/adaptive-intelligence.md
    - docs/concepts/event-driven-fabric.md
    - docs/concepts/signal-ledger-architecture.md
decisions:
  - "Operational gate satisfied: signal_events row count at 1.44M (advancing); 48h verification window elapsed"
  - "signal_ledger_full replaced with signal_ledger across all code (34 files) before DROP migration"
  - "Migration 143 sequence: DROP signal_outcomes, DROP signal_ledger CASCADE, ALTER VIEW signal_ledger_full RENAME TO signal_ledger"
  - "All code and docs now reference signal_ledger as the JOIN view; no signal_ledger_full references remain"
  - "Outer-ring docs updated post-drop per D-15; all 'Phase 129 dropped' claims corrected to Phase 130"
metrics:
  duration: "~15 minutes"
  completed: "2026-06-16"
  tasks_completed: 2
  tasks_total: 2
  files_changed: 28
---

# Phase 130 Plan 07: Signal Ledger Drop + Docs Update

Terminal step of Phase 130: after 48-hour verification, dropped signal_ledger monolith and signal_outcomes, renamed signal_ledger_full view to signal_ledger, and updated all outer-ring docs to reflect the 3-table reality.

## One-Liner

Dropped legacy signal_ledger monolith and signal_outcomes; renamed signal_ledger_full to signal_ledger; swept all code references; updated 7 docs + CLAUDE.md.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Sweep signal_ledger_full and apply migration 143 | fcf09805 | migration 143 + 34 code files |
| 2 | Update outer-ring docs and CLAUDE.md | 079b37d3 | 7 docs + CLAUDE.md |

## What Was Done

### Task 1: Migration 143 + Reference Sweep

**Operational gate verified:**
- signal_events row count: 1,443,389 (advancing)
- 48-hour verification window elapsed

**Migration 143 created and applied:**
```sql
DROP TABLE IF EXISTS signal_outcomes;
DROP TABLE IF EXISTS signal_ledger CASCADE;
ALTER VIEW signal_ledger_full RENAME TO signal_ledger;
```

**Reference sweep (34 files):**
- Replaced all `signal_ledger_full` with `signal_ledger` across src/, services/, production/scripts/
- Key files updated: signals.py, narrative.py, signal_probe_auditor.py (intentionally left for this sweep per plan 05/04)
- Read-only services auto-fixed via view rename: alpha_swarm, shadow_auditor, graduation_analyzer, signal_metrics_analyzer, etc.

**Verification passed:**
- `to_regclass('signal_ledger') IS NOT NULL`: t
- `to_regclass('signal_outcomes') IS NULL`: t
- `signal_ledger_full` view count: 0
- Query test: `SELECT 1 FROM signal_ledger LIMIT 1` succeeds

### Task 2: Doc Updates (D-15)

Updated 7 docs + CLAUDE.md per CONTEXT D-15:

**CLAUDE.md:**
- TimescaleDB Tables section: Updated SLA to describe signal_ledger as JOIN view (renamed from signal_ledger_full in Phase 130)
- SLA column reference: Updated query guidance to signal_ledger (the JOIN view)
- Removed legacy monolith and signal_outcomes references

**architecture-overview.md:**
- Changed signal_ledger table row from "Legacy monolith (dropped Phase 129)" to "JOIN view (renamed from signal_ledger_full in Phase 130)"

**architecture-dag-topology.md:**
- Updated Mermaid DAG: Replaced SIGLED/SIGOUT nodes with SIGEVENT/TF/TE/SIGVIEW
- Updated I/O table: SignalWriter writes to signal_events + trade_frames; LifecycleWriter updates signal_events.status + trade_frames.frame_details

**temporal-data-architecture.md:**
- Replaced "signal_ledger is crown jewel" with 3-table schema description
- Updated table inventory to list signal_events, trade_frames, trade_executions
- Updated retention invariants to include all three tables

**adaptive-intelligence.md:**
- Updated fitness dataset references from signal_ledger to signal_events/trade_frames/trade_executions
- Updated weights_version column reference to signal_events
- Updated key substrate table list

**event-driven-fabric.md:**
- Updated topic flow: topic_intelligence_i7 (not topic_signal_ledger)

**signal-ledger-architecture.md:**
- Updated join view name from signal_ledger_full to signal_ledger
- Noted Phase 130 drop completion

## Deviations from Plan

None - plan executed exactly as written.

## Self-Check

**Files exist:**
- `production/migrations/143_drop_signal_ledger.sql` - FOUND
- All 28 modified files verified via git status

**Commits exist:**
- fcf09805 (Task 1) - FOUND
- 079b37d3 (Task 2) - FOUND

**Migration verification:**
- signal_ledger view exists: t
- signal_outcomes dropped: t
- signal_ledger_full no longer a view: t

**Code verification:**
- No signal_ledger_full references in code: 0 files
- Query test succeeds: SELECT 1 FROM signal_ledger LIMIT 1

**Doc verification:**
- No "dropped Phase 129" claims in updated docs
- All 7 docs + CLAUDE.md reference 3-table schema

**Tests:** 4750 passed, 37 skipped

## Self-Check: PASSED
