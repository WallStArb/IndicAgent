---
phase: 30-redpanda-migration
plan: "02"
subsystem: services
tags: [aiokafka, redpanda, kafka, tws-daemon, indicator-service, market-analysis, timeframes-builder, migration]

# Dependency graph
requires:
  - 30-01 (KafkaProducerClient, KafkaConsumerClient, topic_* builders, Settings.kafka_bootstrap_servers)
provides:
  - tws_daemon.py: Kafka-native bar+tick publisher (services/tws_daemon.py)
  - timeframes_builder_service.py: Kafka consumer+producer for higher-TF aggregation
  - indicator_service.py: Kafka consumer for market.bars, producer for indicators; DB warmup
  - market_analysis_service.py: Kafka consumer for indicators, producer for intelligence
  - KAFKA-05 test coverage: indicator_service publishes to correct topic + key
affects:
  - 30-03-PLAN: Signal + AI Services (consume from dev.intelligence)
  - 30-04-PLAN: Writer Services + API/SSE (consume from dev.intelligence)
  - 30-05-PLAN: Cache Migration + DragonflyDB Removal

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "_get_field() dual-mode dict helper for str/bytes field access (Kafka JSON vs legacy test bytes)"
    - "_seed_bar_history_from_db() Phase 26 pattern applied to indicator_service"
    - "KafkaConsumerClient.messages() async-for loop replaces xreadgroup dict call"
    - "message_key extraction from Kafka msg.key via key.split(':', 1)"
    - "service tests updated to mock kafka_producer.publish instead of redis_client.xadd"

key-files:
  created:
    - services/tws_daemon.py (Kafka-native TWS daemon: market.bars + market.ticks)
    - tests/unit/daemons/test_tws_daemon.py (4 tests: bar publish, tick publish, no-redis assertions)
  modified:
    - services/timeframes_builder_service.py (full rewrite: KafkaConsumerClient + KafkaProducerClient)
    - services/indicator_service.py (Kafka producer/consumer; DB warmup; _get_field helper)
    - services/market_analysis_service.py (Kafka producer/consumer; removed xreadgroup/_stream_map)
    - tests/unit/service_tests/test_indicator_service.py (updated mocks; KAFKA-05 test added)
    - tests/unit/service_tests/test_market_analysis_service.py (updated xadd mocks to kafka publish)

key-decisions:
  - "services/tws_daemon.py created as Kafka-native service — tws_daemon.py did not previously exist in services/; production/daemons/high_frequency_tws_daemon.py remains for legacy reference"
  - "_seed_bar_history_from_db() reads market_data_ohlcv (Phase 26 pattern) — no xrevrange warmup needed after Kafka migration"
  - "market_analysis_service _warmup_bar_history() replaced with no-op stub — bar history accumulates from live Kafka stream on startup"
  - "_get_field() helper added to both indicator_service and market_analysis_service for bytes/str dict compat (supports both Kafka JSON str-keyed and legacy test bytes-keyed dicts)"
  - "TestPublisherFormat tests in test_market_analysis_service.py updated to mock kafka_producer.publish instead of redis_client.xadd (Rule 1 auto-fix)"

requirements-completed: [KAFKA-05, KAFKA-08]

# Metrics
duration: 13min
completed: 2026-03-14
---

# Phase 30 Plan 02: Hot Tier + Intelligence Input Pipeline Migration Summary

**4 services migrated from DragonflyDB to Redpanda: tws_daemon publishes bars/ticks to Kafka, indicator_service consumes market.bars and publishes indicators, market_analysis_service consumes indicators and publishes intelligence — all via KafkaProducerClient/KafkaConsumerClient with no Redis XADD/XREADGROUP calls**

## Performance

- **Duration:** ~13 min
- **Started:** 2026-03-14T06:50:21Z
- **Completed:** 2026-03-14T07:03:11Z
- **Tasks:** 2
- **Files modified:** 7 (2 created, 5 modified)

## Accomplishments

- `services/tws_daemon.py` created: Kafka-native TWS daemon publishing bars to `dev.market.bars` (key: `SYMBOL:1m`) and ticks to `dev.market.ticks` (key: `SYMBOL`)
- `services/timeframes_builder_service.py` rewritten: consumes `dev.market.bars` via KafkaConsumerClient, emits completed higher-TF bars back to `dev.market.bars` with `SYMBOL:TF` key; reuses `_update_accumulator/_floor_to_period` from `timeframe_builder.py`
- `services/indicator_service.py` migrated: consumes `dev.market.bars`, seeds bar_history from `market_data_ohlcv` at startup, publishes to `dev.indicators` with `SYMBOL:TF` key
- `services/market_analysis_service.py` migrated: consumes `dev.indicators`, publishes `IntelligenceEvent` JSON to `dev.intelligence` with `SYMBOL:TF` key
- KAFKA-05 covered: test asserts `topic_indicators(env_name)` and key `ES:1m` in publish call
- 1760 unit tests pass (6 new tests added)

