---
phase: 109-config-foundation-self-healing-engine
reviewed: 2026-05-29T00:00:00Z
depth: standard
files_reviewed: 27
files_reviewed_list:
  - production/migrations/109_config_foundation.sql
  - production/systemd/indicagent-config-service.service
  - production/systemd/indicagent-outbox-dispatcher.service
  - production/systemd/indicagent-self-healing-agent.service
  - services/alpha_swarm_agent.py
  - services/config_service_agent.py
  - services/outbox_dispatcher_agent.py
  - services/self_healing_agent.py
  - services/service_auditor_agent.py
  - src/config/config_consumer.py
  - src/config/config_schema.py
  - src/config/config_service.py
  - src/config/outbox_dispatcher.py
  - src/config/runtime_defaults.py
  - src/config/settings.py
  - src/core/agent/base.py
  - src/core/stream_keys.py
  - src/intelligence/ai/alpha/correlation_agent.py
  - src/intelligence/ai/alpha/counterfactual_agent.py
  - src/intelligence/ai/alpha/ml_scorer_agent.py
  - src/intelligence/ai/alpha/regime_coherence_agent.py
  - src/observability/metrics.py
  - src/self_healing/engine.py
  - src/self_healing/__init__.py
  - src/self_healing/ledger.py
  - src/self_healing/pool_manager.py
  - src/self_healing/strategies.py
  - tests/unit/services/test_service_auditor_agent.py
findings:
  critical: 4
  warning: 8
  info: 4
  total: 16
status: issues_found
---

# Phase 109: Code Review Report

**Reviewed:** 2026-05-29T00:00:00Z
**Depth:** standard
**Files Reviewed:** 27
**Status:** issues_found

## Summary

Phase 109 delivers the config foundation (DB-backed hot-reload, transactional outbox, config HTTP API) and the self-healing engine (Alertmanager webhook, remediation strategies, ledger). The architecture is well-structured and the three-layer invariant (INFRA/STRUCT/OPS) is consistently enforced. However, several correctness issues were found: the migration SQL seeds every config key twice (duplicate inserts will silently fail but also indicate a copy-paste error in the script), the self-healing agent uses a deprecated FastAPI lifecycle API, a blocking subprocess call is buried inside an async method, and the config service pool is never closed on shutdown. There are also several meaningful warnings around security hardening and operational reliability.

---

## Critical Issues

### CR-01: Migration SQL inserts every config_schema and config_state row twice

**File:** `production/migrations/109_config_foundation.sql:282-316`
**Issue:** The migration seeds all 15 regime/swarm/roll/cross_asset/macro rows in both `config_schema` and `config_state` at lines 89-216 (Task 2 first block) and then *again* at lines 282-316 (labeled "Task 2 Plan 05"). Both blocks use `ON CONFLICT DO NOTHING`, so the second block silently does nothing on a fresh install. However, if the first block is ever removed or refactored, the second block's values (which differ in one place: `swarm.min_confidence` default is `'0.6'` in the first block but `'0.60'` in the second) become the canonical seed. More critically, the agent.shadow_mode seed block (lines 377-389) has no corresponding first-block counterpart, so Task 4 adds 4 new rows that are truly additive — but the bulk of Task 2 is pure duplication. The duplicated block at lines 300-316 also seeds `config_state` version=1 for all keys, which will silently no-op even if a previous operator has advanced versions in production; that is intentional. The real risk is maintainability: any future change to a default value must now be made in both locations or the script will behave differently on a fresh install vs. re-run.

**Fix:** Remove the duplicate seed block at lines 282-316 entirely and keep only the first seed block (lines 89-216) plus the new Task 3 (lines 324-370) and Task 4 (lines 377-389) blocks. The first block already uses `ON CONFLICT DO NOTHING` for idempotency. Add a comment before Task 3 explaining the sequence. The Task 2 duplicate block was apparently added when "Plan 05" tasks were stapled onto the original migration script — remove it.

---

### CR-02: `_delete_old_logs` is a blocking subprocess call inside an async method

