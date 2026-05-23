# Phase 091: Instrument Registry — Research

**Researched:** 2026-05-19
**Domain:** PostgreSQL LISTEN/NOTIFY, asyncpg, settings decomposition, API CRUD, migration scripting
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** `instruments.contract_details` JSONB holds all instrument config: `point_value`, `tick_size`, `session_id`, `exchange`, `sector`, `asset_class`, `provider_meta`. No instrument dicts in settings.py. `Instrument` dataclass constructed from DB row + `contract_details` deserialization.
- **D-02:** settings.py retains only: `kafka_bootstrap_servers`, `database_url`, `ibkr_host`, `ibkr_port`, `ibkr_client_id`, `ollama_*`, `env_prefix`, `log_level`, and other pure infra fields. The `contracts: list[Instrument]` field and all `Instrument(symbol=..., point_value=..., ...)` defaults are removed.
- **D-03:** `get_active_contracts()` continues to merge futures (from `contract_metadata` WHERE `is_front_month=true`) with non-futures (from `instruments` WHERE `is_active=true AND asset_class != 'futures'`). The function signature and return type are unchanged — all callers unaffected.
- **D-04:** `CacheManager` gains a `start_instruments_listener(conn: asyncpg.Connection)` method. A background `asyncio.Task` runs `LISTEN instruments` on a dedicated asyncpg connection. On any `NOTIFY instruments` payload, `CacheManager` atomically replaces `_instruments_cache` and calls `invalidate_active_contracts_cache()`.
- **D-05:** The `instruments` table gains a trigger: `CREATE OR REPLACE FUNCTION notify_instrument_change() RETURNS TRIGGER AS $$ BEGIN PERFORM pg_notify('instruments', NEW.symbol); RETURN NEW; END; $$ LANGUAGE plpgsql;` — fired on INSERT, UPDATE, DELETE.
- **D-06:** `invalidate_active_contracts_cache()` in settings.py remains for backward compat but is now also called by the LISTEN handler. The 60s TTL fallback stays as a safety net.
- **D-07:** Empty-DB bootstrap: `IBKR_CONTRACTS_JSON` env var seeds `instruments` table at API startup (`src/api/main.py` already calls `upsert_instruments()` at line 86). First run seeds from env var; subsequent runs read DB only.
- **D-08:** One-time migration script `production/scripts/migrate_instruments.py`: reads current `settings.py` instrument defaults, upserts into `instruments` table with full `contract_details` JSONB. Idempotent — safe to re-run.
- **D-09:** New router `src/api/routes/instruments.py` (file exists, extend it): `POST /api/instruments` (add new), `PUT /api/instruments/{symbol}` (update config or toggle active), `DELETE /api/instruments/{symbol}` (soft-delete: set `is_active=false`). All writes trigger `pg_notify('instruments', symbol)` to propagate changes immediately.
- **D-10:** No auth added to instrument API — internal-only service.
- **D-11:** Settings class lines reduced from ~1136 to ~400. `Instrument` class and all default contract definitions move out. The `contracts_json` / `ibkr_contracts_json` env vars are removed once migration is complete.
- **D-12:** All tests that construct `Settings(contracts=[...])` are updated to mock `get_active_contracts()` instead.

### Claude's Discretion
- Exact JSONB schema for `contract_details` (field names/types — use existing `Instrument` dataclass field names)
- Whether migration script is a one-time CLI or a proper alembic migration
- Exact asyncpg LISTEN loop error handling (reconnect on connection loss)

### Deferred Ideas (OUT OF SCOPE)
- Auth on instrument API (add at v2.7 if external access is required)
- Hot-reload of IBKR connection params
- Instrument schema versioning / audit log
- Proper migration framework (Alembic or Flyway)
</user_constraints>

---

## Summary

The `instruments` table already has 58 rows with complete `contract_details` JSONB covering all active symbols — equities (38), futures (17 base templates), FX (3 of the 4 settings.py entries). The DB table schema is missing `base` and `expiry` columns from create_schema.sql but both exist in production (they were added by later migrations). The `upsert_instruments()` function has a latent bug that causes FX pairs with the same `base` to collide: USDJPY and USDCHF both have `base="USD"`, so USDJPY is missing from the DB. This must be fixed in the migration.

The asyncpg LISTEN/NOTIFY path is net-new for this codebase — no existing LISTEN usage exists in src/. The `CacheManager` pattern is the right host: it already runs 6 background `asyncio.Task` loops via `start_refresh_loops()`. The listener becomes a 7th task following the same lifecycle. The dedicated connection for LISTEN must be acquired from the pool via `asyncpg.create_pool().acquire()` and held for the lifetime of the listener, not from `DatabaseManager.get_connection()` (which uses a context manager and releases on exit).

`get_active_contracts()` currently uses `psycopg2.connect()` (synchronous, GIL-holding) inside a sync function. After this phase, non-futures come from `instruments WHERE is_active=true AND asset_class != 'futures'` queried via asyncpg in the LISTEN handler; `get_active_contracts()` reads the cache set by the handler. The psycopg2 import disappears.

**Primary recommendation:** Fix `upsert_instruments()` to use `c.symbol` (not `c.base`) as the DB primary key before doing anything else. The migration script and all subsequent logic depends on correct DB state.

---

## 1. Current State Analysis

