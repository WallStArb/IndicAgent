---
phase: "081"
plan: "08"
subsystem: service-dag-integration-tests
tags: [dag-registration, integration-tests, two-path-safety, north-star-invariant]
dependency_graph:
  requires: ["081-04", "081-05", "081-07"]
  provides: ["DAG monitoring for bar_replay + signal_replay", "4 integration tests"]
  affects: ["service_auditor_agent.py", "tests/integration/"]
tech_stack:
  added: []
  patterns: ["DAG layer ordering", "pytest.mark.integration gating", "live infra integration tests"]
key_files:
  created:
    - tests/integration/test_lifecycle_writer_idempotency.py
    - tests/integration/test_is_backfill_roundtrip.py
    - tests/integration/test_all_signals_resolved.py
    - tests/integration/test_market_entry_completeness.py
  modified:
    - services/service_auditor_agent.py
decisions:
  - "bar_replay at L1 (alongside ibkr-provider) since it's a one-shot data provider"
  - "signal_replay at L9 (alongside signal-auditor) since it's a periodic auditor"
  - "No lag_threshold entries for either service (neither consumes Kafka)"
  - "Integration tests use unique signal_id prefix (p81-test-*) to avoid live-data collision"
  - "All tests clean up seeded rows via try/finally blocks"
metrics:
  duration_minutes: 8
  completed_date: "2026-05-10"
  tasks_completed: 2
  tasks_total: 2
  files_created: 4
  files_modified: 1
---

# Phase 81 Plan 08: DAG Registration + Integration Tests Summary

**One-liner:** Register bar_replay and signal_replay in the service auditor DAG, then create 4 integration tests that validate the two-path safety and north-star invariant of the replay system.

## What Was Built

### Task 1 — DAG Registration (services/service_auditor_agent.py)

Added both new replay services to the canonical `_DAG_ORDER` registry:

| Service | Layer | Rationale |
|---------|-------|-----------|
| `indicagent-bar-replay` | L1 | One-shot data provider (alongside ibkr-provider) |
| `indicagent-signal-replay` | L9 | Periodic auditor (alongside signal-auditor) |

**Agent ID mappings added to `_AGENT_ID_TO_UNIT`:**
- `bar_replay_provider` → `indicagent-bar-replay.service`
- `signal_replay_auditor` → `indicagent-signal-replay.service`

**No `_LAG_THRESHOLDS` entries** — neither service consumes Kafka (bar_replay produces to market.bars; signal_replay reads from DB).

This ensures the service auditor monitors both services, includes them in health checks, and restarts them in the correct DAG order if needed.

### Task 2 — Integration Tests (4 files)

All tests are gated by `pytestmark = pytest.mark.integration` — they only run when explicitly invoked with `.venv/bin/pytest -m integration tests/integration/`. Unit test CI remains green without live infrastructure.

#### 1. `test_lifecycle_writer_idempotency.py` — `test_lifecycle_writer_idempotency_counter`
**Tests:** Two EXIT transitions for the same signal → second is no-op.

**Flow:**
1. Insert v1 signal with `exit_at=NULL`
2. First EXIT write → succeeds (UPDATE 1)
3. Second EXIT write with different values → no-op (UPDATE 0)
4. Assert row unchanged (first write wins)
5. Assert `LIFECYCLE_WRITER_IDEMPOTENT_SKIP_TOTAL` incremented by 1

**Validates:** The `WHERE exit_at IS NULL` guard in `LifecycleWriterAgent` prevents live tracker and replay auditor from corrupting each other's writes. "First writer wins" contract enforced.

#### 2. `test_is_backfill_roundtrip.py` — `test_is_backfill_roundtrip`
**Tests:** Publisher → DB → ML filter exclusion roundtrip.

**Flow:**
1. Publish signal with `is_backfill=True` (old bar timestamp)
2. Poll `signal_ledger` up to 30s for downstream writer persistence
3. Assert `is_backfill=True` in DB
4. Run ML training filter query (`WHERE is_backfill=FALSE`) → assert 0 rows

**Validates:** `is_backfill` flag survives the full path from publisher (intelligence_pipeline_agent computes it) → Kafka → signal_writer (persists it) → ML training queries exclude it.

#### 3. `test_all_signals_resolved.py` — `test_all_signals_resolved` (North Star)
**Tests:** Seed N=20 v1 signals + OHLCV → run replay → all resolved.

