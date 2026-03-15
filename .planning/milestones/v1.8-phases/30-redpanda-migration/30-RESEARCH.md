# Phase 30: Redpanda Migration - Research

**Researched:** 2026-03-13
**Domain:** aiokafka + Redpanda — asyncio Kafka client, single-node container, transport-layer service migration
**Confidence:** HIGH (aiokafka official docs + Redpanda official docs verified)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **Client library:** aiokafka — replaces `redis.asyncio` streams entirely. No `confluent-kafka`.
- **Remove:** `redis[hiredis]` from requirements.txt (no remaining Redis dependency after migration).
- **Infra:** Redpanda single container in `production/docker-compose.yml`. Replaces DragonflyDB container.
- **Ports:** 9092 (Kafka), 9644 (admin/metrics), 8082 (HTTP proxy — optional).
- **Image:** `redpandadata/redpanda:latest` official image.
- **Topic creation:** dedicated topic init script run at startup.
- **Topic design:** one topic per event type, message key = `SYMBOL:TF`. `{env}.` prefix from `settings.env_name`.
- **Topic mapping:** See full table in CONTEXT.md decisions section.
- **stream_keys.py rewrite:** replace Redis key builders with Kafka topic + message key helpers.
- **stream_utils.py rewrite:** replace XGROUP_CREATE/XGROUP_SETID with aiokafka helpers.
- **Consumer group creation:** implicit in Kafka — just subscribe and commit offsets.
- **`ensure_consumer_group_with_reset()` removed entirely.**
- **`price:SYMBOL:latest` replacement:** `_live_quotes` in-process dict in signal_generator_service; TWS ticks feed it.
- **All Redis-backed caches (drift, llm scores, setup performance weights) replaced with in-process dicts or DB-backed alternatives.**
- **5-plan breakdown:** locked — see CONTEXT.md Plan 1-5 breakdown.
- **Dual-run strategy:** DragonflyDB stays alongside Redpanda through Plans 1-4; removed in Plan 5.
- **`auto_offset_reset="latest"` for live-data-only services.**
- **Testing:** mock aiokafka producer/consumer; all 1659 existing tests must continue to pass.
- **What does NOT change:** IntelligenceEvent schema, I1–I8 plugins, TimescaleDB, IBKR/TWS, Dashboard UI, Prometheus metrics.

### Claude's Discretion

- Exact Redpanda container config (single-node, listeners, etc.)
- Topic partition count (default 1 per topic for single-node dev/prod)
- Retention period per topic (7 days default is reasonable)
- Whether to create `src/core/kafka_utils.py` or rename `stream_utils.py` in-place
- Exact aiokafka producer/consumer wrapper API (keep similar to current redis stream API where possible)

### Deferred Ideas (OUT OF SCOPE)

- Schema registry integration (Redpanda ships one; deferred — Pydantic enforces schemas in-process)
- DragonflyDB re-addition for tick SaaS fan-out (add only when tick streaming SaaS is a real product feature)
- Redpanda multi-node cluster (single-node for current scale)
- Kafka consumer lag monitoring in Prometheus/Grafana (after migration is stable)
</user_constraints>

---

## Summary

This is a pure transport-layer migration: replace `redis.asyncio` stream publish/consume with `aiokafka` Kafka publish/consume. The business logic — I1–I8 plugins, IntelligenceEvent schema, TimescaleDB — is untouched. The entire stream abstraction lives in two files (51-line `stream_utils.py` + 136-line `stream_keys.py`) plus `~20-50 lines per service`. The migration scope is well-bounded and mechanical.

aiokafka 0.13.0 (released 2026-01-02) is the current version, requires Python >=3.10, and is a drop-in async Kafka client. Its lifecycle pattern (`await producer.start()` / `await producer.stop()`) mirrors the existing Redis client connect/close pattern used in all 8 services. Consumer groups are implicit — create `AIOKafkaConsumer(group_id="...")` and call `start()`. No `XGROUP_CREATE` equivalent.

Redpanda is a single-binary C++ Kafka-compatible broker. For our setup — systemd services on the host connecting to a Docker container — the critical listener config is: Redpanda exposes port 19092 externally (host-accessible) while services set `bootstrap_servers="localhost:19092"`. The internal listener (9092) is for container-to-container communication. The `--mode dev-container` flag limits to 1 CPU core.

