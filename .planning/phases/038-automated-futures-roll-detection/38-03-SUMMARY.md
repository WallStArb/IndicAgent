---
phase: 038-automated-futures-roll-detection
plan: "03"
subsystem: pipeline-roll-integration
tags: [roll-detection, kafka, plugin-state-migration, contract-metadata, futures]
dependency_graph:
  requires: ["38-01", "38-02"]
  provides: ["pipeline-roll-integration", "seed-roll-chain"]
  affects: ["indicator_service", "market_analysis_service", "signal_generator_service", "feature_writer_service", "historical_backfill"]
tech_stack:
  added: []
  patterns: ["event-driven roll routing", "price-sensitive state adjustment", "roll boundary marker", "seed-roll-chain upsert"]
key_files:
  created:
    - tests/unit/test_plugin_state_migration.py
    - tests/unit/test_roll_kafka_events.py
    - tests/unit/test_seed_roll_chain.py
  modified:
    - services/indicator_service.py
    - services/market_analysis_service.py
    - services/signal_generator_service.py
    - services/feature_writer_service.py
    - production/scripts/historical_backfill.py
decisions:
  - "_i1_plugin_states uses (plugin_name, symbol, tf) tuple keys — migration iterates by symbol/tf to find all keys"
  - "Price adjustment uses recursive _adjust_price_state() — handles nested dicts and lists of numerics"
  - "Roll boundary marker uses ON CONFLICT ... || merge to preserve any existing i7 data at same ts/symbol/tf"
  - "seed_roll_chain is async to match DatabaseManager.execute_batch() interface"
  - "Event loop fixture in test_seed_roll_chain.py ensures ib_insync/eventkit import works when combined with other test files"
metrics:
  duration_minutes: 9
  completed_date: "2026-03-18"
  tasks_completed: 2
  tasks_total: 2
  files_created: 3
  files_modified: 5
  tests_added: 35
---

# Phase 38 Plan 03: Pipeline Roll Integration Summary

Pipeline integration for roll events: all 4 downstream services consume roll events from Kafka's system.events topic, indicator_service migrates I1 plugin state with roll_gap price adjustments, feature_writer writes roll boundary markers, and historical_backfill seeds contract_metadata roll chains.

## Tasks Completed

### Task 1: Downstream Service Roll Event Consumption + Plugin State Migration

**Commits:** `552d055`

**indicator_service.py:**
- Added `PRICE_SENSITIVE_PLUGINS` frozenset: `{bollinger_bands, keltner_channel, donchian_channel}`
- Added `_adjust_price_state(state, roll_gap) -> dict` helper: recursively adjusts all numeric values (float/int scalars, list elements, nested dicts) by roll_gap; returns a deep copy, never mutates original
- Added `_handle_roll_event(event)`: iterates over all (plugin_name, old_symbol, tf) state keys; price-sensitive plugins get `_adjust_price_state()` treatment; volume-neutral plugins get verbatim copy; old keys deleted after migration
- `start()`: conditionally appends `topic_system_events()` to consumer topics when `roll_monitor_enabled=True`
- `_process_market_data()`: routes messages from system.events topic to `_handle_roll_event()`

**market_analysis_service.py:**
- Added `_handle_roll_event(event)`: discards old_symbol from `_active_symbols`, adds new_symbol
- `start()`: conditionally subscribes to system.events when `roll_monitor_enabled=True`
- `_process_market_data()`: routes system.events messages to `_handle_roll_event()`

**signal_generator_service.py:**
- Added `_handle_roll_event(event)`: transfers bar_history deque contents from `{old_symbol}:{tf}` keys to `{new_symbol}:{tf}` for all 4 TFs; clears old keys; invalidates df_cache
- `_setup_kafka_clients()`: conditionally adds system.events topic when `roll_monitor_enabled=True`
- `_process_loop()`: routes system.events to `_handle_roll_event()`

**feature_writer_service.py:**
- Added `_UPSERT_ROLL_BOUNDARY_SQL`: inserts `{"roll_boundary": "ESM6->ESU6"}` into i7 JSONB; `ON CONFLICT ... DO UPDATE SET i7 = intelligence_features.i7 || EXCLUDED.i7` merges with existing i7 data
- Added `_handle_roll_event(event)`: writes roll boundary marker at `detected_at` timestamp; skips gracefully when `db_manager` is None
- `_setup_kafka_clients()`: conditionally adds system.events topic when `roll_monitor_enabled=True`
- `_process_loop()`: routes system.events to `_handle_roll_event()` before key parsing

