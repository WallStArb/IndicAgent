# Codebase Concerns

**Analysis Date:** 2026-03-11

## Executive Summary

IndicAgent v1.7 is structurally sound (1503 tests passing, plugin system mature, data pipeline stable) but carries **accumulated technical debt from rapid feature velocity**: 139 ruff errors (mostly fixable), hard-coded signal status strings (error-prone), infrastructure blocking data repair (PostgreSQL memory issue), and several fragile patterns in service initialization. None are critical, but collectively they represent operational risk and maintainability drag.

---

## Ruff Linting Debt

**Priority:** Medium (code quality)
**Impact:** None (runtime), but adds noise to CI/CD and hides real issues in output

**Current Status:**
- 89 E501 errors (line too long >100 chars) across production code
- 41 are auto-fixable with `--fix` flag
- Mostly in `production/scripts/historical_backfill.py` (34 errors concentrated here)

**Files Most Affected:**
- `production/scripts/historical_backfill.py` (34 E501) — docstrings and help text exceeding 100 chars
- Scattered across `src/` and `services/` (remaining 55)

**Action:** Run `.venv/bin/ruff check . --fix` to auto-fix. For remaining docstring overflows, split long lines in docstrings or wrap help text manually.

**Follow-up:** Add pre-commit hook check to prevent new E501 errors from landing.

---

## Signal Status Strings — No Enum, Raw Literals Everywhere

**Priority:** High (error-prone, scattered)
**Impact:** Silent bugs if any service forgets a status value; refactoring nightmares; no IDE autocomplete

**Current State:**
Signal status is represented as raw string literals across **5 files**:
- `src/intelligence/trading/signal_ledger.py` — `status: str = "pending"`
- `src/intelligence/trading/lifecycle_tracker.py` — two string comparisons `if status == "pending"`
- `services/signal_generator_service.py` — assignment `entry_status = "pending" if ... else "regime_suppressed"`
- `services/signal_lifecycle_service.py` — 4 status comparisons spread across activation + lifecycle logic

**Valid Statuses:** `"pending"`, `"active"`, `"regime_suppressed"` (no others currently)

**Risk:**
1. Typo in any status string is silent — comparison fails, signal quietly skipped
2. Adding a fourth status requires changes across all 5 files with high error risk
3. No IDE autocomplete — developers must remember the three strings
4. Lifecycle state machine is implicit (hardcoded in if/else chains) instead of explicit

**Fix Approach:**
1. Create `src/intelligence/trading/signal_status.py` with Python enum:
   ```python
   from enum import Enum

   class SignalStatus(Enum):
       PENDING = "pending"
       ACTIVE = "active"
       REGIME_SUPPRESSED = "regime_suppressed"
   ```
2. Update all files to use `SignalStatus.PENDING` instead of `"pending"`
3. Update DB schema migration to include CHECK constraint on status values
4. Add to `.planning/todos/pending/` as v1.8 cleanup task

---

## Sequential Stream Polling in `feature_writer_service`

**Priority:** Medium (performance, documented)
**Impact:** 5-10ms latency per stream × 92 streams = worst-case ~920ms lag before feature write

**Current Behavior:**
`feature_writer_service._base_process_loop()` at line 494+ reads from intelligence: streams via `xreadgroup`. However, the service consumes **I7 and I8 enrichment streams separately** in subsequent async tasks:
- `_process_loop()` — reads intelligence: streams (base features)
- `_enrich_i7_loop()` — reads intelligence_i7: streams (separate consumer group)
- `_enrich_i8_loop()` — reads intelligence_i8: streams (separate consumer group)

Each loop blocks independently (default 100ms block per stream). If I7/I8 data arrives out of sync with base intelligence features, rows can be written without enrichment, then upserted later.

**Better Pattern (proven in `market_analysis_service`):**
Single `xreadgroup` call with dict of all streams:
```python
all_streams = {name: ">" for name in self._stream_map}
messages = await self.redis_client.xreadgroup(
    group, consumer, all_streams, count=10, block=1000
)
```

**Todo Exists:**
`.planning/todos/pending/2026-02-24-fix-sequential-stream-polling-in-feature-writer-service.md` (not yet tackled)

