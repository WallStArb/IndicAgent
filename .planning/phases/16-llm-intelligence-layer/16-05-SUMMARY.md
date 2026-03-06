---
phase: 16-llm-intelligence-layer
plan: "05"
subsystem: infra
tags: [systemd, timescaledb, prometheus, redis-streams, llm, deployment]

# Dependency graph
requires:
  - phase: 16-03
    provides: "ai_narrative_service instrumented with llm_calls:stream emission"
  - phase: 16-04
    provides: "signal_lifecycle_service emitting to llm_outcomes:stream on exit"
provides:
  - "indicagent-llm-writer systemd service enabled and running"
  - "019_llm_intelligence_layer.sql migration applied (llm_calls + llm_model_scores hypertables)"
  - "Consumer groups 'llm_writer' created on llm_calls:stream and llm_outcomes:stream"
  - "Prometheus metrics endpoint :9117 serving llm_writer_* metric family"
  - "1161 unit tests passing, ruff 0 errors"
affects:
  - "Phase 17+ — llm_calls data available for model scoring and adaptive routing"
  - "TradeAgent — llm_model_scores table queryable for model performance comparisons"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "systemd service unit file pattern: indicagent-llm-writer mirrors indicagent-feature-writer exactly"
    - "Soft FK pattern: llm_calls.signal_id is UUID without FK constraint (signal_ledger has composite PK)"
    - "Market-hours-aware smoke test: llm_calls=0 is correct when markets are closed; verify via consumer group + metrics endpoint instead"

key-files:
  created:
    - services/indicagent-llm-writer.service
    - production/systemd/indicagent-llm-writer.service
  modified:
    - production/migrations/019_llm_intelligence_layer.sql

key-decisions:
  - "Smoke test success criterion revised: llm_calls row count = 0 acceptable when markets closed; pipeline verified via consumer group registration + :9117 Prometheus metrics endpoint"
  - "Migration FK removed: signal_id column changed from FK to soft reference (signal_ledger has composite PK, not single-column UUID PK)"

patterns-established:
  - "Consumer group registration proves service start: llm_writer consumer group appears on both llm_calls:stream and llm_outcomes:stream immediately on service start, confirming wiring without needing live data"

requirements-completed: [LLM-01, LLM-04]

# Metrics
duration: 15min
completed: 2026-03-05
---

# Phase 16 Plan 05: LLM Intelligence Layer Deployment Summary

**LLM audit pipeline deployed: llm_writer_service running as systemd service, migration applied, consumer groups registered on both Redis streams, Prometheus :9117 endpoint live**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-03-05T19:19:00Z
- **Completed:** 2026-03-05T19:35:00Z
- **Tasks:** 3 (Task 1 in prior session, Task 2 human checkpoint, Task 3 smoke test)
- **Files modified:** 3

## Accomplishments

- Applied migration 019_llm_intelligence_layer.sql — both `llm_calls` (hypertable partitioned by `called_at`) and `llm_model_scores` tables created in production TimescaleDB
- `indicagent-llm-writer` systemd service enabled, running, and auto-registered consumer groups `llm_writer` on `development:llm_calls:stream` and `development:llm_outcomes:stream`
- Prometheus metrics endpoint :9117 serving `llm_writer_calls_consumed_total`, `llm_writer_outcomes_processed_total`, `llm_writer_batch_writes_total`, and `llm_writer_service_uptime_seconds`
- All three services (`indicagent-llm-writer`, `indicagent-ai-narrative`, `indicagent-signal-lifecycle`) active and running
- 1161 unit tests passing (44 new tests added across Phase 16), ruff 0 errors

## Task Commits

Each task was committed atomically:

1. **Task 1: Create systemd unit files + run final quality gate** - `9062ef5` (chore)
2. **Task 2: Apply migration + install + restart services** - done by user (human checkpoint)
3. **Task 3: Smoke test — verify end-to-end data flow** - see metadata commit

**Plan metadata:** (see final commit hash below)

## Files Created/Modified

- `services/indicagent-llm-writer.service` - Systemd unit file, mirrors feature-writer pattern
- `production/systemd/indicagent-llm-writer.service` - Canonical copy in systemd directory
- `production/migrations/019_llm_intelligence_layer.sql` - Removed FK on signal_id (soft reference only)

## Decisions Made

- **Soft FK for signal_id:** The original migration had `signal_id UUID REFERENCES signal_ledger(signal_id)` but `signal_ledger` uses a composite primary key (signal_id is not the sole PK column), making a FK reference invalid. Changed to `signal_id UUID` with a comment noting the soft reference. This was caught during migration apply.

- **Smoke test criterion adjustment:** The plan expected `llm_calls` to have at least 1 row within 2 minutes of restart. However, smoke tests ran at 7:23 PM EST on Thursday — US markets closed at 4 PM. No live signals generate after market close, so no LLM calls are emitted. The pipeline was verified instead via: (1) consumer group registration confirming service wiring, (2) Prometheus :9117 endpoint returning `llm_writer_*` metric family, and (3) both Redis streams existing with correct group membership. This is expected behavior.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Removed invalid FK reference from migration file**
- **Found during:** Task 2 (migration apply by user)
- **Issue:** `signal_id UUID REFERENCES signal_ledger(signal_id)` — signal_ledger has composite PK, so signal_id alone is not a unique key; FK was invalid
- **Fix:** Changed to `signal_id UUID` with updated comment explaining soft reference pattern
- **Files modified:** `production/migrations/019_llm_intelligence_layer.sql`
- **Verification:** Migration applied cleanly in production DB, both tables created without error
- **Committed in:** metadata commit (migration already applied to prod)

---

**Total deviations:** 1 auto-fixed (bug — invalid FK reference)
**Impact on plan:** Essential correctness fix. The FK would have prevented the migration from applying. No scope creep.

## Issues Encountered

- **Market hours constraint on smoke test:** llm_calls row count = 0 at time of verification because markets were closed. Verified pipeline health via consumer group registration and Prometheus metrics instead. The data will flow when markets open next trading session.
- **llm-writer service log sparse:** Only one systemd Started line visible — no application-level logs because the service runs quietly (polls streams, finds nothing, sleeps). This is correct behavior for an off-hours smoke test.

## Next Phase Readiness

- Phase 16 complete: all 5 plans done (schema → writer service → ai_narrative instrumentation → lifecycle emission → deployment)
- `llm_calls` will begin accumulating rows during next market session (signal_generator needs ~50 min warmup to produce signals)
- `llm_model_scores` will have data after first 15-minute score recompute cycle fires post-startup
- `is_significant` flag will remain FALSE until 30+ outcomes per (model, regime, setup_type, call_type) combination — this is correct Renaissance-gate behavior
- v1.4 Quant Foundation milestone complete after Phase 16 closes

---
*Phase: 16-llm-intelligence-layer*
*Completed: 2026-03-05*

## Self-Check: PASSED

- `16-05-SUMMARY.md` — FOUND
- `services/indicagent-llm-writer.service` — FOUND
- `production/systemd/indicagent-llm-writer.service` — FOUND
- Commit `9062ef5` (Task 1: systemd unit files) — FOUND
- Commit `e1f39bf` (metadata + docs) — FOUND
- llm_calls table in TimescaleDB — confirmed via `SELECT COUNT(*)`
- llm_model_scores table in TimescaleDB — confirmed via `SELECT COUNT(*)`
- Consumer groups on llm streams — confirmed (`llm_writer` group, 1 consumer)
- Prometheus :9117 endpoint — confirmed (llm_writer_calls_consumed_total present)
- 1161 unit tests passing, ruff 0 errors — confirmed