**File:** `src/self_healing/engine.py:397-403`
**Issue:** `_delete_old_logs` uses `subprocess.run(...)` (synchronous, blocking) inside an `async def`. This blocks the asyncio event loop for the duration of the `find ... -delete` command, which can run for seconds on a large log directory. The method is called from `_execute_action` which is awaited under `asyncio.timeout(strategy.timeout_seconds)`, so the timeout does not actually cancel a blocking subprocess call — it only cancels the coroutine *after* the blocking call returns (timeouts do not interrupt synchronous code in asyncio).

```python
# src/self_healing/engine.py:396-403 (current — WRONG)
async def _delete_old_logs(self, mountpoint: str) -> None:
    subprocess.run(                          # blocks the event loop
        ["find", mountpoint, "-name", "*.log", "-mtime", "+7", "-delete"],
        check=True,
        capture_output=True,
        timeout=30,
    )
```

**Fix:** Use `asyncio.create_subprocess_exec` (or `loop.run_in_executor`) so the event loop remains responsive and the `asyncio.timeout` can actually cancel it:

```python
async def _delete_old_logs(self, mountpoint: str) -> None:
    proc = await asyncio.create_subprocess_exec(
        "find", mountpoint, "-name", "*.log", "-mtime", "+7", "-delete",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"find -delete failed: {stderr.decode().strip()}")
```

---

### CR-03: `ConfigService` pool is never closed — connection leak in config HTTP API

**File:** `services/config_service_agent.py:65-78`
**Issue:** The `lifespan` context manager creates a `ConfigService` via `await config_service.initialize()` (which opens an asyncpg pool) but never calls any close method on it. The comment at line 77 says "pool cleanup handled by garbage collection (asyncpg pool)" — but asyncpg pools are NOT safely GC-closeable; they hold open TCP connections to PostgreSQL that can exhaust the server's connection limit. This is a connection leak on every restart of the config-service process.

```python
# services/config_service_agent.py:65-78 (current — WRONG)
@asynccontextmanager
async def lifespan(app: FastAPI):
    global config_service
    settings = get_settings()
    config_service = ConfigService(database_url=settings.database_url)
    await config_service.initialize()
    ...
    yield
    # Shutdown: pool cleanup handled by garbage collection (asyncpg pool)  <-- BUG
    logger.info("config_service_agent.shutdown")
```

**Fix:** Close the pool explicitly in the shutdown path. Add a `close()` method to `ConfigService` and call it:

```python
# In ConfigService (src/config/config_service.py):
async def close(self) -> None:
    if self._db_pool is not None:
        await self._db_pool.close()
        self._db_pool = None

# In lifespan (services/config_service_agent.py):
@asynccontextmanager
async def lifespan(app: FastAPI):
    global config_service
    settings = get_settings()
    config_service = ConfigService(database_url=settings.database_url)
    await config_service.initialize()
    yield
    if config_service is not None:
        await config_service.close()
    logger.info("config_service_agent.shutdown")
```

---

### CR-04: `self_healing_agent.py` uses deprecated `@app.on_event` lifecycle hooks

**File:** `services/self_healing_agent.py:30-48`
**Issue:** `@app.on_event("startup")` and `@app.on_event("shutdown")` were deprecated in FastAPI 0.93.0 (early 2023) and removed in FastAPI 0.114 (2024). The project uses FastAPI and will eventually hit a version where these hooks silently do nothing, meaning `_self_healing_engine` is never initialized and every webhook call returns HTTP 503. Meanwhile `config_service_agent.py` (written in the same phase) correctly uses the `lifespan` context manager pattern. The inconsistency between the two files in the same phase is a latent upgrade hazard.

**Fix:** Convert to the `lifespan` context manager pattern (consistent with `config_service_agent.py`):

```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    from src.config.settings import get_settings
    from src.self_healing.engine import SelfHealingEngine
    from src.self_healing.pool_manager import ManagedPool

    settings = get_settings()
    managed_pool = ManagedPool(settings.database_url, pool_name="self_healing")
    await managed_pool.initialize()
    global _self_healing_engine
    _self_healing_engine = SelfHealingEngine(managed_pool)
    await _self_healing_engine.initialize()
    yield
    if _self_healing_engine:
        await _self_healing_engine.close()

app = FastAPI(title="IndicAgent Self-Healing Engine", version="1.0.0", lifespan=lifespan)
# Remove the @app.on_event decorators
```

