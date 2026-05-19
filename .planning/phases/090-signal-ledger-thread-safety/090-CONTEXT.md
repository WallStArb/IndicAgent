# Phase 090: Signal Ledger Hardening + Thread Safety - Context

**Gathered:** 2026-05-19 (updated)
**Status:** Ready for planning

<domain>
## Phase Boundary

Two correctness items that compound post-Phase-089:

1. **Signal ledger named params**: `LedgerEntry.to_insert_params()` returns a 65-element positional tuple — the highest-volume writer and the one Phase 085 PERSIST-05 skipped. Every v2.7 lane adds signal fields; the tuple is a maintenance trap. Replace with `_to_row()` named-field helper consistent with the fleet pattern. Add a tuple-count guard test that validates `len(_to_row())` against `_INSERT_SQL` dynamically — no hardcoded constants.

2. **Thread safety - settings.py only**: `_settings_singleton`, `_active_contracts_cache`, and `_active_contracts_last_refresh` in `settings.py` are naked module-level globals with no synchronization. ThreadPoolExecutor plugin threads and service startup both call `_default_settings()`. Add `_settings_lock = threading.RLock()` and wrap all three globals.

   **NOTE:** CacheManager asyncio locks (THREAD-02) were shipped in Phase 089 — `_cross_asset_lock`, `_macro_lock`, `_htf_intel_lock` are already in `cache_manager.py:131-133` and in use. Do NOT re-implement.

Zero behavior change. Zero signal logic affected.

</domain>

<decisions>
## Implementation Decisions

### Signal Ledger Named Params (LEDGER-01, LEDGER-02)
- **D-01:** `LedgerEntry.to_insert_params()` is renamed to `_to_row()` (underscore = internal helper, not public API). Returns the same tuple but with one field-name comment per position (`# signal_id`, `# timestamp`, ...). Pattern: identical to `feature_writer_agent._record_to_insert_params()` (lines 158-203) — the fleet reference. Follow that file's comment style verbatim.
- **D-02:** All call sites updated: `signal_writer_agent.py` (calls `to_insert_params()` via `_payload_to_ledger_entries()`), `signal_ledger_repository.py` (calls it in `insert_batch()` at line 555 and `insert_one()` at line 568), and `tests/unit/test_pipeline_attribution.py:94` (test call site — must be updated in the same change, not left broken).
- **D-03:** Lifecycle update queries (`UPDATE signal_ledger SET exit_at=$1 ...`) reviewed for positional consistency — add field comments to any raw SQL with >= 5 positional params.
- **D-04:** No schema change, no DB migration. Pure Python rename + comment addition.
- **D-05 (Renaissance guard):** Add `test_to_row_returns_correct_count()` to `tests/unit/test_signal_ledger_repository.py`. The test must count `$N` tokens in `_INSERT_SQL` dynamically (e.g., `len(re.findall(r'\$\d+', _INSERT_SQL))`) and assert it equals `len(entry._to_row())`. No hardcoded 65 — the test is self-maintaining as columns are added. This mirrors `test_record_to_insert_params_returns_31_tuple()` in `test_feature_writer_agent.py` and closes the fleet coverage gap.

### Thread Safety: settings_singleton (THREAD-01)
- **D-06:** Add `_settings_lock = threading.RLock()` at module scope in `settings.py`. Wrap `_settings_singleton` read/write in `_default_settings()` with `with _settings_lock:`. RLock (reentrant) because `_default_settings()` may be called recursively from validators.
- **D-07:** `_active_contracts_cache` and `_active_contracts_last_refresh` globals also protected by `_settings_lock` — same lock, same scope. The check-then-set pattern (`if _active_contracts_cache is not None and cache_age < TTL: return cache`) is a read-modify-write race; the lock makes it atomic.
- **D-08:** No removal of `_active_contracts_cache` globals in this phase — that's a future CacheManager migration. Lock them as-is.

### Thread Safety: CacheManager pipeline caches (THREAD-02) — ALREADY DONE
- **D-09 (status):** `asyncio.Lock()` for `_cross_asset_cache`, `_macro_cache`, and `_htf_intel` was shipped in Phase 089. Locks exist at `cache_manager.py:131-133` and are used at lines 208, 214, 220. Plan 02 must NOT re-add these.
- **D-10 (intentional lock-free reads):** `CacheManager.snapshot()` reads the three caches WITHOUT locks — this is correct and intentional. `snapshot()` is a synchronous `def` (not `async def`), so in asyncio's single-threaded event loop it cannot be preempted by another coroutine mid-read. The planner must add a comment to `snapshot()` explaining this invariant so a future engineer doesn't "fix" it by asyncifying it and breaking the sync contract. Comment: `# sync method — cannot be preempted in asyncio event loop; lock-free reads are safe`.

### Plan Structure
- **D-11:** Two plans, wave 1 (parallel):
  - Plan 01: Signal ledger `_to_row()` refactor (touches `signal_ledger_repository.py`, `signal_writer_agent.py`, `test_pipeline_attribution.py`, `test_signal_ledger_repository.py`)
  - Plan 02: Thread safety - settings.py only (touches `settings.py`; optionally adds snapshot() comment to `cache_manager.py`)
  Plans are independent — different files, same wave.

