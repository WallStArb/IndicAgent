---
phase: 091
reviewers: [gemini]
reviewed_at: 2026-05-19T14:00:00Z
post_execution_review_at: 2026-05-19T20:00:00Z
plans_reviewed:
  - 091-01-PLAN.md
  - 091-02-PLAN.md
  - 091-03-PLAN.md
  - 091-04-PLAN.md
  - 091-05-PLAN.md
  - 091-06-PLAN.md
---

# Cross-AI Plan Review — Phase 091: instrument-registry

## Gemini Review

### Summary
The plan is highly structured, logical, and demonstrates a strong grasp of the project's architectural constraints (e.g., asyncpg usage, event bus dependency, and the separation of infra vs. business logic). The multi-wave approach minimizes blast radius, and the focus on idempotency throughout the database migrations and triggers is excellent. The plan effectively achieves the goal of decentralizing instrument configuration while maintaining backward compatibility and performance.

### Strengths
- **Idempotency & Safety:** The use of `ON CONFLICT`, `CREATE OR REPLACE`, and careful handling of collision rows (`USD` cleanup) shows a mature approach to schema and data management.
- **Decoupling:** Correctly identifies that consumers must be updated *before* the removal of `settings.contracts` (Plan 091-03 before 091-04).
- **Performance:** Utilizing `LISTEN/NOTIFY` for near-instant pipeline updates instead of polling is optimal.
- **Testing Coverage:** The inclusion of unit tests for the pipeline listener and API CRUD, alongside mocking strategies for existing tests, ensures high confidence in the refactor.

### Concerns
- **Plan 091-02 (Listener Reliability):** (MEDIUM) The listener uses a separate raw `asyncpg` connection with backoff. If the DB goes down and comes back up, ensure the `CacheManager` doesn't just re-schedule tasks indefinitely. Verify that `_reload_instruments_cache` handles partial failures gracefully (e.g., if a DB query fails during reload, existing cache state should remain until the next success).
- **Plan 091-06 (API CRUD Consistency):** (LOW) The plan mentions `PUT` performs a "dynamic JSONB merge". Ensure the logic for this merge doesn't accidentally overwrite nested keys or mangle types required by the pipeline (e.g., `tick_size` as float vs string).
- **Circular Dependencies:** (LOW) The plan explicitly mentions "import `invalidate_active_contracts_cache` lazily". While necessary, this is a code smell. Consider if `CacheManager` and `get_active_contracts` should live in a shared `src/core/instruments.py` to avoid this entirely.

### Suggestions
- **Pipeline Resilience:** In Plan 091-02, add a `try-except` block inside `_reload_instruments_cache`. If it fails, log an `ERROR` event and keep the old cache. Avoid entering a crash loop if the DB is intermittently unavailable.
- **Validation:** In Plan 091-06, enforce the schema of `contract_details` using a Pydantic model (e.g., `ContractDetails`) rather than just accepting a raw `dict` or JSONB. This ensures the API acts as a gatekeeper for data integrity.
- **Migration Script:** Add a check in Plan 091-04 to verify the count of instruments before and after migration. If migration results in zero instruments, the script should fail loudly, preventing the pipeline from starting with an empty configuration.

### Risk Assessment
**Risk Level: LOW**
The plan is well-phased and addresses the critical bugs found during research (FX collision, missing triggers). The reliance on `asyncpg` matches project standards, and the back-compatibility strategy (maintaining `get_active_contracts` behavior) mitigates risk to existing services. The primary risk is downtime or cache inconsistency during the registry "flip", which is addressed by the sequential wave approach.

---

## Consensus Summary

*Single reviewer — no divergence analysis applicable.*

### Agreed Strengths
- Idempotency via `ON CONFLICT` + `CREATE OR REPLACE` throughout
- Wave sequencing: consumers updated before `settings.contracts` removed
- LISTEN/NOTIFY preferred over polling — correct primitive for the problem
- Comprehensive test coverage including listener unit tests and API CRUD tests

### Agreed Concerns (priority order)
1. **MEDIUM — Listener cache-on-failure:** `_reload_instruments_cache` should preserve old cache on failure, not clear it. Plan 091-02 task action should explicitly state: on exception, keep `self._instruments_cache` unchanged and log at ERROR.
2. **LOW — JSONB PUT merge safety:** Dynamic JSONB merge in PUT endpoint could corrupt numeric types if caller passes strings. Plan 091-06 should validate all numeric fields (tick_size, point_value) are the correct Python types before the merge.
3. **LOW — Lazy import as code smell:** The lazy import of `invalidate_active_contracts_cache` inside `_reload_instruments_cache` is a workaround for circular import. Acceptable for now but worth noting as technical debt.

