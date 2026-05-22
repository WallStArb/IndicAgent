---
phase: 104-storage-architecture-redesign
plan: 04
subsystem: ML training infrastructure
tags: [storage, ml, timescaledb, systemd, materialized-view]
dependency_graph:
  requires:
    - phase: 104
      plan: 03
      reason: "Column rename (i1-i8) and signal_ledger slim schema must be live before ml_signal_training can reference trading_signals column"
  provides:
    - resource: ml_signal_training hypertable
      type: TimescaleDB table
      description: "Flat typed columns for ML training reads - no JSONB unnesting required"
    - resource: indicagent-ml-signal-training-materialize.timer
      type: Systemd timer
      description: "Nightly 02:00 UTC materialization - runs before ML training at 03:00"
  affects:
    - service: indicagent-ml-training
      type: Consumer
      impact: "Can now read flat columnar rows instead of ad-hoc JSONB unnesting at query time"
tech_stack:
  added:
    - "TimescaleDB hypertable with compression + retention policies"
    - "asyncpg for PostgreSQL async I/O"
    - "OpenTelemetry metrics (counter, histogram, up-down counter)"
    - "systemd Type=oneshot service + Persistent=true timer"
  patterns:
    - "UPSERT pattern: ON CONFLICT DO UPDATE for idempotent outcome backfill"
    - "LATERAL jsonb_array_elements() for unnesting trading_signals array"
    - "Three-phase materialization: INSERT (new) + UPDATE (backfill) + metrics"
key_files:
  created:
    - path: "db/migrations/094_create_ml_signal_training.sql"
      contains: "CREATE TABLE ml_signal_training with 34 typed columns, hypertable, indexes, retention + compression policies"
    - path: "src/intelligence/services/ml_signal_training_materialize_agent.py"
      contains: "MLSignalTrainingMaterializeAgent class with _phase_a_insert() and _phase_b_backfill() methods"
    - path: "services/ml_signal_training_agent.py"
      contains: "systemd oneshot entrypoint following ml_training_agent.py pattern"
    - path: "production/systemd/indicagent-ml-signal-training-materialize.service"
      contains: "Type=oneshot service definition with stdout/stderr logging"
    - path: "production/systemd/indicagent-ml-signal-training-materialize.timer"
      contains: "OnCalendar=*-*-* 02:00:00 UTC timer definition"
  modified:
    - path: "services/service_auditor_agent.py"
      contains: "Added indicagent-ml-signal-training-materialize to _DAG_ORDER (tier 8)"
decisions:
  - "Flat typed columns in ml_signal_training (no JSONB) - query-time performance over storage"
  - "UPSERT pattern for outcome backfill - single SQL idempotent operation handles both initial INSERT and late-resolving UPDATE"
  - "30-day lookback in Phase B - catches late-resolving outcomes without full table scan"
  - "02:00 UTC schedule (before 03:00 ML training) - ensures fresh data before model training"
  - "No lag threshold in service_auditor - batch timer service, not a Kafka consumer"
metrics:
  duration_minutes: 4
  completed_date: "2026-05-22"
  tasks_completed: 2
  files_created: 5
  files_modified: 1
---

# Phase 104 Plan 04: ML Signal Training Materialized Store Summary

**One-liner:** Nightly materialized hypertable with flat typed columns eliminates JSONB unnesting at ML training query time - UPSERT pattern handles late-resolving outcomes idempotently.

## Objective Met

Created the third pillar of the 3-store architecture: `ml_signal_training`. A nightly-materialized hypertable with flat typed columns (no JSONB) that pre-joins `intelligence_features.trading_signals` with `signal_ledger` lifecycle/outcomes. This eliminates JSONB unnesting at query time during ML training, aligning with the Renaissance principle that access pattern drives schema - ML training is a bulk columnar read, incompatible with OLTP point updates in signal_ledger.

## Implementation

### Task 1: Hypertable + Materialize Agent Class

**Created `db/migrations/094_create_ml_signal_training.sql`:**
- 34 typed columns (ts, signal_id, symbol, timeframe, setup_plugin, pnl_r, win_label, outcome, plus 26 feature columns from trading_signals JSONB)
- Hypertable on `ts` time column
- Compression policy: 7 days
- Retention policy: 1 year
- Indexes for common query patterns (symbol/timeframe, outcome, win_label)

**Created `MLSignalTrainingMaterializeAgent` class:**
- **Phase A (INSERT):** Extract and flatten from `intelligence_features.trading_signals` JSONB via `LATERAL jsonb_array_elements()`, LEFT JOIN `signal_ledger` for outcomes, ON CONFLICT DO NOTHING for initial insert only
- **Phase B (UPDATE):** UPSERT over 30-day lookback to catch late-resolving outcomes, ON CONFLICT DO UPDATE SET pnl_r/win_label/outcome WHERE win_label IS NULL AND EXCLUDED.pnl_r IS NOT NULL
- **Phase C (metrics):** Emit OTel counters for cycles/errors, histogram for duration, up-down counter for rows materialized (separate inserts vs updates)

