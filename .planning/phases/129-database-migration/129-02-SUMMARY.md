---
phase: 129
plan: "02"
subsystem: data-migration
tags: [migration, signal-architecture, psycopg2, idempotency]
dependency_graph:
  requires: [129-01]
  provides: [production/scripts/migrate_signal_ledger.py]
  affects: [signal_events, trade_frames]
tech_stack:
  added: [psycopg2 (direct use in migration script)]
  patterns: [batched-offset-pagination, deterministic-uuid5, ON CONFLICT DO NOTHING]
key_files:
  created: [production/scripts/migrate_signal_ledger.py]
  modified: []
decisions:
  - "Deterministic frame_id via uuid5(NAMESPACE_DNS, signal_id:at_close) — random uuid4 would break idempotency across restarts"
  - "raw_confidence NULL sentinel: signal_events.raw_confidence is NOT NULL; rows predating the field get 0.0 rather than aborting"
  - "batch progress: print every 10 batches (100K rows) not 50 as context suggests — matches plan spec exactly"
metrics:
  duration: "~8 minutes"
  completed: "2026-06-16"
  tasks_completed: 3
  tasks_total: 3
  files_modified: 1
---

# Phase 129 Plan 02: Data Migration Script Summary

Wrote `production/scripts/migrate_signal_ledger.py` — a batched Python migration script that copies 1,442,914 signal_ledger rows into signal_events + trade_frames using psycopg2 with 10K-row batches and full idempotency.

## What Was Built

`production/scripts/migrate_signal_ledger.py` is a standalone script (not a daemon) that:

1. Connects to indicagent DB via psycopg2 with explicit credentials
2. Counts total signal_ledger rows and prints a banner
3. Processes rows in 10,000-row batches ordered by `timestamp ASC, signal_id ASC`
4. For each batch: INSERT into signal_events + trade_frames using `psycopg2.extras.execute_values()`, then COMMIT
5. Prints progress every 10 batches (100K rows)
6. On batch error: logs batch range + error, rolls back the batch, continues
7. Reports final row counts and elapsed time
8. Supports `--dry-run` flag: SELECTs only, prints sample mapping, exits without writing

Column mapping per 129-CONTEXT.md D-01 and D-02:

- `direction` int (1/-1) converted to text ('long'/'short')
- `stop_loss` renamed to `stop_price`
- `targets[0]` extracted as `target_price`; `r_multiple` computed in Python
- `signal_schema_version` text cast to int4 (None if blank)
- `status` hardcoded 'expired' (all historical rows are past TTL)
- `entry_type` hardcoded 'at_close'
- Stop architecture + shadow fields archived to `frame_details` JSONB (15 fields)
- ECL columns (factor_scores, context_features, ctf_score, ctf_confirmed, zone_friction_score) set NULL -- not in signal_ledger
- `concurrent_signal_count`, `concurrent_plugins` set NULL -- Phase 130 writer populates

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Deterministic frame_id instead of random uuid4**

- **Found during:** Task 1 (writing script)
- **Issue:** The plan specified `frame_id: gen_random_uuid()` (in Python: `str(uuid.uuid4())`). A random UUID on every run means ON CONFLICT (frame_id) DO NOTHING cannot provide idempotency -- re-running the migration would insert duplicate trade_frames rows (different frame_ids for the same signal).
- **Fix:** Used `uuid.uuid5(uuid.NAMESPACE_DNS, f"{signal_id}:at_close")` -- a deterministic UUID derived from signal_id and entry_type. The same signal always produces the same frame_id. ON CONFLICT (frame_id) DO NOTHING is now truly idempotent across restarts.
- **Files modified:** production/scripts/migrate_signal_ledger.py
- **Commit:** 0cb2ad2f

Note: The plan also specified `ON CONFLICT (signal_id, entry_type) DO NOTHING` for trade_frames, but no UNIQUE constraint exists on those columns -- only the PK (frame_id). With deterministic frame_ids, ON CONFLICT (frame_id) DO NOTHING achieves the same semantic result.

**2. [Rule 1 - Bug] Handle raw_confidence NULL for signal_events NOT NULL constraint**

- **Found during:** Task 1 (inspecting signal_ledger schema)
- **Issue:** `signal_ledger.raw_confidence` is nullable (47 columns, confirmed via \d). `signal_events.raw_confidence` is NOT NULL. A NULL raw_confidence would cause batch failures.
- **Fix:** `raw_confidence = row["raw_confidence"] or 0.0` -- rows predating the confidence field (where raw_confidence is NULL) receive sentinel value 0.0. This is semantically correct: confidence unknown = lowest possible confidence.
- **Files modified:** production/scripts/migrate_signal_ledger.py
- **Commit:** 0cb2ad2f (same)

**3. [Rule 3 - Blocking] Symlink .venv into worktree for pre-commit hook**

- **Found during:** Task 3 (commit attempt)
- **Issue:** The pre-commit hook resolves `REPO_ROOT` via `git rev-parse --show-toplevel`, which in a worktree returns the worktree path, not the main repo. It then looks for `${REPO_ROOT}/.venv/bin/ruff` -- which doesn't exist in the worktree directory.
- **Fix:** `ln -s /home/bg/dev/indicagent/.venv /home/bg/dev/indicagent/.claude/worktrees/agent-a160a5efaee08ebf7/.venv` -- symlink the main repo's venv into the worktree so the hook resolves correctly.
- **Files modified:** (symlink only, not tracked in git)
- **Commit:** N/A (infrastructure fix)

## Verification Results

Dry-run output confirms all acceptance criteria:

```
migrate_signal_ledger.py -- dry-run mode

Total rows in signal_ledger: 1,442,914
Sample mapping (first row):
  signal_id:            01d68347-ee46-cfef-6617-dbfc485aa2e7
  ts:                   2025-06-12 00:00:00+00:00
  direction (int->text):-1 -> 'short'
  entry_type:           at_close  (hardcoded)
  status:               expired  (hardcoded)
  entry_type:           at_close
  target_price:         199.65  (was targets[0])
  r_multiple:           1.9626307922272048
  frame_id (det.):      21451072-1d02-58bc-a132-120b3dfd81a5

Dry-run complete. No rows written.
```

signal_events row count remains 0 after dry-run (confirmed via psql).

## Commits

| Task | Description | Commit |
|------|-------------|--------|
| 1-3 | Write, verify, and commit migrate_signal_ledger.py | 0cb2ad2f |

## Self-Check: PASSED

- production/scripts/migrate_signal_ledger.py: FOUND (518 lines)
- Commit 0cb2ad2f: FOUND
- signal_events row count = 0 (dry-run wrote nothing): CONFIRMED