**Primary recommendation:** Use `kafka_utils.py` (new file, not rename) so both redis-based `stream_utils.py` and the new file coexist during the Plan 1-4 dual-run period. Rename only in Plan 5 when DragonflyDB is removed.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| aiokafka | 0.13.0 | Async Kafka producer/consumer/admin | Pure asyncio, no JVM dependency, Kafka-compatible, matches existing async service pattern |
| redpandadata/redpanda | v25.3.x (latest) | Kafka-compatible event broker | Single binary, C++, no ZooKeeper, Prometheus metrics built-in |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| aiokafka.admin (AIOKafkaAdminClient + NewTopic) | same | Topic creation at startup | Plan 1 topic init script |
| mockafka-py | latest | In-memory Kafka mock for unit tests | Optional — AsyncMock on producer/consumer is simpler for this codebase's existing test style |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| aiokafka | confluent-kafka | confluent-kafka is C extension, not pure asyncio — worse fit for our async services |
| aiokafka | kafka-python | kafka-python is sync; requires thread executor wrapper |

**Installation:**
```bash
# Add to requirements.txt:
aiokafka>=0.13.0

# Remove from requirements.txt:
# redis[hiredis]>=7.1.0
```

---

## Architecture Patterns

### Recommended Project Structure Changes
```
src/core/
├── stream_keys.py      → rewritten: topic names + message key builders (replaces Redis key helpers)
├── stream_utils.py     → kept during dual-run (Plans 1-4), deleted in Plan 5
├── kafka_utils.py      → NEW: aiokafka producer/consumer helpers (the new stream_utils.py)
└── service_utils.py    → unchanged

production/
├── scripts/
│   └── kafka_init_topics.py   → NEW: topic creation script (run once at startup)
└── docker-compose.yml  → Redpanda container added (Plan 1), DragonflyDB removed (Plan 5)
```

### Pattern 1: Producer (publish a message)

The current pattern is `await redis_client.xadd(stream_key, fields, maxlen=N)`.
The Kafka replacement sends bytes, with optional key for partition routing.

```python
# Source: aiokafka official docs (https://aiokafka.readthedocs.io/)
import json
from aiokafka import AIOKafkaProducer

# At service startup:
producer = AIOKafkaProducer(bootstrap_servers="localhost:19092")
await producer.start()

# Per message (equivalent to redis xadd):
topic = "dev.indicators"
key = b"ES:1m"                          # SYMBOL:TF — routes to same partition
value = json.dumps(msg_dict).encode()   # dict → bytes
await producer.send_and_wait(topic, value=value, key=key)

# At service shutdown:
await producer.stop()
```

**Key serialization note:** Both `key` and `value` must be `bytes`. The current Redis approach sends `dict[str, str]` with `xadd`. For Kafka, serialize the entire message dict as JSON bytes for `value`. The `key` is just `b"SYMBOL:TF"`.

### Pattern 2: Consumer (consume messages in a group)

The current pattern is `await redis_client.xreadgroup(group, consumer, streams, count=10, block=1000)` then `xack`.
The Kafka replacement subscribes once and iterates.

```python
# Source: aiokafka official docs (https://aiokafka.readthedocs.io/en/stable/examples/group_consumer.html)
from aiokafka import AIOKafkaConsumer

# At service startup:
consumer = AIOKafkaConsumer(
    "dev.indicators",               # topic name(s) — varargs
    bootstrap_servers="localhost:19092",
    group_id="indicator_group",     # consumer group — offsets tracked durably
    auto_offset_reset="latest",     # live-data-only services: skip old messages
    enable_auto_commit=True,        # default True — commits every auto_commit_interval_ms (5000)
)
await consumer.start()

# Main consume loop:
try:
    async for msg in consumer:
        # msg.topic, msg.partition, msg.offset, msg.key, msg.value
        payload = json.loads(msg.value)
        symbol_tf = msg.key.decode() if msg.key else None  # e.g. "ES:1m"
        symbol, tf = symbol_tf.split(":", 1) if symbol_tf else (None, None)
        await process(symbol, tf, payload)
finally:
    await consumer.stop()
```

**No `xack` needed:** With `enable_auto_commit=True` (default), aiokafka commits offsets automatically every 5 seconds. This is equivalent to xack for our services that process-and-forget.

**`auto_offset_reset` decision per service:**
- `"latest"` (default) — all live-data services: indicator, market_analysis, signal_generator, signal_lifecycle, ai_narrative, feature_writer, llm_writer
- No service needs `"earliest"` in the current architecture; the warmup pattern (reading history from DB) replaces the Redis `xrevrange` warmup

### Pattern 3: Multi-topic consumer (services consuming multiple topics)

Several services consume from multiple topics simultaneously. With Redis, this was a single `xreadgroup` call with a dict of all streams. With aiokafka, subscribe to multiple topics in one consumer.