**Recommendation:**
Refactor to single `xreadgroup` after v1.7 ships. Low urgency — current batch flush model absorbs latency well. Flag for v1.8.

---

## Service Test Pattern — Manual `__new__` Attribute Synchronization

**Priority:** Medium (fragile test maintenance)
**Impact:** Test bugs if service `__init__` is modified without updating all test fixtures

**Current Pattern:**
Unit tests in `tests/unit/service_tests/` and `tests/unit/services/` use `ServiceClass.__new__(ServiceClass)` to bypass `__init__`, avoiding full service initialization:

```python
svc = IndicatorService.__new__(IndicatorService)
svc.bar_history = defaultdict(OrderedDict)
svc._bar_history_max = 5
svc._plugin_cache = {}
svc._i1_plugin_states = {}
# ... manually set 8-10 more attributes
```

**Problem:**
When `__init__` adds a new instance attribute (e.g., `self._new_field = ...`), **tests silently fail** if the test fixture doesn't set it. The error is indirect: `AttributeError: 'IndicatorService' object has no attribute '_new_field'` appears deep in a method, not at setup.

**Examples (already affected):**
- `tests/unit/service_tests/test_concurrent_lock_behavior.py` — 4 test functions manually set `_*_locks` dicts
- `tests/unit/service_tests/test_feature_writer_service.py` — manually sets logger, config
- `tests/unit/test_indicator_service_warmup.py` — manually sets config, bar_history, plugin fields

**Safer Alternative:**
1. Extract init logic into a `_init_attributes()` method, call from both `__init__` and test fixture builder
2. Or create a `ServiceTestFactory` helper that mimics `__init__` setup without async/Redis/DB calls
3. Add a test that verifies the two paths stay in sync

**Recommendation:**
Document the risk in code comments. Create a pattern guide in `src/core/service_utils.py` for safe test fixtures. Flagged for v1.8+ refactor.

---

## CIS Data Repair Blocked by PostgreSQL Shared Memory Issue

**Priority:** High (data quality, infrastructure)
**Impact:** 1,863,228 NULL `cis_score` rows in `signal_ledger` cannot be repaired; ML training data incomplete

**Situation:**
Phase 25 (CIS Data Repair) code is **complete and tested** (11 tests passing):
- `production/scripts/repair_cis_nulls.py` — audit + repair script
- `tests/unit/scripts/test_repair_cis_nulls.py` — TDD test suite

**However:** Running the audit query on the 1.8M NULL rows causes PostgreSQL to crash:
```
psycopg2.errors.DiskFull: could not resize shared memory segment
```

Error is misleading — not actually a disk space issue. Root cause is PostgreSQL shared memory segment allocation when processing large result sets. Multiple mitigation attempts:
- Increased `work_mem` from 6MB → 256MB
- Tested `shared_buffers` at 16GB → 4GB
- Added table aliases to prevent ambiguous columns
- Batch fetching with `fetchmany(1000)` to reduce per-iteration memory

**Code Status:**
- Backfill fix committed: `15297a4` — `historical_backfill.py` now passes `features=` kwarg, CIS fields will populate for future backfill runs
- Repair script code committed; ready to run once PostgreSQL issue resolved

**Data Debt:**
- **Backfill-able rows:** ~1.8M — can recover if PostgreSQL memory can be tuned
- **Orphaned rows:** Unknown count — rows with NULL `cis_score` and NO matching `intelligence_features` row (lost to gaps)

**Resolution Path:**
1. Docker PostgreSQL container memory constraints (cgroup limits) — check `docker inspect timescaledb | grep -i memory`
2. PostgreSQL config tunables (`max_locks_per_transaction` already raised to 16384 on 2026-03-07)
3. Consider split the repair into multiple smaller transactions (symbol-by-symbol)
4. Last resort: manual DELETE of orphaned rows, then VACUUM

**Temporary Workaround:** Future backfill runs will populate CIS fields correctly. Over time, as live signals accumulate, the problem becomes less severe (only old historical signals remain affected).

---

## Consumer Group Silent Failure Pattern

**Priority:** Medium (operational)
**Impact:** After service restart, if consumer group exists, `xgroup_create(..., "$")` silently fails → service processes entire backlog instead of starting at latest

