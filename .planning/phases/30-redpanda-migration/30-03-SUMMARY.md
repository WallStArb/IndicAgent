---
phase: 30-redpanda-migration
plan: 03
subsystem: infra
tags: [kafka, redpanda, aiokafka, signal-lifecycle, ai-narrative, llm-scores-cache, freshness-decay]

# Dependency graph
requires:
  - phase: 30-02
    provides: KafkaConsumerClient, KafkaProducerClient, topic_* builders, indicator+market_analysis migrated
  - phase: 29-08
    provides: signal_lifecycle_service QUAL-03 freshness decay, effective_confidence
provides:
  - signal_lifecycle_service consuming market.bars + signals.aggregated via Kafka
  - ai_narrative_service consuming signals.aggregated via Kafka
  - _llm_scores_cache in-process dict replacing Redis HSET/HGETALL for LLM score routing
  - KAFKA-08 contract tests in test_ai_narrative_service.py and test_signal_lifecycle_service.py
affects:
  - 30-04 (SSE + writer services migration — next wave)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "In-process cache pattern: _llm_scores_cache dict seeded from DB at startup + refreshed every 15 min via asyncio loop"
    - "Consumer group migration: xreadgroup removed, KafkaConsumerClient multi-topic subscribe"
    - "Producer migration: xadd removed, KafkaProducerClient.publish with message_key(symbol, tf)"

key-files:
  created: []
  modified:
    - services/signal_lifecycle_service.py
    - services/ai_narrative_service.py
    - src/core/stream_keys.py
    - tests/unit/service_tests/test_ai_narrative_service.py
    - tests/unit/service_tests/test_signal_lifecycle_service.py
    - tests/unit/service_tests/test_lifecycle_freshness.py

key-decisions:
  - "signal_lifecycle_service Redis client fully removed — no remaining Redis ops after migration; Kafka covers all stream I/O"
  - "ai_narrative_service Redis client fully removed — _llm_scores_cache in-process dict + DB warm replaces all Redis HSET/HGETALL"
  - "_group_fingerprints in-process dict replaces Redis hset fingerprint tracking in _synthesize_group"
  - "i8 stream publish deferred to Plan 4 (SSE migration) — code has pass + TODO(30-04) comment; tests document deferred behavior"
  - "KAFKA-08 tests added: redis_client absence contract, _llm_scores_cache presence, Kafka client attributes"

patterns-established:
  - "DB warm on startup + periodic refresh: _warm_llm_scores_cache_from_db() called at startup, asyncio.create_task schedules 15-min refresh loop"
  - "__new__ test helpers must set env_name (not just env_prefix) — all topic_* builders use env_name"

requirements-completed:
  - KAFKA-08

# Metrics
duration: 35min
completed: 2026-03-14
---

# Phase 30 Plan 03: Signal + Narrative Redpanda Migration Summary

**signal_lifecycle_service and ai_narrative_service fully migrated to Redpanda; _llm_scores_cache in-process dict replaces Redis HSET/HGETALL for LLM score routing; 1774 tests passing**

## Performance

- **Duration:** ~35 min
- **Started:** 2026-03-14T07:10:00Z
- **Completed:** 2026-03-14T07:45:00Z
- **Tasks:** 2 (Task 1 from prior session, Task 2 this session)
- **Files modified:** 6

## Accomplishments

- signal_lifecycle_service fully Kafka-native: KafkaConsumerClient on market.bars + signals.aggregated topics; KafkaProducerClient publishing terminal events to signals.aggregated + llm.outcomes; Redis client entirely removed; no xreadgroup/xadd remain
- ai_narrative_service fully Kafka-native: KafkaConsumerClient on signals.aggregated; KafkaProducerClient to narratives + llm.calls + narratives.group; _llm_scores_cache in-process dict warmed from llm_model_scores DB at startup and refreshed every 15 min; Redis client removed; _group_fingerprints dict replaces Redis hash fingerprint tracking
- All test mocks updated for KAFKA-08: stale redis_client assertions removed; replaced with _kafka_producer.publish assertions; 3 new KAFKA-08 contract tests verify Kafka-native interface; _make_service_new and _make_service_concurrent helpers fixed to not set redis_client; test_lifecycle_freshness.py _make_service helper fixed (missing _kafka_producer attribute)

