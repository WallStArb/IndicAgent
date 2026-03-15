---
phase: 30-redpanda-migration
plan: "01"
subsystem: infra
tags: [aiokafka, redpanda, kafka, stream-keys, docker-compose, transport-layer]

# Dependency graph
requires: []
provides:
  - KafkaProducerClient and KafkaConsumerClient wrappers in src/core/kafka_utils.py
  - Idempotent topic creation script for all 11 topics (production/scripts/kafka_init_topics.py)
  - 11 topic_* builder functions and message_key() helper in src/core/stream_keys.py
  - Redpanda v25.3.10 container in production/docker-compose.yml (external listener 19092)
  - Settings.kafka_bootstrap_servers field (default localhost:19092)
  - aiokafka>=0.13.0 in requirements.txt and installed in venv
  - 6 new unit tests (kafka_utils + kafka_init_topics) GREEN
  - 17 new topic_* stream_keys tests GREEN
affects:
  - 30-02-PLAN: Hot Tier + Intelligence Pipeline (tws_daemon, indicator_service, market_analysis_service)
  - 30-03-PLAN: Signal + AI Services
  - 30-04-PLAN: Writer Services + API/SSE
  - 30-05-PLAN: Cache Migration + DragonflyDB Removal

# Tech tracking
tech-stack:
  added:
    - aiokafka 0.13.0 (async Kafka producer/consumer/admin client)
    - Redpanda v25.3.10 (Kafka-compatible broker, single-node dev-container mode)
  patterns:
    - KafkaProducerClient.start()/publish(topic, msg_dict, key)/stop() lifecycle pattern
    - KafkaConsumerClient.start()/messages()/stop() async generator pattern
    - topic_{event_type}(env_name) -> str topic builder convention
    - env_prefix(env_name) period-separator (contrast with Redis prefix() colon-separator)
    - message_key(symbol, timeframe) -> SYMBOL:TF partition routing key
    - TopicAlreadyExistsError (not TopicExistsException) for aiokafka 0.13.0 idempotency
    - create_topics(bootstrap_servers, env_name) with AIOKafkaAdminClient async init pattern

key-files:
  created:
    - src/core/kafka_utils.py (KafkaProducerClient, KafkaConsumerClient)
    - production/scripts/kafka_init_topics.py (idempotent topic creation for 11 topics)
    - tests/unit/core/test_kafka_utils.py (6 tests)
    - tests/unit/core/test_kafka_init_topics.py (2 tests)
    - tests/unit/core/__init__.py
  modified:
    - src/core/stream_keys.py (11 topic builders + env_prefix + message_key added; Redis helpers kept)
    - src/config/settings.py (kafka_bootstrap_servers field added after redis fields)
    - production/docker-compose.yml (Redpanda service + redpanda-data volume added)
    - requirements.txt (aiokafka>=0.13.0 added; redis[hiredis] kept for dual-run)
    - tests/unit/test_stream_keys.py (17 new topic_* + message_key test cases)

key-decisions:
  - "kafka_utils.py created as new file (not stream_utils.py rename) so both coexist during dual-run Plans 1-4"
  - "TopicAlreadyExistsError (aiokafka 0.13.0) — not TopicExistsException (removed in 0.13.0)"
  - "Redpanda external listener on port 19092; internal 9092 for container-to-container only"
  - "env_prefix() uses period-separator (dev.indicators) vs Redis prefix() colon-separator (dev:indicators)"
  - "stream_keys.py dual-run: new topic_* functions added above existing Redis helpers; neither removed until Plan 5"

patterns-established:
  - "Topic naming: {env_name}.{event_type_dotted} e.g. dev.intelligence.i7"
  - "Message key: SYMBOL:TF for bar-level topics, SYMBOL-only for tick topics"
  - "KafkaProducerClient: inject bootstrap_servers; call start() before first publish; stop() in finally"
  - "KafkaConsumerClient: auto_offset_reset=latest for all live-data services; enable_auto_commit=True"
  - "Topic init: always catch TopicAlreadyExistsError AND 'already exists' str fallback"

requirements-completed: [KAFKA-01, KAFKA-02, KAFKA-03, KAFKA-04]

# Metrics
duration: 6min
completed: 2026-03-14
---

# Phase 30 Plan 01: Redpanda Infrastructure + Core Abstractions Summary

**aiokafka 0.13.0 wrappers (KafkaProducerClient/Consumer), Redpanda v25.3.10 container on port 19092, and 11 topic builders in stream_keys.py — transport foundation for Plans 2-4 service migration**

## Performance

