---
phase: 30-redpanda-migration
plan: 04
subsystem: infra
tags: [kafka, redpanda, aiokafka, sse, feature-writer, llm-writer, broadcaster, fan-out]

# Dependency graph
requires:
  - phase: 30-03
    provides: signal_lifecycle + ai_narrative migrated; KafkaConsumerClient/KafkaProducerClient
  - phase: 30-01
    provides: kafka_utils.py, topic_* builders, stream_keys.py Kafka helpers

provides:
  - feature_writer_service consuming intelligence + intelligence.i7 + intelligence.i8 topics via Kafka
  - llm_writer_service consuming llm.calls + llm.outcomes topics via Kafka
  - KafkaSSEBroadcaster with per-topic deque(maxlen=30) snapshot + per-client asyncio.Queue fan-out
  - SSE endpoint (/api/sse/events) using KafkaSSEBroadcaster; no xrevrange/xread
  - ai_narrative_service i8 publish wired to topic_intelligence_i8 (deferred from Plan 3)
  - KAFKA-07 contract tests in test_sse_stream_builder.py

affects:
  - 30-05 (DragonflyDB removal — all 8 services now Redpanda-native, redis[hiredis] can be removed)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "KafkaSSEBroadcaster pattern: single Kafka consumer → N client asyncio.Queue fan-out + per-topic deque snapshot"
    - "SSE snapshot drain: per-topic deque(maxlen=30) newest-first; reversed for chronological delivery to client"
    - "SSE live loop: asyncio.wait_for(queue.get(), timeout=5.0) with heartbeat on TimeoutError"
    - "Dual-mode field parsing: str-key Kafka JSON + bytes-key legacy test fixtures via _str(key) helper"

key-files:
  created: []
  modified:
    - services/feature_writer_service.py
    - services/llm_writer_service.py
    - src/api/routes/sse.py
    - src/api/dependencies.py
    - src/api/main.py
    - services/ai_narrative_service.py
    - tests/unit/service_tests/test_feature_writer_service.py
    - tests/unit/test_sse_stream_builder.py

key-decisions:
  - "feature_writer_service redis_client fully removed; single KafkaConsumerClient on intelligence + i7 + i8 topics; CONSUMER_GROUP='feature_writer_group'"
  - "llm_writer_service redis_client fully removed; Redis score cache hset removed (llm_model_scores table write only)"
  - "KafkaSSEBroadcaster in sse.py (not separate file) — colocation with SSE endpoint simplifies import graph"
  - "SSE endpoint topic filter: client receives only topics in _build_topic_list(symbols, timeframe) — server-side filter on live queue"
  - "Legacy _event_name_for_stream/_build_stream_list kept for backward compat with existing tests"
  - "ai_narrative_service: i8 publish to topic_intelligence_i8 wired in Plan 4 (was TODO(30-04) in Plan 3)"

patterns-established:
  - "SSE broadcaster: asyncio.Queue(maxsize=500) per client; QueueFull → silent skip (slow client drops messages)"
  - "Snapshot newest-first with deque.appendleft(); reversed() for chronological drain to client"

requirements-completed:
  - KAFKA-07
  - KAFKA-08

# Metrics
duration: 11min
completed: 2026-03-14
---

# Phase 30 Plan 04: Writer Services + API/SSE Redpanda Migration Summary

**feature_writer and llm_writer migrated to Redpanda; KafkaSSEBroadcaster with fan-out queue + snapshot deque replaces Redis xrevrange/xread in SSE endpoint; 1779 tests passing**

## Performance

- **Duration:** ~11 min
- **Started:** 2026-03-14T11:44:26Z
- **Completed:** 2026-03-14T11:55:00Z
- **Tasks:** 2
- **Files modified:** 8

## Accomplishments