**Pattern:**
```python
try:
    await redis_client.xgroup_create(stream, group, "$")
except redis.ResponseError:
    pass  # Group already exists
```

**Problem:**
When the group exists, Redis silently returns error, group position is NOT reset, and service begins consuming from wherever it left off. If the service was stopped for hours, it could replay 100+ backlog messages.

**Mitigation Deployed:**
Commit `137fcc7` (2026-02-28) added the proper fix in `src/core/stream_utils.py`:
```python
async def ensure_consumer_group_with_reset(redis_client, stream, group):
    try:
        await redis_client.xgroup_create(stream, group, "$")
    except redis.ResponseError:
        # Group exists — force reset to "$" (latest)
        await redis_client.xgroup_setid(stream, group, "$")
```

**Current Status:**
✅ Fixed across all services:
- `indicator_service.py` — uses `ensure_consumer_group_with_reset`
- `signal_generator_service.py` — uses `ensure_consumer_group_with_reset`
- `market_analysis_service.py` — uses `ensure_consumer_group_with_reset`
- `feature_writer_service.py` — uses `ensure_consumer_group_with_reset`

**No action needed** — pattern is already fixed. Document as a "gotcha" in service development guide.

---

## Aggregator Must Derive `active` from `all_ranked`, Not Raw `signals`

**Priority:** High (correctness, subtle bug risk)
**Impact:** If `active` is derived from raw `signals` instead of `all_ranked`, the performance weighting system (`perf_multiplier`) silently has zero effect on winner selection

**Current Correctness:**
`src/intelligence/trading/aggregator.py` correctly derives `active` from `all_ranked`:
```python
all_ranked = _build_all_ranked(...)  # Applies perf_multiplier
active = [s for s in all_ranked if s.get("regime_eligible", True)]
```

**Risk Area:**
If someone adds a new aggregation mode or modifies winner selection logic, they might mistakenly use:
```python
# WRONG:
active = [s for s in signals if s.get("regime_eligible", True)]
# RIGHT:
active = [s for s in all_ranked if s.get("regime_eligible", True)]
```

**Gotcha Details:**
- `_build_all_ranked()` copies signal dicts and adds `adjusted_rank` field
- Raw `signals` list is never modified — `perf_weights` are only applied during the copy
- The bug is silent: signals still fire, just with wrong priority

**Mitigation:**
1. Add a comment in `aggregator.py` at the `active` derivation point:
   ```python
   # CRITICAL: Always derive active from all_ranked, NOT raw signals
   # all_ranked applies perf_multiplier weighting; raw signals don't have adjusted_rank
   ```
2. Add assertion in tests: verify that `active[0].get("adjusted_rank")` exists and matches `all_ranked[0]`
3. Document in `src/intelligence/CLAUDE.md` under Gotchas section (already partially done)

**Status:** ✅ Currently correct in code. High risk of regression if refactored.

---

## Missing Cross-TF Confluence Features

**Priority:** Low (feature gap, research-first)
**Impact:** CIS scoring and confluence metrics ignore cross-TF alignment for FVG and Order Blocks

**Current State:**
`src/intelligence/confluence/cross_timeframe.py` has placeholder zeros:
```python
"i6_fvg_tf_alignment": 0.0,   # TODO: FVG overlap across TFs — implement in next pass
"i6_ob_tf_alignment": 0.0,    # TODO: OB confluence across TFs — implement in next pass
```

**What's Needed:**
1. Multi-TF FVG sweep detection (e.g., 1m FVG filled on 5m bar)
2. Multi-TF order block alignment (same level across 1m/5m/15m/1h)
3. Tier 1 priority but deferred to v1.8+ after signal lifecycle closes

**Analysis:**
`.planning/IDEAS.md` and `docs/ideas/i6-confluence-expansion.md` document this. Research phase already complete.

---

## PostgreSQL Transaction Locking Gotcha

**Priority:** Medium (operational knowledge)
**Impact:** Full-table operations (COUNT(*) on 10k-chunk hypertable) can hit `max_locks_per_transaction` limit

**Background:**
`market_data_ohlcv` hypertable has **10,083 chunks** (7-year OHLCV backfill = 1,826 days × 1m bars). Running COUNT(*) or a broad JOIN locks all chunks. Previous value: 512 (too low). Raised to 16384 on 2026-03-07.

