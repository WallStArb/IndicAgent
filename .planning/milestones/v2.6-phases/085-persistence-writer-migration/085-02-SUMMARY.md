---
phase: 085-persistence-writer-migration
plan: "02"
subsystem: persistence-writers
tags: [bug-fix, data-loss, observability, writer-hardening]
dependency_graph:
  requires: []
  provides: [PERSIST-02, PERSIST-03]
  affects: [feature_snapshot_writer_agent, llm_writer_service]
tech_stack:
  added: []
  patterns: [base-writer-inheritance, structured-error-logging]
key_files:
  created: []
  modified:
    - services/feature_snapshot_writer_agent.py
    - services/llm_writer_service.py
key_decisions:
  - "PERSIST-02: delete _do_flush override; base re-raise contract eliminates silent data loss"
  - "PERSIST-03: wrap execute_batch in explicit except to make DB errors visible in metrics and structured logs"
metrics:
  duration_minutes: 10
  completed_date: "2026-05-17"
  tasks_completed: 2
  files_modified: 2
---

# Phase 085 Plan 02: Persistence Writer Bug Fixes Summary

## One-liner

Eliminated silent data loss in FeatureSnapshotWriterAgent (PERSIST-02) and silent metric blindness in llm_writer_service outcome writes (PERSIST-03) via targeted deletion and explicit exception handling.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Delete _do_flush override (PERSIST-02) | cf7a4924 | services/feature_snapshot_writer_agent.py |
| 2 | Make outcome DB errors visible (PERSIST-03) | f321987f | services/llm_writer_service.py |

## What Was Built

### Task 1 - PERSIST-02: FeatureSnapshotWriterAgent _do_flush Override Deleted

The `_do_flush()` override in `FeatureSnapshotWriterAgent` (lines 96-110) was deleted entirely. The override contained a silent data loss bug: on flush failure, it cleared the in-memory buffer after logging the exception, meaning the rows were permanently dropped without any retry or reprocessing.

After deletion, the class inherits `_do_flush()` from `BaseWriterAgent`, which:
- On `_flush_batch()` exception: increments `_flush_errors_total`, logs `"flush_failed"`, and re-raises
- Does NOT clear the buffer
- Systemd restart reprocesses from the last committed Kafka offset (no data loss)

No new code was written. This is a pure deletion fix.

### Task 2 - PERSIST-03: llm_writer_service Outcome Write Error Visibility

`_process_outcome_message()` had an unguarded `await self.db_manager.execute_batch(...)` call. DB exceptions from that call would propagate to the outer `except Exception as e` block, which incremented `error_count_total` and sent to DLQ - but did NOT log a structured `"outcome_write_failed"` event, making it impossible to distinguish outcome write failures from other error types in logs/metrics.

Added an explicit `except Exception as db_exc` immediately wrapping the `execute_batch` call that:
1. Increments `self.error_count_total` (the existing counter - no new counter added)
2. Logs `self.logger.error("outcome_write_failed", signal_id=..., error=str(db_exc))` with structured fields
3. Calls bare `raise` to propagate the exception to the outer handler, which routes to DLQ

## Deviations from Plan

None - plan executed exactly as written.

## Verification Results

- `grep -n "_do_flush" services/feature_snapshot_writer_agent.py` - returns no matches
- `grep -n "outcome_write_failed" services/llm_writer_service.py` - returns match at line 762
- `ruff check` on both files - zero errors
- `pytest tests/unit/ -q` - 3260 passed, 1 skipped

## Self-Check

### Files Modified

- [x] `/home/bg/dev/indicagent/.claude/worktrees/agent-ae102d5d2a947e38a/services/feature_snapshot_writer_agent.py` - _do_flush override deleted
- [x] `/home/bg/dev/indicagent/.claude/worktrees/agent-ae102d5d2a947e38a/services/llm_writer_service.py` - outcome_write_failed exception handling added

### Commits

- [x] cf7a4924 - fix(085-02): delete _do_flush override in FeatureSnapshotWriterAgent (PERSIST-02)
- [x] f321987f - fix(085-02): make outcome DB errors visible in llm_writer_service (PERSIST-03)

## Self-Check: PASSED