---

## Warnings

### WR-01: `outbox_dispatcher.py` uses inline `.isoformat().replace()` instead of `format_iso_ts()`

**File:** `src/config/outbox_dispatcher.py:186`
**Issue:** Line 186 uses `datetime.now(UTC).isoformat().replace("+00:00", "Z")` directly instead of `format_iso_ts()` from `service_utils.py`. CLAUDE.md explicitly states: "use `format_iso_ts(dt)` from `service_utils.py` for Kafka/JSON. Never inline `.isoformat().replace('+00:00', 'Z')`." This is both a CLAUDE.md violation and a maintenance hazard — if the timestamp format ever changes, this site will be missed.

**Fix:**
```python
from src.core.service_utils import format_iso_ts
# ...
"changed_at": format_iso_ts(datetime.now(UTC)),
```

---

### WR-02: `SelfHealingEngine.__init__` constructs `RemediationLedger` with `managed_pool.pool` before pool is initialized

**File:** `src/self_healing/engine.py:74`
**Issue:** `self._ledger = RemediationLedger(managed_pool.pool)` is called in `__init__`, but `managed_pool.pool` raises `RuntimeError("ManagedPool not initialized — call initialize() first")` if the pool has not yet been initialized. The calling code in `self_healing_agent.py` calls `await managed_pool.initialize()` before constructing `SelfHealingEngine`, so this works in practice — but the ordering is fragile: if a caller constructs `SelfHealingEngine` before calling `managed_pool.initialize()`, it crashes with a confusing error at construction time, not at use time. The `_flush_connection_pool` method already correctly re-binds the ledger after flush: `self._ledger = RemediationLedger(self._managed_pool.pool)`.

**Fix:** Defer ledger construction to `initialize()` to match the lifecycle contract:

```python
def __init__(self, managed_pool: ManagedPool) -> None:
    self._managed_pool = managed_pool
    self._ledger: RemediationLedger | None = None  # initialized in initialize()
    ...

async def initialize(self) -> None:
    self._http_session = aiohttp.ClientSession()
    self._ledger = RemediationLedger(self._managed_pool.pool)
```

---

### WR-03: `ConfigConsumerMixin._pre_setup_config_load` creates a new `ConfigService` (and pool) on every call — no sharing with service's own pool

**File:** `src/config/config_consumer.py:69-70`
**Issue:** `_pre_setup_config_load` creates a fresh `ConfigService(self.settings.database_url)` and calls `await svc.initialize()` on every agent startup. This opens a new asyncpg pool that is never closed (same issue as CR-03 — there is no `await svc.close()` or `finally` block). Every agent that uses `ConfigConsumerMixin` leaks a DB pool connection on startup. With ~25 daemons, this can exhaust the PostgreSQL connection limit.

```python
# src/config/config_consumer.py:69-70 (current — leaks pool)
svc = ConfigService(self.settings.database_url)
await svc.initialize()
snapshot = await svc.list()
# svc goes out of scope; pool never closed
```

**Fix:** Add a `finally` block to close the ephemeral ConfigService pool after loading the snapshot:

```python
svc = ConfigService(self.settings.database_url)
try:
    await svc.initialize()
    snapshot = await svc.list()
finally:
    await svc.close()  # requires ConfigService.close() from CR-03 fix
```

---

### WR-04: Token timing error in `verify_auth` -- malformed `Authorization` header emits wrong metric label

**File:** `services/config_service_agent.py:115-117`
**Issue:** When the `Authorization` header is present but not in `Bearer <token>` format (e.g. `Basic xyz`), the code emits `CONFIG_AUTH_FAILED_TOTAL.add(1, {"reason": "missing_header"})` at line 116 — but the reason should be `"invalid_format"` or similar, not `"missing_header"`. The header is present; it is just malformed. This makes the metric misleading for operators investigating auth failures.

**Fix:**
```python
if len(parts) != 2 or parts[0].lower() != "bearer":
    CONFIG_AUTH_FAILED_TOTAL.add(1, {"reason": "invalid_format"})
    raise HTTPException(status_code=401, detail="Authorization header must be Bearer <token>")
```