```python
# Source: aiokafka docs — AIOKafkaConsumer accepts multiple topic args
consumer = AIOKafkaConsumer(
    "dev.intelligence",
    "dev.market.ticks",    # for signal_generator: needs both intelligence + ticks
    bootstrap_servers="localhost:19092",
    group_id="signal_generator_group",
    auto_offset_reset="latest",
)
await consumer.start()

async for msg in consumer:
    if msg.topic == "dev.intelligence":
        await handle_intelligence(msg)
    elif msg.topic == "dev.market.ticks":
        await handle_tick(msg)    # update _live_quotes dict
```

### Pattern 4: Topic creation (Plan 1 init script)

```python
# Source: https://dfrojas.com/software/creating-kafka-topics-with-aiokafka-python.html (verified 2026-03)
import asyncio
from contextlib import asynccontextmanager
from aiokafka.admin import AIOKafkaAdminClient, NewTopic

TOPICS = [
    ("dev.market.ticks",        1, "604800000"),  # 7 days ms
    ("dev.market.bars",         1, "604800000"),
    ("dev.indicators",          1, "604800000"),
    ("dev.intelligence",        1, "604800000"),
    ("dev.intelligence.i7",     1, "86400000"),   # 1 day (high-volume enrichment)
    ("dev.intelligence.i8",     1, "86400000"),
    ("dev.signals",             1, "604800000"),
    ("dev.signals.aggregated",  1, "604800000"),
    ("dev.narratives",          1, "604800000"),
    ("dev.llm.calls",           1, "604800000"),
    ("dev.llm.outcomes",        1, "604800000"),
]

async def create_topics(bootstrap_servers: str) -> None:
    client = AIOKafkaAdminClient(bootstrap_servers=bootstrap_servers)
    await client.start()
    try:
        new_topics = [
            NewTopic(
                name=name,
                num_partitions=partitions,
                replication_factor=1,
                topic_configs={"retention.ms": retention_ms},
            )
            for name, partitions, retention_ms in TOPICS
        ]
        await client.create_topics(new_topics)
    except Exception as e:
        if "already exists" in str(e).lower() or "TopicExistsException" in str(e):
            pass  # idempotent — topics already created
        else:
            raise
    finally:
        await client.close()
```

**Critical:** `await client.start()` must be called before `create_topics()`. The async admin client does NOT auto-initialize on construction (unlike the sync client).

### Pattern 5: Shutdown lifecycle (service teardown)

Current pattern: `await redis_client.close()` in `finally` block.
New pattern: `await producer.stop()` and `await consumer.stop()`.

```python
# Standard asyncio service shutdown pattern with aiokafka
async def run(self):
    self._producer = AIOKafkaProducer(bootstrap_servers=self.bootstrap_servers)
    self._consumer = AIOKafkaConsumer(
        self.topic,
        bootstrap_servers=self.bootstrap_servers,
        group_id=self.group_id,
        auto_offset_reset="latest",
    )
    await self._producer.start()
    await self._consumer.start()
    try:
        async for msg in self._consumer:
            if self.shutdown_requested:
                break
            await self._process(msg)
    finally:
        await self._consumer.stop()   # leaves consumer group, commits pending offsets
        await self._producer.stop()   # flushes pending sends, closes connections
```

**Gotcha:** `consumer.stop()` automatically commits pending offsets and leaves the consumer group cleanly. Do NOT call `consumer.stop()` inside the `async for` loop — call it in `finally`.

### Pattern 6: SSE endpoint migration (Plan 4)

Current SSE uses `redis.xrevrange` (snapshot) then `redis.xread` (live loop). The Kafka replacement:
- **Snapshot:** No direct equivalent to `xrevrange`. Options: (a) store last N messages in a service-level in-memory ring buffer that SSE reads on connect, or (b) use `auto_offset_reset="earliest"` on a short-lived consumer per SSE connection and read until caught up. Option (a) is simpler; option (b) adds per-connection overhead.
- **Live loop:** `async for msg in consumer:` with per-SSE-client consumer or a shared consumer that fan-outs via asyncio Queues.

**Recommended SSE architecture:** One background consumer per topic set per symbol (shared across SSE clients), pushing to `asyncio.Queue` per connected SSE client. SSE clients subscribe to queues, not directly to Kafka.

```python
# Shared consumer → per-client queue fan-out
class KafkaSSEBroadcaster:
    def __init__(self):
        self._queues: list[asyncio.Queue] = []

    async def run(self, consumer: AIOKafkaConsumer):
        async for msg in consumer:
            for q in self._queues:
                await q.put(msg)

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._queues.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        self._queues.remove(q)
```