**Mitigation Deployed:**
1. `production/scripts/pipeline_reset.py` (_row_count function) — now uses `reltuples` estimate instead of COUNT(*)
2. `production/migrations/022_db_optimization.sql` — raised to 16384

**Gotcha:**
Changes to `max_locks_per_transaction` require PostgreSQL server restart (postmaster setting, not online tunable).

```bash
# How to apply:
ALTER SYSTEM SET max_locks_per_transaction = 16384;
docker compose restart timescaledb
```

**Status:** ✅ Fixed for current infrastructure.

---

## Incomplete LLM Call Tracking

**Priority:** Medium (observability)
**Impact:** Missing cost analysis, error debugging, and model optimization signals

**Current Gaps:**

| Field | Status | Issue |
|-------|--------|-------|
| `tokens_in` / `tokens_out` | Missing | Using word-count proxy; Ollama response has real counts |
| `error_message` | Missing | `succeeded=False` rows have no detail (timeout vs OOM vs bad format) |
| `cis_score`, `entry_zone_low/high` | Columns exist, never filled | Available in signal context but not persisted |
| Retry chain visibility | Missing | Only final winning provider logged; failures silent |
| Request params | Missing | `temperature`, `max_tokens` not logged |

**Files Involved:**
- `services/ai_narrative_service.py` — publish side
- `services/llm_writer_service.py` — insert side
- `src/intelligence/schemas.py` — schema definitions

**Analysis:**
Detailed breakdown in `.planning/todos/pending/2026-03-07-improve-llm-call-tracking.md`

**Implementation Order (easiest first):**
1. Real token counts — Ollama already returns `prompt_eval_count` / `eval_count`
2. Error message on failures — capture exception in except block
3. Fill `cis_score` / zone fields — wire through publish payload
4. Request params — add `temperature`, `max_tokens` to schema

**Recommendation:**
Queue for v1.8+ after Phase 27 ships. Low urgency but high ROI for model tuning.

---

## Dashboard I7 All-Ranked Panel — Missing SSE Route

**Priority:** Medium (feature incomplete)
**Impact:** Cannot display all ranked setups in real time; drill panel only shows active signal

**Current State:**
- SSE streams exist for: indicators, intelligence (I1-I6), signals_aggregated, narratives
- Signal selection model publishes best signal to `signals:SYMBOL:TF:aggregated` (single winner)
- `i7` JSONB in `intelligence_features` contains **all ranked setups** but never streams to client

**Missing Piece:**
No SSE route for full `i7` array (all fired + ranked setups). Would need:
1. New Redis stream: `intelligence_i7_all_ranked:SYMBOL:TF` (or extend existing i7 stream schema)
2. SSE endpoint `/api/sse/intelligence?symbol=ES&timeframe=1m&domain=i7_all_ranked`
3. Dashboard panel rendering all ranked setups with scores/ranks
4. Use-market-stream hook to subscribe and cache

**Analysis:**
Partially planned in Phase 27 (Signal Lifecycle Stream Events) but deferred to post-v1.7. Design doc: `docs/plans/2026-03-06-signal-lifecycle-stream-events-design.md`

**Todo Reference:**
`.planning/todos/pending/2026-03-06-dashboard-intelligence-field-gaps.md` — marked as "LARGELY COMPLETE" but all_ranked panel is the one remaining gap

---

## Dead Database Table — `technical_indicators`

**Priority:** Low (cleanup)
**Impact:** Schema confusion, zero functional impact (table is never written to)

**Evidence:**
- 4 rows, last written Feb 22 – Mar 1
- Zero active services write to it (confirmed via grep of `src/` and `services/`)
- Pipeline uses `intelligence_features` (full JSONB feature vectors) instead

**Cleanup Action:**
1. Confirm via grep: `grep -r "technical_indicators" src/ services/`
2. Write migration `026_drop_technical_indicators.sql`:
   ```sql
   DROP TABLE IF EXISTS public.technical_indicators CASCADE;
   ```
3. Update `docs/guides/database-management.md`

**Todo:**
`.planning/todos/pending/2026-03-06-audit-and-remove-dead-database-tables.md` — scheduled for v1.8

---