### What Exists in the DB Right Now

**instruments table schema (confirmed live):**
```
symbol           TEXT PRIMARY KEY
base             TEXT NOT NULL
contract_details JSONB
is_active        BOOLEAN DEFAULT TRUE
created_at       TIMESTAMPTZ DEFAULT NOW()
updated_at       TIMESTAMPTZ DEFAULT NOW()
expiry           DATE
```
Indexes: `instruments_pkey` on `symbol`, `idx_instruments_base` on `base`.

**Row counts by asset_class:**
| asset_class | count |
|-------------|-------|
| equity      | 38    |
| futures     | 17    |
| fx          | 3     |
| **total**   | **58** |

**All 58 symbols confirmed present, is_active=true, contract_details fully populated** (name, sector, session_id all non-null for all 58 rows).

### The FX Symbol Collision Bug (CRITICAL)

`upsert_instruments()` (database_manager.py line 136):
```python
params = [(c.base, c.base, c.model_dump(), True) for c in contracts]
```
Uses `c.base` as the DB `symbol` primary key. USDJPY and USDCHF both have `base="USD"`. The API startup loop upserts them in order — USDCHF wins, USDJPY never gets a row. Current DB: symbol=`USD` with `contract_details.symbol=USDCHF`. USDJPY is simply absent.

**Fix required:** Change params tuple to `(c.symbol, c.base, c.model_dump(), True)`.

### The FX PK Mismatch Problem

Even after fixing upsert, the DB stores FX by `base` (EUR, GBP, USD) not by full symbol (EURUSD, GBPUSD). The `contract_details.symbol` field contains the full symbol. The DB primary key is `base` for FX but `symbol` for everything else (equities use symbol=base). This asymmetry is carried forward into `get_active_contracts()` which calls `_build_instrument_from_db_row()` and reads contract_details to reconstruct the `Instrument` object — `contract_details.symbol` holds the real symbol.

After D-03 flip, `get_active_contracts()` must read non-futures from `instruments WHERE is_active=true AND asset_class != 'futures'`. For FX, it reads `contract_details->>'symbol'` as the Instrument's symbol, not the row's `symbol` column. The `_build_instrument_from_db_row()` function must be updated or the query must use `contract_details->>'symbol'` as the symbol field.

**Decision required by planner:** Either (a) keep FX rows keyed by base (EUR, GBP, USD) in the DB and always read full symbol from contract_details, or (b) fix the migration to use full symbol as PK for FX (EURUSD, GBPUSD, USDJPY, USDCHF). Option (b) is cleaner. Migration script uses `c.symbol` as PK for all asset classes.

### What is NOT in settings.py After Removal (Migration Payload)

Settings.py currently has these Instrument defaults (lines 266-940). All are in DB already except USDJPY:

**Futures (17 base templates):**
ES, NQ, RTY, YM, CL, NG, GC, SI, HG, VIX, ZN, ZF, ZB, ZT, ZS, ZC, ZW

Notable: VIX has `provider_meta={"ibkr": {"trading_class": "VX"}}` — confirmed present in DB.

**FX (4 instruments, only 3 in DB):**
EURUSD (base=EUR), GBPUSD (base=GBP), USDJPY (base=USD) — MISSING, USDCHF (base=USD) — present.

**Equities (38 ETFs):** All 38 confirmed present in DB.

**Commented-out crypto (2 instruments — DEACTIVATED 2026-04-13):**
BTCUSD, ETHUSD — correctly absent from DB.

### Key Helper Functions That Touch settings.contracts

These functions in settings.py iterate `s.contracts` and will need updating:
- `get_active_contracts()` (lines 1058-1122) — primary target
- `get_base_symbols()` (lines 1134-1143) — iterates `s.contracts`; called nowhere in src/ except settings.py itself
- `get_contract_info()` (lines 1146-1152) — reads `s.contracts`; called nowhere in src/ outside settings.py
- `get_point_value()` (line 1155) — calls `get_contract_info()`; not called outside settings.py
- `get_tick_size()` (line 1161) — calls `get_contract_info()`; not called outside settings.py