### Anti-Patterns to Avoid
- **One consumer per SSE client:** Each consumer creates a Kafka connection and joins a consumer group. With N concurrent dashboard users, N Kafka consumers is expensive. Use the fan-out queue pattern above.
- **Calling `consumer.start()` from within an `async for` loop:** `start()` must be called once before the loop.
- **`decode_responses=True` equivalent:** Kafka returns raw bytes — always decode `msg.value` with `json.loads(msg.value.decode())`. No auto-decode like Redis `decode_responses=True`.
- **`maxlen` on publish:** Redis `xadd` took `maxlen` per-publish. Kafka retention is set at topic-creation time, not per-message. Remove all `maxlen` arguments from publish calls.
- **Passing `api_version` to aiokafka 0.13.0:** Breaking change in 0.13.0 — the `api_version` parameter has been removed. API versions are now resolved automatically at broker connection. Do not pass it.
- **Using topic as the stream key lookup:** The current `_stream_map` in indicator_service maps Redis stream name → (symbol, tf). With Kafka, use `msg.key.decode().split(":", 1)` instead — the message key IS the routing information.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Consumer group offset tracking | Custom Redis key for "last processed offset" | aiokafka built-in group offset commit | Kafka tracks offsets durably per group; no manual tracking needed |
| Message ordering per instrument | Custom partitioning logic | `key=b"SYMBOL:TF"` in producer | Kafka guarantees order within a partition; same key → same partition |
| Graceful consumer shutdown | Custom drain-and-stop logic | `await consumer.stop()` | Commits pending offsets and leaves group cleanly |
| Topic creation idempotency | Check-then-create pattern | Exception handling on `TopicExistsException` | create_topics raises if topic exists; catch and continue |
| Service restart replay prevention | `ensure_consumer_group_with_reset()` (current Redis workaround) | `auto_offset_reset="latest"` | Kafka consumer groups resume from committed offset; `latest` only applies when no committed offset exists (first run) |

**Key insight:** The `ensure_consumer_group_with_reset()` pattern exists because Redis consumer groups can get stuck replaying old backlog. This problem does not exist in Kafka — consumer groups track committed offsets durably. A service restart resumes from the last committed offset, not from the tail. `auto_offset_reset="latest"` only controls first-time behavior when no committed offset exists.

---

## Common Pitfalls

### Pitfall 1: Host-to-Docker listener mismatch
**What goes wrong:** Services running on the host (systemd) connect to `localhost:9092` but Redpanda's internal listener is only accessible from within the Docker network. Services can't reach the broker.
**Why it happens:** Redpanda distinguishes internal (container-to-container) and external (host-accessible) listeners. The internal listener `redpanda-0:9092` only resolves inside Docker's bridge network.
**How to avoid:** Map the external listener to the host. In docker-compose.yml, Redpanda's external port is 19092. Services on the host use `bootstrap_servers="localhost:19092"`. Add `KAFKA_BOOTSTRAP_SERVERS` to Settings.
**Warning signs:** `NoBrokersAvailable` or `KafkaConnectionError` on service startup.

### Pitfall 2: Message serialization — dict vs bytes
**What goes wrong:** Current Redis `xadd` accepts `dict[str, str]` and stores flat string fields. Kafka requires `bytes` for both key and value.
**Why it happens:** The transport model is fundamentally different: Redis streams store field-value maps; Kafka stores opaque byte blobs.
**How to avoid:** In `build_i1_message()` and equivalent functions, the return type changes from `dict[str, str]` to either `bytes` (JSON-encoded) or the dict is serialized by the publish helper. The cleaner approach: publish helpers in `kafka_utils.py` accept the dict and serialize internally, keeping service code unchanged.
**Warning signs:** `TypeError: a bytes-like object is required` on `producer.send_and_wait()`.

### Pitfall 3: Warmup pattern replacement
**What goes wrong:** Current services call `redis.xrevrange(stream, count=N)` at startup to warm up bar history. No Redpanda equivalent — `xrevrange` does not exist in Kafka.
**Why it happens:** Redis Streams allowed time-based seek and reverse iteration. Kafka offset-based access requires knowing specific offsets or using `seek_to_beginning()` on specific partitions.
**How to avoid:** For indicator_service warmup, the correct Kafka approach is to seek to the beginning with a time-limited read, OR (simpler) read warmup bars directly from `market_data_ohlcv` in TimescaleDB at startup. The DB-based warmup is already the pattern used by signal_generator_service for DB seed on restart (Phase 26). Extend that pattern to indicator_service warmup.
**Warning signs:** Indicator service fires signals before enough bars are accumulated; I1 warmup bar count is 0 at startup.