## Task Commits

1. **Task 1: Migrate signal_generator_service** - `aadb494` (feat) — prior session
2. **Task 2: Migrate signal_lifecycle + ai_narrative; fix tests** - `2c090cb` (feat)

## Files Created/Modified

- `services/signal_lifecycle_service.py` - Full Kafka migration; Redis client removed
- `services/ai_narrative_service.py` - Full Kafka migration; _llm_scores_cache in-process dict; Redis client removed
- `src/core/stream_keys.py` - topic_* helpers confirmed/extended
- `tests/unit/service_tests/test_ai_narrative_service.py` - All Redis mock assertions replaced with Kafka; 3 new KAFKA-08 tests; _make_service_new/concurrent helpers updated
- `tests/unit/service_tests/test_signal_lifecycle_service.py` - KAFKA-08 contract tests already present (from prior session)
- `tests/unit/service_tests/test_lifecycle_freshness.py` - _make_service helper updated with _kafka_producer=None and env_name

## Decisions Made

- signal_lifecycle_service Redis client fully removed — no remaining Redis ops after migration; Kafka covers all stream I/O
- ai_narrative_service Redis client fully removed — _llm_scores_cache in-process dict + DB warm replaces all Redis HSET/HGETALL
- _group_fingerprints in-process dict replaces Redis hset fingerprint tracking in _synthesize_group (no more Redis roundtrip per group synthesis cycle)
- i8 stream publish deferred to Plan 4 (SSE migration) — code has `pass` with TODO(30-04) comment; tests document deferred behavior explicitly
- KAFKA-08 tests verify: redis_client absence, _llm_scores_cache presence, Kafka client attributes

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Stale redis_client test assertions after service migration**
- **Found during:** Task 2 (running test suite after services confirmed migrated)
- **Issue:** test_ai_narrative_service.py had 11 failing tests with stale redis_client.xadd / redis_client.xack / Redis hgetall assertions; _make_service_new and _make_service_concurrent helpers set svc.redis_client = AsyncMock(); test_lifecycle_freshness.py _make_service helper missing _kafka_producer and env_name attributes
- **Fix:** Updated all helpers to use _kafka_producer instead of redis_client; replaced xadd call_args assertions with _kafka_producer.publish assertions; rewrote group synthesis tests for in-process _group_fingerprints dict; rewrote _apply_score_routing tests for in-process _llm_scores_cache dict; replaced _setup_consumer_groups test with 3 KAFKA-08 contract tests; updated i8 tests to document deferred Plan 4 behavior; fixed env_name missing in __new__ helpers
- **Files modified:** tests/unit/service_tests/test_ai_narrative_service.py, tests/unit/service_tests/test_lifecycle_freshness.py
- **Verification:** 1774 tests passing (up from 1659 baseline — new tests added)
- **Committed in:** 2c090cb (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - test correctness)
**Impact on plan:** Test fixes required for correctness — services were already migrated, tests reflected old Redis interface.

## Issues Encountered

- Both signal_lifecycle_service and ai_narrative_service were already fully migrated to Kafka in the working tree (changes staged but not committed). Task 2 execution confirmed migration correctness and fixed the 11 failing tests that still referenced the old Redis interface.

## Next Phase Readiness

- 3 of 5 business logic services migrated to Redpanda: indicator, market_analysis, signal_generator, signal_lifecycle, ai_narrative
- Plan 4 migrates writer services (feature_writer, llm_writer) and SSE API endpoint
- i8 stream publish (currently `pass`) will be wired in Plan 4 when SSE consumer is migrated

---
*Phase: 30-redpanda-migration*
*Completed: 2026-03-14*
