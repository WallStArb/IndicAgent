# Instrument Registry Hardening — Design

**Date:** 2026-05-19
**Phase:** 091 post-execution corrections
**Status:** Approved — ready for planning

## Problem Statement

Phase 091 shipped correct behavior but with four architectural violations identified
in post-execution Gemini review and internal analysis:

| Violation | Symptom |
|-----------|---------|
| Dead state | `CacheManager._instruments_cache` populated, never read |
| Wrong dependency direction | CacheManager imports from settings (lazy import, ruff noqa suppressed) |
| Manual operations required | Trigger SQL needs human on fresh deploy; integration test is manual |
| No observability on listener | Silent listener death undetectable without waiting for missed invalidation |

Plus two correctness bugs: deprecated `asyncio.get_event_loop()`, no startup guard
against empty instruments.

## Renaissance Principles Applied

- **Modularity** — Each component owns exactly one thing. Settings owns infra config.
  CacheManager owns pipeline caches. Neither imports the other's internals.
- **Automation over manual** — Trigger installation and integration testing run
  automatically. No human-required steps after service start.
- **Observability** — Every cache state transition metered. Listener health surfaced
  as a Prometheus gauge so Grafana alerting works without dashboard work.
- **Fail-fast** — Never run the pipeline with zero instruments. That is a broken
  deployment, not a degraded-but-OK state.
- **Efficiency** — One DB connection per `get_active_contracts()` miss (was three).

## The Eight Fixes

### Fix 1: Callback injection — correct dependency direction

**Files:** `src/intelligence/pipeline/cache_manager.py`,
`services/intelligence_pipeline_agent.py`

`CacheManager.__init__` gains:
```python
on_instruments_changed: Callable[[], None] | None = None
```
stored as `self._on_instruments_changed = on_instruments_changed or (lambda: None)`.

`_reload_instruments_cache()` replaces the lazy import block with:
```python
self._on_instruments_changed()
```

In `intelligence_pipeline_agent._setup()`, wire the callback at construction time:
```python
from src.config.settings import invalidate_active_contracts_cache
self._cache_mgr = CacheManager(
    ...,
    on_instruments_changed=invalidate_active_contracts_cache,
)
```

The lazy import, its `noqa: PLC0415` comment, and the `# Lazy import to avoid
circular import` comment are all deleted. CacheManager has zero imports from
`src.config.settings`.

### Fix 2: Remove dead state

**File:** `src/intelligence/pipeline/cache_manager.py`

`self._instruments_cache: list = []` (line 164) is deleted. No other code reads it.
Dead state is deleted, not commented out. If a future consumer needs the post-reload
list, it calls `get_active_contracts()` after the callback fires — single source of
truth.

### Fix 3: Startup fail-fast

**File:** `services/intelligence_pipeline_agent.py`

After line 114 (`self._contracts = get_active_contracts(self.settings)`):
```python
if not self._contracts:
    raise RuntimeError(
        "intelligence_pipeline_agent: no active instruments at startup. "
        "DB unreachable or instruments table empty. Check DB connectivity "
        "and ensure production/scripts/migrate_instruments.py has been run."
    )
```

Invariant: the pipeline never starts with zero instruments. A misconfigured or
unreachable DB is a deployment error, not a tolerable degraded state.

### Fix 4: One psycopg2 connection per cache miss

**File:** `src/config/settings.py` — `get_active_contracts()`

Current code opens three `psycopg2.connect()` calls sequentially. Rewrite to one
`with psycopg2.connect(s.database_url) as conn:` block with three cursor operations
inside. Same semantics, one-third the connection overhead. The three queries are:
1. Futures templates from `instruments WHERE asset_class='futures'`
2. Front-month contracts from `contract_metadata WHERE is_front_month=true`
3. Non-futures from `instruments WHERE is_active=true AND asset_class!='futures'`

### Fix 5: asyncio.get_running_loop()

**File:** `src/intelligence/pipeline/cache_manager.py` — `_on_instrument_notify()`

```python
# Before (deprecated Python 3.10+)
asyncio.get_event_loop().call_soon_threadsafe(...)

# After
asyncio.get_running_loop().call_soon_threadsafe(...)
```