`get_base_symbols()`, `get_contract_info()`, `get_point_value()`, `get_tick_size()` are dead code in practice — zero callers in src/ outside settings.py. They can be left as-is (they'll still work via `s.contracts` shim during the transition) or removed. D-11 says the line count drops ~700 lines.

### Direct settings.contracts Access (Outside settings.py)

Three call sites:
1. `src/api/main.py:87` — `await dependencies.db_manager.upsert_instruments(settings.contracts)`
2. `src/api/utils.py:31,35` — `resolve_contract()` iterates `settings.contracts` to map base→symbol

After D-02, `settings.contracts` disappears. These must be updated:
- `main.py:87`: Remove entirely (DB is already seeded; no re-seed needed on every API start) OR seed from DB query instead.
- `api/utils.py:resolve_contract()`: Must query `instruments` table directly or use a cached lookup.

### Trigger Status

No triggers on `instruments` table (confirmed: `SELECT ... FROM information_schema.triggers WHERE event_object_table = 'instruments'` → 0 rows). D-05 trigger does not yet exist.

### asyncpg LISTEN/NOTIFY — No Existing Usage

Zero LISTEN/NOTIFY usage in src/. This is net-new. The pattern is:
```python
# Dedicated connection (NOT from pool context manager — must hold the connection)
conn = await asyncpg.connect(database_url)
await conn.execute("LISTEN instruments")
conn.add_listener("instruments", callback)
# Keep conn alive for lifetime of listener
```

The `add_listener` callback signature is `(connection, pid, channel, payload) -> None`. It runs synchronously on the event loop thread. For CacheManager, the callback should call `asyncio.create_task(self._reload_instruments())` to avoid blocking.

### CacheManager.start_refresh_loops() Pattern

```python
def start_refresh_loops(self) -> list[asyncio.Task]:
    return [
        asyncio.create_task(self._run_refresh_loop(fn, interval)),
        ...  # 6 tasks
    ]
```

The instruments listener follows the same pattern: `start_instruments_listener()` returns one additional `asyncio.Task`. The caller in `intelligence_pipeline_agent.py` line 256 appends all tasks from `start_refresh_loops()` to `self._background_tasks`. The instruments listener task goes there too.

### psycopg2 Sync Call in get_active_contracts()

Lines 1088-1097:
```python
import psycopg2
with psycopg2.connect(s.database_url) as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT symbol, base_symbol, exchange FROM contract_metadata ...")
        rows = cur.fetchall()
```

This synchronous DB call blocks the event loop when called from async code. After D-03, non-futures come from the `_instruments_cache` populated by the LISTEN handler (async, already loaded). The futures query still needs to happen — it should use the same cache approach or be converted to asyncpg. D-03 says the function signature is unchanged (sync), so it must continue reading from a cache, not making a direct asyncio call.

**Critical design point:** `get_active_contracts()` is a module-level sync function. It cannot `await`. The LISTEN handler populates `_instruments_cache` with non-futures Instruments. `get_active_contracts()` reads that cache for non-futures (fast, no DB call). The futures query from `contract_metadata` still uses psycopg2 sync (or can also be cached by a separate mechanism). D-06 says the 60s TTL fallback stays — the existing cache for the full result remains.

---

## 2. Implementation Risks

### Risk 1: FX Symbol Collision Silently Drops USDJPY
**What goes wrong:** USDJPY and USDCHF share `base="USD"`. `upsert_instruments()` with the current bug writes USDCHF and silently drops USDJPY.
**Impact:** USDJPY never appears as an active contract. FX coverage is 3 of 4 instruments.
**Fix:** Change `params` tuple from `(c.base, c.base, ...)` to `(c.symbol, c.base, ...)`. Migration script must also add the USDJPY row explicitly.
**Test:** Verify post-migration: `SELECT symbol FROM instruments WHERE contract_details->>'asset_class' = 'fx'` returns EURUSD, GBPUSD, USDJPY, USDCHF.

### Risk 2: LISTEN Connection Drops (Reconnect Pattern)
**What goes wrong:** The dedicated asyncpg connection for LISTEN is a raw connection (not a pool connection). If the DB restarts or the connection drops, the listener task exits silently.
**Pattern required:** The listener task must be a retry loop:
```python
async def _listen_loop(self) -> None:
    while True:
        try:
            conn = await asyncpg.connect(self._settings.database_url)
            try:
                await conn.set_type_codec(...)  # JSONB codec
                await conn.execute("LISTEN instruments")
                conn.add_listener("instruments", self._on_instrument_notify)
                # Wait forever — asyncpg delivers notifications via event loop
                while not conn.is_closed():
                    await asyncio.sleep(10)  # heartbeat
            finally:
                await conn.close()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._logger.warning("instruments_listener.reconnecting", error=str(exc))
            await asyncio.sleep(5)  # backoff before reconnect
```
**Note:** `asyncio.sleep(10)` inside the loop is correct — asyncpg delivers NOTIFY callbacks on the event loop without needing to poll. The sleep just keeps the task alive and provides a heartbeat for liveness detection.

### Risk 3: get_active_contracts() Called Before instruments_cache Populated
**What goes wrong:** `intelligence_pipeline_agent.__init__` calls `get_active_contracts()` at line 114 — before `start_instruments_listener()` is ever called (which happens in `_setup()` at line 256+). The cache is cold.
**Impact:** First call uses psycopg2 path (or fails to fallback). This is the existing behavior and is unchanged by this phase. The LISTEN listener enriches the cache for subsequent calls. No regression.

### Risk 4: api/utils.py resolve_contract() After settings.contracts Removal
**What goes wrong:** `resolve_contract()` iterates `settings.contracts` to map base symbol to active contract code. After D-02 removes `contracts`, this breaks.
**Fix:** `resolve_contract()` must query `instruments` table via the API's `DatabaseManager` or use `get_active_contracts()`. Since it's called in an async route context, it can `await db.execute_query(...)` directly.

### Risk 5: api/main.py Seeding Call After settings.contracts Removal
**What goes wrong:** Line 87 calls `upsert_instruments(settings.contracts)`. After D-02, `settings.contracts` is gone.
**Fix options:**
- (A) Remove the call entirely — DB is already seeded via the migration script.
- (B) Replace with a DB-to-DB no-op (query instruments, no seed if rows exist).
- (C) Keep `IBKR_CONTRACTS_JSON` env var as the seed source (D-07 bootstrap path).
Decision: D-07 says env var seeds on first run. The correct fix is: read from env var JSON if set, otherwise skip. Remove the `settings.contracts` dependency.

### Risk 6: Tests That Assert on s.contracts or s.instruments
**Impact:** Multiple test files will fail after `contracts: list[Instrument]` field is removed.
Files affected:
- `tests/unit/test_settings.py` — 7 tests directly asserting `s.contracts`
- `tests/unit/config/test_settings_equity.py` — 15 tests asserting `s.instruments` (which aliases `s.contracts`)
- `tests/unit/test_service_contract_resolution.py` — tests psycopg2 mock of `get_active_contracts()`
- `tests/unit/providers/test_ibkr_adapter.py:277` — `settings.contracts` access
- `tests/unit/service_tests/test_feature_writer_agent.py:446` — `s.contracts = instruments` mutation
- `tests/unit/api/test_api_utils.py:42` — `mock_settings.contracts` access

### Risk 7: Trigger on DELETE Uses NEW.symbol (NULL on DELETE)
**What goes wrong:** D-05 trigger uses `NEW.symbol` in the plpgsql function. On DELETE, `NEW` is NULL — the trigger will error.
**Fix:** Use `COALESCE(NEW.symbol, OLD.symbol)` or split into separate per-operation triggers:
```sql
CREATE OR REPLACE FUNCTION notify_instrument_change() RETURNS TRIGGER AS $$
BEGIN
    PERFORM pg_notify('instruments', COALESCE(NEW.symbol, OLD.symbol));
    RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql;
```

### Risk 8: _instrument_map Stale After Hot-Reload
**What goes wrong:** `intelligence_pipeline_agent` builds `self._instrument_map` in `__init__` at line 144 from `self._contracts = get_active_contracts()`. When the LISTEN handler fires and updates the cache, `_instrument_map` is not rebuilt.
**Assessment:** Hot-reload of `_instrument_map` at the pipeline level is out of scope for this phase (D-deferred). The LISTEN handler refreshes `_instruments_cache` and invalidates the TTL cache. The pipeline picks up the new contract list on its next restart, or on the next cache TTL expiry. This is acceptable for v2.6.

### Risk 9: Schema in create_schema.sql Mismatch
The `production/schemas/create_schema.sql` instruments table (line 67) is missing `base TEXT NOT NULL` and `expiry DATE` columns that exist in production. If CI runs schema creation from scratch, it will diverge from production. The migration script must either be idempotent against both schemas, or the create_schema.sql must be updated to match production.

---

## 3. Design Decisions

### D-05 Trigger — Correct Implementation

```sql
CREATE OR REPLACE FUNCTION notify_instrument_change()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    PERFORM pg_notify('instruments', COALESCE(NEW.symbol, OLD.symbol));
    RETURN COALESCE(NEW, OLD);
END;
$$;

CREATE OR REPLACE TRIGGER trg_instruments_notify
AFTER INSERT OR UPDATE OR DELETE ON instruments
FOR EACH ROW EXECUTE FUNCTION notify_instrument_change();
```

The `AFTER` trigger fires after the row is committed and visible to other connections. `FOR EACH ROW` fires once per affected row. The trigger is idempotent (`CREATE OR REPLACE`).

### CacheManager.start_instruments_listener() Design

```python
def start_instruments_listener(self) -> asyncio.Task:
    """Create and return the instruments LISTEN background task.
    
    The caller (orchestrator) appends this to _background_tasks alongside
    the 6 refresh loop tasks. Reconnects automatically on connection loss.
    """
    return asyncio.create_task(self._run_instruments_listener())

async def _run_instruments_listener(self) -> None:
    while True:
        try:
            conn = await asyncpg.connect(self._settings.database_url)
            try:
                await conn.execute("LISTEN instruments")
                conn.add_listener("instruments", self._on_instrument_notify)
                while not conn.is_closed():
                    await asyncio.sleep(10)
            finally:
                conn.remove_listener("instruments", self._on_instrument_notify)
                await conn.close()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._logger.warning(
                "cache_manager.instruments_listener_error",
                error=str(exc)
            )
            await asyncio.sleep(5)

def _on_instrument_notify(self, conn, pid, channel, payload) -> None:
    """Called synchronously by asyncpg on NOTIFY. Schedules async reload."""
    self._logger.info("cache_manager.instrument_changed", symbol=payload)
    asyncio.get_event_loop().call_soon_threadsafe(
        lambda: asyncio.ensure_future(self._reload_instruments_cache())
    )

async def _reload_instruments_cache(self) -> None:
    """Async reload of non-futures instruments from DB + invalidate TTL."""
    try:
        rows = await self._db.execute_query(
            "SELECT symbol, base, contract_details FROM instruments "
            "WHERE is_active = true AND contract_details->>'asset_class' != 'futures'"
        )
        instruments = [_instrument_from_row(r) for r in rows]
        self._instruments_cache = instruments
        from src.config.settings import invalidate_active_contracts_cache
        invalidate_active_contracts_cache()
        self._logger.info("cache_manager.instruments_reloaded", count=len(instruments))
    except Exception as exc:
        self._logger.warning("cache_manager.instruments_reload_failed", error=str(exc))
```

Note: `asyncio.get_event_loop().call_soon_threadsafe()` is needed because `add_listener` callbacks may fire from the asyncpg internal I/O callback, which is already on the event loop thread. `asyncio.ensure_future()` is the correct idiom to schedule an async coroutine from a sync callback that's already on the event loop.

### upsert_instruments() Fix

```python
# BEFORE (buggy — uses c.base as PK, collides for FX pairs with same base):
params = [(c.base, c.base, c.model_dump(), True) for c in contracts]

# AFTER (correct — uses c.symbol as PK):
params = [(c.symbol, c.base, c.model_dump(), True) for c in contracts]
```

### get_active_contracts() After D-03

```python
def get_active_contracts(settings: Settings | None = None) -> list[Instrument]:
    # ... cache check unchanged ...
    
    s = settings or _default_settings()
    
    try:
        import psycopg2  # still needed for futures query (sync function)
        with psycopg2.connect(s.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT symbol, base_symbol, exchange "
                    "FROM contract_metadata "
                    "WHERE is_front_month = true AND asset_class = 'futures'"
                )
                rows = cur.fetchall()
        db_instruments = [_build_instrument_from_db_row(row, ...) for row in rows]
        
        # NEW: non-futures from instruments table, not s.contracts
        with psycopg2.connect(s.database_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT contract_details FROM instruments "
                    "WHERE is_active = true AND contract_details->>'asset_class' != 'futures'"
                )
                nf_rows = cur.fetchall()
        non_futures = [
            Instrument(**json.loads(r[0]) if isinstance(r[0], str) else r[0])
            for r in nf_rows
        ]
        
        result = db_instruments + non_futures
        # ... cache write unchanged ...
        return result
    
    except Exception as exc:
        # fallback: if cache has data, return it; else return empty (no s.contracts anymore)
        with _settings_lock:
            if _active_contracts_cache:
                return _active_contracts_cache
        return []
```

**Important:** The fallback can no longer be `return list(s.contracts)` since `s.contracts` is removed. The fallback becomes: return the last valid cache, or return empty list if cold start fails. Document this behavioral change in a comment.

The LISTEN handler sets `_instruments_cache` for non-futures. `get_active_contracts()` can read `self._instruments_cache` instead of making a second psycopg2 call — but since CacheManager and get_active_contracts() are in different modules with no shared reference, the cleanest approach is: the LISTEN handler calls `invalidate_active_contracts_cache()`, and `get_active_contracts()` re-queries on next TTL miss. This is the D-06 design.

### Migration Script Design

`production/scripts/migrate_instruments.py` — idempotent CLI:

```python
"""Migrate instruments from settings.py defaults to instruments DB table.

Run: python production/scripts/migrate_instruments.py
Idempotent: safe to re-run. Skips rows where contract_details is already populated.
"""

import asyncio, asyncpg
from src.config.settings import Settings
from src.core.models import Instrument, AssetClass

async def main():
    settings = Settings()
    # Build the full list of instruments from settings.py defaults
    # (before they are removed — this is the pre-removal migration)
    contracts = settings.contracts  # still works during transition
    
    conn = await asyncpg.connect(settings.database_url)
    
    for c in contracts:
        await conn.execute("""
            INSERT INTO instruments (symbol, base, contract_details, is_active, updated_at)
            VALUES ($1, $2, $3::jsonb, $4, NOW())
            ON CONFLICT (symbol) DO UPDATE
                SET contract_details = EXCLUDED.contract_details,
                    is_active = EXCLUDED.is_active,
                    updated_at = NOW()
        """, c.symbol, c.base, c.model_dump(), True)
    
    print(f"Migrated {len(contracts)} instruments")
    await conn.close()

asyncio.run(main())
```

This uses `c.symbol` as PK (the fix). Run before removing `settings.contracts`.

---

## 4. File-by-File Change Map

| File | Change | LOC Delta |
|------|--------|-----------|
| `src/config/settings.py` | Remove `contracts: list[Instrument]` field, `build_contracts()` validator, all 58+ Instrument defaults (lines 134-940). Remove `contracts_json`, `ibkr_contracts_json` fields. Keep `invalidate_active_contracts_cache()`. Update `get_active_contracts()` non-futures path (from `s.contracts` to DB query). Update fallback (no `s.contracts`). Remove `@property instruments` alias. | -700 |
| `src/core/database_manager.py` | Fix `upsert_instruments()`: change `c.base` to `c.symbol` as PK in params tuple (line 136). | -1/+1 |
| `src/intelligence/pipeline/cache_manager.py` | Add `_instruments_cache`, `start_instruments_listener()`, `_run_instruments_listener()`, `_on_instrument_notify()`, `_reload_instruments_cache()` methods. Add `asyncpg` import. | +60 |
| `services/intelligence_pipeline_agent.py` | Add `start_instruments_listener()` call after `start_refresh_loops()` loop. Wire returned task into `_background_tasks`. | +5 |
| `src/api/routes/instruments.py` | Add `POST /api/instruments`, `PUT /api/instruments/{symbol}`, `DELETE /api/instruments/{symbol}`. Each write calls `pg_notify('instruments', symbol)` via `conn.execute("SELECT pg_notify('instruments', $1)", symbol)`. | +80 |
| `src/api/main.py` | Line 87: Replace `upsert_instruments(settings.contracts)` with env-var-based seed (D-07) or remove. | +5/-3 |
| `src/api/utils.py` | `resolve_contract()`: remove `settings.contracts` iteration; replace with `get_active_contracts()` call or DB query. | +5/-5 |
| `production/schemas/create_schema.sql` | Add `base TEXT NOT NULL DEFAULT ''` and `expiry DATE` columns to instruments CREATE TABLE IF NOT EXISTS. | +2 |
| `production/scripts/migrate_instruments.py` | New file. Idempotent migration script. | +40 |
| `production/scripts/add_instruments_trigger.sql` | New file. CREATE FUNCTION + CREATE TRIGGER statements. | +15 |
| `tests/unit/test_settings.py` | Delete or update all 7 tests: `s.contracts` → `get_active_contracts()` mock | -70/+40 |
| `tests/unit/config/test_settings_equity.py` | Delete or update all 15 tests: `s.instruments` → `get_active_contracts()` mock | -130/+60 |
| `tests/unit/test_service_contract_resolution.py` | Update psycopg2 mocks — non-futures now come from instruments table not `s.contracts`. Update `_make_settings()` helper. | -20/+30 |
| `tests/unit/providers/test_ibkr_adapter.py:277` | Replace `settings.contracts` with `get_active_contracts()` mock | -3/+5 |
| `tests/unit/service_tests/test_feature_writer_agent.py:446` | Replace `s.contracts =` mutation with `get_active_contracts()` mock/patch | -2/+5 |
| `tests/unit/api/test_api_utils.py:42` | Update `mock_settings.contracts` to mock `get_active_contracts()` | -1/+3 |
| `tests/unit/pipeline_tests/test_cache_manager.py` | Add tests for `start_instruments_listener()` returns one Task, `_reload_instruments_cache()` calls `invalidate_active_contracts_cache()` | +40 |

**Estimated total:** -750/+350 net. Settings.py drops from ~1136 lines to ~400.

---

## 5. Test Impact

### Tests That Will Break (Confirmed)

**Group A — Assert on `s.contracts` or `s.instruments` (settings hardcoded list):**

`tests/unit/test_settings.py` — All 7 tests in `TestBuildContractsBaseSymbolTemplates`:
- Pattern: `s = Settings(); futures = [c for c in s.contracts if ...]`
- Fix pattern: These tests validated the now-deleted `build_contracts()` logic. They should be deleted or rewritten to test that `Settings()` has no `contracts` field. New test: `Settings()` does not have `contracts` attribute.

`tests/unit/config/test_settings_equity.py` — All 15 tests in `TestPilotETFs` and `TestFullETFRollout`:
- Pattern: `s = Settings(); symbols = {inst.symbol for inst in s.instruments}`
- Fix pattern: Mock `get_active_contracts()` to return a fake list. Or, for integration-style coverage, query the actual DB. Since these test the data shape, most should be rewritten as DB-state tests.
- `test_total_instrument_count_60`: After migration, this assertion moves to a DB count test.

**Group B — Tests Mocking psycopg2 for get_active_contracts():**

`tests/unit/test_service_contract_resolution.py` — 6 tests:
- Currently patches `psycopg2.connect` and provides mock rows for futures.
- After D-03, non-futures come from a second psycopg2 query (instruments table). The mock must supply two fetchall results.
- `_make_mock_db_conn` needs to support multiple cursor calls.
- `test_db_error_falls_back_to_config`: fallback changes from `list(mock_settings.contracts)` to `_active_contracts_cache` or empty list. Test must be updated.

**Group C — settings.contracts Mutation in Test Setup:**

`tests/unit/service_tests/test_feature_writer_agent.py:446`:
- `s.contracts = instruments` — direct mutation no longer valid after contracts field removed.
- Fix: Patch `get_active_contracts()` instead.

`tests/unit/providers/test_ibkr_adapter.py:277`:
- `settings.contracts` access — replace with `get_active_contracts()` mock.

### Tests That Are Fine

- `tests/unit/core/test_instrument_session.py` — constructs `Instrument(...)` directly, no `Settings`. Unaffected.
- `tests/unit/core/test_models.py` — `Instrument(symbol="NQH6")` direct construction. Unaffected.
- `tests/unit/pipeline_tests/test_cache_manager.py` — tests CacheManager directly. Will need additions for new listener method.

### New Tests Required

```python
# tests/unit/pipeline_tests/test_cache_manager.py — additions
def test_start_instruments_listener_returns_one_task():
    """start_instruments_listener returns exactly 1 asyncio.Task."""

async def test_reload_instruments_cache_calls_invalidate():
    """_reload_instruments_cache calls invalidate_active_contracts_cache()."""

async def test_on_instrument_notify_schedules_reload():
    """_on_instrument_notify callback triggers _reload_instruments_cache."""

# tests/unit/api/test_instruments_crud.py — new file
async def test_post_instrument_creates_row():
    """POST /api/instruments creates DB row and calls pg_notify."""

async def test_put_instrument_updates_and_notifies():
    """PUT /api/instruments/{symbol} updates row and calls pg_notify."""

async def test_delete_instrument_soft_deletes():
    """DELETE /api/instruments/{symbol} sets is_active=false."""

# tests/unit/config/test_get_active_contracts_non_futures_from_db.py — new file
def test_non_futures_from_instruments_table():
    """get_active_contracts() returns non-futures from instruments WHERE is_active=true."""
    # Patches psycopg2 for both the contract_metadata query AND instruments query.
```

---

## 6. Validation Architecture

### Phase Goal Verification

**INST-01:** instruments table is single source of truth
- Run: `PGPASSWORD=postgres psql ... -c "SELECT COUNT(*) FROM instruments WHERE is_active=true"`
- Check: 58+ rows, all with complete contract_details
- Check: `cat src/config/settings.py | grep -c "Instrument("` → 0 (no hardcoded Instrument instances)

**INST-02:** API CRUD works without code deploy
- Test: `curl -X POST http://localhost:8000/api/instruments -d '{"symbol":"TESTX",...}'`
- Verify: Row appears in DB within 1 second.
- Verify: pg_notify fired: check via LISTEN in a psql session.

**INST-03:** Pipeline picks up changes within 1 second
- Setup: Open psql session with `LISTEN instruments;`
- Action: `UPDATE instruments SET is_active=false WHERE symbol='SPY'`
- Verify: psql receives `NOTIFY instruments, "SPY"` within 1 second.
- Verify: `invalidate_active_contracts_cache()` was called (log line `instruments_listener.instrument_changed`).
- Verify: Next `get_active_contracts()` call does not include SPY.

**INST-04 (implicit from D-08):** Migration is idempotent
- Run `python production/scripts/migrate_instruments.py` twice.
- Verify: Row count unchanged on second run.
- Verify: No duplicate key errors.

**INST-05 (implicit from D-11/D-12):** Tests pass without settings.contracts
- Run: `.venv/bin/pytest tests/unit/ -q` → all green.

### Regression Guard

`get_active_contracts()` return shape must be identical before and after:
- Returns `list[Instrument]`
- Futures entries: symbol is the active contract code (e.g., ESM6), not base (ES)
- Non-futures entries: symbol is the full symbol (e.g., EURUSD, SPY)
- VIX entry includes `provider_meta={"ibkr": {"trading_class": "VX"}}`

Run `get_active_contracts()` in a Python REPL before and after the change. Compare the symbol list. Any symbol missing from the new result is a regression.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| DB change notification | Polling loop in CacheManager | asyncpg LISTEN/NOTIFY | Zero compute, push-based, <1s latency |
| Instrument config broadcast | Redis pub/sub, Kafka topic | pg_notify in SQL trigger | DB already has the event; no extra infra |
| Row-level audit on instrument changes | Custom audit table | Deferred to v2.7 | Scope boundary from CONTEXT.md |

---

## Common Pitfalls

### Pitfall 1: LISTEN Connection Released Back to Pool
**What goes wrong:** Using `async with self._db.get_connection() as conn:` for LISTEN. The context manager releases the connection when the `async with` block exits — the LISTEN subscription is lost immediately.
**How to avoid:** Use `asyncpg.connect(database_url)` to acquire a raw dedicated connection. Hold it for the lifetime of the listener loop. Close it explicitly in the `finally` block.

### Pitfall 2: add_listener Callback Is Sync, Not Async
**What goes wrong:** The callback passed to `conn.add_listener()` is a sync function. Calling `await` inside it raises `RuntimeError: no running event loop`.
**How to avoid:** In the callback, use `asyncio.ensure_future(coroutine)` or `loop.call_soon(lambda: asyncio.create_task(coroutine))`. The loop is already running — you just need to schedule a task onto it.

### Pitfall 3: NOTIFY Before Transaction Commits
**What goes wrong:** If `pg_notify` is called inside a transaction (in the API route) before the INSERT/UPDATE commits, listeners receive the notification but the row is not yet visible. Race condition.
**How to avoid:** The DB trigger uses `AFTER INSERT OR UPDATE OR DELETE` — it fires after the row is committed. The API routes should also use the trigger pattern (write the row; trigger fires) rather than explicit `pg_notify` calls in the route handler. If the route calls `pg_notify` explicitly, it must do so after the DB execute completes and is committed (autocommit mode or after commit).

### Pitfall 4: settings.contracts Fallback Returns Empty List
**What goes wrong:** After D-02 removes `s.contracts`, the fallback in `get_active_contracts()` can no longer return `list(s.contracts)`. If the DB is unavailable at cold start and `_active_contracts_cache` is None, the function returns `[]`, causing the pipeline to start with no instruments.
**How to avoid:** Log a CRITICAL warning when returning empty list. Consider keeping `IBKR_CONTRACTS_JSON` env var as the last-resort fallback for cold start (D-07). The migration script ensures the DB is seeded before the env var is removed.

### Pitfall 5: USDJPY Missing From DB After Naive Re-run of upsert_instruments
**What goes wrong:** Calling `upsert_instruments(settings.contracts)` with the old buggy code (c.base as PK) after migration will drop USDJPY and overwrite the correct USD row (USDCHF). If the seeding call in main.py is not removed or fixed, every API restart corrupts the FX data.
**How to avoid:** Fix `upsert_instruments()` to use `c.symbol` as PK AND update the seeding call in main.py before any deployment.

### Pitfall 6: Trigger Function Returns Wrong Value on DELETE
**What goes wrong:** `RETURN NEW` in a DELETE trigger returns NULL, which causes the trigger chain to abort in some PostgreSQL versions (though for AFTER triggers it does not affect the DML result, it is still incorrect).
**How to avoid:** Use `RETURN COALESCE(NEW, OLD)` in the trigger function.

---

## Code Examples

### asyncpg LISTEN Subscription (verified pattern)
```python
import asyncpg

async def listen_example():
    conn = await asyncpg.connect("postgresql://...")
    
    def callback(connection, pid, channel, payload):
        print(f"Got notification on {channel}: {payload}")
    
    await conn.execute("LISTEN my_channel")
    conn.add_listener("my_channel", callback)
    
    # Keep connection alive; notifications arrive via callback
    try:
        while True:
            await asyncio.sleep(60)
    finally:
        conn.remove_listener("my_channel", callback)
        await conn.close()
```

### pg_notify from API Route
```python
@router.post("/instruments")
async def create_instrument(payload: InstrumentCreate, db_manager = Depends(get_db_manager)):
    await db_manager.execute_command(
        "INSERT INTO instruments (symbol, base, contract_details, is_active) VALUES ($1, $2, $3::jsonb, $4)",
        payload.symbol, payload.base, payload.model_dump(), True
    )
    # Trigger fires automatically via DB trigger — no explicit pg_notify needed here.
    # But if trigger is not yet deployed, explicit call:
    # await db_manager.execute_command("SELECT pg_notify('instruments', $1)", payload.symbol)
    return {"status": "created", "symbol": payload.symbol}
```

### Instrument from DB Row
```python
import json
from src.core.models import Instrument

def instrument_from_db_row(row: dict) -> Instrument:
    """Build Instrument from instruments table row (asyncpg dict)."""
    cd = row["contract_details"]  # already dict via asyncpg JSONB codec
    return Instrument(
        symbol=cd.get("symbol") or row["symbol"],  # FX: use full symbol from contract_details
        base=row["base"],
        name=cd.get("name", ""),
        asset_class=cd.get("asset_class", "futures"),
        exchange=cd.get("exchange", ""),
        sector=cd.get("sector", ""),
        tick_size=cd.get("tick_size", 0),
        point_value=cd.get("point_value", 0),
        session_id=cd.get("session_id", "futures_24_5"),
        provider_meta=cd.get("provider_meta", {}),
        expiry=cd.get("expiry", ""),
    )
```

---

## Open Questions

1. **FX PK strategy after migration**
   - What we know: Current DB stores FX by base (EUR/GBP/USD), but `contract_details.symbol` holds full symbol (EURUSD/GBPUSD/USDCHF). After fix, upsert uses `c.symbol` — DB rows become EURUSD, GBPUSD, USDJPY, USDCHF.
   - What's unclear: Does any code in the pipeline or provider reference the DB instruments table by `base` for FX? The `idx_instruments_base` index suggests some join by base exists.
   - Recommendation: Search for `WHERE base =` in queries; if none, use full symbol as PK for clarity.

2. **get_active_contracts() psycopg2 removal**
   - What we know: D-03 says the function signature is unchanged (sync). Two psycopg2 calls remain (futures from contract_metadata, non-futures from instruments).
   - What's unclear: D-04 says CacheManager populates `_instruments_cache`. Does `get_active_contracts()` read from that cache for non-futures (avoiding the second psycopg2 call)?
   - Recommendation: Keep psycopg2 for both queries in the sync function. The LISTEN handler fires `invalidate_active_contracts_cache()` which causes the next TTL-miss to re-query. This is simple and correct.

3. **api/main.py seeding behavior after D-02**
   - What we know: Line 87 calls `upsert_instruments(settings.contracts)`. This must change.
   - What's unclear: D-07 says "IBKR_CONTRACTS_JSON env var seeds on first run". How does the code distinguish first-run from subsequent runs?
   - Recommendation: Check `SELECT COUNT(*) FROM instruments WHERE is_active=true`. If 0, seed from env var. If >0, skip.

---

## Sources

### Primary (HIGH confidence)
- Live DB query: `\d instruments` — confirmed table schema
- Live DB query: `SELECT COUNT(*), asset_class FROM instruments GROUP BY asset_class` — 58 rows, 3 asset classes
- Live DB query: `SELECT trigger_name FROM information_schema.triggers WHERE event_object_table = 'instruments'` — 0 triggers
- `src/core/database_manager.py` lines 121-139 — upsert_instruments() implementation and bug
- `src/config/settings.py` lines 266-940 — full migration payload (all Instrument defaults)
- `src/config/settings.py` lines 1058-1122 — get_active_contracts() full implementation
- `src/intelligence/pipeline/cache_manager.py` — CacheManager.start_refresh_loops() pattern
- `services/intelligence_pipeline_agent.py` lines 114, 144, 252-258 — orchestrator wiring

### Secondary (MEDIUM confidence)
- asyncpg documentation pattern: LISTEN/NOTIFY via `conn.add_listener()`, verified against asyncpg API design
- PostgreSQL AFTER trigger behavior: `RETURN COALESCE(NEW, OLD)` for DELETE safety

---

## Metadata

**Confidence breakdown:**
- Current state / migration payload: HIGH — verified from live DB + source code
- FX symbol collision bug: HIGH — confirmed from source code + DB query
- asyncpg LISTEN pattern: HIGH — well-documented asyncpg API
- Test impact: HIGH — confirmed by grep over all test files
- CacheManager integration: HIGH — read full source

**Research date:** 2026-05-19
**Valid until:** 2026-06-19 (stable schema, no fast-moving deps)