### Pitfall 4: SSE snapshot (no xrevrange equivalent)
**What goes wrong:** Current SSE endpoint calls `redis.xrevrange(stream, count=2)` per stream on connect to send the client the most recent data immediately. Kafka has no equivalent single-call "get last N messages from a stream I'm not yet consuming."
**Why it happens:** Kafka's consumer model requires subscribing, starting, and polling — there is no random-access read-last-N by stream name.
**How to avoid:** Two options: (a) maintain a per-topic in-memory ring buffer in the SSE broadcaster that new connections drain before switching to live, (b) accept the UX change — clients start from live data only (no snapshot on reconnect). Option (a) is the correct solution to preserve existing UX. Keep the ring buffer small (last 30 entries per topic, same as current `count=30` for indicators).
**Warning signs:** Dashboard shows empty state on fresh load until next bar fires.

### Pitfall 5: `enable_auto_commit` and duplicate processing
**What goes wrong:** With `enable_auto_commit=True` (default), if a service crashes mid-processing, messages between the last auto-commit and the crash will be reprocessed on restart.
**Why it happens:** Auto-commit happens every 5 seconds regardless of whether processing completed.
**How to avoid:** For this migration, `enable_auto_commit=True` is acceptable — all services use `ON CONFLICT DO NOTHING` in their DB writes, making reprocessing safe. No change needed from the default.
**Warning signs:** Duplicate entries in `intelligence_features` or `signal_ledger` — already guarded by `ON CONFLICT DO NOTHING`.

### Pitfall 6: `ai_narrative_service` llm_scores_cache migration
**What goes wrong:** `ai_narrative_service` reads and writes `llm_scores_cache` using Redis HSET/HGETALL. This is NOT a stream operation — it's a key/value cache that survives across requests. Simply removing Redis will break the LLM model selection logic.
**Why it happens:** The llm_scores_cache is one of three Redis key/value (non-stream) uses that must be replaced in Plan 5.
**How to avoid:** Replace with in-process dict `self._llm_scores_cache: dict[str, dict]` in ai_narrative_service. The cache re-warms from `llm_model_scores` DB table on startup (same pattern as setup_performance — already DB-backed). `llm_writer_service` writes to the DB table; ai_narrative reads from it at startup + refreshes periodically.

### Pitfall 7: `drift_monitor_service` Redis dependency
**What goes wrong:** `drift_monitor_service` writes KS drift severity to `drift:ks:SYMBOL:TF` Redis keys. `signal_generator_service` reads those keys via `_read_drift_penalty()`. After DragonflyDB removal, both break.
**Why it happens:** The drift penalty mechanism uses Redis as a shared state store between two services.
**How to avoid:** In Plan 5, replace with a DB-backed pattern: drift_monitor writes severity to a `drift_state` table (or updates a column in an existing table); signal_generator reads from DB at the start of each bar evaluation, or maintains an in-memory dict refreshed periodically. The in-memory refresh approach (every 4h, same as current drift check interval) is simplest.

### Pitfall 8: `setup_performance_weights_cache` Redis dependency
**What goes wrong:** signal_generator reads perf weights via `redis_client.get(setup_performance_weights_cache(...))`. This is a Redis string key (not a stream).
**Why it happens:** The weights cache was written to Redis for fast access, but the source of truth is the `setup_performance` DB table.
**How to avoid:** In Plan 5, remove the Redis cache entirely. signal_generator reads directly from `setup_performance` DB table at startup and every 60 min, using the existing `_load_perf_weights()` method. Change the method body from Redis GET to an asyncpg query against `setup_performance` where `sample_size >= 30`.

---

## Code Examples

Verified patterns from official sources:

### Producer wrapper (kafka_utils.py)
```python
# Pattern: keep the interface similar to current stream_utils.py helpers
# Source: aiokafka official docs
import json
from aiokafka import AIOKafkaProducer

class KafkaProducerClient:
    """Thin wrapper around AIOKafkaProducer matching current service patterns."""

    def __init__(self, bootstrap_servers: str):
        self._bootstrap = bootstrap_servers
        self._producer: AIOKafkaProducer | None = None

    async def start(self) -> None:
        self._producer = AIOKafkaProducer(bootstrap_servers=self._bootstrap)
        await self._producer.start()

    async def stop(self) -> None:
        if self._producer:
            await self._producer.stop()

    async def publish(self, topic: str, msg: dict, key: str | None = None) -> None:
        """Publish dict message to topic with optional routing key."""
        value = json.dumps(msg).encode()
        key_bytes = key.encode() if key else None
        await self._producer.send_and_wait(topic, value=value, key=key_bytes)
```