## VACUUM Cannot Run Inside Transaction Block

**Priority:** Low (operational knowledge)
**Impact:** Cannot VACUUM inside a PL/pgSQL function or multi-statement transaction

**Pattern:**
```sql
-- WRONG: PostgreSQL error
BEGIN;
VACUUM indicagent;
COMMIT;

-- RIGHT: Standalone command
VACUUM indicagent;
```

**Workaround:**
Run VACUUM directly in psql, or write a shell script that issues separate `psql -c "VACUUM ..."` commands.

**When Needed:**
After large backfill or signal_ledger cleanup migrations to recover bloat.

**Status:** ✅ Documented in `.planning/db-operations.md` memory file. No code changes needed.

---

## Service `__init__` Timing — Health Check Before Redis Ready

**Priority:** Low (race condition, low probability)
**Impact:** Health check endpoint returns 503 if queried before Redis connection succeeds

**Pattern:**
Services start health check server immediately, but Redis connection is async and may not complete instantly:

```python
def __init__(self):
    # Health check server starts here
    start_metrics_server(port=9116)

    # But Redis connection happens in async main()
    async def main(self):
        self.redis_client = await redis.Redis(...).from_url(...)
```

**Risk:**
If a probe hits `/health` before `redis_client` is initialized, checks that depend on Redis return false.

**Current Mitigation:**
Services initialize Redis in `async def run()` before entering main loop. Health check server is started early, but actual health checks verify `self.redis_client is not None`.

**Recommendation:**
Accept as low-priority (race window is <1s at startup). Document in service development guide.

---

## VWAP and Session Plugin Timeframe Guards — Missing

**Priority:** Low (correctness, edge case)
**Impact:** VWAP and session-based indicators may fire on inappropriate timeframes (e.g., 1d)

**Status:**
Todo exists: `.planning/todos/pending/2026-03-10-research-vwap-and-session-plugin-timeframe-guards.md` (not yet researched)

**Issue:**
- VWAP resets at session open; only meaningful on intraday TFs (1m–4h)
- Session context (London open, NY open) less relevant on 1d
- Currently no guards prevent these plugins from running on all TFs

**Research Required:**
Which I1/I4/I5 plugins are sensitive to timeframe? Add explicit `valid_timeframes` attribute or InputSpec constraint.

**Recommendation:**
Queue for v1.8 after all Phase 27 work complete.

---

## Signal Generator Warmup Phase (COMPLETED v1.7)

**Priority:** ✅ Resolved
**Status:** Phase 26 complete — `signal_generator_service` now seeds `bar_history` from `intelligence_features` on startup

**What Was Solved:**
- Previously: 50-min warmup window before signals fire after restart (needed ~120 live 1m bars to warm up)
- Now: DB seed at startup fills bar_history before consuming live stream
- Graceful fallback: if DB unreachable, service logs WARNING and starts normally (falls back to live warmup)

**References:**
- Implementation: `services/signal_generator_service.py._seed_bar_history_from_db()`
- Phase plan: `.planning/milestones/v1.7-phases/26-signal-generator-warmup/`

---

## Missing Broker-Agnostic Instrument Provider

**Priority:** Low (future architecture)
**Impact:** Adding a second broker (e.g., Coinbase, Kraken) requires tight coupling to IBKR code

**Current State:**
All asset/contract logic tightly coupled to IBKR in:
- `src/providers/ibkr.py` — 592 lines, handles all IBKR-specific contract details
- `src/config/settings.py` — hardcoded contract list

**Vision:**
Abstract instrument provider interface:
```python
class InstrumentProvider(Protocol):
    async def subscribe(self, contract: InstrumentSpec) -> AsyncIterator[Tick]:
        ...
    async def fetch_historical_bars(self, contract, start, end, timeframe) -> List[Bar]:
        ...
```

Multiple impls: `IBKRProvider`, `CoinbaseProvider`, etc.

**Status:**
Deferred to v2.0+ (see `.planning/todos/pending/2026-03-07-broker-agnostic-instrument-provider-meta.md`)

---

## Signal Lifecycle Redesign — Complete (v1.7)

**Priority:** ✅ Resolved
**Status:** Fully implemented and live