### Claude's Discretion
- Exact comment style for positional params in `_to_row()` — follow `feature_writer_agent._record_to_insert_params()` verbatim, no deviation
- Whether to add `snapshot()` comment in Plan 01 or Plan 02 (either is fine; Plan 02 is slightly more natural since it covers CacheManager awareness)
- Import placement for `re` in the test (standard library, top of test file)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Signal Ledger — rename target
- `src/persistence/repository/signal_ledger_repository.py:154` — `to_insert_params()` 65-element tuple; full field list to comment; `_INSERT_SQL` at :240 for dynamic count in test
- `services/signal_writer_agent.py:156` — `_payload_to_ledger_entries()` which builds LedgerEntry objects; calls `to_insert_params()`
- `tests/unit/test_pipeline_attribution.py:94` — call site that uses `to_insert_params()`; MUST be updated in Plan 01

### Fleet reference pattern
- `services/feature_writer_agent.py:158-203` — `_record_to_insert_params()` — fleet reference for named-field helper pattern; follow comment style verbatim
- `tests/unit/service_tests/test_feature_writer_agent.py:133` — `test_record_to_insert_params_returns_31_tuple()` — fleet test reference; replicate pattern (with dynamic `_INSERT_SQL` count) in `test_signal_ledger_repository.py`

### Thread safety — settings.py
- `src/config/settings.py:946-970` — `_settings_singleton`, `_active_contracts_cache`, `_active_contracts_last_refresh`, `_default_settings()` — RLock target; all three globals get the same lock
- `src/config/settings.py:1059-1099` — `get_active_contracts()` — reads/writes `_active_contracts_cache` and `_active_contracts_last_refresh`; wrap in `_settings_lock`

### CacheManager — already done, read for awareness
- `src/intelligence/pipeline/cache_manager.py:131-133` — locks already in place; do not re-add
- `src/intelligence/pipeline/cache_manager.py:228` — `snapshot()` sync method; add comment per D-10

### Phase context
- `.planning/REQUIREMENTS.md` §LEDGER-01, LEDGER-02, THREAD-01, THREAD-02
- `.planning/phases/085-persistence-writer-migration/085-PATTERNS.md` — PERSIST-05 named-param pattern documentation

</canonical_refs>

<code_context>
## Existing Code Insights

### Signal Ledger
- `to_insert_params()` has partial inline comments (`# $40`, `# $47::jsonb`) — partially documented. `_to_row()` completes this with field-name comments per position for ALL 65.
- `_INSERT_SQL` uses `$1..$65` positional params — asyncpg constraint, not removable. Goal is readable Python mapping, not SQL change.
- `LedgerEntry` is a `@dataclass` — `_to_row()` maps `self.field_name` → positional index explicitly.
- No existing test in `test_signal_ledger_repository.py` validates the 65-element count — this is the gap vs the fleet standard.

### Thread Safety — settings.py
- `_default_settings()` is synchronous; called from service startup (main thread), plugin threads (ThreadPoolExecutor), and test setup. RLock is correct (allows same-thread re-entry).
- Check-then-set in `get_active_contracts()` (line 1065-1067) is the primary race: two threads can both see `_active_contracts_cache is None` and both build the cache. Benign for correctness (idempotent) but `_active_contracts_last_refresh` write is a separate operation, creating a torn-write window. Lock closes this.

### CacheManager (reference only — already correct)
- Writes are locked: `update_cross_asset()`, `update_macro()`, `update_htf_intel()` all use `async with self._X_lock:`.
- `snapshot()` is sync (`def`, not `async def`) — cannot yield in asyncio, so dict reads are non-preemptible. Lock-free is correct by the asyncio execution model, not by accident.

</code_context>

<specifics>
- "Correctness before scale" — thread races are deterministic at low concurrency, non-deterministic at high concurrency. Fix before PERF-07 ships, not after an intermittent data corruption is observed in production.
- "Instrument everything, automate everything" (Jim Simons / Renaissance principle): the tuple-count test must be self-maintaining — parse `_INSERT_SQL` dynamically rather than hardcoding 65. If column 66 ships without updating `_to_row()`, the test fails automatically, no human counting required.
- "Fleet consistency" — 085 established the named-param pattern; 090 applies it to the one writer that was skipped. Every writer in the fleet uses `_to_row()` or equivalent after this phase.
- "No manual tasks" — the test is the automation. No human needs to count SQL columns vs Python fields.

</specifics>

<deferred>
- Full asyncpg named-parameter support (asyncpg uses $N positional — named params would require a custom wrapper; not worth the complexity)
- Signal ledger schema reduction (removing unused columns requires data migration; deferred to v2.7 cleanup)
- Removal of `_active_contracts_cache` globals from settings.py (deferred to the CacheManager migration phase)
- Observability metric for `_settings_lock` contention (lock is uncontested > 99.9% of the time at startup; overhead not worth instrumenting given the "balance efficiency with simplicity" principle)

</deferred>

---
*Phase: 090-signal-ledger-thread-safety*
*Context gathered: 2026-05-19*
