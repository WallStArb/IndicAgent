# Phase 090: Signal Ledger Hardening + Thread Safety - Research

**Researched:** 2026-05-19
**Domain:** Python dataclass tuple helpers, asyncpg positional params, threading.RLock, asyncio.Lock
**Confidence:** HIGH

## Summary

Phase 090 has two independent work streams with zero behavior change. Both are pure correctness fixes.

Stream 1 (LEDGER-01, LEDGER-02): `LedgerEntry.to_insert_params()` returns a 67-element positional tuple (the docstring and CONTEXT.md say 65, but code verification shows `$1..$67` in `_INSERT_SQL` and 67 `self.*` references in the return). The rename to `_to_row()` plus per-field comments follows a fleet pattern already established in `feature_writer_agent._record_to_insert_params()`. Three call sites must be updated in the same change. A dynamic tuple-count guard test must be added; `test_pipeline_attribution.py:95` hardcodes `67` and must be updated to the dynamic pattern.

Stream 2 (THREAD-01): `_settings_singleton`, `_active_contracts_cache`, and `_active_contracts_last_refresh` in `settings.py` are naked module-level globals. `_default_settings()` has a check-before-create pattern with no lock. `get_active_contracts()` has a check-then-set race on `_active_contracts_cache` plus a separate `_active_contracts_last_refresh` write, creating a torn-write window. `threading.RLock` wrapping both functions closes this. THREAD-02 (CacheManager asyncio locks) was shipped in Phase 089 and must NOT be re-implemented.

**Primary recommendation:** Two parallel plans — Plan 01 is the ledger rename, Plan 02 is the settings.py RLock. Both touch different files; no merge conflicts.

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Signal Ledger Named Params (LEDGER-01, LEDGER-02)**
- D-01: `LedgerEntry.to_insert_params()` is renamed to `_to_row()`. Returns the same tuple with one field-name comment per position (`# signal_id`, `# timestamp`, ...). Pattern: identical to `feature_writer_agent._record_to_insert_params()` (lines 158-203). Follow that file's comment style verbatim.
- D-02: All call sites updated: `signal_writer_agent.py` (calls `to_insert_params()` via `_payload_to_ledger_entries()`), `signal_ledger_repository.py` (`insert_signals` line 555, `insert_signals_with_features` line 568), and `tests/unit/test_pipeline_attribution.py:94`.
- D-03: Lifecycle update queries reviewed for positional consistency - add field comments to any raw SQL with >= 5 positional params.
- D-04: No schema change, no DB migration. Pure Python rename + comment addition.
- D-05 (Renaissance guard): Add `test_to_row_returns_correct_count()` to `tests/unit/test_signal_ledger_repository.py`. The test counts `$N` tokens in `_INSERT_SQL` dynamically (`len(re.findall(r'\$\d+', _INSERT_SQL))`) and asserts it equals `len(entry._to_row())`. No hardcoded count.

**Thread Safety: settings_singleton (THREAD-01)**
- D-06: Add `_settings_lock = threading.RLock()` at module scope in `settings.py`. Wrap `_settings_singleton` read/write in `_default_settings()` with `with _settings_lock:`. RLock (reentrant) because `_default_settings()` may be called recursively from validators.
- D-07: `_active_contracts_cache` and `_active_contracts_last_refresh` globals also protected by `_settings_lock` in `get_active_contracts()`. The check-then-set pattern is a read-modify-write race; the lock makes it atomic.
- D-08: No removal of `_active_contracts_cache` globals — deferred to future CacheManager migration.

**Thread Safety: CacheManager pipeline caches (THREAD-02) - ALREADY DONE**
- D-09 (status): `asyncio.Lock()` for `_cross_asset_cache`, `_macro_cache`, and `_htf_intel` was shipped in Phase 089. Locks exist at `cache_manager.py:131-133`. Plan 02 must NOT re-add these.
- D-10 (intentional lock-free reads): `CacheManager.snapshot()` reads without locks — correct and intentional. `snapshot()` is a synchronous `def` (not `async def`), so in asyncio's single-threaded event loop it cannot be preempted. Add comment to `snapshot()`: `# sync method — cannot be preempted in asyncio event loop; lock-free reads are safe`.

