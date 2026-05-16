---
phase: 82-ml-intelligence-quality-qualitative-foundation
reviewed: 2026-05-13T00:00:00Z
depth: standard
files_reviewed: 30
files_reviewed_list:
  - production/migrations/085_ctx_schema.sql
  - production/migrations/086_validation_results.sql
  - production/systemd/indicagent-ctx-writer.service
  - production/systemd/indicagent-feature-validation.service
  - production/systemd/indicagent-hmm-training.service
  - services/ctx_writer_agent.py
  - services/feature_validation_agent.py
  - services/hmm_training_agent.py
  - services/service_auditor_agent.py
  - src/api/main.py
  - src/api/routes/validation.py
  - src/core/stream_keys.py
  - src/intelligence/features/smc_context/hmm_regime.py
  - src/intelligence/pipeline/regime_gate.py
  - src/intelligence/services/feature_validation_compute_agent.py
  - src/intelligence/services/hmm_training_compute_agent.py
  - src/observability/metrics.py
  - tests/unit/test_ctx_writer_agent.py
  - tests/unit/test_feature_validation_compute_agent.py
  - tests/unit/test_hmm_training_compute_agent.py
  - tests/unit/test_regime_gate_soft.py
  - tests/unit/test_stream_keys_ctx.py
  - src/intelligence/trading/plugin_utils.py
  - src/intelligence/trading/confidence_utils.py
  - src/intelligence/trading/signal_schema.py
  - src/intelligence/trading/state_utils.py
  - src/intelligence/trading/atr_utils.py
  - src/intelligence/trading/exhaustion_utils.py
  - src/intelligence/trading/microstructure_utils.py
  - src/intelligence/trading/volume_profile_utils.py
findings:
  critical: 1
  warning: 8
  info: 0
  total: 9
status: issues_found
---

# Phase 82: Code Review Report

**Reviewed:** 2026-05-13T00:00:00Z
**Depth:** standard
**Files Reviewed:** 30
**Status:** issues_found

## Summary

Phase 82 introduces a CTX (qualitative context) substrate, an HMM multi-timeframe training pipeline, a regime gate soft-band, and a daily feature validation agent. The overall architecture is sound and follows project conventions well — asyncpg JSONB handling is correct, UTC timestamps are used consistently, and stream keys go through `stream_keys.py`. 

One critical data-integrity defect was found in the migration: the `ctx_snapshots` table declares `symbol` as nullable but includes it in the PRIMARY KEY, which PostgreSQL implicitly makes NOT NULL — making the intended global-event design (NULL symbol) impossible to use without a migration fix. The remaining eight warnings cover: dead code in the validation query builder, double logging initialization in two entrypoints, a `DatabaseManager` encapsulation bypass, wide CORS origin policy in main.py, hardcoded `INDICAGENT_ENV=development` in all three new systemd units, inconsistent `ExecStart` invocation style, and an unclosed event loop in a test helper.

## Critical Issues

### CR-01: `ctx_snapshots` PRIMARY KEY implicitly NOT-NULLs `symbol`, blocking global events

**File:** `production/migrations/085_ctx_schema.sql:32`

**Issue:** The DDL declares `symbol TEXT` (no NOT NULL constraint) with the intent of allowing NULL for global macro events (e.g., CPI, FOMC). However, line 34 includes `symbol` in `PRIMARY KEY (symbol, event_type, valid_from)`. PostgreSQL enforces NOT NULL on every column in a primary key — the nullable declaration is silently overridden. Any INSERT with `symbol = NULL` will fail with:

```
ERROR: null value in column "symbol" violates not-null constraint
```

This means every code path that tries to write a global ctx snapshot (symbol=NULL) will fail at runtime with no schema-level warning during migration.

**Fix:** Either (a) remove `symbol` from the PK and use a partial unique index for the non-NULL case, or (b) use a surrogate sentinel value (e.g. `'__global__'`) instead of NULL:

```sql
-- Option A: partial unique index
ALTER TABLE ctx_snapshots DROP CONSTRAINT ctx_snapshots_pkey;
ALTER TABLE ctx_snapshots ADD COLUMN id BIGSERIAL PRIMARY KEY;
CREATE UNIQUE INDEX ctx_snapshots_symbol_etype_valid_from_uq
    ON ctx_snapshots (symbol, event_type, valid_from)
    WHERE symbol IS NOT NULL;
CREATE UNIQUE INDEX ctx_snapshots_global_etype_valid_from_uq
    ON ctx_snapshots (event_type, valid_from)
    WHERE symbol IS NULL;

-- Option B (simpler): use sentinel, never NULL
-- Replace nullable TEXT with NOT NULL DEFAULT '__global__'
-- and update CtxWriterAgent to coerce None -> '__global__'
```

## Warnings

### WR-01: Dead code in `_fetch_slice_df()` — initial query/params construction never used

**File:** `src/intelligence/services/feature_validation_compute_agent.py:173`

**Issue:** Lines 173–194 construct a `query` string and `params` list with an inline `if regime_filter` branch. Lines 197–231 then unconditionally reassign both `query` and `params` using cleaner conditional branches. The first construction (lines 173–194) is never executed in any code path — it is always overwritten before `db_manager.execute_query()` is called.

**Fix:** Delete lines 173–194. The correct query/params construction starts at line 197. The dead code can cause confusion during future maintenance (e.g., someone editing the dead block expecting it to take effect).

---