---

### WR-05: `SelfHealingEngine.execute_remediation` does not record a ledger entry when `alert_already_processed` returns True

**File:** `src/self_healing/engine.py:130-138`
**Issue:** When `alert_already_processed` returns True (idempotent skip), the engine returns `RemediationResult(status="no_action", error="Already processed (durable)")` without recording a ledger row. This is intentional for idempotency, but it means there is no audit trail for repeated Alertmanager deliveries of the same alert. If Alertmanager fires the same alert multiple times (common in production), only the first delivery is visible in the ledger. This makes it impossible to correlate Alertmanager logs with the ledger, and to detect runaway alert storms.

**Fix:** Either log a structured warning with the alert_id + "idempotent_skip" reason, or record a ledger row with `outcome="idempotent_skip"` so operators can see repeat deliveries. At minimum, emit a metric:

```python
if await self._ledger.alert_already_processed(alert.alert_id):
    logger.info("self_healing.idempotent_skip", alert_id=alert.alert_id)
    # optional: WEBHOOK_RECEIVED_TOTAL.add(1, {..., "status": "idempotent_skip"})
    return RemediationResult(...)
```

---

### WR-06: `ConfigSchemaEntry.created_at` mutable default uses `datetime.now(UTC)` at class definition time

**File:** `src/config/config_schema.py:28`
**Issue:** `created_at: datetime = datetime.now(UTC)` is evaluated once when the class is defined (module import time), not when an instance is created. All `ConfigSchemaEntry` instances that do not explicitly pass `created_at` will share the same timestamp — the time the module was first imported. For a Pydantic v2 model, the correct pattern is `Field(default_factory=lambda: datetime.now(UTC))`.

```python
# current — WRONG (evaluated at class definition)
created_at: datetime = datetime.now(UTC)
```

**Fix:**
```python
from pydantic import Field
created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
```

---

### WR-07: `RemediationLedger.attempts_in_last_hour` counts ALL outcomes, not just attempts

**File:** `src/self_healing/ledger.py:107-115`
**Issue:** The rate-limit query counts all ledger rows matching `action=$1 AND timestamp >= cutoff`, regardless of `outcome`. This means `no_action` entries (e.g. pre-value within threshold, or idempotent skips if they were recorded) would count against the hourly rate limit. More importantly, `execute_remediation` records a ledger entry with `outcome="failed"` or `outcome="partial"` on exception — those failed attempts correctly count toward the rate limit. But any callers that happen to produce `outcome="no_action"` records would also count. The intent is clearly to rate-limit actual action executions, not measurements. At present `no_action` records are NOT written to the ledger (only actual action attempts are recorded), so this is not a current bug — but it is a latent correctness issue if the write path is ever widened.

**Fix:** Add a WHERE clause to exclude `no_action` outcomes for precision, and document the intent:
```python
"SELECT COUNT(*) AS n FROM remediation_ledger "
"WHERE action=$1 AND timestamp >= $2 AND outcome != 'no_action'"
```

---

### WR-08: `_apply_shadow_mode_config` on AI agents calls `self.get_config()` but agents may not be `ConfigConsumerMixin` subclasses

**File:** `src/intelligence/ai/alpha/correlation_agent.py:84`, `counterfactual_agent.py:58`, `regime_coherence_agent.py:84`, `ml_scorer_agent.py:104`
**Issue:** All four alpha agents call `self.get_config(...)` in `_apply_shadow_mode_config()`. `get_config` is defined on `ConfigConsumerMixin` (mixed into `BaseAgent`). These agents extend `BaseMultiplierAgent`, not `BaseAgent` — whether they inherit `get_config` depends on `BaseMultiplierAgent`'s inheritance chain, which is not in scope. If `BaseMultiplierAgent` does not inherit `ConfigConsumerMixin`, the call to `self.get_config()` will raise `AttributeError` at the first hot-reload, silently leaving `shadow_only=True` (fail-closed, so no data loss, but the config system is broken). The `AlphaSwarmComputeAgent._setup` manually copies keys into `agent._config_cache` before calling `_apply_shadow_mode_config()`, which works only if agents also have a `_config_cache` dict attribute.

