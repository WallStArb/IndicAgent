# Phase 090: Signal Ledger Hardening + Thread Safety - Pattern Map

**Mapped:** 2026-05-19
**Files analyzed:** 5 modified files + 2 test files
**Analogs found:** 5 / 5

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `src/persistence/repository/signal_ledger_repository.py` | repository | CRUD | `services/feature_writer_agent.py` | role-match (named-param tuple helper) |
| `src/config/settings.py` | config/singleton | request-response | `src/intelligence/pipeline/cache_manager.py` | data-flow-match (lock-protected shared state) |
| `src/intelligence/pipeline/cache_manager.py` | cache | request-response | self (comment addition only) | exact |
| `tests/unit/test_signal_ledger_repository.py` | test | CRUD | `tests/unit/service_tests/test_feature_writer_agent.py` | exact |
| `tests/unit/test_pipeline_attribution.py` | test | CRUD | self (call site update only) | exact |

---

## Pattern Assignments

### `src/persistence/repository/signal_ledger_repository.py` (repository, CRUD)

**Analog:** `services/feature_writer_agent.py` lines 158-203

**Plan:** 01 (Signal ledger `_to_row()` refactor)

**Core pattern — named-field tuple helper** (`feature_writer_agent.py` lines 158-203):

```python
def _record_to_insert_params(
    record: BarIntelligenceRecord,
    expiry_map: dict[str, date] | None = None,
) -> tuple:
    """Build a 31-element tuple of INSERT parameters for _INSERT_FEATURE_SQL."""
    # ... setup logic ...
    return (
        event.ts,              # $1 ts
        event.symbol,          # $2 symbol
        event.tf,              # $3 tf
        event.platform,        # $4 platform
        event.source,          # $5 source
        record.schema_version, # $6 schema_version
        event.bar.model_dump(), # $7 bar jsonb
        # ... continues through $31
        days,                  # $31 days_to_expiry
    )
```

Key style rules (copy verbatim):
- Docstring says "N-element tuple of INSERT parameters for _INSERT_SQL"
- Each return element has `# $N field_name` comment on the same line
- JSONB columns note: `asyncpg serializes them to jsonb natively via codec`
- No blank lines between elements; phase comments allowed (e.g., `# Phase 32: stop basis fields`)

**Current `to_insert_params()` state** (`signal_ledger_repository.py` lines 154-233):

The method currently has partial comments — only some positions are annotated (e.g., `# $23`, `# $40`, `# $47::jsonb`). The rename to `_to_row()` must annotate ALL 67 positions with `# $N field_name` in the same `event.field  # $N name` style as the fleet reference.

Current docstring says "65-element tuple" — must be corrected to "67-element tuple". Two columns (`is_backfill` at $66, `ttl_bars` at $67) were added after the docstring was written.

**Call sites to update** (both in `signal_ledger_repository.py`):

```python
# Line 555 — insert_signals():
params = [entry.to_insert_params() for entry in entries]
# BECOMES:
params = [entry._to_row() for entry in entries]

# Line 568 — insert_signals_with_features():
await conn.execute(_INSERT_SQL, *entry.to_insert_params())
# BECOMES:
await conn.execute(_INSERT_SQL, *entry._to_row())
```

**Lifecycle SQL call sites — add field comments (D-03)**

These Python `execute_command()` calls pass >= 5 positional args and need `# $N field_name` inline comments. The SQL itself is self-documenting via `SET col = $N`; the Python args are what need comments.

`update_signal_status()` (lines 581-600) — 17 params, `_UPDATE_STATUS_SQL`:
```python
await self._db_manager.execute_command(
    _UPDATE_STATUS_SQL,
    signal_id,              # $1 signal_id
    kwargs.get("status"),   # $2 status
    kwargs.get("activated_at"),   # $3 activated_at
    kwargs.get("exit_at"),        # $4 exit_at
    kwargs.get("exit_price"),     # $5 exit_price
    kwargs.get("exit_reason"),    # $6 exit_reason
    kwargs.get("pnl_ticks"),      # $7 pnl_ticks
    kwargs.get("pnl_r"),          # $8 pnl_r
    kwargs.get("pnl_dollars"),    # $9 pnl_dollars
    kwargs.get("signal_quality"), # $10 signal_quality
    kwargs.get("activation_price"),    # $11 activation_price
    kwargs.get("zone_entry_pct"),      # $12 zone_entry_pct
    kwargs.get("bars_to_activation"),  # $13 bars_to_activation
    kwargs.get("mae"),            # $14 mae
    kwargs.get("mfe"),            # $15 mfe
    kwargs.get("bars_in_trade"),  # $16 bars_in_trade
    kwargs.get("outcome"),        # $17 outcome
)
```

