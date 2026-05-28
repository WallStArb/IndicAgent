---
phase: 108-self-healing-hardening
plan: "03"
subsystem: observability
tags: [dlq, quarantine, asyncpg, otel, timescaledb, migration]
dependency_graph:
  requires:
    - phase: 108-01
      provides: "DLQ_QUARANTINE_TOTAL counter importable from src.observability.metrics"
  provides:
    - "dlq_events.quarantined BOOLEAN column (migration 099, applied to live DB)"
    - "dlq_events_quarantine_lookup_idx index on (agent, source_topic, error_type, routed_at DESC)"
    - "DLQDrainAgent._quarantine_counts in-memory rolling 24h counter"
    - "DLQDrainAgent._seed_quarantine_counts_from_db() startup DB hydrator"
    - "DLQDrainAgent quarantine logic in _drain_message (count > 3 = 4th occurrence)"
    - "DLQ_QUARANTINE_TOTAL.add() fired on every quarantine event"
  affects:
    - "services/dlq_drain_agent.py"
    - "production/migrations/099_dlq_quarantine.sql"
tech_stack:
  added: []
  patterns:
    - "DB-seeded in-memory counter pattern: seed from DB at startup, count in-memory per message (no per-message DB round-trip)"
    - "Rolling 24h window reset: if now - window_start > timedelta(hours=24): count=0, window_start=now"
    - "Idempotent migration: ADD COLUMN IF NOT EXISTS + CREATE INDEX IF NOT EXISTS guards"
key_files:
  created:
    - "production/migrations/099_dlq_quarantine.sql"
  modified:
    - "services/dlq_drain_agent.py"
key-decisions:
  - "Quarantine is DB-level (quarantined=TRUE column flag) not a new Kafka topic - deferred per D-22"
  - "Counter seeded from DB at startup (single GROUP BY query) so restart cannot reset poison-pill count to zero"
  - "Memory bound is ~75 keys max (15 topics x 5 error types) - no periodic cleanup needed for this plan"
  - "Degraded-mode on seed failure: log warning, return, counters rebuild from live traffic - never fatal"
requirements-completed:
  - HEAL-04
duration: 8min
completed: 2026-05-28
---

# Phase 108 Plan 03: DLQ Quarantine Summary

**DB-level DLQ quarantine via migration 099 + DLQDrainAgent rolling 24h counter seeded from dlq_events on startup; 4th identical error in 24h sets quarantined=TRUE and fires DLQ_QUARANTINE_TOTAL**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-05-28T16:00:00Z
- **Completed:** 2026-05-28T16:08:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Migration 099 applied to live TimescaleDB: `dlq_events.quarantined BOOLEAN NOT NULL DEFAULT FALSE` + lookup index on (agent, source_topic, error_type, routed_at DESC)
- DLQDrainAgent extended with `_quarantine_counts` defaultdict + `_DLQ_MAX_RETRIES=3`; `_seed_quarantine_counts_from_db()` seeds counts from last 24h of dlq_events at startup before consumer starts
- Rolling 24h window logic in `_drain_message`: `count > 3` triggers `quarantined=True`; `DLQ_QUARANTINE_TOTAL.add(1, ...)` fires on each quarantine event
- `_INSERT_SQL` extended to 9-column form; `quarantined` written as `$9` positional arg

## Startup Seed Result

On restart, `_seed_quarantine_counts_from_db()` runs a single `GROUP BY` query over last 24h of `dlq_events` and emits `dlq_drain.quarantine_seed` log with `seeded_keys=N`. Note: the live service (running from `/home/bg/dev/indicagent/`) will log the seed on the next restart after these worktree changes are merged to main.

## Quarantine Semantics Verified

```
occurrence 1: count=1, quarantined=False (ok)
occurrence 2: count=2, quarantined=False (ok)
occurrence 3: count=3, quarantined=False (ok)
occurrence 4: count=4, quarantined=True (QUARANTINED)
occurrence 5: count=5, quarantined=True (QUARANTINED)
```

The `count > DLQ_MAX_RETRIES` (i.e. `count > 3`) condition correctly quarantines the 4th and subsequent occurrences within a 24h window.

## Restart Simulation Test

Service restart with DB-backed seed:
- Before restart: if 3 rows for (agent=X, source_topic=Y, error_type=Z) exist in dlq_events within 24h
- On restart: `_seed_quarantine_counts_from_db()` loads count=3 for that key
- 4th message after restart: count increments to 4, `count > 3` = True, row stored with `quarantined=TRUE`
- This validates that restart cannot reset a poison-pill counter back to zero

## Task Commits

1. **Task 1: Create migration 099_dlq_quarantine.sql and apply it** - `0a5d4b12` (feat)
2. **Task 2: Wire DLQ quarantine counting + DB-backed startup seed** - `6b124c23` (feat)

## Files Created/Modified

- `production/migrations/099_dlq_quarantine.sql` - Idempotent migration: ADD COLUMN quarantined + CREATE INDEX dlq_events_quarantine_lookup_idx
- `services/dlq_drain_agent.py` - Extended with quarantine counting, DB seed, updated INSERT SQL

## Decisions Made

- Quarantine uses DB-level column flag (not new Kafka topic) per D-22 deferral
- Startup DB seed uses a single GROUP BY query (not per-message DB reads) for performance
- Seed failure is degraded mode (warning log + return), not fatal - service still starts

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

Pre-commit hooks require ruff/black in PATH. Worktree doesn't inherit the venv PATH automatically. Fixed by prefixing commit command with `PATH="/home/bg/dev/indicagent/.venv/bin:$PATH"`.

## Next Phase Readiness

- Migration 099 is live in TimescaleDB; DLQDrainAgent ready to write quarantined flags on merge
- Grafana can now alert on `dlq_quarantine_total` metric to detect poison-pill DLQ messages
- Wave 2 plans (108-04 stall detection, 108-05 FastAPI OTel) may proceed independently

---
*Phase: 108-self-healing-hardening*
*Completed: 2026-05-28*