**Tests: 26 tests in test_plugin_state_migration.py + test_roll_kafka_events.py**
- `_adjust_price_state()`: float/int/list/nested-dict/non-numeric/no-mutation
- `_handle_roll_event()` on indicator_service: price-sensitive adjusted, volume-neutral verbatim, old key deleted, multi-TF, non-roll ignored, malformed skipped, default gap=0
- `_handle_roll_event()` on market_analysis_service: symbol update, non-roll ignored, malformed skipped
- `_handle_roll_event()` on signal_generator_service: bar_history migration, non-roll ignored, malformed skipped
- `_handle_roll_event()` on feature_writer_service: DB write with correct marker, format verification, no-DB skip, non-roll ignored, malformed skipped
- Roll monitor disabled guard: indicator_service.start() references roll_monitor_enabled

### Task 2: historical_backfill.py --seed-roll-chain with Unit Tests

**Commits:** `5616e19`

**production/scripts/historical_backfill.py:**
- Imported `derive_roll_chain` from `src.config.contracts` and `DatabaseManager` from `src.core.database_manager`
- Added `_SEED_ROLL_CHAIN_SQL`: `INSERT INTO contract_metadata (symbol, base_symbol, asset_class, roll_from, roll_to, is_front_month) ... ON CONFLICT (symbol) DO UPDATE SET ...` — idempotent
- Added `async def seed_roll_chain(settings, db)`: deduplicates futures base symbols via `dict.fromkeys()`, calls `derive_roll_chain()` per base, UPSERTs 3-contract chain with `is_front_month=True` for index 0, `False` for 1 and 2; per-base error caught and logged
- Added `--seed-roll-chain` argparse flag
- Wired early-exit branch in `main()`: creates `DatabaseManager`, awaits `seed_roll_chain()`, returns
- Rule 1 fix: removed redundant local `import asyncio` inside IBKR fetch block (asyncio already imported at module level; local import caused ruff F823)

**Tests: 9 tests in test_seed_roll_chain.py**
- Base symbol iteration: ES/NQ/CL iterated; SPY/EUR skipped
- Non-futures only: equity + crypto produce no `derive_roll_chain` calls
- Deduplication: ESM6 + ESU6 same base → `derive_roll_chain("ES")` called once
- is_front_month assignment: index 0 = True, index 1+2 = False
- ON CONFLICT SQL verification: "ON CONFLICT" + "DO UPDATE" present in SQL
- Idempotency: double call succeeds without error
- DB error handling: exception caught, not re-raised
- Summary log: function completes without crash
- CLI flag: `--seed-roll-chain` appears in `--help` output

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Removed redundant local `import asyncio` in historical_backfill.py main()**
- **Found during:** Task 2 implementation
- **Issue:** `import asyncio` inside `if not args.replay_only:` block shadowed the top-level import, causing ruff F823 ("Local variable `asyncio` referenced before assignment") when `asyncio.run()` was used earlier in the function
- **Fix:** Removed the redundant local import; the top-level `import asyncio` at line 54 was sufficient
- **Files modified:** `production/scripts/historical_backfill.py`
- **Commit:** `5616e19`

**2. [Rule 1 - Bug] Event loop fixture for test_seed_roll_chain.py**
- **Found during:** Task 2 test execution (combined test run)
- **Issue:** When tests run combined with `test_plugin_state_migration.py`, `asyncio.run()` calls in the migration tests close the default event loop. `historical_backfill` imports `IBKRProvider` → `ib_insync` → `eventkit` which calls `asyncio.get_event_loop()` at import time in module-level code. With no current event loop, eventkit raises `RuntimeError`.
- **Fix:** Added `ensure_event_loop` autouse fixture in `test_seed_roll_chain.py` that creates a fresh event loop per test and tears it down after
- **Files modified:** `tests/unit/test_seed_roll_chain.py`
- **Commit:** `5616e19`

## Self-Check: PASSED

All 8 required files exist. Both commits (552d055, 5616e19) confirmed in git log. 35 unit tests pass.