**Plan Structure**
- D-11: Two plans, wave 1 (parallel):
  - Plan 01: Signal ledger `_to_row()` refactor
  - Plan 02: Thread safety - settings.py only (plus snapshot() comment)

### Claude's Discretion
- Exact comment style for positional params in `_to_row()` — follow `feature_writer_agent._record_to_insert_params()` verbatim, no deviation
- Whether to add `snapshot()` comment in Plan 01 or Plan 02 (Plan 02 is slightly more natural)
- Import placement for `re` in the test (standard library, top of test file)

### Deferred Ideas (OUT OF SCOPE)
- Full asyncpg named-parameter support (asyncpg uses $N positional)
- Signal ledger schema reduction (requires data migration)
- Removal of `_active_contracts_cache` globals from settings.py (deferred to CacheManager migration phase)
- Observability metric for `_settings_lock` contention
</user_constraints>

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `threading.RLock` | stdlib | Reentrant lock for module-level globals | RLock allows same-thread re-entry; `_default_settings()` may be called from validators during Settings construction |
| `asyncio.Lock` | stdlib | Coroutine-safe lock | Already used in CacheManager at lines 131-133; consistent with fleet |
| `re` | stdlib | Dynamic SQL param count | Used in test to count `$N` tokens in `_INSERT_SQL` without hardcoding |

### Already in Use (reference only)
| Pattern | Where | Notes |
|---------|-------|-------|
| `_record_to_insert_params()` field comments | `feature_writer_agent.py:158-203` | Fleet reference; copy comment style exactly |
| `asyncio.Lock` per cache | `cache_manager.py:131-133` | Shipped Phase 089; do not re-add |

**Installation:** No new packages. All standard library.

## Architecture Patterns

### Pattern 1: Named-field tuple helper (`_to_row()`)

**What:** A module-private method on `LedgerEntry` that returns the same positional tuple as `to_insert_params()` but with one inline comment per position identifying the field name and SQL parameter number.

**When to use:** Any writer that builds a positional tuple for asyncpg `$N` parameters.

**Reference implementation** (`feature_writer_agent.py:158-203`):
```python
def _record_to_insert_params(
    record: BarIntelligenceRecord,
    expiry_map: dict[str, date] | None = None,
) -> tuple:
    """Build a 31-element tuple of INSERT parameters for _INSERT_FEATURE_SQL."""
    # ...
    return (
        event.ts,              # $1 ts
        event.symbol,          # $2 symbol
        event.tf,              # $3 tf
        # ...
    )
```

**Apply to `LedgerEntry`:**
```python
def _to_row(self) -> tuple:
    """Return a 67-element tuple ready for batch INSERT.

    JSONB columns (targets, supporting_factors, market_context, bucket_scores,
    trailing_stop_price, features_snapshot) are passed as Python dicts/lists;
    asyncpg serializes them to jsonb natively via codec.
    """
    return (
        self.signal_id,          # $1 signal_id
        self.timestamp,          # $2 timestamp
        self.symbol,             # $3 symbol
        # ... all 67 fields with $N comments
    )
```

### Pattern 2: Dynamic tuple-count guard test

**What:** A unit test that counts `$N` tokens in `_INSERT_SQL` using `re.findall` and asserts it equals `len(entry._to_row())`. Self-maintaining — no hardcoded count.

**Fleet reference** (`test_feature_writer_agent.py:133-141`):
```python
def test_record_to_insert_params_returns_31_tuple():
    """_record_to_insert_params returns a 31-element tuple matching SQL columns."""
    from services.feature_writer_agent import _record_to_insert_params

    record = _make_valid_bar_intelligence_record()
    params = _record_to_insert_params(record)

    assert isinstance(params, tuple)
    assert len(params) == 31
```

