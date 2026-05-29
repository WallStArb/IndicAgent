---
phase: 109-config-foundation-self-healing-engine
plan: "04"
subsystem: self-healing
tags: [self-healing, webhook, prometheus, remediation, asyncpg, circuit-breaker, otel-metrics, hypertable]
dependency_graph:
  requires:
    - remediation_ledger_schema  # 109-04 Task 1: hypertable created here
    - config_foundation_db_schema  # 109-01: config tables + DB connection
    - config_and_selfhealing_metrics  # 109-02: REMEDIATION_ATTEMPT_TOTAL etc
    - ManagedPool  # 109-04 Task 2: created here
  provides:
    - SelfHealingEngine
    - RemediationLedger
    - ManagedPool
    - REMEDIATION_STRATEGIES
    - remediation_ledger_hypertable
    - remediation_success_rates_MV
  affects:
    - src/observability/metrics.py (REMEDIATION_POOL_FLUSH_TOTAL + REMEDIATION_CIRCUIT_BREAKER_OPEN_TOTAL added)
    - 109-05  # FastAPI webhook router wires to SelfHealingEngine
tech_stack:
  added: []
  patterns:
    - Fail-closed Prometheus measurement (no action on sensor failure)
    - Durable ledger-backed idempotency (alert_id dedupe survives restarts)
    - Durable ledger-backed rate limiting (action count survives restarts)
    - ManagedPool graceful-drain flush (create -> verify -> atomic swap -> drain old)
    - Circuit breaker via direct DB query (rolling 5-minute window)
    - Defense-in-depth webhook auth (HTTP layer + engine layer)
    - Auto-disable on low success rate (count>=10 AND rate<0.8)
key_files:
  created:
    - src/self_healing/__init__.py
    - src/self_healing/strategies.py
    - src/self_healing/pool_manager.py
    - src/self_healing/ledger.py
    - src/self_healing/engine.py
  modified:
    - production/migrations/109_config_foundation.sql
    - src/observability/metrics.py
decisions:
  - "ManagedPool.flush() atomically swaps pool only after SELECT 1 verify succeeds - rollback preserves old pool on failure"
  - "Circuit breaker implemented via direct remediation_ledger query (no in-memory state) - trips when >50% of last-5-min attempts failed AND total>=4"
  - "PROMETHEUS_URL from env var not hardcoded - fail-closed on measurement failure (no remediation without sensor)"
  - "db_pool_exhausted strategy enabled=True (flush is live); other two strategies default OFF gated by alert-level config"
  - "Re-bind self._ledger after successful pool flush so subsequent ledger writes use the new pool"
metrics:
  duration_minutes: 6
  completed_date: "2026-05-29"
  tasks_completed: 5
  files_created: 5
  files_modified: 2
---

# Phase 109 Plan 04: Self-Healing Engine Summary

**One-liner:** Alertmanager webhook engine with fail-closed Prometheus measurement, durable ledger-backed idempotency/rate-limiting, ManagedPool graceful flush + rollback, and circuit breaker - all three Phase 1 remediation strategies live.

## What Was Built

### Task 1: remediation_ledger Hypertable + MV (39d4fe6b)

Appended to `production/migrations/109_config_foundation.sql`:

| Object | Type | Purpose |
|--------|------|---------|
| `remediation_ledger` | TimescaleDB hypertable | Durable audit log for all remediation attempts |
| `idx_remediation_alert_time` | Index on (alert_id, timestamp DESC) | Powers durable idempotency dedupe |
| `idx_remediation_action_time` | Index on (action, timestamp DESC) | Powers durable rate-limit count queries |
| `remediation_success_rates` | Materialized view (30d rolling) | `get_success_rate()` and auto-disable logic |
| `idx_remediation_success_rates_action` | Unique index on MV | Required for `REFRESH CONCURRENTLY` |

Compression enabled: `timescaledb.compress_segmentby = 'action'`, 7-day policy. Retention: 90 days.

Idempotency verification:
```
psql => remediation_success_rates MV confirmed
Second run: no errors (IF NOT EXISTS on all objects)
```

