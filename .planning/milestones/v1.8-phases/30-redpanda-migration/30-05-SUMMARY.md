---
phase: 30-redpanda-migration
plan: "05"
subsystem: redpanda-migration
tags:
  - redpanda
  - kafka
  - dragonfly-removal
  - drift-state
  - perf-weights
dependency_graph:
  requires:
    - 30-04
  provides:
    - dragonfly-removed
    - drift-state-table
    - redis-free-signal-generator
  affects:
    - services/signal_generator_service.py
    - services/drift_monitor_service.py
    - src/monitoring/ks_drift_monitor.py
    - src/monitoring/cusum_monitor.py
    - production/docker-compose.yml
    - src/core/stream_keys.py
    - src/core/stream_utils.py
tech_stack:
  added:
    - "drift_state TimescaleDB table (symbol, tf PRIMARY KEY; KS + CUSUM severity)"
  patterns:
    - "asyncpg INSERT ON CONFLICT DO UPDATE for drift state upsert"
    - "In-process dict refresh loop (4h cycle) for drift penalties"
    - "DB-direct perf_weights read from setup_performance table (rank by avg_pnl_r)"
key_files:
  created:
    - production/migrations/030_drift_state.sql
    - tests/unit/service_tests/test_drift_state_db.py
    - tests/unit/service_tests/test_perf_weights_db.py
  modified:
    - services/signal_generator_service.py
    - services/drift_monitor_service.py
    - src/monitoring/ks_drift_monitor.py
    - src/monitoring/cusum_monitor.py
    - src/intelligence/setup_performance_updater.py
    - src/core/stream_keys.py
    - src/core/stream_utils.py
    - src/core/timeframe_builder.py
    - production/daemons/high_frequency_tws_daemon.py
    - production/docker-compose.yml
decisions:
  - "drift_state unified table: KS rows (symbol=SYMBOL, tf=TF) and CUSUM rows (symbol=setup_plugin, tf='_cusum') share same table via sentinel TF"
  - "redis[hiredis] kept in requirements.txt: src/api/routes/market_data.py still reads Redis streams; removal deferred to Phase 30 follow-up"
  - "CUSUM penalty adjustment removed from setup_performance_updater (was reading drift_cusum Redis key); signal_generator reads drift_penalties independently from drift_state table"
  - "get_stream_maxlen removed from stream_keys.py; callers use local constants (_MARKET_STREAM_MAXLEN, _MARKET_1M_STREAM_MAXLEN)"
metrics:
  duration: "~90 minutes"
  completed: "2026-03-14"
  tasks_completed: 3
  tasks_total: 4
  files_modified: 14
---

# Phase 30 Plan 05: DragonflyDB Removal + Redis Non-Stream Cleanup Summary

**DragonflyDB container removed from docker-compose; drift state migrated to TimescaleDB; perf_weights read directly from DB; stream_keys.py v3.0.0 with only topic_* builders; signal_generator fully Redis-free**

## What Was Built

### Task 1: drift_state DB migration + KS/CUSUM drift key replacement

Created `production/migrations/030_drift_state.sql` — unified table replacing all drift Redis keys:

```sql
CREATE TABLE IF NOT EXISTS drift_state (
    symbol TEXT NOT NULL, tf TEXT NOT NULL,
    ks_severity TEXT NOT NULL DEFAULT 'none',
    cusum_severity TEXT NOT NULL DEFAULT 'none',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (symbol, tf)
);
```

- `KSDriftMonitor._upsert_drift_state()`: asyncpg INSERT ON CONFLICT DO UPDATE for KS rows
- `CUSUMMonitor._upsert_cusum_state()`: same pattern with `tf='_cusum'` sentinel for CUSUM
- `DriftMonitorService`: removed all Redis client code (`_connect_redis`, `redis_client`, cleanup)
- `SignalGeneratorService`: added `_drift_penalties: dict[tuple, float]` in-process dict; `_refresh_drift_penalties_from_db()` reads `SELECT symbol, tf, ks_severity FROM drift_state WHERE tf != '_cusum'`; called at startup + every 4h; `_read_drift_penalty()` is now a simple dict lookup

