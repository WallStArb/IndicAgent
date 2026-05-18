# Phase 091: Signal Ledger Hardening + Thread Safety - Context

**Gathered:** 2026-05-18
**Status:** Ready for planning

<domain>
## Phase Boundary

Two correctness items that compound post-Phase-089:

1. **Signal ledger named params**: `LedgerEntry.to_insert_params()` returns a 65-element positional tuple — the highest-volume writer and the one Phase 085 PERSIST-05 skipped. Every v2.7 lane adds signal fields; the tuple is a maintenance trap. Replace with `_to_row()` named-field helper consistent with the fleet pattern.

2. **Thread safety**: Module-level caches accessed from concurrent contexts without synchronization. PERF-07's per-key workers make these live races. Two locks needed: `threading.RLock` for `_settings_singleton` (sync + async callers), `asyncio.Lock` for `_cross_asset_cache` / `_macro_cache` (async-only pipeline caches).

Zero behavior change. Zero signal logic affected.

</domain>

<decisions>
## Implementation Decisions

### Signal Ledger Named Params (LEDGER-01, LEDGER-02)
- **D-01:** `LedgerEntry.to_insert_params()` is renamed to `_to_row()` (underscore = internal helper, not public API). Returns the same tuple but with one comment per position (`# signal_id`, `# timestamp`, ...). Pattern: identical to `feature_writer_agent._record_to_insert_params()` (lines 158-203) which is the fleet reference.
- **D-02:** All call sites updated: `signal_writer_agent.py` which calls `to_insert_params()` via `_payload_to_ledger_entries()`. `signal_ledger_repository.py` which calls it in `insert_batch()` and `insert_one()`.
- **D-03:** Lifecycle update queries (`UPDATE signal_ledger SET exit_at=$1, outcome=$2 ... WHERE signal_id=$N`) reviewed for positional consistency — add field comments to any raw SQL with ≥5 positional params.
- **D-04:** No schema change, no DB migration. Pure Python rename + comment addition.

### Thread Safety: settings_singleton (THREAD-01)
- **D-05:** Add `_settings_lock = threading.RLock()` at module scope in `settings.py`. Wrap the `_settings_singleton` read/write in `_default_settings()` with `with _settings_lock:`. RLock (reentrant) because `_default_settings()` may be called recursively from validators.
- **D-06:** `get_active_contracts()` currently calls `_default_settings()` which accesses `_settings_singleton`. After Phase 090 ships, `get_active_contracts()` reads from CacheManager directly — but the RLock fix is needed regardless because settings.py is still used for infra config from ThreadPoolExecutor plugin threads.
- **D-07:** `_active_contracts_cache` and `_active_contracts_last_refresh` globals in settings.py: also protected by `_settings_lock` for the interim period before Phase 090 CacheManager takes over. After Phase 090, these globals are removed.

### Thread Safety: pipeline caches (THREAD-02)
- **D-08:** `_cross_asset_cache: dict` and `_macro_cache: dict` in `IntelligencePipelineComputeAgent` (post-088: in `CacheManager`) are updated from the Kafka consumer coroutine (async) and read from the I1-I7 compute path. After PERF-07 launches per-key workers (multiple concurrent coroutines), these are live data races.
- **D-09:** Add `_cross_asset_lock = asyncio.Lock()` and `_macro_lock = asyncio.Lock()` to `CacheManager`. Wrap all reads with `async with self._cross_asset_lock:` / `async with self._macro_lock:` — brief critical sections (dict read/write only). Writes are already atomic dict replacement (consistent with D-11 in 088 context), reads get snapshot consistency.
- **D-10:** Lock acquisition is per-read/write, not per-bar. Lock contention is negligible for infrequent cross-asset/macro updates vs per-bar reads.

### Plan Structure
- **D-11:** Two plans, wave 1 (parallel):
  - Plan 01: Signal ledger `_to_row()` refactor (touches `signal_ledger_repository.py`, `signal_writer_agent.py`)
  - Plan 02: Thread safety locks (touches `settings.py`, `CacheManager` post-088)
  Plans are independent — different files, same wave.

### Claude's Discretion
- Whether to rename `to_insert_params` → `_to_row` in one commit or add `_to_row` first and deprecate `to_insert_params` (prefer direct rename — no callers outside this codebase)
- Exact comment style for positional params in `_to_row()` (follow feature_writer_agent verbatim)

</decisions>

<canonical_refs>
## Canonical References

- `src/persistence/repository/signal_ledger_repository.py:154` — `to_insert_params()` 65-element tuple; full field list to comment
- `services/signal_writer_agent.py:156` — `_payload_to_ledger_entries()` which builds LedgerEntry objects
- `services/feature_writer_agent.py:158-203` — `_record_to_insert_params()` — fleet reference for named-field helper pattern
- `src/config/settings.py:931-955` — `_settings_singleton`, `_default_settings()` — RLock target
- `services/intelligence_pipeline_agent.py:442-443` — `_cross_asset_cache`, `_macro_cache` — asyncio.Lock target (post-088: in CacheManager)
- `.planning/phases/085-persistence-writer-migration/085-PATTERNS.md` — PERSIST-05 named-param pattern documentation
- `.planning/REQUIREMENTS.md` §LEDGER-01, LEDGER-02, THREAD-01, THREAD-02

</canonical_refs>

<code_context>
## Existing Code Insights

### Signal Ledger
- `to_insert_params()` has inline comments `# $40`, `# $47::jsonb` etc — already partially documented. `_to_row()` completes this with field-name comments per position.
- `_INSERT_SQL` in signal_ledger_repository.py uses `$1..$65` positional params — asyncpg constraint, not removable. The goal is readable Python mapping, not SQL change.
- `LedgerEntry` is a `@dataclass` — `_to_row()` maps `self.field_name` → positional index explicitly.

### Thread Safety
- `_default_settings()` is synchronous; called from service startup (main thread), plugin threads (ThreadPoolExecutor), and test setup. RLock is correct (allows same-thread re-entry).
- `_cross_asset_cache` updates come from a Kafka consumer coroutine `_consume_cross_asset()` at line 797 — async context only. asyncio.Lock is correct (no threading.Lock needed for async-only access).
- Per PERF-07 (Phase 089): per-key workers are asyncio.Tasks, not threads. They share the same event loop. asyncio.Lock prevents concurrent coroutine access, threading.Lock would deadlock here.

</code_context>

<specifics>
- "Consistency" — 085 established the fleet pattern; 091 applies it to the one writer that was skipped. Every writer in the fleet uses `_to_row()` or equivalent after this phase.
- "Correctness before scale" — thread races are deterministic at low concurrency, non-deterministic at high concurrency. Fix before PERF-07 ships, not after an intermittent data corruption is observed in production.
</specifics>

<deferred>
- Full asyncpg named-parameter support (asyncpg uses $N positional — named params would require a custom wrapper; not worth the complexity)
- Signal ledger schema reduction (removing unused columns requires data migration; deferred to v2.7 cleanup)
</deferred>

---
*Phase: 091-signal-ledger-thread-safety*
*Context gathered: 2026-05-18*