**Dynamic version for Phase 090** (to add to `test_signal_ledger_repository.py`):
```python
def test_to_row_returns_correct_count():
    """_to_row() tuple length matches $N param count in _INSERT_SQL — self-maintaining."""
    import re
    from src.persistence.repository.signal_ledger_repository import (
        LedgerEntry,
        _INSERT_SQL,
    )
    # Build minimal LedgerEntry
    entry = LedgerEntry(...)
    sql_param_count = len(re.findall(r'\$\d+', _INSERT_SQL))
    assert len(entry._to_row()) == sql_param_count
```

### Pattern 3: RLock wrapping module-level singleton

**What:** Wrap both `_settings_singleton` init and `_active_contracts_cache` check-then-set in a single `threading.RLock`. Same lock protects all three globals.

```python
import threading

_settings_lock = threading.RLock()
_settings_singleton: Settings | None = None
_active_contracts_cache: list[Instrument] | None = None
_active_contracts_last_refresh: float = 0.0

def _default_settings() -> Settings:
    global _settings_singleton  # noqa: PLW0603
    with _settings_lock:
        if _settings_singleton is None:
            _settings_singleton = Settings()
        return _settings_singleton

def get_active_contracts(settings: Settings | None = None) -> list[Instrument]:
    global _active_contracts_cache, _active_contracts_last_refresh  # noqa: PLW0603
    with _settings_lock:
        now = time.monotonic()
        cache_age = now - _active_contracts_last_refresh
        if _active_contracts_cache is not None and cache_age < _ACTIVE_CONTRACTS_TTL:
            return _active_contracts_cache
    # ... build result outside lock (DB query can be slow) ...
    with _settings_lock:
        _active_contracts_cache = result
        _active_contracts_last_refresh = now
    return result
```

**NOTE:** `get_active_contracts()` should acquire the lock for the check, release it for the DB query (which can be slow), then re-acquire to write. This avoids holding the lock during the DB query while still making each individual check-then-set atomic.

### Anti-Patterns to Avoid

- **Hardcoding 67 in test:** `test_pipeline_attribution.py:95` currently hardcodes `assert len(params) == 67`. The new guard test must NOT repeat this pattern - use `re.findall(r'\$\d+', _INSERT_SQL)` instead.
- **Re-adding asyncio locks to CacheManager:** Locks at `cache_manager.py:131-133` already exist. Adding them again creates duplicate lock objects that won't actually protect shared state.
- **Making `snapshot()` async:** `snapshot()` is intentionally sync - converting it to `async def` would break its asyncio non-preemptability invariant and all callers.
- **Using threading.Lock (non-reentrant):** `_default_settings()` may be called from within Pydantic validators during `Settings()` construction. A plain `Lock` would deadlock on re-entry; `RLock` is required.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| SQL param count validation | Hardcoded constant | `re.findall(r'\$\d+', _INSERT_SQL)` | Self-maintaining as columns are added |
| Thread safety for module globals | Custom boolean flag | `threading.RLock` | Handles re-entrant calls from validators |
| Async cache protection | Custom sentinel pattern | `asyncio.Lock` already in `cache_manager.py` | Already correct - do not re-add |

## Common Pitfalls

### Pitfall 1: Tuple element count mismatch between code and docs

**What goes wrong:** CONTEXT.md and the existing docstring say "65-element tuple" but code verification shows `$1..$67` in `_INSERT_SQL` and 67 `self.*` references in `to_insert_params()`. The test at `test_pipeline_attribution.py:95` correctly asserts `len(params) == 67`.

**Why it happens:** Two columns (`is_backfill`, `ttl_bars`) were added after the docstring was written; docs weren't updated.