### WR-02: Double `setup_service_logging` in feature-validation entrypoint and agent

**File:** `services/feature_validation_agent.py:18` and `src/intelligence/services/feature_validation_compute_agent.py` (inside `start()`)

**Issue:** `feature_validation_agent.py` calls `setup_service_logging("logs/feature_validation_agent.log")` at line 18. Then `FeatureValidationComputeAgent.start()` calls `setup_service_logging("logs/feature_validation_compute_agent.log")`. The second call wins — structlog is re-initialized to a different file, making the entrypoint's log call a no-op. Logs written before `start()` may go nowhere or to the wrong file.

**Fix:** Remove the `setup_service_logging` call from the entrypoint. Let the agent's `start()` method own logging initialization, consistent with how other oneshot agents operate. If entrypoint-level logging is needed before `start()`, use a single canonical log file shared by both.

---

### WR-03: Double `setup_service_logging` in hmm-training entrypoint and agent `__init__`

**File:** `services/hmm_training_agent.py` and `src/intelligence/services/hmm_training_compute_agent.py.__init__`

**Issue:** Same pattern as WR-02. The entrypoint initializes structlog to `logs/hmm_training_agent.log`, then `HMMTrainingComputeAgent.__init__` calls `setup_service_logging("logs/hmm_training_compute_agent.log")` at construction time — before `start()` is even called. Any log lines emitted in the entrypoint after agent construction (including the entrypoint's startup banner) go to the wrong file.

**Fix:** Move `setup_service_logging` out of `__init__` into `start()` (or into the entrypoint only, with `__init__` omitting the call). Prefer a single canonical log path.

---

### WR-04: `hmm_training_agent.py` bypasses `DatabaseManager.close()` encapsulation

**File:** `services/hmm_training_agent.py:38`

**Issue:** The oneshot teardown calls `await db_manager.pool.close()` directly instead of `await db_manager.close()`. `DatabaseManager.close()` likely performs additional teardown (connection health checks, metrics flush, etc.). Bypassing it via direct pool access couples the entrypoint to internal implementation details and means any future logic added to `close()` is silently skipped.

**Fix:**
```python
# Replace:
await db_manager.pool.close()

# With:
await db_manager.close()
```

---

### WR-05: `allow_origins=["*"]` CORS policy in `src/api/main.py`

**File:** `src/api/main.py:127`

**Issue:** CORS middleware is configured with `allow_origins=["*"]`, accepting requests from any origin. The comment reads "Configure appropriately for production" but the permissive setting ships as-is. The validation API endpoint exposes internal trading intelligence data (IC scores, p-values, regime decisions) that should not be served cross-origin to arbitrary web pages.

**Fix:** Restrict to the specific origins used by the dashboard:
```python
allow_origins=["http://localhost:3000", "http://192.168.68.53:3000"],
```
Or read from `Settings` so it can be environment-controlled without code changes.

---

### WR-06: `INDICAGENT_ENV=development` hardcoded in all three new systemd unit files

**File:** `production/systemd/indicagent-ctx-writer.service`, `production/systemd/indicagent-feature-validation.service`, `production/systemd/indicagent-hmm-training.service`

**Issue:** All three units set `Environment=INDICAGENT_ENV=development`. The existing production units use `production` (or an env-controlled value). Running these services in development mode on a production host means they subscribe to `dev.ctx.snapshot` (not `production.ctx.snapshot`), write to the wrong topics, and produce no data flow — the symptom being silent zero-throughput with no error.

**Fix:** Change to `INDICAGENT_ENV=production` in all three unit files (matching the pattern used by existing production systemd units). If the value must be environment-specific, use a `EnvironmentFile=` directive pointing to `/etc/indicagent/env`.

---

### WR-07: Inconsistent `ExecStart` invocation style across new systemd units

**File:** `production/systemd/indicagent-ctx-writer.service`, `production/systemd/indicagent-feature-validation.service`, `production/systemd/indicagent-hmm-training.service`

**Issue:** `indicagent-ctx-writer.service` uses module invocation:
```
ExecStart=/home/bg/dev/indicagent/.venv/bin/python -m services.ctx_writer_agent
```
But `indicagent-feature-validation.service` and `indicagent-hmm-training.service` use script invocation:
```
ExecStart=/home/bg/dev/indicagent/.venv/bin/python services/feature_validation_agent.py
ExecStart=/home/bg/dev/indicagent/.venv/bin/python services/hmm_training_agent.py
```
The script invocation requires the working directory to be set correctly (via `WorkingDirectory=`) for relative imports to resolve. The module invocation is more robust. All existing production units use `-m` style.

**Fix:** Change the two oneshot units to use `-m` invocation:
```
ExecStart=/home/bg/dev/indicagent/.venv/bin/python -m services.feature_validation_agent
ExecStart=/home/bg/dev/indicagent/.venv/bin/python -m services.hmm_training_agent
```

---

### WR-08: `_run()` helper in `test_regime_gate_soft.py` leaks event loop

**File:** `tests/unit/test_regime_gate_soft.py` (the `_run()` helper function)

**Issue:** The helper creates a new event loop via `asyncio.new_event_loop()` and calls `run_until_complete()` but never closes the loop. Unclosed event loops generate `ResourceWarning` under Python 3.11+ and can accumulate OS-level file descriptors across the test suite.

**Fix:**
```python
def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
```

---

_Reviewed: 2026-05-13T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