### Divergent Views
N/A — single reviewer.

### Actionable Fixes Before Execution
These are low-risk, targeted amendments to incorporate before running `/gsd-execute-phase 091`:

1. **091-02 Task 1** — In `_reload_instruments_cache`, add explicit "preserve old cache on failure" behavior: catch exception, log at ERROR (`cache_manager.instruments_reload_failed`), and do NOT overwrite `self._instruments_cache`. The plan action text says "On exception: log at WARNING" — upgrade to ERROR and confirm the cache is not cleared.

2. **091-06 Task 1** — In `InstrumentUpdate(BaseModel)`, add type validation for `tick_size: float | None` and `point_value: float | None` so FastAPI's Pydantic layer rejects strings. The plan already uses `Literal` for `asset_class` — extend that strictness to numerics.

3. **091-04 Task 1** — In `migrate_instruments.py`, after the upsert loop, assert `SELECT COUNT(*) FROM instruments WHERE is_active=true` > 0. If zero, `sys.exit(1)` with a clear error message. Prevents a silent empty-DB scenario post-migration.

---

## Post-Execution Review — Gemini (2026-05-19)

*Reviewed after phase 091 was fully executed. This review reflects both the plan quality and any issues surfaced by the implementation.*

# Cross-AI Plan Review: 091-instrument-registry

## Summary
Phase 091 successfully migrates the instrument configuration from hardcoded defaults in `settings.py` to a database-driven registry. This is a critical architectural improvement that enables runtime instrument management via an API, removing the need for deployments to adjust the tradeable universe. The phased execution plan (091-01 through 091-06) is logically sound, properly handling database state invariants (trigger installation, symbol collision fix) before shifting the pipeline and API consumption patterns.

## Strengths
*   **Logical Dependency Chain:** Correctly identifying the need to fix the DB PK collision (Plan 01) before running the migration (Plan 04) prevents silent data loss.
*   **Idempotency:** The plan places high emphasis on idempotent SQL and Python migration scripts (`CREATE OR REPLACE`, `ON CONFLICT DO UPDATE`), which is essential for safely modifying a live production database.
*   **Event-Driven Evolution:** Replacing polling with asyncpg `LISTEN/NOTIFY` (Plan 02) is the correct architectural pattern for sub-second configuration propagation in a microservice environment.
*   **Gradual Decomposition:** Shrinking `Settings` class from ~1100 to ~400 lines by removing static data (Plan 04) while preserving infra-only configuration follows clean separation of concerns.

## Concerns
*   **Fallback Complexity (Medium):** In Plan 091-03, Task 1, removing `settings.contracts` while falling back to an empty list `[]` on cold-start DB failure could lead to an intelligence pipeline that silently starts with zero instruments.
    *   *Severity:* MEDIUM.
    *   *Mitigation:* The existing assertion in the agent's startup sequence likely catches this, but an explicit check/warning here is prudent.
*   **Test Mocking Overload (Medium):** Plans 091-03/05 rely heavily on mocking `get_active_contracts()`. While acceptable for unit tests, this increases the risk of "mock drift" where tests pass despite the real DB-query logic in `settings.py` being broken.
    *   *Severity:* MEDIUM.
*   **Trigger Logic (Low):** The use of `COALESCE(NEW.symbol, OLD.symbol)` in the notification trigger is correct, but ensure that the `DELETE` trigger does not cause issues if a symbol is hard-deleted (though only soft-deletes are planned).

## Suggestions
*   **Pipeline Startup Validation:** Add a startup assertion in `IntelligencePipelineComputeAgent` that verifies the number of active contracts is > 0. If 0, the agent should fail loudly (log CRITICAL/raise exception) rather than running in an "empty" state.
*   **Migration Verification:** Add a mandatory unit test to the `migrate_instruments.py` suite (or a separate check) that validates row counts against expected counts for all asset classes immediately after running the migration.
*   **Refinement of `get_active_contracts` Fallback:** Rather than silently returning `[]`, consider logging the error state and, if the cache is truly cold, failing the service startup. An empty registry is usually a sign of a misconfiguration (DB unreachable) that should be fixed, not masked.

## Risk Assessment
**Overall Risk: LOW**

The design is sound, and the implementation steps are surgical. The primary risk (FX symbol collision) is identified and prioritized in the first wave. The transition from hardcoded to registry-backed configuration is handled with a backward-compatible shim (the TTL-cached `get_active_contracts` call), which minimizes disruption to the existing pipeline. Proceed with execution.
