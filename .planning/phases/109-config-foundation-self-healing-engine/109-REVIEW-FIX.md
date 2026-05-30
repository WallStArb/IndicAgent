---
phase: 109-config-foundation-self-healing-engine
fixed_at: 2026-05-29T18:54:30Z
review_path: .planning/phases/109-config-foundation-self-healing-engine/109-REVIEW.md
iteration: 1
findings_in_scope: 12
fixed: 11
skipped: 1
status: partial
---

# Phase 109: Code Review Fix Report

**Fixed at:** 2026-05-29T18:54:30Z
**Source review:** `.planning/phases/109-config-foundation-self-healing-engine/109-REVIEW.md`
**Iteration:** 1

**Summary:**
- Findings in scope: 12 (CR-01 through CR-04, WR-01 through WR-08)
- Fixed: 11
- Skipped: 1 (WR-08 - inheritance already correct, no fix needed)

## Fixed Issues

### CR-01: Migration SQL inserts every config_schema and config_state row twice

**Files modified:** `production/migrations/109_config_foundation.sql`
**Commit:** ee8a20f5
**Applied fix:** Removed the duplicate "Task 2 (Plan 05)" seed block (lines 282-316) that re-inserted all 15 regime/swarm/roll/cross_asset/macro rows. The first canonical seed block (lines 89-216) with `ON CONFLICT DO NOTHING` is authoritative. Task 3 and Task 4 blocks were preserved intact.

---

### CR-02: `_delete_old_logs` is a blocking subprocess call inside an async method

**Files modified:** `src/self_healing/engine.py`
**Commit:** 1c2d75d6
**Applied fix:** Replaced `subprocess.run(...)` with `asyncio.create_subprocess_exec(...)` + `await proc.communicate()`. Raises `RuntimeError` on non-zero return code. Also removed the unused `import subprocess` from the module imports.

---

### CR-03: `ConfigService` pool is never closed — connection leak in config HTTP API

**Files modified:** `src/config/config_service.py`, `services/config_service_agent.py`
**Commit:** 4b056987
**Applied fix:** Added `ConfigService.close()` method that calls `await self._db_pool.close()` and sets `_db_pool = None`. Updated `lifespan` in `config_service_agent.py` to call `await config_service.close()` in the shutdown path (replacing the "pool cleanup handled by garbage collection" comment).

---

### CR-04: `self_healing_agent.py` uses deprecated `@app.on_event` lifecycle hooks

**Files modified:** `services/self_healing_agent.py`
**Commit:** b1578ba3
**Applied fix:** Converted from `@app.on_event("startup")` / `@app.on_event("shutdown")` to an `@asynccontextmanager` `lifespan` function passed to `FastAPI(lifespan=lifespan)`. Pattern is now consistent with `config_service_agent.py`.

---

### WR-01: `outbox_dispatcher.py` uses inline `.isoformat().replace()` instead of `format_iso_ts()`

**Files modified:** `src/config/outbox_dispatcher.py`
**Commit:** 491a4763
**Applied fix:** Added `from src.core.service_utils import format_iso_ts` import and replaced `datetime.now(UTC).isoformat().replace("+00:00", "Z")` with `format_iso_ts(datetime.now(UTC))` at line 186.

---

### WR-02: `SelfHealingEngine.__init__` constructs `RemediationLedger` with `managed_pool.pool` before pool is initialized

**Files modified:** `src/self_healing/engine.py`
**Commit:** 7cf4600f
**Applied fix:** Changed `self._ledger = RemediationLedger(managed_pool.pool)` in `__init__` to `self._ledger: RemediationLedger | None = None` (with comment) and moved construction to `initialize()` as `self._ledger = RemediationLedger(self._managed_pool.pool)`. The `_flush_connection_pool` re-bind is unaffected.

---

### WR-03: `ConfigConsumerMixin._pre_setup_config_load` creates a new `ConfigService` (and pool) on every call — no sharing with service's own pool

**Files modified:** `src/config/config_consumer.py`
**Commit:** c5c8de42
**Applied fix:** Moved `svc = ConfigService(...)` construction outside the `try` block and added a `finally: await svc.close()` clause to ensure the ephemeral pool is always closed after loading the snapshot, even if an exception occurs. Requires `ConfigService.close()` from CR-03 fix.

---

### WR-04: Token timing error in `verify_auth` -- malformed `Authorization` header emits wrong metric label

**Files modified:** `services/config_service_agent.py`
**Commit:** f2d6af33
**Applied fix:** Changed metric label from `{"reason": "missing_header"}` to `{"reason": "invalid_format"}` for the case where the Authorization header is present but not in `Bearer <token>` format.

---

### WR-05: `SelfHealingEngine.execute_remediation` does not record a ledger entry when `alert_already_processed` returns True

**Files modified:** `src/self_healing/engine.py`
**Commit:** 6b308315
**Applied fix:** Added `logger.info("self_healing.idempotent_skip", alert_id=alert.alert_id)` before the early return in `handle_webhook` when `alert_already_processed` returns True. This creates a structured audit trail for repeated Alertmanager deliveries.

---

### WR-06: `ConfigSchemaEntry.created_at` mutable default uses `datetime.now(UTC)` at class definition time

**Files modified:** `src/config/config_schema.py`
**Commit:** 11131c54
**Applied fix:** Added `Field` to the `pydantic` import and changed `created_at: datetime = datetime.now(UTC)` to `created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))` so the timestamp is evaluated at instance creation time, not module import time.

---

### WR-07: `RemediationLedger.attempts_in_last_hour` counts ALL outcomes, not just attempts

**Files modified:** `src/self_healing/ledger.py`
**Commit:** ab387f6b
**Applied fix:** Added `AND outcome != 'no_action'` to the SQL WHERE clause in `attempts_in_last_hour`. Updated docstring to document the intent. Prevents any future `no_action` ledger writes from incorrectly counting against the hourly rate limit.

---

## Skipped Issues

### WR-08: `_apply_shadow_mode_config` on AI agents calls `self.get_config()` but agents may not be `ConfigConsumerMixin` subclasses

**File:** `src/intelligence/ai/alpha/correlation_agent.py:84`
**Reason:** Inheritance verified - no fix needed. Checked the full inheritance chain: `CorrelationAgent` (and the other three agents) extend `BaseMultiplierAgent` -> `BaseAIAgent` -> `BaseAgent`, and `BaseAgent` directly imports and inherits `ConfigConsumerMixin` (confirmed at `src/core/agent/base.py:37-38`). All four agents have both `get_config()` and `_config_cache` available via this chain. The reviewer's concern was a false positive.
**Original issue:** Agents call `self.get_config()` but may not inherit `ConfigConsumerMixin` if `BaseMultiplierAgent` does not include it.

---

_Fixed: 2026-05-29T18:54:30Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