**How to avoid:** The `_to_row()` docstring must say "67-element tuple". The dynamic test catches future count drift automatically.

**Warning signs:** Docstring count != `re.findall(r'\$\d+', _INSERT_SQL)` count.

### Pitfall 2: Holding RLock during DB query in `get_active_contracts()`

**What goes wrong:** If the entire `get_active_contracts()` function body is wrapped in a single `with _settings_lock:` block, the lock is held during the `psycopg2.connect()` + `cur.execute()` call. This blocks all other threads (including plugin threads trying to read settings) for the duration of the DB query.

**Why it happens:** Naive lock-everything approach.

**How to avoid:** Use double-checked locking: lock for the cache read, release for the DB query, lock again for the cache write. The check-then-build-then-set is idempotent (worst case: two threads both build the cache, second write wins, both return valid data).

**Warning signs:** Slow tests when multiple threads call `get_active_contracts()` concurrently.

### Pitfall 3: `invalidate_active_contracts_cache()` not protected by lock

**What goes wrong:** `invalidate_active_contracts_cache()` sets `_active_contracts_last_refresh = 0.0` without the lock. A thread could be mid-write to `_active_contracts_last_refresh` in `get_active_contracts()` while `invalidate_active_contracts_cache()` writes concurrently.

**Why it happens:** The function wasn't in scope when CONTEXT.md was written.

**How to avoid:** Wrap the `_active_contracts_last_refresh = 0.0` assignment in `invalidate_active_contracts_cache()` with `with _settings_lock:`.

**Warning signs:** Cache is invalidated but TTL check incorrectly uses a half-written timestamp.

### Pitfall 4: Updated call sites missed

**What goes wrong:** `to_insert_params()` is called in three places: `signal_ledger_repository.py:555` (via `insert_signals`), `signal_ledger_repository.py:568` (via `insert_signals_with_features`), and `tests/unit/test_pipeline_attribution.py:94`. Missing any of these causes `AttributeError` at runtime.

**Why it happens:** Text search for `to_insert_params` doesn't surface `_payload_to_ledger_entries` in `signal_writer_agent.py` because that function creates `LedgerEntry` objects but doesn't directly call `to_insert_params` — the repository methods do.

**How to avoid:** Run `grep -rn "to_insert_params" src/ services/ tests/` after the rename to confirm zero remaining references. `signal_writer_agent.py` itself may not need changes (it calls repository methods, which call `_to_row()` internally).

## Code Examples

### Call site inventory (verified by grep)

The following call sites reference `to_insert_params()` and must be updated:

- `src/persistence/repository/signal_ledger_repository.py:555` - `insert_signals()`: `params = [entry.to_insert_params() for entry in entries]`
- `src/persistence/repository/signal_ledger_repository.py:568` - `insert_signals_with_features()`: `await conn.execute(_INSERT_SQL, *entry.to_insert_params())`
- `tests/unit/test_pipeline_attribution.py:94` - `params = entry.to_insert_params()` + `assert len(params) == 67`

`signal_writer_agent.py` calls the repository, not `to_insert_params()` directly — no change needed there.

### Lifecycle SQL queries with >= 5 positional params (LEDGER-02 scope)

These UPDATE statements have >= 5 params and should get field comments per D-03:

- `_UPDATE_STATUS_SQL` (17 params: `$1...$17`) — `signal_ledger_repository.py:409`
- `_RECORD_ACTIVATION_SQL` (5 params: `$1...$5`) — `signal_ledger_repository.py:482`
- `_RECORD_ZONE_RESOLUTION_SQL` (12 params: `$1...$12`) — `signal_ledger_repository.py:492`
- `_RECORD_MARKET_RESOLUTION_SQL` (10 params: `$1...$10`) — `signal_ledger_repository.py:508`
- `_RECORD_ZONE_WITH_ACTIVATION_SQL` (16 params: `$1...$16`) — `signal_ledger_repository.py:524`