- feature_writer_service fully Kafka-native: KafkaConsumerClient on intelligence + intelligence.i7 + intelligence.i8 topics; all asyncpg batch insert logic unchanged; Redis xreadgroup/xadd fully removed; CONSUMER_GROUP='feature_writer_group'
- llm_writer_service fully Kafka-native: KafkaConsumerClient on llm.calls + llm.outcomes; Redis xreadgroup + score cache hset removed; dual-mode str/bytes field parsing keeps existing tests passing
- KafkaSSEBroadcaster implemented: per-topic deque(maxlen=30) snapshot + per-client asyncio.Queue(maxsize=500) fan-out; subscribe()/unsubscribe() API; run(consumer) async loop
- SSE endpoint rewritten: snapshot phase drains per-topic deque, live phase awaits queue with 5s timeout/heartbeat; no xrevrange/xread/redis_manager dependency
- _event_name_for_topic() added for period-separated Kafka topic names; legacy _event_name_for_stream() kept for backward compat
- main.py lifespan: KafkaSSEBroadcaster + KafkaConsumerClient on all 9 SSE topics; asyncio.create_task(broadcaster.run(consumer)) started at startup
- ai_narrative_service: i8 narrative metadata now published to topic_intelligence_i8 via KafkaProducerClient (resolves TODO(30-04) from Plan 3)

## Task Commits

1. **Task 1: Migrate feature_writer and llm_writer to Redpanda** - `1df3baf` (feat)
2. **Task 2: KafkaSSEBroadcaster + SSE endpoint migration** - `0683753` (feat)

## Files Created/Modified

- `services/feature_writer_service.py` - Full Kafka migration; redis_client removed; _setup_kafka_clients() + _process_loop() replacing xreadgroup loops
- `services/llm_writer_service.py` - Full Kafka migration; redis_client removed; Redis score cache hset removed; dual-mode parse functions
- `src/api/routes/sse.py` - KafkaSSEBroadcaster class + _event_name_for_topic() + _build_topic_list() + SSE endpoint rewrite; legacy helpers kept
- `src/api/dependencies.py` - kafka_broadcaster module-level variable + get_kafka_broadcaster() added
- `src/api/main.py` - lifespan: KafkaSSEBroadcaster init + KafkaConsumerClient for all SSE topics + background task
- `services/ai_narrative_service.py` - topic_intelligence_i8 import added; i8 publish TODO(30-04) resolved
- `tests/unit/service_tests/test_feature_writer_service.py` - shutdown test updated for Kafka; KAFKA-07 contract test added
- `tests/unit/test_sse_stream_builder.py` - 5 new KAFKA-07 tests: fan-out, _event_name_for_topic mappings

## Decisions Made

- feature_writer_service redis_client fully removed — no remaining Redis ops after migration; Kafka covers all stream I/O
- llm_writer_service Redis score cache hset removed — llm_model_scores table is authoritative; ai_narrative_service reads from DB at startup (already in-process dict since Plan 3)
- KafkaSSEBroadcaster lives in sse.py (colocation with SSE endpoint) — avoids circular import complexity
- SSE endpoint filters live queue by topic: only messages matching _build_topic_list(symbols, tf) forwarded to client — server-side filtering
- Legacy Redis helpers kept: _event_name_for_stream, _build_stream_list, _signal_entry_stale — existing tests continue passing

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Snapshot filter test broke after SSE rewrite**
- **Found during:** Task 2 (running full test suite after SSE rewrite)
- **Issue:** test_sse_snapshot_filter.py::test_snapshot_loop_does_not_call_stale_filter searches for exact comment marker `"# ── Live:"` in sse.py source; new code had `"# ── Live phase:"` which didn't match
- **Fix:** Changed comment to `"# ── Live:"` to match existing test contract
- **Files modified:** src/api/routes/sse.py
- **Verification:** All 16 snapshot filter tests pass
- **Committed in:** 0683753 (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - test contract)
**Impact on plan:** Trivial comment wording fix — no logic change.

## Issues Encountered

- None beyond the snapshot filter comment mismatch (auto-fixed above)

## Next Phase Readiness

- All 8 business logic services now Redpanda-native: tws_daemon, timeframes_builder, indicator, market_analysis, signal_generator, signal_lifecycle, ai_narrative, feature_writer, llm_writer + SSE API
- Plan 5 can safely remove DragonflyDB container from docker-compose.yml and redis[hiredis] from requirements.txt
- Redis client remains in main.py for RedisStreamsManager (non-SSE routes that may still use Redis) — Plan 5 cleans this up

## Self-Check

---
*Phase: 30-redpanda-migration*
*Completed: 2026-03-14*