### Consumer wrapper (kafka_utils.py)
```python
# Source: aiokafka official docs
import json
from collections.abc import AsyncGenerator
from aiokafka import AIOKafkaConsumer

class KafkaConsumerClient:
    """Thin wrapper around AIOKafkaConsumer matching current service patterns."""

    def __init__(
        self,
        *topics: str,
        bootstrap_servers: str,
        group_id: str,
        auto_offset_reset: str = "latest",
    ):
        self._consumer = AIOKafkaConsumer(
            *topics,
            bootstrap_servers=bootstrap_servers,
            group_id=group_id,
            auto_offset_reset=auto_offset_reset,
            enable_auto_commit=True,
        )

    async def start(self) -> None:
        await self._consumer.start()

    async def stop(self) -> None:
        await self._consumer.stop()

    async def messages(self) -> AsyncGenerator[tuple[str, str | None, dict], None]:
        """Yield (topic, key, payload_dict) tuples."""
        async for msg in self._consumer:
            topic = msg.topic
            key = msg.key.decode() if msg.key else None
            try:
                payload = json.loads(msg.value)
            except Exception:
                continue
            yield topic, key, payload
```

### Topic naming (stream_keys.py rewrite)
```python
# New stream_keys.py — topic names and message keys
# Source: CONTEXT.md locked decisions

def env_prefix(env_name: str) -> str:
    """Return topic prefix: 'dev.' or '' (empty for production with no env_name)."""
    return f"{env_name}." if env_name else ""

def topic_market_ticks(env: str) -> str:
    return f"{env_prefix(env)}market.ticks"

def topic_market_bars(env: str) -> str:
    return f"{env_prefix(env)}market.bars"

def topic_indicators(env: str) -> str:
    return f"{env_prefix(env)}indicators"

def topic_intelligence(env: str) -> str:
    return f"{env_prefix(env)}intelligence"

def topic_intelligence_i7(env: str) -> str:
    return f"{env_prefix(env)}intelligence.i7"

def topic_intelligence_i8(env: str) -> str:
    return f"{env_prefix(env)}intelligence.i8"

def topic_signals(env: str) -> str:
    return f"{env_prefix(env)}signals"

def topic_signals_aggregated(env: str) -> str:
    return f"{env_prefix(env)}signals.aggregated"

def topic_narratives(env: str) -> str:
    return f"{env_prefix(env)}narratives"

def topic_llm_calls(env: str) -> str:
    return f"{env_prefix(env)}llm.calls"

def topic_llm_outcomes(env: str) -> str:
    return f"{env_prefix(env)}llm.outcomes"

def message_key(symbol: str, timeframe: str | None = None) -> str:
    """Routing key for partitioning. SYMBOL:TF for most topics; SYMBOL-only for ticks."""
    if timeframe:
        return f"{symbol}:{timeframe}"
    return symbol
```

### Redpanda docker-compose service block
```yaml
# Source: Redpanda official docs (https://docs.redpanda.com/redpanda-labs/docker-compose/single-broker/)
# Adapted for our use: services run on host (not in Docker), so external port 19092
# is the bootstrap_servers address. Internal 9092 is unused by our services.

  redpanda:
    image: docker.redpanda.com/redpandadata/redpanda:v25.3.10
    container_name: redpanda
    restart: unless-stopped
    command:
      - redpanda
      - start
      - --kafka-addr internal://0.0.0.0:9092,external://0.0.0.0:19092
      - --advertise-kafka-addr internal://redpanda:9092,external://localhost:19092
      - --pandaproxy-addr internal://0.0.0.0:8082,external://0.0.0.0:18082
      - --advertise-pandaproxy-addr internal://redpanda:8082,external://localhost:18082
      - --schema-registry-addr internal://0.0.0.0:8081,external://0.0.0.0:18081
      - --rpc-addr redpanda:33145
      - --advertise-rpc-addr redpanda:33145
      - --mode dev-container
      - --smp 1
      - --default-log-level=info
    ports:
      - "19092:19092"   # Kafka API — host services use localhost:19092
      - "18082:18082"   # HTTP proxy (optional)
      - "18081:18081"   # Schema registry (optional, for future use)
      - "9644:9644"     # Admin API + Prometheus metrics
    volumes:
      - redpanda-data:/var/lib/redpanda/data
```

**Settings.py addition:**
```python
# Add to Settings class:
kafka_bootstrap_servers: str = Field(
    default="localhost:19092",
    validation_alias="KAFKA_BOOTSTRAP_SERVERS",
)
```