### Task 2: perf_weights DB-direct read + stream_keys.py v3.0.0 cleanup

- `_load_perf_weights()`: reads `SELECT setup_plugin, win_rate, avg_pnl_r FROM setup_performance WHERE sample_size >= 30`; builds rank-ordered multipliers [0.5, 1.5]; no Redis
- `setup_performance_updater.run_setup_performance_update()`: removed Redis write and CUSUM adjustment step; DB-only persistence
- `stream_keys.py v3.0.0`: removed `get_stream_maxlen`, `quote_latest`, `llm_scores_cache`, `setup_performance_weights_cache`, `drift_ks`, `drift_cusum`, all pattern helpers (`*_pattern()`)
- `stream_utils.py`: replaced with deprecation stub (ensure_consumer_group_with_reset removed)
- `timeframe_builder.py`: local `_MARKET_STREAM_MAXLEN` constant replaces `get_stream_maxlen()` call
- `high_frequency_tws_daemon.py`: local `_MARKET_1M_STREAM_MAXLEN = 2000` constant

### Task 3: DragonflyDB removed from infrastructure

- `docker-compose.yml`: removed `dragonfly:` service block and `dragonfly-data:` volume
- `signal_generator_service.py`: removed `redis.asyncio` import, `redis_client` attribute, `_connect_redis()`, `redis` config block, and redis cleanup in `stop()`

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] hf_tws_daemon imported get_stream_maxlen (removed from stream_keys)**
- **Found during:** Task 2 — full unit suite run
- **Issue:** `production/daemons/high_frequency_tws_daemon.py` imported `get_stream_maxlen` which was removed
- **Fix:** Replaced with local `_MARKET_1M_STREAM_MAXLEN = 2000` constant; updated `test_poll_1m_bars_uses_get_stream_maxlen` test to check constant value instead of patching
- **Files modified:** `production/daemons/high_frequency_tws_daemon.py`, `tests/unit/daemons/test_poll_1m_bars.py`
- **Commit:** d57da49

**2. [Rule 1 - Bug] test_signal_generator_perf_weights.py TestLoadPerfWeights tests tested old Redis behavior**
- **Found during:** Task 2 — full unit suite run
- **Issue:** `TestLoadPerfWeights` class (4 tests) checked `redis_client.get()` calls and Redis key format — behavior that no longer exists
- **Fix:** Removed `TestLoadPerfWeights` class; equivalent DB-based tests are in `test_perf_weights_db.py`
- **Files modified:** `tests/unit/service_tests/test_signal_generator_perf_weights.py`
- **Commit:** d57da49

### Deferred Items

**redis[hiredis] NOT removed from requirements.txt**
- **Reason:** `src/api/routes/market_data.py` still uses `redis_streams_manager` for historical stream reads; removing the package would cause ImportError at API startup
- **Plan's expectation:** redis[hiredis] removed
- **Reality:** Still needed by market_data, health, and drift API routes
- **Tracked in:** `.planning/phases/30-redpanda-migration/deferred-items.md`
- **Resolution path:** Migrate market_data API routes from Redis xread to Kafka offset queries

## Test Results

- Pre-plan: 1659 passing
- Post-plan: 1783 passing (+124 new tests across Tasks 1-3)
- All tests pass with `pytest tests/unit/`

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| Task 1 | 73bf02c | feat(30-05): replace drift Redis keys with drift_state DB table |
| Task 2 | d57da49 | feat(30-05): replace perf_weights Redis cache with DB read; clean stream_keys/stream_utils |
| Task 3 | f698dd0 | feat(30-05): remove DragonflyDB from docker-compose; remove Redis from signal_generator |

## Self-Check

- [x] `production/migrations/030_drift_state.sql` created
- [x] `tests/unit/service_tests/test_drift_state_db.py` created
- [x] `tests/unit/service_tests/test_perf_weights_db.py` created
- [x] DragonflyDB removed from docker-compose.yml
- [x] stream_keys.py v3.0.0 — no get_stream_maxlen, no drift_ks, no drift_cusum
- [x] stream_utils.py is a deprecation stub
- [x] signal_generator_service.py has no redis imports
- [x] 1783 unit tests passing