`record_activation()` (lines 611-618) — 5 params, `_RECORD_ACTIVATION_SQL`:
```python
await self._db_manager.execute_command(
    _RECORD_ACTIVATION_SQL,
    signal_id,                       # $1 signal_id
    kwargs.get("activated_at"),      # $2 activated_at
    kwargs.get("activation_price"),  # $3 activation_price
    kwargs.get("zone_entry_pct"),    # $4 zone_entry_pct
    kwargs.get("bars_to_activation"), # $5 bars_to_activation
)
```

`record_zone_resolution()` (lines 622-636) — 12 params, `_RECORD_ZONE_RESOLUTION_SQL`:
```python
await self._db_manager.execute_command(
    _RECORD_ZONE_RESOLUTION_SQL,
    signal_id,                    # $1 signal_id
    kwargs.get("status"),         # $2 status
    kwargs.get("exit_at"),        # $3 exit_at
    kwargs.get("exit_price"),     # $4 exit_price
    kwargs.get("exit_reason"),    # $5 exit_reason
    kwargs.get("pnl_r"),          # $6 pnl_r
    kwargs.get("pnl_dollars"),    # $7 pnl_dollars
    kwargs.get("signal_quality"), # $8 signal_quality
    kwargs.get("mae"),            # $9 mae
    kwargs.get("mfe"),            # $10 mfe
    kwargs.get("bars_in_trade"),  # $11 bars_in_trade
    kwargs.get("outcome"),        # $12 outcome
)
```

`record_market_resolution()` (lines 640-652) — 10 params, `_RECORD_MARKET_RESOLUTION_SQL`:
```python
await self._db_manager.execute_command(
    _RECORD_MARKET_RESOLUTION_SQL,
    signal_id,                              # $1 signal_id
    kwargs.get("market_entry_at"),          # $2 market_entry_at
    kwargs.get("market_entry_exit_price"),  # $3 market_entry_exit_price
    kwargs.get("market_entry_exit_at"),     # $4 market_entry_exit_at
    kwargs.get("market_entry_pnl_r"),       # $5 market_entry_pnl_r
    kwargs.get("market_entry_mae"),         # $6 market_entry_mae
    kwargs.get("market_entry_mfe"),         # $7 market_entry_mfe
    kwargs.get("market_entry_bars_in_trade"), # $8 market_entry_bars_in_trade
    kwargs.get("market_entry_outcome"),     # $9 market_entry_outcome
    kwargs.get("market_entry_gap_bars"),    # $10 market_entry_gap_bars
)
```

`record_zone_resolution_with_activation()` (lines 656-668) — 16 params, `_RECORD_ZONE_WITH_ACTIVATION_SQL`:
```python
await self._db_manager.execute_command(
    _RECORD_ZONE_WITH_ACTIVATION_SQL,
    signal_id,                        # $1 signal_id
    kwargs.get("status"),             # $2 status
    kwargs.get("activated_at"),       # $3 activated_at
    kwargs.get("activation_price"),   # $4 activation_price
    kwargs.get("zone_entry_pct"),     # $5 zone_entry_pct
    kwargs.get("bars_to_activation"), # $6 bars_to_activation
    kwargs.get("exit_at"),            # $7 exit_at
    kwargs.get("exit_price"),         # $8 exit_price
    kwargs.get("exit_reason"),        # $9 exit_reason
    kwargs.get("pnl_r"),              # $10 pnl_r
    kwargs.get("pnl_dollars"),        # $11 pnl_dollars
    # ... continue through $16 per SQL definition
)
```

---

### `src/config/settings.py` (config/singleton, request-response)

**Analog:** `src/intelligence/pipeline/cache_manager.py` lines 131-133 (asyncio.Lock pattern); `threading.RLock` is the sync equivalent for module-level globals.

**Plan:** 02 (Thread safety - settings.py only)

**Current naked globals** (lines 946-970):
```python
_settings_singleton: Settings | None = None
_active_contracts_cache: list[Instrument] | None = None
_active_contracts_last_refresh: float = 0.0
_ACTIVE_CONTRACTS_TTL = 60.0  # seconds

def invalidate_active_contracts_cache() -> None:
    global _active_contracts_last_refresh  # noqa: PLW0603
    _active_contracts_last_refresh = 0.0

def _default_settings() -> Settings:
    global _settings_singleton  # noqa: PLW0603
    if _settings_singleton is None:
        _settings_singleton = Settings()
    return _settings_singleton
```

