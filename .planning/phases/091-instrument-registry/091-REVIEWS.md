---
phase: 091
reviewers: [gemini]
reviewed_at: 2026-05-19T14:00:00Z
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