- **Duration:** ~6 min
- **Started:** 2026-03-14T06:41:30Z
- **Completed:** 2026-03-14T06:46:52Z
- **Tasks:** 3
- **Files modified:** 9 (5 created, 4 modified + 1 deferred-items.md)

## Accomplishments

- KafkaProducerClient and KafkaConsumerClient wrappers match existing Redis service patterns (start/stop/publish lifecycle)
- Idempotent topic creation script creates all 11 topics with correct retention periods (7d general, 1d i7/i8)
- Redpanda v25.3.10 added to docker-compose alongside DragonflyDB for dual-run period
- stream_keys.py extended with topic_* builders and message_key() helper; all existing Redis functions preserved
- aiokafka importable in venv; Settings.kafka_bootstrap_servers = "localhost:19092"
- 6 new kafka tests + 17 new stream_keys tests all GREEN; 1751 unit tests pass (pre-existing failure out of scope)

## Task Commits

1. **Task 1: Wave 0 test stubs** - `a982ce1` (test)
2. **Task 2: kafka_utils.py + kafka_init_topics.py implementation** - `35ce40d` (feat)
3. **Task 3: stream_keys topic builders + Settings + docker-compose + aiokafka dep** - `a64378b` (feat)

## Files Created/Modified

- `/home/bg/dev/indicagent/src/core/kafka_utils.py` - KafkaProducerClient and KafkaConsumerClient wrappers
- `/home/bg/dev/indicagent/production/scripts/kafka_init_topics.py` - Idempotent creation of 11 Redpanda topics
- `/home/bg/dev/indicagent/src/core/stream_keys.py` - 11 topic_* builders + env_prefix() + message_key() added
- `/home/bg/dev/indicagent/src/config/settings.py` - kafka_bootstrap_servers field added
- `/home/bg/dev/indicagent/production/docker-compose.yml` - Redpanda v25.3.10 service + redpanda-data volume
- `/home/bg/dev/indicagent/requirements.txt` - aiokafka>=0.13.0 added
- `/home/bg/dev/indicagent/tests/unit/core/test_kafka_utils.py` - 4 producer/consumer tests
- `/home/bg/dev/indicagent/tests/unit/core/test_kafka_init_topics.py` - 2 topic creation tests
- `/home/bg/dev/indicagent/tests/unit/test_stream_keys.py` - 17 new topic_* and message_key assertions

## Decisions Made

- Used `TopicAlreadyExistsError` (not `TopicExistsException`) — the latter was removed in aiokafka 0.13.0
- Created `kafka_utils.py` as a new file rather than renaming `stream_utils.py` to allow both to coexist during the dual-run period (Plans 1-4)
- Redpanda external listener on port 19092 (not 9092) — host services cannot reach the internal Docker listener; `localhost:19092` is the bootstrap_servers default
- `env_prefix()` uses period separator (topic prefix convention) vs existing `prefix()` which uses colon (Redis convention) — both live in stream_keys.py under different names

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Updated test to use TopicAlreadyExistsError**
- **Found during:** Task 2 (implementing kafka_init_topics.py)
- **Issue:** Plan stub test used `from aiokafka.errors import TopicExistsException` — this class does not exist in aiokafka 0.13.0 (removed; replaced by `TopicAlreadyExistsError`)
- **Fix:** Updated `test_kafka_init_topics.py` to import and use `TopicAlreadyExistsError`; implemented `kafka_init_topics.py` to catch the same
- **Files modified:** tests/unit/core/test_kafka_init_topics.py, production/scripts/kafka_init_topics.py
- **Verification:** Both tests pass GREEN
- **Committed in:** `35ce40d` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - Bug: wrong exception class name in aiokafka 0.13.0)
**Impact on plan:** Necessary correctness fix. No scope creep.

## Issues Encountered

- Pre-existing test failure: `test_validate_equity_backfill.py::test_zero_count_exits_zero` — confirmed failing before Phase 30 began (git stash verification). Logged to `deferred-items.md`. Not caused by this plan's changes.

## User Setup Required

None — Redpanda container will start automatically with `docker compose up -d` in production/. Topics must be created by running `python -m production.scripts.kafka_init_topics [env_name]` once after Redpanda starts. No env vars needed (defaults work for local dev).

## Next Phase Readiness

- Plan 30-02 (Hot Tier + Intelligence Pipeline) can proceed: all transport abstractions are in place
- DragonflyDB remains running (dual-run) — Plans 02-04 migrate services one at a time
- Redpanda will need to be started before Plan 02 integration testing: `cd production && docker compose up -d redpanda`

---
*Phase: 30-redpanda-migration*
*Completed: 2026-03-14*