### Task 2: Strategies Registry + ManagedPool + Metrics (ce5edde1)

**`src/self_healing/strategies.py`:**
- `REMEDIATION_STRATEGIES`: 3 entries
  - `disk_usage_high` - `delete_old_logs`, threshold=80%, max 3/hr, **enabled=False**
  - `consumer_lag_high` - `restart_consumer`, threshold=1000, max 2/hr, **enabled=False**
  - `db_pool_exhausted` - `flush_connection_pool`, threshold=90%, max 5/hr, **enabled=True**
- `IMPLEMENTED_ACTIONS`: frozenset of all 3 action names
- `state_variable_to_strategy_key()`: O(1) dict lookup
- `disable_strategy()`: in-place disable with structlog warning
- No module-level rate-limit state (delegated to RemediationLedger)

**`src/self_healing/pool_manager.py`:**

`ManagedPool.flush()` implements Renaissance standard:
1. Acquire `asyncio.Lock` (serialize concurrent flushes)
2. `create_pool()` with same URL/kwargs
3. `SELECT 1` via new pool (health verify BEFORE swap)
4. On verify failure: close new pool, raise - `self._pool` unchanged (rollback path)
5. Atomic swap: `self._pool = new_pool` (only after verify succeeds)
6. `asyncio.wait_for(old_pool.close(), timeout=drain_timeout)` with `terminate()` fallback
7. Return `{"create_ms", "verify_ms", "drain_ms", "drain_forced"}`

**`src/observability/metrics.py`:**
- `REMEDIATION_POOL_FLUSH_TOTAL`: counter by `outcome` (success|failed)
- `REMEDIATION_CIRCUIT_BREAKER_OPEN_TOTAL`: counter by `reason`

Verification:
```
python -c "from src.self_healing.strategies import REMEDIATION_STRATEGIES, IMPLEMENTED_ACTIONS; assert 'flush_connection_pool' in IMPLEMENTED_ACTIONS; assert REMEDIATION_STRATEGIES['db_pool_exhausted'].enabled is True; print('OK')"
=> OK
python -c "from src.self_healing.pool_manager import ManagedPool; print('OK')"
=> OK
python -c "from src.observability.metrics import REMEDIATION_POOL_FLUSH_TOTAL; print('OK')"
=> OK
```

### Task 3: RemediationLedger (f5854bed)

`src/self_healing/ledger.py` provides:

| Method | Purpose | Index used |
|--------|---------|------------|
| `record()` | INSERT + OTel metrics emit | - |
| `alert_already_processed()` | Durable idempotency check | `idx_remediation_alert_time` |
| `attempts_in_last_hour()` | Durable rate-limit count | `idx_remediation_action_time` |
| `get_success_rate()` | Read from MV; (0.0, 0) on miss | MV lookup |
| `refresh_success_rates()` | `REFRESH MATERIALIZED VIEW CONCURRENTLY` | requires unique MV index |

All three query methods are ledger-backed (not in-memory) - idempotency and rate limits survive process restarts.

### Tasks 4+5: SelfHealingEngine + Circuit Breaker (d0cf5664)

`src/self_healing/engine.py`:

**`handle_webhook()` flow:**
1. Engine-layer auth (defense-in-depth; HTTP-layer in 109-05 is primary gate)
2. Payload validation (400 on bad data)
3. `WEBHOOK_RECEIVED_TOTAL` increment
4. Durable idempotency: `alert_already_processed()` - returns "Already processed (durable)" if seen

**`execute_remediation()` control loop:**
```
Prometheus pre-measure (fail-closed on None)
  -> Circuit breaker check (_check_circuit_breaker)
    -> Strategy lookup + enabled check
      -> IMPLEMENTED_ACTIONS gate
        -> Durable rate-limit check (attempts_in_last_hour)
          -> Action execution (asyncio.timeout)
            -> Post-measure
              -> Ledger record (success/partial/failed)
                -> Auto-disable check
```