**Target pattern — RLock wrapping** (add `import threading` to existing stdlib imports; `time` is already imported at line 15):

```python
import threading

_settings_lock = threading.RLock()
_settings_singleton: Settings | None = None
_active_contracts_cache: list[Instrument] | None = None
_active_contracts_last_refresh: float = 0.0
_ACTIVE_CONTRACTS_TTL = 60.0  # seconds

def invalidate_active_contracts_cache() -> None:
    """Force next get_active_contracts() call to re-query the database."""
    global _active_contracts_last_refresh  # noqa: PLW0603
    with _settings_lock:
        _active_contracts_last_refresh = 0.0

def _default_settings() -> Settings:
    """Lazily create a module-level Settings instance."""
    global _settings_singleton  # noqa: PLW0603
    with _settings_lock:
        if _settings_singleton is None:
            _settings_singleton = Settings()
        return _settings_singleton
```

**`get_active_contracts()` — double-checked locking pattern** (lines 1059-1109):

The DB query (psycopg2 connect + execute) can be slow. Use double-checked locking: lock for cache read, release during DB query, re-acquire for cache write. Do NOT hold the lock across the entire DB call.

```python
def get_active_contracts(settings: Settings | None = None) -> list[Instrument]:
    global _active_contracts_cache, _active_contracts_last_refresh  # noqa: PLW0603

    s = settings or _default_settings()

    # Check cache under lock (atomic read)
    now = time.monotonic()
    with _settings_lock:
        cache_age = now - _active_contracts_last_refresh
        if _active_contracts_cache is not None and cache_age < _ACTIVE_CONTRACTS_TTL:
            return _active_contracts_cache
    # Lock released here — DB query runs without holding lock

    # ... build result (DB query or config fallback) ...

    # Write cache under lock (atomic write)
    with _settings_lock:
        _active_contracts_cache = result
        _active_contracts_last_refresh = now
    return result
```

RLock is required (not plain `Lock`) because `_default_settings()` may be called from within Pydantic validators during `Settings()` construction, which can trigger re-entrant calls from the same thread.

---

### `src/intelligence/pipeline/cache_manager.py` (cache, request-response)

**Analog:** self — comment addition only.

