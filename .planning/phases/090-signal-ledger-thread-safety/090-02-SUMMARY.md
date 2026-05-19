---
phase: 090-signal-ledger-thread-safety
plan: "02"
subsystem: config/settings
tags: [thread-safety, rlock, singleton, double-checked-locking, testing]
dependency_graph:
  requires: []
  provides: [THREAD-01, THREAD-02-docs]
  affects: [src/config/settings.py, src/intelligence/pipeline/cache_manager.py]
tech_stack:
  added: [threading.RLock]
  patterns: [double-checked-locking, sync-method-invariant-comment]
key_files:
  created:
    - tests/unit/test_settings_thread_safety.py
  modified:
    - src/config/settings.py
    - src/intelligence/pipeline/cache_manager.py
decisions:
  - "Used threading.RLock (not Lock) per D-06 - reentrant to handle potential validator callbacks during Settings() construction"
  - "Double-checked locking in get_active_contracts: two separate with _settings_lock: blocks with DB query running outside the lock (Pitfall 2)"
  - "Used single hyphen in snapshot() comment per CLAUDE.md no-em-dash rule (fallback from plan's em-dash suggestion)"
metrics:
  duration_minutes: 15
  completed_date: "2026-05-19"
  tasks_completed: 3
  files_modified: 3
---

# Phase 090 Plan 02: Thread Safety - settings.py + CacheManager.snapshot() Summary

Added `threading.RLock` protection to three naked module-level globals in `settings.py` (`_settings_singleton`, `_active_contracts_cache`, `_active_contracts_last_refresh`) using double-checked locking, and documented the asyncio non-preemptibility invariant in `CacheManager.snapshot()`.

## What Was Done

### Task 1: settings.py RLock protection (commit 83a5ef93)

**Lock variable:** `_settings_lock = threading.RLock()` added at module scope, immediately above `_settings_singleton` declaration (~line 947).

**Four `with _settings_lock:` sites:**

1. `_default_settings()` - wraps the entire `if _settings_singleton is None: _settings_singleton = Settings()` block. RLock used (not plain Lock) because `_default_settings()` may be called from within Pydantic validators during `Settings()` construction. Docstring documents the Phase 090 verification that no recursive call chain exists.

2. `get_active_contracts()` - first block (read): checks `_active_contracts_cache` and `_active_contracts_last_refresh`, returns early on cache hit. Lock released before DB query.

3. `get_active_contracts()` - second block (write): assigns `_active_contracts_cache = result` and `_active_contracts_last_refresh = now` after the DB query completes. The two separate blocks confirm the DB query (psycopg2 connect + execute) runs entirely outside the lock per Pitfall 2.

4. `invalidate_active_contracts_cache()` - wraps `_active_contracts_last_refresh = 0.0`. Closes Pitfall 3: without this, a concurrent `get_active_contracts()` write could tear with this reset.

**DB query not held under lock:** Confirmed - the comment `# Lock released here — DB query runs without holding the lock (Pitfall 2)` is placed between the two lock blocks.

### Task 2: CacheManager.snapshot() invariant comment (commit 7205f35e)

**Exact comment added** (after the docstring's closing `"""`):
```
# sync method - cannot be preempted in asyncio event loop; lock-free reads are safe
```

Note: CLAUDE.md prohibits em-dash in files; single hyphen used as allowed fallback from the plan's suggested em-dash text.

`snapshot()` remains a synchronous `def` - not changed to `async def`. The lock-free reads are correct because a synchronous method cannot yield control mid-execution in a single-threaded asyncio event loop.

**Phase 089 locks untouched:** `_cross_asset_lock`, `_macro_lock`, and `_htf_intel_lock` (asyncio.Lock objects at lines 131-133) are unchanged.

### Task 3: Unit tests (commit 975955af)

Three tests in `tests/unit/test_settings_thread_safety.py`:

1. `test_default_settings_singleton_under_threads` - spawns 16 threads via `ThreadPoolExecutor`, each calls `_default_settings()`, asserts all 16 return `id()` values are identical. GIL caveat documented in docstring: this is primarily a structural correctness check; source assertions in tests 2 and 3 are the primary guarantee.

2. `test_invalidate_active_contracts_cache_is_lock_protected` - source-string assertion: `"with _settings_lock:" in inspect.getsource(invalidate_active_contracts_cache)`.

3. `test_get_active_contracts_uses_double_checked_locking` - source-string assertion: `src.count("with _settings_lock:") == 2` confirms exactly two lock blocks (read + write) in `get_active_contracts`.

All three tests pass.

## Verification Results

```
pytest tests/unit/test_settings_thread_safety.py -v
  test_default_settings_singleton_under_threads    PASSED
  test_invalidate_active_contracts_cache_is_lock_protected  PASSED
  test_get_active_contracts_uses_double_checked_locking     PASSED

pytest tests/unit/ -q -k "settings or cache_manager"
  72 passed in 5.69s

grep -c "with _settings_lock:" src/config/settings.py    -> 4
grep -c "cannot be preempted" cache_manager.py           -> 1
grep -c "asyncio.Lock()" cache_manager.py                -> 3  (Phase 089 locks intact)
grep -c "async def snapshot" cache_manager.py            -> 0  (snapshot remains sync)
```

## Deviations from Plan

None - plan executed exactly as written. The `.venv` symlink was created in the worktree to satisfy the pre-commit hook's tool discovery (worktree-specific setup, not a code deviation).

## Self-Check

All committed files exist:
- `src/config/settings.py` - modified (commit 83a5ef93)
- `src/intelligence/pipeline/cache_manager.py` - modified (commit 7205f35e)
- `tests/unit/test_settings_thread_safety.py` - created (commit 975955af)

All commits exist in git log:
- 83a5ef93 feat(090-02): add threading.RLock protection to settings.py module globals
- 7205f35e docs(090-02): add asyncio sync-invariant comment to CacheManager.snapshot()
- 975955af test(090-02): add concurrent-callers thread safety tests for settings.py

## Self-Check: PASSED