**`_check_circuit_breaker()`:**
- Direct DB query on `remediation_ledger` last 5 minutes
- Returns `(True, reason)` when `total >= 4 AND failed/total > 0.5`
- Minimum-sample gate (4) prevents single-failure trips
- `REMEDIATION_CIRCUIT_BREAKER_OPEN_TOTAL` emitted when open

**`_flush_connection_pool()`:**
- Delegates to `ManagedPool.flush()`
- `REMEDIATION_POOL_FLUSH_TOTAL{outcome=success}` on success
- `REMEDIATION_POOL_FLUSH_TOTAL{outcome=failed}` on failure (re-raises)
- Re-binds `self._ledger = RemediationLedger(self._managed_pool.pool)` after swap

**Unit tests after all changes: 4052 passed, 31 skipped (zero failures)**

## Acceptance Criteria Verification

```
grep -q "flush_connection_pool" src/self_healing/strategies.py          => FOUND
grep -q "TODO Phase 110" src/self_healing/strategies.py                 => NOT FOUND (correct: no deferrals)
grep -q "REMEDIATION_POOL_FLUSH_TOTAL" src/observability/metrics.py     => FOUND
grep -q "PROMETHEUS_URL" src/self_healing/engine.py                     => FOUND
grep -q "_check_circuit_breaker" src/self_healing/engine.py             => FOUND
grep -q "circuit_breaker_open" src/self_healing/engine.py               => FOUND
grep -q "REMEDIATION_CIRCUIT_BREAKER_OPEN_TOTAL" src/observability/metrics.py => FOUND
grep -q "_processed_alerts" src/self_healing/engine.py                  => NOT FOUND (correct: no in-memory set)
grep -q "defense-in-depth" src/self_healing/engine.py                   => FOUND

Circuit breaker before strategy lookup (line order):
  _check_circuit_breaker: line 183
  strategy_key lookup: line 197 (AFTER circuit breaker - correct)

DB objects verified:
  remediation_ledger hypertable: CONFIRMED
  idx_remediation_alert_time + idx_remediation_action_time: CONFIRMED
  remediation_success_rates MV + unique index: CONFIRMED
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing] ALTER TABLE compression before add_compression_policy**
- **Found during:** Task 1 migration run
- **Issue:** `add_compression_policy` fails with "columnstore not enabled" when `ALTER TABLE SET (timescaledb.compress = true)` is missing
- **Fix:** Added `ALTER TABLE remediation_ledger SET (timescaledb.compress = true, timescaledb.compress_segmentby = 'action')` before the compression policy
- **Files modified:** `production/migrations/109_config_foundation.sql`
- **Commit:** 39d4fe6b

**2. [Rule 3 - Blocking] Pre-commit hook could not find ruff/black in worktree path**
- **Found during:** Task 2 commit
- **Issue:** Hook uses `${REPO_ROOT}/.venv/bin/ruff` where REPO_ROOT resolves to worktree path; no `.venv` in worktree
- **Fix:** Created symlink `.venv -> /home/bg/dev/indicagent/.venv` in worktree root (not committed to git)

**3. [Rule 1 - Bug] asyncio.TimeoutError deprecated alias**
- **Found during:** Task 2 ruff check
- **Issue:** `asyncio.TimeoutError` is deprecated; ruff auto-fixed to `TimeoutError`
- **Fix:** Applied by ruff --fix automatically during pre-commit
- **Files modified:** `src/self_healing/pool_manager.py`
- **Commit:** ce5edde1

## Self-Check: PASSED

Files verified:
- `src/self_healing/__init__.py` - FOUND
- `src/self_healing/strategies.py` - FOUND
- `src/self_healing/pool_manager.py` - FOUND
- `src/self_healing/ledger.py` - FOUND
- `src/self_healing/engine.py` - FOUND
- `src/observability/metrics.py` - FOUND
- `production/migrations/109_config_foundation.sql` - FOUND

Commits verified:
- `39d4fe6b` (ledger hypertable) - FOUND
- `ce5edde1` (strategies + pool_manager + metrics) - FOUND
- `f5854bed` (ledger.py) - FOUND
- `d0cf5664` (engine.py) - FOUND