### Unit test mock pattern
```python
# Source: existing test patterns in tests/unit/service_tests/ — adapted for aiokafka
# Uses AsyncMock to replace AIOKafkaProducer/Consumer — same approach as current redis mocks

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

@pytest.mark.asyncio
async def test_service_publishes_to_correct_topic():
    from services.indicator_service import IndicatorService

    svc = IndicatorService()
    mock_producer = AsyncMock()
    mock_producer.send_and_wait = AsyncMock()
    svc._producer = mock_producer

    # Exercise the publish path
    await svc._publish_indicators("ES", "1m", {"rsi_14": 58.3})

    mock_producer.send_and_wait.assert_awaited_once()
    call_args = mock_producer.send_and_wait.call_args
    assert call_args[0][0] == "dev.indicators"  # topic
    assert b"ES:1m" in call_args[1]["key"]       # routing key


@pytest.mark.asyncio
async def test_service_consumer_group_setup():
    from services.indicator_service import IndicatorService

    svc = IndicatorService()
    mock_consumer = AsyncMock()
    mock_consumer.start = AsyncMock()

    with patch("services.indicator_service.AIOKafkaConsumer", return_value=mock_consumer):
        await svc._setup_consumer()

    mock_consumer.start.assert_awaited_once()
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Redis XREADGROUP per stream in loop | Single xreadgroup call with all streams dict | market_analysis_service refactor | This pattern does NOT carry over to Kafka — Kafka multi-topic consumer is cleaner |
| `ensure_consumer_group_with_reset()` | Implicit Kafka consumer group offset tracking | Phase 30 | Entire function removed; no replacement needed |
| Per-message `maxlen` in xadd | Topic-level retention set at creation time | Phase 30 | `get_stream_maxlen()` function removed; retention configured in topic init script |
| Redis hash for `price:SYMBOL:latest` | In-process `_live_quotes` dict | Phase 30 Plan 5 | Simpler, faster, no network hop for live quote lookup |

**Deprecated/outdated:**
- `ensure_consumer_group_with_reset()`: remove in Plan 1 for new code, delete entirely in Plan 5
- `get_stream_maxlen()`: remove in Plan 1; retention is in topic init script
- `quote_latest()` helper: remove in Plan 5
- `setup_performance_weights_cache()` helper: remove in Plan 5 (replaced by direct DB read)
- `drift_ks()` and `drift_cusum()` helpers: remove in Plan 5 (replaced by DB-backed drift state)
- `llm_scores_cache()` helper: remove in Plan 5 (replaced by in-process dict + DB re-warm)

---

## Open Questions

1. **Warmup bars from DB vs Kafka seek**
   - What we know: indicator_service currently calls `xrevrange` to warm up bar history at startup; this has no direct Kafka equivalent.
   - What's unclear: Whether to implement DB-based warmup (read from `market_data_ohlcv`) or a Kafka seek-based approach (seek to N bars back on each partition).
   - Recommendation: DB-based warmup — `market_data_ohlcv` has full OHLCV history; read the last `min_bars_for_tf(tf) * 2` rows per symbol/TF at startup. This is what signal_generator already does (Phase 26). Consistent pattern, no Kafka-specific seek complexity.

2. **drift_monitor_service inter-service state sharing**
   - What we know: drift_monitor writes `severity` strings to Redis keys; signal_generator reads them per bar. After Redis removal, this inter-service communication breaks.
   - What's unclear: Whether to use DB table, Kafka topic, or in-process dict with API polling.
   - Recommendation: Add a `drift_state` table (or lightweight JSON column to existing table) and have signal_generator refresh its in-memory penalty dict every 4h — matching drift_monitor's check interval. No new Kafka topic needed for this low-frequency state.

3. **SSE snapshot UX fidelity**
   - What we know: Current SSE sends last 1-30 entries per stream on fresh connect (xrevrange snapshot). No Kafka xrevrange equivalent.
   - What's unclear: Whether to maintain per-topic in-memory ring buffers in the SSE broadcaster or accept live-only behavior.
   - Recommendation: Implement a per-topic deque(maxlen=30) in the SSE broadcaster. Populated by the shared consumer. New SSE connections drain the deque then switch to the live queue. This preserves current UX at low memory cost.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.4.0 + pytest-asyncio |
| Config file | `pytest.ini` or `pyproject.toml` (check project root) |
| Quick run command | `.venv/bin/pytest tests/unit/ -v -x` |
| Full suite command | `.venv/bin/pytest tests/unit/ tests/integration/ -v` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| KAFKA-01 | `kafka_utils.py` KafkaProducerClient start/stop/publish | unit | `.venv/bin/pytest tests/unit/core/test_kafka_utils.py -x` | ❌ Wave 0 |
| KAFKA-02 | `kafka_utils.py` KafkaConsumerClient start/stop/messages iteration | unit | `.venv/bin/pytest tests/unit/core/test_kafka_utils.py -x` | ❌ Wave 0 |
| KAFKA-03 | `stream_keys.py` topic name builders return correct `env.topic` strings | unit | `.venv/bin/pytest tests/unit/test_stream_keys.py -x` | ✅ (extend) |
| KAFKA-04 | Topic init script creates all 11 topics idempotently | unit | `.venv/bin/pytest tests/unit/core/test_kafka_init_topics.py -x` | ❌ Wave 0 |
| KAFKA-05 | indicator_service publishes to `dev.indicators` with key `SYMBOL:TF` | unit | `.venv/bin/pytest tests/unit/service_tests/test_indicator_service.py -x` | ✅ (extend) |
| KAFKA-06 | signal_generator `_live_quotes` updated from ticks topic | unit | `.venv/bin/pytest tests/unit/service_tests/test_signal_generator_service.py -x` | ✅ (extend) |
| KAFKA-07 | SSE broadcaster fan-out queue pattern | unit | `.venv/bin/pytest tests/unit/test_sse_stream_builder.py -x` | ✅ (extend) |
| KAFKA-08 | All 1659 existing unit tests still pass after migration | unit | `.venv/bin/pytest tests/unit/ -v` | ✅ |

### Sampling Rate
- **Per task commit:** `.venv/bin/pytest tests/unit/ -x -q`
- **Per wave merge:** `.venv/bin/pytest tests/unit/ -v`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/unit/core/test_kafka_utils.py` — covers KAFKA-01, KAFKA-02: producer/consumer wrapper unit tests
- [ ] `tests/unit/core/test_kafka_init_topics.py` — covers KAFKA-04: topic creation script with mocked AIOKafkaAdminClient
- [ ] `production/scripts/kafka_init_topics.py` — the actual topic creation script (Plan 1)
- [ ] `src/core/kafka_utils.py` — producer/consumer wrappers (Plan 1)