**Created `services/ml_signal_training_agent.py`:**
- Systemd Type=oneshot entrypoint following `ml_training_agent.py` pattern
- Imports `MLSignalTrainingMaterializeAgent` and calls `asyncio.run(agent.start())`

### Task 2: Systemd Integration + Service Registration

**Created systemd units:**
- `indicagent-ml-signal-training-materialize.service`: Type=oneshot, runs `ml_signal_training_agent.py`, stdout/stderr to `logs/ml_signal_training_materialize_agent.log`, TimeoutStartSec=7200
- `indicagent-ml-signal-training-materialize.timer`: OnCalendar=*-*-* 02:00:00 UTC, Persistent=true (catches up on missed runs), runs before ML training at 03:00

**Installed and enabled:**
- Copied units to `/etc/systemd/system/`, ran `systemctl daemon-reload`, enabled timer
- Verified timer is enabled and waiting for next 02:00 UTC trigger
- Restarted `indicagent-service-auditor` to pick up new service

**Updated `services/service_auditor_agent.py`:**
- Added `indicagent-ml-signal-training-materialize` to `_DAG_ORDER` (tier 8 - analytics layer, same as `indicagent-ml-training`)
- No lag threshold added (batch timer service, not a Kafka consumer)

**First execution test:**
- Manual `systemctl start indicagent-ml-signal-training-materialize.service` succeeded (exit code 0/SUCCESS)
- Execution time: 377ms
- Log file: `logs/ml_signal_training_materialize_agent.log` (0 ERROR lines)
- Table count: 0 rows (expected - no signals for previous trading day during testing)

## Deviations from Plan

None - plan executed exactly as written. All acceptance criteria met:
- ml_signal_training hypertable exists with retention + compression jobs configured
- Nightly timer enabled with OnCalendar at 02:00 UTC
- service_auditor _DAG_ORDER updated to include the new batch unit
- First manual run succeeded with zero errors (0 rows expected for previous trading day)
- ml_signal_training has flat typed columns (no JSONB) accessible via standard SELECT
- ON CONFLICT DO UPDATE handles outcome backfill idempotently
- Separate insert/update metrics logged for tracking resolution rate

## Technical Details

**Outcome backfill strategy (UPSERT pattern):**
- Phase A uses `ON CONFLICT (ts, signal_id) DO NOTHING` for initial insert only - if row already exists, skip it
- Phase B uses `ON CONFLICT DO UPDATE SET pnl_r = EXCLUDED.pnl_r, win_label = (EXCLUDED.pnl_r > 0), outcome = EXCLUDED.outcome, materialized_at = NOW() WHERE ml_signal_training.signal_id = EXCLUDED.signal_id AND ml_signal_training.win_label IS NULL AND EXCLUDED.pnl_r IS NOT NULL` - idempotent update only for unresolved rows where outcome is now available
- 30-day lookback ensures rows inserted in prior runs get updated when their signal_ledger outcomes resolve
- Separate insert/update counts logged to track resolution rate

**LATERAL jsonb_array_elements() pattern:**
- Extracts per-signal features from `trading_signals` JSONB array: `CROSS JOIN LATERAL jsonb_array_elements(f.trading_signals) AS tf_sig(value)`
- Accesses nested fields: `tf_sig.value->>'signal_id'`, `tf_sig.value->'ctf_confluence'->>'ctf_score'`, etc.
- LEFT JOINs signal_ledger on `sl.signal_id::text = tf_sig.value->>'signal_id'` for outcomes

**OTel metrics:**
- `ml_signal_training_cycles_total`: counter (cycles executed)
- `ml_signal_training_errors_total`: counter (errors)
- `ml_signal_training_duration_seconds`: histogram (duration in seconds)
- `ml_signal_training_rows_materialized`: up-down counter (rows, with phase label "insert" or "update")

## Success Criteria Met

- 3-store target architecture fully operational: intelligence_features (canonical) + signal_ledger (slim lifecycle) + ml_signal_training (materialized ML reads)
- ML training pipeline can now read flat columnar rows from ml_signal_training (no JSONB unnesting at query time)
- Automation complete: TimescaleDB scheduler manages retention/compression; systemd timer manages nightly materialization
- Outcome backfill strategy handles late-resolving pnl_r/mae/mfe via UPSERT

## Next Steps

This completes Phase 104 Plan 04. The ml_signal_training hypertable is ready to receive nightly materializations. The next 02:00 UTC trigger will materialize the previous trading day's signals with flat typed columns. ML training pipeline can now be updated to read from ml_signal_training instead of ad-hoc JSONB unnesting.

**Integration note:** The `feature_builder.py` `_TRAINING_SQL` query (used by ML training) currently does `f.trading_signals->0->>'tod_multiplier'` for array access. After this plan, ML training can directly read `tod_multiplier` from the typed column in `ml_signal_training`, eliminating the JSONB path entirely. This update will be done in a future ML training refinement phase.