## Task Commits

1. **Task 1: tws_daemon + timeframes_builder migration** - `e4b5326` (feat)
2. **Task 2: indicator_service + market_analysis_service migration** - `4b39192` (feat)

## Files Created/Modified

- `/home/bg/dev/indicagent/services/tws_daemon.py` - Kafka-native TWS daemon
- `/home/bg/dev/indicagent/services/timeframes_builder_service.py` - Kafka consumer+producer for TF aggregation
- `/home/bg/dev/indicagent/services/indicator_service.py` - Kafka consumer/producer + DB warmup
- `/home/bg/dev/indicagent/services/market_analysis_service.py` - Kafka consumer/producer
- `/home/bg/dev/indicagent/tests/unit/daemons/test_tws_daemon.py` - 4 new tests
- `/home/bg/dev/indicagent/tests/unit/service_tests/test_indicator_service.py` - Updated + KAFKA-05 test
- `/home/bg/dev/indicagent/tests/unit/service_tests/test_market_analysis_service.py` - Updated mocks

## Decisions Made

- `services/tws_daemon.py` created as new file (the previous TWS daemon was `production/daemons/high_frequency_tws_daemon.py` using Redis); the plan's `files_modified` target was interpreted as the intended location for the Kafka-native service
- `_seed_bar_history_from_db()` follows the Phase 26 signal_generator pattern: reads `market_data_ohlcv` via asyncpg at startup, falls back silently if DB unreachable
- `market_analysis_service._warmup_bar_history()` is replaced with a no-op stub — the xrevrange-based warmup is not applicable after Kafka migration; bar history accumulates naturally from live indicator messages
- `_get_field()` helper handles both `str`-keyed dicts (from Kafka JSON payloads) and `bytes`-keyed dicts (from legacy unit tests) — backward compat without breaking existing tests
- `test_market_analysis_service.py` `TestPublisherFormat` tests updated from `redis_client.xadd` mocks to `kafka_producer.publish` mocks (Rule 1 auto-fix — existing tests referenced removed interface)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] tests/unit/service_tests/test_market_analysis_service.py used redis_client.xadd mock**
- **Found during:** Task 2 (full test run after market_analysis_service migration)
- **Issue:** Three `TestPublisherFormat` tests mocked `svc.redis_client.xadd` — which no longer exists after Kafka migration; tests failed with `AttributeError: 'NoneType' has no attribute 'send_and_wait'`
- **Fix:** Updated `_make_service()` to set `svc._kafka_producer = AsyncMock()` and updated all three test assertions to use `svc._kafka_producer.publish.call_args`
- **Files modified:** tests/unit/service_tests/test_market_analysis_service.py
- **Verification:** All 3 tests pass GREEN

**2. [Rule 2 - Missing attr] test_tws_daemon.py tests used __new__ without setting env_name**
- **Found during:** Task 1 TDD GREEN run
- **Issue:** `_tick_loop` and `_fetch_bars_for_symbol` reference `self.env_name` but tests used `TwsDaemon.__new__` without setting it
- **Fix:** Added `daemon.env_name = "dev"` and `daemon.contracts = [...]` to test setup
- **Files modified:** tests/unit/daemons/test_tws_daemon.py
- **Verification:** All 4 tests pass GREEN

### Structural Note

The plan specified `files_modified: services/tws_daemon.py` but this file did not previously exist; the existing TWS daemon was at `production/daemons/high_frequency_tws_daemon.py`. The new `services/tws_daemon.py` is a Kafka-native implementation following the same service-layer pattern as `indicator_service.py`. The original daemon remains for reference during the dual-run period.

## Self-Check: PASSED

- services/tws_daemon.py: FOUND
- services/timeframes_builder_service.py: FOUND
- services/indicator_service.py: FOUND
- services/market_analysis_service.py: FOUND
- 30-02-SUMMARY.md: FOUND
- Commit e4b5326 (Task 1): FOUND
- Commit 4b39192 (Task 2): FOUND
- 1760 unit tests passing