The callback fires inside asyncpg's event loop dispatch; the running loop always
exists here. Removes the Python 3.10+ DeprecationWarning.

### Fix 6: Listener health metric

**File:** `src/intelligence/pipeline/cache_manager.py`

Add one OTel up-down gauge in `__init__`:
```python
from src.observability.metrics import up_down_counter
self._listener_connected = up_down_counter(
    "instruments_listener_connected",
    "1 when LISTEN instruments connection is active, 0 when reconnecting",
)
```

In `_run_instruments_listener()`:
- After `await conn.execute("LISTEN instruments")`: `self._listener_connected.add(1)`
- In the exception handler before `asyncio.sleep(5)`: `self._listener_connected.add(-1)`

The existing Prometheus scrape + Grafana stack picks this up automatically.
No manual dashboarding needed. Enables alerting on silent listener death.

### Fix 7: Automated trigger installation

**Files:** `src/core/database_manager.py`,
`services/intelligence_pipeline_agent.py`

Add to `DatabaseManager`:
```python
async def ensure_instruments_trigger(self) -> None:
    """Idempotently install the pg_notify trigger on the instruments table.

    Uses CREATE OR REPLACE — safe to call on every startup. Eliminates the
    need to manually apply production/scripts/add_instruments_trigger.sql
    on fresh deployments or after DB restores.
    """
    sql = """
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
    """
    await self.execute_command(sql)
```

Call from `intelligence_pipeline_agent._setup()` before starting the listener:
```python
await self._db_manager.ensure_instruments_trigger()
```

The SQL in `production/scripts/add_instruments_trigger.sql` stays for
documentation and emergency manual use. It is no longer the operational
mechanism — the service installs its own trigger.

### Fix 8: Automated integration test

**File:** `tests/integration/test_instrument_registry.py` (new)

```python
pytestmark = pytest.mark.integration

def test_get_active_contracts_returns_nonzero():
    result = get_active_contracts()
    assert len(result) > 0

def test_all_required_symbols_present():
    symbols = {c.symbol for c in get_active_contracts()}
    assert "SPY" in symbols      # equity
    assert "USDJPY" in symbols   # FX (phase 091 collision fix)
    assert "EURUSD" in symbols   # FX

def test_trigger_installed():
    # Verifies the trigger was auto-installed by ensure_instruments_trigger()
    ...query information_schema.triggers...
    assert "trg_instruments_notify" in trigger_names
```

Runs automatically via `pytest tests/integration/ -m integration` — already
wired in `pytest.ini`. Pattern matches existing integration tests (asyncpg,
`pytestmark = pytest.mark.integration`). No human required.

## What Does NOT Change

- `invalidate_active_contracts_cache()` stays in `settings.py` — public API
- 60s TTL cache stays — safety net for the sync call path
- `get_active_contracts()` stays synchronous — 20+ call sites
- LISTEN reconnect loop logic is correct as-is
- `production/scripts/add_instruments_trigger.sql` stays for documentation

## Dependency Direction After Fixes

```
intelligence_pipeline_agent
  imports → settings.invalidate_active_contracts_cache  (passed as callback)
  constructs → CacheManager(on_instruments_changed=callback)
                 asyncpg LISTEN  (no settings import)
                 callback()      (fires the settings invalidation, no import needed)
```

Zero circular imports. DAG is clean.

## Files Modified

| File | Change |
|------|--------|
| `src/intelligence/pipeline/cache_manager.py` | +callback param, -dead state, -lazy import, +gauge, fix asyncio |
| `services/intelligence_pipeline_agent.py` | +callback wiring, +startup guard, +ensure_trigger call |
| `src/core/database_manager.py` | +ensure_instruments_trigger() |
| `src/config/settings.py` | 3 connections → 1 in get_active_contracts() |
| `tests/integration/test_instrument_registry.py` | new — 3 automated integration tests |
| `tests/unit/pipeline_tests/test_cache_manager.py` | update constructor call for new param |

## Testing

- `pytest tests/unit/ -q` — must stay green (3405 passing)
- `pytest tests/integration/ -m integration` — new test passes against live DB
- Manual smoke: restart `indicagent-intelligence-pipeline`, confirm
  `instruments_listener_connected` gauge = 1 in Prometheus