**What Was Delivered:**
- New `signal_lifecycle_service` — zone-aware signal tracking with MAE/MFE, outcome classification
- 8-class outcome taxonomy: `never_activated`, `stopped_at_entry`, `stopped_in_trade`, `target_1`, `target_1_2`, `target_full`, `ttl_expired_ahead`, `ttl_expired_behind`
- 14 new columns on `signal_ledger` for lifecycle tracking
- Migration `015_signal_lifecycle_fields.sql` applied

**References:**
- Design: `docs/plans/2026-03-03-signal-lifecycle-redesign.md`
- Phase: `.planning/milestones/v1.5-ROADMAP.md` (Phases 18-22)

---

## Test Coverage Gaps

**Priority:** Low (informational)
**Current:** 1503 tests passing

**Known Untested Areas:**
1. **Dashboard SSE reconnection** — reconnect logic in `use-market-stream.ts` is not end-to-end tested
2. **Multi-symbol parallel aggregation** — aggregator tested on single symbol, not concurrent multiple
3. **Service graceful shutdown under load** — SIGINT/SIGTERM handling with pending writes not fully stress-tested
4. **PostgreSQL transaction failures** — retry logic in `database_manager.py` not tested for mid-batch failure
5. **LLM fallback chain** — `llm_providers.py` fallback order tested, but not realistic timeout scenarios

**No action needed** — coverage is solid for core logic. Add targeted tests as issues surface.

---

## Fragile Areas

### 1. Plugin State Write-Back (`market_analysis_service`, `indicator_service`)
**Files:** `services/market_analysis_service.py`, `services/indicator_service.py`
**Why Fragile:** GARCH and HMM plugins fully reassign `_state` dict; must write back after `compute_full()` or changes are lost
**Safe Modification:**
- Never skip the `_plugin_states[key] = p._state` line after plugin computation
- Always swap state onto plugin before calling compute: `p._state = self._plugin_states[key]`
- Add assertion in tests to verify state persists across bars

### 2. Signal Aggregation Logic (`aggregator.py`)
**Files:** `src/intelligence/trading/aggregator.py`
**Why Fragile:** Perf weighting only applies if `active` derives from `all_ranked` (not raw `signals`)
**Safe Modification:**
- Always use `active = [s for s in all_ranked if s.get("regime_eligible", True)]`
- Never use raw `signals` for winner selection
- Add comment explaining why this matters

### 3. TimescaleDB Hypertable Indexes
**Files:** `production/migrations/024_index_audit_and_optimization.sql`
**Why Fragile:** 10k+ chunks × multiple TFs = complex index interactions; full table scans can hit lock limits
**Safe Modification:**
- Always use `reltuples` estimates instead of COUNT(*) for large tables
- Batch large UPDATEs by symbol/TF to avoid locking all chunks
- Monitor `pg_stat_statements` for slow queries after any schema change

### 4. Consumer Group Position Reset
**Files:** `src/core/stream_utils.py`, all services using `ensure_consumer_group_with_reset`
**Why Fragile:** Group creation silently fails if group exists; must explicitly reset position
**Safe Modification:**
- Always use `ensure_consumer_group_with_reset()`, never raw `xgroup_create()`
- Never catch `ResponseError` and silently ignore — must call `xgroup_setid()` to reset

---

## Summary of Action Items

### Immediate (v1.7 completion)
- [ ] Phase 27: Signal Lifecycle Stream Events (7 plans)

### High Priority (v1.8)
- [ ] Signal status enum (prevent typos)
- [ ] CIS data repair (unblock PostgreSQL issue investigation)
- [ ] Dashboard all_ranked panel (complete I7 visibility)

### Medium Priority (v1.8–v1.9)
- [ ] Fix sequential stream polling in feature_writer_service
- [ ] LLM call tracking improvements (tokens, errors, context)
- [ ] Service test pattern documentation
- [ ] Ruff linting fixes (auto-fix + pre-commit hook)

### Low Priority (v1.9+, nice-to-have)
- [ ] Drop dead `technical_indicators` table
- [ ] Research VWAP/session TF guards
- [ ] Broker-agnostic instrument provider design
- [ ] Dashboard SSE stress tests

---

*Concerns audit: 2026-03-11. Next review: after v1.7 ships and Phase 27 completes.*