**Fix:** Verify that `BaseMultiplierAgent` provides `_config_cache` and `get_config`. If not, these agents should fall back to checking `getattr(self, '_config_cache', {}).get(...)` directly, or `BaseMultiplierAgent` should mixin `ConfigConsumerMixin`.

---

## Info

### IN-01: `config_service_agent.py` uses bare `assert` for runtime guards in production endpoints

**File:** `services/config_service_agent.py:183, 201, 209, 217`
**Issue:** Production endpoint handlers use `assert config_service is not None, "ConfigService not initialized"`. In Python, `assert` statements are removed when the interpreter runs with `-O` (optimized mode). While the project likely does not use `-O`, bare asserts in FastAPI request handlers should be replaced with proper HTTPExceptions to produce correct HTTP status codes rather than 500 InternalServerError.

**Fix:** Replace asserts with guard clauses:
```python
if config_service is None:
    raise HTTPException(status_code=503, detail="ConfigService not initialized")
```

---

### IN-02: `disable_strategy` mutates a module-level dict — not thread/process safe, resets on restart

**File:** `src/self_healing/strategies.py:76-80`
**Issue:** `disable_strategy` modifies `REMEDIATION_STRATEGIES[strategy_key].enabled = False` in-place on the module-level dict. This state is lost on process restart. The comment says "Called by the engine when success rate < 80%" — but after a restart, the disabled strategy will be re-enabled (default `enabled=False` for most, `enabled=True` for `db_pool_exhausted`). For `db_pool_exhausted` specifically, if it is disabled due to 80%+ failure rate and then the process restarts, it becomes re-enabled. This is a correctness gap for the auto-disable feedback loop.

**Fix:** Persist the disabled state to `config_state` under an `ai.strategy.<key>.enabled` key so it survives restarts. The `ConfigService.set()` path already handles this transactionally.

---

### IN-03: `config_history` PRIMARY KEY on `(timestamp, config_key, version)` can conflict if two writes arrive within the same microsecond

**File:** `production/migrations/109_config_foundation.sql:47`
**Issue:** The primary key `PRIMARY KEY (timestamp, config_key, version)` uses `NOW()` for the timestamp. If two concurrent writes for the same `config_key` complete within the same microsecond (possible under load), the second INSERT will fail with a PK conflict. In practice, `SELECT ... FOR UPDATE` in the transaction serializes writes for the same key, so same-key same-microsecond conflicts are unlikely. However, different-key writes could theoretically produce the same `(timestamp, config_key, version)` tuple for different keys, which is not a conflict due to the `config_key` component. The real risk is same-key fast successive writes. Since `new_version` is incremented from the current state row, two concurrent writers would need to read the same version and commit within the same microsecond — the `FOR UPDATE` lock prevents this.

**Fix:** No code change required given the `FOR UPDATE` lock. However, consider adding a `gen_random_uuid()` as a tiebreaker column, or switching to `BIGSERIAL` for the hypertable PK, to eliminate the theoretical collision risk entirely. Document the `FOR UPDATE` dependency explicitly in the migration comment.

---

### IN-04: Outbox `status='pending'` index uses partial index but `status` can take undocumented values

**File:** `production/migrations/109_config_foundation.sql:79-81`
**Issue:** `CREATE INDEX IF NOT EXISTS idx_outbox_pending ON config_outbox (next_attempt_at) WHERE status = 'pending'` — the `status` column is `TEXT` with no CHECK constraint, so values outside `'pending'`, `'publishing'`, `'published'` are silently accepted. The dispatcher sets `'publishing'` and `'published'` but there is no schema-level enforcement. A bug that writes an unexpected status (e.g. `'error'`) would create rows that never get processed and never appear in the partial index, silently accumulating.

**Fix:** Add a CHECK constraint:
```sql
ALTER TABLE config_outbox ADD CONSTRAINT chk_outbox_status
    CHECK (status IN ('pending', 'publishing', 'published', 'failed'));
```

---

_Reviewed: 2026-05-29T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
