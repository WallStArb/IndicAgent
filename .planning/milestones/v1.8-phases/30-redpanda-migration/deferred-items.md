# Phase 30 Deferred Items

## Pre-existing test failure (out of scope)

**File:** `tests/unit/scripts/test_validate_equity_backfill.py::TestValidateEquityBackfill::test_zero_count_exits_zero`
**Status:** Failing before Phase 30 began (confirmed by git stash test)
**Details:** `validate_symbol()` returns 1 when `count=0`, but test expects 0. Pre-existing regression from commit `0c94bee`.
**Owner:** Separate investigation needed; not caused by Redpanda migration work.

## redis[hiredis] still in requirements.txt (Plan 05 partial)

**Status:** Not removed — still needed
**Details:** `src/api/routes/market_data.py` and `src/api/routes/health.py` still import `redis.asyncio`
via `src/core/redis_streams_manager.py`. These routes read historical snapshots from Redis streams.
Plan 04 migrated the SSE broadcaster to Kafka but left `market_data.py` Redis-dependent.
**Impact:** redis[hiredis] cannot be removed until market_data API routes are migrated to Kafka.
**Owner:** Phase 30 follow-up or Phase 31.