**Plan:** 02 (or 01 — planner's discretion per D-10; Plan 02 is more natural)

**Context:** Phase 089 shipped asyncio locks at lines 131-133. The only change in Phase 090 is adding a comment to `snapshot()` at line 228.

**Current `snapshot()` signature** (line 228):
```python
def snapshot(self) -> CacheSnapshot:
    """Build a CacheSnapshot from current cache state for per-bar consumption.

    Imports CacheSnapshot locally to avoid a circular import between
    cache_manager and signal_processor at module level.
    """
```

**Target: add sync-invariant comment** (insert after the existing docstring body):
```python
def snapshot(self) -> CacheSnapshot:
    """Build a CacheSnapshot from current cache state for per-bar consumption.

    Imports CacheSnapshot locally to avoid a circular import between
    cache_manager and signal_processor at module level.
    """
    # sync method — cannot be preempted in asyncio event loop; lock-free reads are safe
```

Do NOT make `snapshot()` async. Do NOT add locks inside it. The lock-free reads are correct by the asyncio execution model: a synchronous `def` cannot yield control mid-execution in a single-threaded asyncio event loop.

---

### `tests/unit/test_signal_ledger_repository.py` (test, CRUD)

**Analog:** `tests/unit/service_tests/test_feature_writer_agent.py` lines 133-141

**Plan:** 01

**Fleet reference test** (`test_feature_writer_agent.py` lines 133-141):
```python
def test_record_to_insert_params_returns_31_tuple():
    """_record_to_insert_params returns a 31-element tuple matching SQL columns."""
    from services.feature_writer_agent import _record_to_insert_params

    record = _make_valid_bar_intelligence_record()
    params = _record_to_insert_params(record)

    assert isinstance(params, tuple)
    assert len(params) == 31
```

Note: the fleet reference hardcodes `31`. The D-05 decision requires the Phase 090 test to use the dynamic `re.findall` pattern instead — self-maintaining as columns are added.

**Target test to add** (new function in `test_signal_ledger_repository.py`):
```python
def test_to_row_returns_correct_count():
    """_to_row() tuple length matches $N param count in _INSERT_SQL — self-maintaining."""
    import re
    from src.persistence.repository.signal_ledger_repository import (
        LedgerEntry,
        _INSERT_SQL,
    )

    # Build minimal LedgerEntry with required fields
    entry = LedgerEntry(
        signal_id="00000000-0000-0000-0000-000000000001",
        timestamp=...,  # planner fills in minimal fixture
        symbol="ES",
        timeframe="1m",
        setup_plugin="test_plugin",
        signal_type="long",
        direction="long",
        entry_price=4500.0,
        stop_loss=4490.0,
        targets=[],
        confidence=0.75,
        confluence_score=0.7,
        regime_context={},
        supporting_factors=[],
        was_selected=True,
        num_signals_bar=1,
        num_agreeing=1,
        num_conflicting=0,
        resolution_method="in_process",
        composite_rank=1,
    )
    sql_param_count = len(re.findall(r'\$\d+', _INSERT_SQL))
    assert isinstance(entry._to_row(), tuple)
    assert len(entry._to_row()) == sql_param_count
```

Current test file imports (line 3): `from src.persistence.repository.signal_ledger_repository import SignalLedgerRepository`. The new test adds `LedgerEntry` and `_INSERT_SQL` as additional imports; `re` is standard library, added at the top of the test file.

---

### `tests/unit/test_pipeline_attribution.py` (test, CRUD)

**Analog:** self — call site update only.

**Plan:** 01

**Current state** (lines 94-97):
```python
params = entry.to_insert_params()
assert len(params) == 67, f"Expected 67 params, got {len(params)}"
assert params[58] == 0.80, "pre_quality_confidence should be $59 (index 58)"
assert params[59] == 0.68, "pre_calibration_confidence should be $60 (index 59)"
```

**Target state** (per RESEARCH.md recommendation to apply dynamic pattern here too):
```python
import re
from src.persistence.repository.signal_ledger_repository import _INSERT_SQL

params = entry._to_row()
sql_param_count = len(re.findall(r'\$\d+', _INSERT_SQL))
assert len(params) == sql_param_count, f"Expected {sql_param_count} params, got {len(params)}"
assert params[58] == 0.80, "pre_quality_confidence should be $59 (index 58)"
assert params[59] == 0.68, "pre_calibration_confidence should be $60 (index 59)"
```

The positional index assertions (`params[58]`, `params[59]`) remain — they test that specific fields map to the correct positions, which is separate from the count assertion.

---

## Shared Patterns

### Named-field tuple helper — `# $N field_name` comment style
**Source:** `services/feature_writer_agent.py` lines 171-203
**Apply to:** `LedgerEntry._to_row()` in `signal_ledger_repository.py`

Rules:
- Comment is on the same line as the field: `self.signal_id,  # $1 signal_id`
- Phase context comments on their own line before a group: `# Phase 32: stop basis fields`
- Type hints in comments for JSONB/special types: `self.co_fire_partners,  # $64::text[]`
- Docstring names the tuple size and references the SQL constant

### Dynamic SQL param count guard test
**Source:** `tests/unit/service_tests/test_feature_writer_agent.py` lines 133-141 (fleet reference), upgraded to dynamic pattern per D-05
**Apply to:** `tests/unit/test_signal_ledger_repository.py` (new test), `tests/unit/test_pipeline_attribution.py` (update existing test)

Pattern:
```python
import re
sql_param_count = len(re.findall(r'\$\d+', _INSERT_SQL))
assert len(entry._to_row()) == sql_param_count
```

### RLock module-level singleton protection
**Source:** `threading.RLock` stdlib; CacheManager asyncio.Lock at `cache_manager.py:131-133` is the async analog
**Apply to:** `settings.py` `_settings_singleton`, `_active_contracts_cache`, `_active_contracts_last_refresh`

Double-checked locking is required for `get_active_contracts()` specifically (slow DB query inside). For `_default_settings()` a simple `with _settings_lock:` block is sufficient.

### Verification grep after rename
**Apply to:** after implementing Plan 01, run:
```bash
grep -rn "to_insert_params" src/ services/ tests/
```
Must return zero results. Any remaining reference is a missed call site.

---

## No Analog Found

No files in this phase lack a codebase analog.

---

## Metadata

**Analog search scope:** `src/persistence/repository/`, `src/config/`, `src/intelligence/pipeline/`, `services/`, `tests/unit/`
**Files scanned:** 7 (signal_ledger_repository.py, feature_writer_agent.py, settings.py, cache_manager.py, test_feature_writer_agent.py, test_signal_ledger_repository.py, test_pipeline_attribution.py)
**Pattern extraction date:** 2026-05-19