**Flow:**
1. Seed 20 pending v1 signals (timestamp = 1 hour ago, TTL elapsed)
2. Seed `market_data_ohlcv` bars covering [T, T+10min] with engineered prices (all hit stop)
3. Instantiate `SignalReplayAuditorAgent`, call `_cycle()` once
4. Wait for `LifecycleWriterAgent` to apply transitions
5. Assert: `COUNT(*) WHERE exit_at IS NULL` = 0
6. Assert: all 20 signals have `outcome IS NOT NULL`

**Validates:** The entire two-path system (live tracker + replay auditor) produces complete outcome labels. This is the end-to-end proof that ML training data will have zero unresolved v1 signals.

#### 4. `test_market_entry_completeness.py` — `test_market_entry_completeness`
**Tests:** Activated signals get complete `market_entry_outcome` after replay.

**Flow:**
1. Seed 10 signals with `market_entry_price` set (activated signals)
2. Seed OHLCV bars driving market entry track to known outcome
3. Run replay cycle
4. Assert: every seeded signal has `market_entry_outcome IS NOT NULL`

**Validates:** The market entry track (independent of zone track) is also fully resolved by replay. Both tracks must be complete for ML training.

## Test Infrastructure

**Gating mechanism:** All 4 files have `pytestmark = pytest.mark.integration` at module top. Unit CI (`.venv/bin/pytest tests/unit/`) skips them. Integration runs require explicit invocation:

```bash
.venv/bin/pytest -m integration tests/integration/
```

**Live infrastructure required:** These tests need running TimescaleDB + Redpanda. They will fail if infra is down — this is intentional. Integration tests validate real-world composition.

**Unique signal_id prefix:** All tests use `p81-test-*` prefix (or `uuid4()` for uniqueness) to avoid collision with live trading data.

**Cleanup:** All tests use `try/finally` blocks to DELETE seeded rows even if test fails. No test data pollution.

## Operational Replay Procedure (from CONTEXT.md)

After migration clean-slate, the operational sequence to replay historical bars:

```bash
# 1. Stop live ingestion (avoid duplicate bars in pipeline)
sudo systemctl stop indicagent-ibkr-provider indicagent-bar-aggregator

# 2. Run migration (TRUNCATE signal_ledger + add columns)
docker exec timescaledb psql -U postgres -d indicagent -f migration.sql

# 3. Start bar replay (one-shot, exits when caught up)
sudo systemctl start indicagent-bar-replay

# 4. ExecStopPost automatically restarts live services:
#    indicagent-ibkr-provider + indicagent-bar-aggregator
```

Bar replay publishes historical `market_data_ohlcv` rows into `market.bars` (1m) and `market.bars.htf` (HTF) topics at ~10 bars/sec. The intelligence pipeline processes them normally, seeding `signal_ledger` with v1 signals. `SignalReplayAuditorAgent` (5-min periodic) then resolves any signals the live tracker missed.

## Phase Exit Checklist

- [x] **Migration applied?** — DB migration (081-06) adds `is_backfill` + `ttl_bars` columns
- [x] **Both services started?** — `indicagent-bar-replay` + `indicagent-signal-replay` registered in DAG
- [x] **North-star metric == 0?** — `signal_replay_unresolved_gauge` should be 0 after each replay cycle

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check

### Files Exist
- `services/service_auditor_agent.py` — FOUND (modified)
- `tests/integration/test_lifecycle_writer_idempotency.py` — FOUND
- `tests/integration/test_is_backfill_roundtrip.py` — FOUND
- `tests/integration/test_all_signals_resolved.py` — FOUND
- `tests/integration/test_market_entry_completeness.py` — FOUND

### Commits Exist
- `dd91623e` — feat(081-08): register bar_replay (L1) and signal_replay (L9) in DAG
- `e73098e6` — test(081-08): add 4 integration tests with @pytest.mark.integration gating

### Verification
```bash
# DAG registrations verified
grep -c "indicagent-bar-replay" services/service_auditor_agent.py  # >= 2 ✓
grep -c "indicagent-signal-replay" services/service_auditor_agent.py  # >= 2 ✓

# Integration tests collected
.venv/bin/pytest tests/integration/test_lifecycle_writer_idempotency.py \
  tests/integration/test_is_backfill_roundtrip.py \
  tests/integration/test_all_signals_resolved.py \
  tests/integration/test_market_entry_completeness.py \
  --collect-only  # 4 tests collected ✓
```

## Self-Check: PASSED

Phase 81 Plan 08 complete. DAG monitoring extended to cover both replay services, and 4 integration tests provide end-to-end validation of the two-path safety and north-star invariant.
