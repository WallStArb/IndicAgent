# Phase 091: Instrument Registry - Context

**Gathered:** 2026-05-18
**Status:** Ready for planning

<domain>
## Phase Boundary

Flip the source of truth for instrument configuration from hardcoded Python in settings.py to the `instruments` DB table. settings.py becomes pure infra config (kafka, db, IBKR connection params only). The `instruments.contract_details` JSONB column holds all per-instrument business config. An API CRUD layer lets operators add/remove/toggle symbols without code deploy. The pipeline picks up changes within 1 second via asyncpg LISTEN/NOTIFY — no polling, no restart.

Non-futures (equities, FX, crypto) are the primary migration target — futures already flow from `contract_metadata` DB. Zero behavior change to signal generation or the I1-I7 pipeline.

</domain>

<decisions>
## Implementation Decisions

### Source of Truth
- **D-01:** `instruments.contract_details` JSONB holds all instrument config: `point_value`, `tick_size`, `session_id`, `exchange`, `sector`, `asset_class`, `provider_meta`. No instrument dicts in settings.py. `Instrument` dataclass constructed from DB row + `contract_details` deserialization.
- **D-02:** settings.py retains only: `kafka_bootstrap_servers`, `database_url`, `ibkr_host`, `ibkr_port`, `ibkr_client_id`, `ollama_*`, `env_prefix`, `log_level`, and other pure infra fields. The `contracts: list[Instrument]` field and all `Instrument(symbol=..., point_value=..., ...)` defaults are removed.
- **D-03:** `get_active_contracts()` continues to merge futures (from `contract_metadata` WHERE `is_front_month=true`) with non-futures (from `instruments` WHERE `is_active=true AND asset_class != 'futures'`). The function signature and return type are unchanged — all callers unaffected.

### Hot-Reload via DB NOTIFY
- **D-04:** `CacheManager` (Phase 088) gains a `start_instruments_listener(conn: asyncpg.Connection)` method. A background `asyncio.Task` runs `LISTEN instruments` on a dedicated asyncpg connection. On any `NOTIFY instruments` payload, `CacheManager` atomically replaces `_instruments_cache` and calls `invalidate_active_contracts_cache()`.
- **D-05:** The `instruments` table gains a trigger: `CREATE OR REPLACE FUNCTION notify_instrument_change() RETURNS TRIGGER AS $$ BEGIN PERFORM pg_notify('instruments', NEW.symbol); RETURN NEW; END; $$ LANGUAGE plpgsql;` — fired on INSERT, UPDATE, DELETE. Pipeline reacts within 1 second; no polling required.
- **D-06:** `invalidate_active_contracts_cache()` in settings.py remains for backward compat but is now also called by the LISTEN handler. The 60s TTL fallback stays as a safety net.

### Bootstrap + Migration
- **D-07:** Empty-DB bootstrap: `IBKR_CONTRACTS_JSON` env var seeds `instruments` table at API startup (`src/api/main.py` already calls `upsert_instruments()` at line 86). First run seeds from env var; subsequent runs read DB only.
- **D-08:** One-time migration script `production/scripts/migrate_instruments.py`: reads current `settings.py` instrument defaults, upserts into `instruments` table with full `contract_details` JSONB. Idempotent — safe to re-run.

### API CRUD
- **D-09:** New router `src/api/routes/instruments.py` (file exists, extend it): `POST /api/instruments` (add new), `PUT /api/instruments/{symbol}` (update config or toggle active), `DELETE /api/instruments/{symbol}` (soft-delete: set `is_active=false`). All writes trigger `pg_notify('instruments', symbol)` to propagate changes immediately.
- **D-10:** No auth added to instrument API — internal-only service, consistent with existing API. Note for v2.7: if external access is added, auth should be added then.

### Settings Decomposition
- **D-11:** Settings class lines reduced from ~1136 to ~400. `Instrument` class and all default contract definitions move out. The `contracts_json` / `ibkr_contracts_json` env vars are removed once migration is complete (kept for one phase as bootstrap fallback).
- **D-12:** All tests that construct `Settings(contracts=[...])` are updated to mock `get_active_contracts()` instead — simpler and more realistic.

### Claude's Discretion
- Exact JSONB schema for `contract_details` (field names/types — use existing `Instrument` dataclass field names)
- Whether migration script is a one-time CLI or a proper alembic migration
- Exact asyncpg LISTEN loop error handling (reconnect on connection loss)

</decisions>

<canonical_refs>
## Canonical References

- `src/config/settings.py` — lines 228-430: all `Instrument` defaults being migrated; lines 934-1103: `get_active_contracts()`, `_active_contracts_cache`, `invalidate_active_contracts_cache()`
- `src/api/routes/instruments.py` — existing instrument CRUD; extend rather than replace
- `src/api/main.py:86` — startup seeding call `upsert_instruments()`
- `src/core/database_manager.py:122` — `upsert_instruments()` implementation
- `src/intelligence/pipeline/cache_manager.py` (post-088) — add `start_instruments_listener()` here
- `.planning/REQUIREMENTS.md` §INST-01–INST-05

</canonical_refs>

<code_context>
## Existing Code Insights

### Already Working
- `get_active_contracts()` already reads futures from `contract_metadata` (psycopg2 sync query). Non-futures from `s.contracts` fallback. The flip: non-futures from `instruments WHERE is_active=true`.
- `instruments` table has 58 rows with `symbol`, `base`, `is_active`, `contract_details` JSONB — structure already exists.
- `upsert_instruments()` in `database_manager.py` already writes to `instruments` table from Instrument list.
- asyncpg supports LISTEN/NOTIFY natively; `CacheManager` already has a pattern for background asyncio.Task (refresh loops).

### Integration Points
- `CacheManager.start_refresh_loops()` returns background tasks to orchestrator — `start_instruments_listener()` follows same pattern, returns one more task handle.
- `get_active_contracts()` is module-level (not async) — LISTEN handler calls `invalidate_active_contracts_cache()` which is sync; safe from async context.
- `settings.py` module-level `_active_contracts_cache` global: THREAD-01 fix (Phase 091) adds RLock; this phase removes the psycopg2 sync call inside `get_active_contracts()` (replaces with CacheManager async read).

</code_context>

<specifics>
- "DB owns config" — Renaissance separation: infra config (kafka, DB URLs) vs business config (tradeable instruments) belong in different layers. DB is the right home for business config because it's mutable, auditable, and accessible via API without code changes.
- "Event-driven, not polling" — LISTEN/NOTIFY is the natural database event primitive. Adding a new equity for v2.7 should propagate to a running pipeline in under 1 second, not up to 60 seconds. This is the correct model.
- "Automation over manual tasks" — the DB trigger fires automatically on any INSERT/UPDATE/DELETE; no operator needs to remember to call an invalidation endpoint.
</specifics>

<deferred>
- Auth on instrument API (add at v2.7 if external access is required)
- Hot-reload of IBKR connection params (not instruments; different problem)
- Instrument schema versioning / audit log (track who changed what instrument config)
- Proper migration framework (Alembic or Flyway) — per-service `ensure_schema()` startup migrations scatter schema ownership across agents. A single migration registry is the correct long-term design. Acceptable now; revisit when service count grows.
</deferred>

---
*Phase: 091-instrument-registry*
*Context gathered: 2026-05-18*