*(Existing `tests/unit/test_stream_keys.py` will be extended in Plan 1; `tests/unit/core/test_stream_utils.py` will be replaced or removed in Plan 5)*

---

## Sources

### Primary (HIGH confidence)
- aiokafka official docs (https://aiokafka.readthedocs.io/) — AIOKafkaProducer, AIOKafkaConsumer, AIOKafkaAdminClient API
- aiokafka group_consumer example (https://aiokafka.readthedocs.io/en/stable/examples/group_consumer.html) — consumer group pattern
- aiokafka API reference (https://aiokafka.readthedocs.io/en/stable/api.html) — parameter signatures
- PyPI aiokafka (https://pypi.org/project/aiokafka/) — version 0.13.0, released 2026-01-02
- Redpanda official single-broker docs (https://docs.redpanda.com/redpanda-labs/docker-compose/single-broker/) — docker-compose flags, listener config, version v25.3.10
- Project CONTEXT.md — all locked decisions (topic mapping, 5-plan breakdown, library choice)

### Secondary (MEDIUM confidence)
- aiokafka AdminClient topic creation (https://dfrojas.com/software/creating-kafka-topics-with-aiokafka-python.html) — `AIOKafkaAdminClient` + `NewTopic` example (verified against aiokafka admin module)
- aiokafka 0.13.0 changelog — `api_version` parameter removed (verified via search)
- Kafka `retention.ms` topic config (https://kafka.apache.org/41/configuration/topic-configs/) — topic retention configuration key names

### Tertiary (LOW confidence)
- mockafka-py (https://github.com/alm0ra/mockafka-py) — in-memory Kafka mock; flagged as optional since AsyncMock pattern is simpler

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — aiokafka 0.13.0 and Redpanda v25.3.x confirmed current via official sources
- Architecture: HIGH — aiokafka API verified against official docs; Redpanda docker config from official lab
- Pitfalls: HIGH — host/container listener mismatch and message serialization change are verified from docs and code inspection; warmup and SSE snapshot pitfalls are MEDIUM (derived from code analysis)
- Redis non-stream dependencies: HIGH — identified by direct code inspection (drift_ks, llm_scores_cache, setup_performance_weights_cache all verified in service files)

**Research date:** 2026-03-13
**Valid until:** 2026-04-13 (aiokafka is stable; Redpanda API is stable; 30 days)