LEDGER-02 requires field-name comments on the Python call sites that pass params to these SQL queries, not changes to the SQL itself. The SQL already has column names in the `SET col = $N` syntax, so the SQL is self-documenting. The Python call sites passing positional args to `execute_command()` or `execute()` are where comments add value.

### `invalidate_active_contracts_cache()` lock pattern

```python
def invalidate_active_contracts_cache() -> None:
    """Force next get_active_contracts() call to re-query the database."""
    global _active_contracts_last_refresh  # noqa: PLW0603
    with _settings_lock:
        _active_contracts_last_refresh = 0.0
```

## State of the Art

| Old Approach | Current Approach | Notes |
|--------------|------------------|-------|
| `to_insert_params()` — public, no field comments, docstring says 65 | `_to_row()` — private (underscore), all 67 fields annotated with `# $N field_name` | Pure rename + documentation |
| Naked module globals in settings.py | `threading.RLock` wrapping all three globals | Standard Python idiom for singleton pattern in threaded code |
| CacheManager caches unprotected | asyncio.Lock per cache (shipped Phase 089) | Already done; do not revisit |

## Open Questions

1. **Double-checked locking vs single lock scope for `get_active_contracts()`**
   - What we know: the DB query can be slow (psycopg2 connect + execute). Holding the lock during the query blocks plugin threads.
   - What's unclear: CONTEXT.md D-07 says "wrap in `_settings_lock`" but does not specify whether to release during the DB query.
   - Recommendation: Use double-checked locking pattern (check under lock, build outside lock, write under lock). This is safe because the build is idempotent and the window for duplicate builds is negligible at service startup.

2. **`test_pipeline_attribution.py:95` hardcoded count**
   - What we know: The existing test asserts `len(params) == 67` with a hardcoded literal. After the rename, the test must call `entry._to_row()` instead of `entry.to_insert_params()`.
   - What's unclear: Should the hardcoded `67` be replaced with the dynamic `re.findall` pattern here too, or only in the new guard test in `test_signal_ledger_repository.py`?
   - Recommendation: Replace the hardcoded `67` with the dynamic count in `test_pipeline_attribution.py` as well. Consistency across the fleet is the Renaissance principle. The dynamic pattern is 2 lines and has zero maintenance cost.

## Sources

### Primary (HIGH confidence)
- Direct code inspection of `src/persistence/repository/signal_ledger_repository.py` - verified 67-element tuple, all call sites, all lifecycle SQL
- Direct code inspection of `src/config/settings.py:946-970, 1059-1099` - verified race conditions in `_default_settings()` and `get_active_contracts()`
- Direct code inspection of `src/intelligence/pipeline/cache_manager.py:131-133` - verified Phase 089 locks already in place
- Direct code inspection of `services/feature_writer_agent.py:158-203` - fleet reference pattern confirmed
- Direct code inspection of `tests/unit/test_pipeline_attribution.py:94-97` - confirmed call site and hardcoded 67
- Direct code inspection of `tests/unit/test_signal_ledger_repository.py` - confirmed gap (no tuple-count test exists)
- `.planning/phases/090-signal-ledger-thread-safety/090-CONTEXT.md` - all decisions D-01 through D-11 confirmed

### Secondary (MEDIUM confidence)
- Python stdlib `threading.RLock` docs - RLock re-entrancy semantics are well-established; not requiring external verification

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - stdlib only, no external dependencies
- Architecture (Plan 01 - rename): HIGH - exact call sites verified by code inspection
- Architecture (Plan 02 - RLock): HIGH - race conditions verified by code inspection; RLock pattern is idiomatic Python
- Pitfalls: HIGH - derived from direct code reading, not inference

**Research date:** 2026-05-19
**Valid until:** This research is tied to specific line numbers; valid as long as the files haven't been modified. Re-verify line numbers before execution if any other phase touches these files.
