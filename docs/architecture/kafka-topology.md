# Kafka/Redpanda Topology Architecture

**Version:** 2.8
**Last Updated:** 2026-05-28

---

## Overview

IndicAgent uses Redpanda (Kafka-compatible) as the central message bus for the data pipeline. All real-time data flows through Kafka topics, which provide durability, replay capability, and decoupling between producers and consumers.

**Design principles:**
- Kafka is transport, not state (hot state lives in memory, cold state in DB)
- Topics use dot notation (no colons) via `stream_keys.py`
- Consumer groups enable parallel processing
- Retention tiers match data lifecycle (hot/buffer/cold)

---

## Redpanda Container

**Container:** `redpanda` (from `production/docker-compose.yml`)
**Ports:**
- `:9092` — Internal Kafka API (container-to-container)
- `:19092` — External Kafka API (host access)
- `:9644` — Admin API
- `:18843` — Schema Registry (if needed)

**Management commands:**
```bash
# List topics
docker exec redpanda rpk topic list

# Describe topic
docker exec redpanda rpk topic describe <topic-name>

# Consume topic (for debugging)
docker exec redpanda rpk topic consume <topic-name> --from-beginning

# Create topic
docker exec redpanda rpk topic create <topic-name> --partitions 1 --replicas 1

# Delete topic (use caution)
docker exec redpanda rpk topic delete <topic-name>
```

---

## Topic Catalog

### Market Data Topics

| Topic | Purpose | Producers | Consumers | Retention |
|-------|---------|-----------|-----------|-----------|
| `{env}.market.bars.raw.ibkr` | IBKR raw 5s RTB + 1m bars | `IBKRProviderAgent` | `ProviderMergerAgent` | 1h |
| `{env}.market.bars` | Canonical 1m bars | `ProviderMergerAgent` | `BarAggregator`, `IntelligencePipeline`, `BarWriter` | 24h |
| `{env}.market.bars.htf` | HTF bars (5m-1d) | `BarAggregatorAgent` | `BarWriter`, `IntelligencePipeline` | 7d |

### Intelligence Topics

| Topic | Purpose | Producers | Consumers | Retention |
|-------|---------|-----------|-----------|-----------|
| `{env}.intelligence.journal` | Full I1-I7 features (BarIntelligenceRecord) | `IntelligencePipelineAgent` | `FeatureWriter`, `FeatureSnapshotWriter`, `ParityAuditor` | 24h |
| `{env}.intelligence.i7.signals` | Winner I7 signals | `IntelligencePipelineAgent` | `SignalWriter`, `SignalTracker`, `AlphaSwarm` | 7d |

### Lifecycle Topics

| Topic | Purpose | Producers | Consumers | Retention |
|-------|---------|-----------|-----------|-----------|
| `{env}.lifecycle.transitions` | Signal state changes | `SignalTrackerComputeAgent` | `LifecycleWriterAgent` | 7d |

### Quality & Events

| Topic | Purpose | Producers | Consumers | Retention |
|-------|---------|-----------|-----------|-----------|
| `{env}.market.data.quality` | Provider quality side-channel | `ProviderMergerAgent` | (future consumers) | 24h |
| `{env}.market.events.gap_requests` | Gap fill requests | `BarAuditorAgent` | (future gap fill service) | 24h |

### DLQ Topics

| Topic | Purpose | Producers | Consumers | Retention |
|-------|---------|-----------|-----------|-----------|
| `{env}.intelligence.feature.writer.dlq` | Feature writer failures | `FeatureWriterAgent` | `DLQDrainAgent` | 7d |
| `{env}.intelligence.signal.writer.dlq` | Signal writer failures | `SignalWriterAgent` | `DLQDrainAgent` | 7d |
| `{env}.bar.writer.dlq` | Bar writer failures | `BarWriterAgent` | `DLQDrainAgent` | 7d |

### AI/LLM Topics

| Topic | Purpose | Producers | Consumers | Retention |
|-------|---------|-----------|-----------|-----------|
| `{env}.llm.calls` | LLM audit log entries | NarrativeCompute, AlphaSwarm | `LLMWriterAgent` | 7d |
| `{env}.llm.outcomes` | LLM outcome backfill | `LLMWriterAgent` | (internal) | 1d |

### Cross-Asset Topics

| Topic | Purpose | Producers | Consumers | Retention |
|-------|---------|-----------|-----------|-----------|
| `{env}.cross_asset` | Cross-asset spread dynamics | `CrossAssetService` | (future consumers) | 24h |

---

## Topic Naming Convention

All topics are constructed via `src/core/stream_keys.py`:

```python
def topic_stream_keys(topic_name: str, env_prefix: str = None) -> str:
    """Construct full topic key with env prefix"""
    env = env_prefix or Settings.indicagent_env
    return f"{env}.{topic_name}" if env else topic_name
```

**Pattern:** `{env}.{category}.{subcategory}.{name}`

**Examples:**
- `dev.market.bars`
- `dev.intelligence.journal`
- `dev.intelligence.i7.signals`

**Important:** Always use `stream_keys.py` — never hardcode topic strings.

---

## Consumer Groups

### Why Consumer Groups

Consumer groups enable:
- Parallel processing (multiple consumers per topic)
- Offset tracking (resume after restart)
- Load balancing (auto-rebalance on consumer join/leave)

### Active Consumer Groups

| Group | Topic | Consumers | Purpose |
|-------|-------|------------|---------|
| `feature_writer_group` | `intelligence.journal` | `FeatureWriterAgent` (1 instance) | Persist features to DB |
| `signal_writer_group` | `intelligence.i7.signals` | `SignalWriterAgent` (1 instance) | Persist signals to DB |
| `ai_narrative` | `narratives` | `NarrativeGroupComputeAgent` (1 instance) | Process I8 LLM events |
| `sse-consumer` | Various | API SSE router | Fanout to HTTP clients |

### Consumer Group Management

```bash
# List consumer groups
docker exec redpanda rpk group list

# Describe group (lag, offsets)
docker exec redpanda rpk group describe <group-name> --topic <topic>

# Reset offset (for reprocessing)
docker exec redpanda rpk group reset-offset <group> --topic <topic> -to-earliest
```

---

## Partitioning

### Current State

All topics use single-partition configuration:

```bash
# Topic creation
docker exec redpanda rpk topic create market.bars --partitions 1 --replicas 1
```

**Why single partition:**
- Ordering guarantees within topic (in-order message delivery)
- Simpler offset management
- Sufficient for current throughput (~4.5 bars/sec)

### When to Add Partitions

Consider adding partitions when:
- Single consumer can't keep up (consumer lag growing)
- Need parallel consumption (multiple instances of same service)
- Topic has high write rate requiring producer sharding

**Trade-offs:**
- Partitioning breaks ordering guarantees (per-partition ordering only)
- More complex offset management
- Rebalancing overhead

---

## Retention Policies

### Retention by Tier

| Tier | Retention | Rationale |
|------|-----------|-----------|
| Raw (RTB) | 1h | Debugging only; canonical bars persisted to DB |
| Canonical (1m) | 24h | Replay window for feature writers; DB is source of truth |
| HTF | 7d | Longer replay for longer timeframes |
| Intelligence | 24h | Feature writers batch; DB is source of truth |
| Signals | 7d | Signal replay and analysis |
| LLM | 7d | Audit trail for AI decisions |
| DLQ | 7d | Quarantine period |

### Setting Retention

```bash
# Create topic with retention
docker exec redpanda rpk topic create <name> --config retention.ms=86400000

# Update retention on existing topic
docker exec redpanda rpk topic alter-config <name> --set retention.ms=86400000
```

**Conversions:**
- 1 hour = 3,600,000 ms
- 1 day = 86,400,000 ms
- 7 days = 604,800,000 ms

---

## Producer Configuration

### aiokafka Settings

```python
from aiokafka import AIOKafkaProducer

producer = AIOKafkaProducer(
    bootstrap_servers=settings.kafka_bootstrap_servers,
    # Durability
    acks="all",  # Wait for all replicas
    retries=3,   # Retry on failure
    max_in_flight_requests_per_connection=5,
    # Batching
    batch_size=16384,
    linger_ms=10,
    # Compression
    compression_type="snappy",
)
```

**Key settings:**
- `acks="all"` — Wait for all replicas (durability)
- `retries=3` — Retry transient failures
- `compression_type="snappy"` — Reduce bandwidth

---

## Consumer Configuration

### aiokafka Settings

```python
from aiokafka import AIOKafkaConsumer

consumer = AIOKafkaConsumer(
    bootstrap_servers=settings.kafka_bootstrap_servers,
    group_id="feature_writer_group",
    # Offset management
    auto_offset_reset="earliest",  # Start from beginning on new group
    enable_auto_commit=False,      # Manual commit after processing
    # Poll settings
    max_poll_records=100,
    max_poll_interval_ms=300000,
)
```

**Key settings:**
- `auto_offset_reset="earliest"` — No data loss on new consumer
- `enable_auto_commit=False` — Commit only after successful processing
- `max_poll_interval_ms=300000` — 5min max between polls

---

## Performance Tuning

### Producer Tuning

**High throughput:**
```python
batch_size=32768,        # Larger batches
linger_ms=50,            # Wait longer for batching
compression_type="lz4",  # Better compression
```

**Low latency:**
```python
batch_size=16384,
linger_ms=0,             # Send immediately
compression_type="none",
```

### Consumer Tuning

**Reduce lag:**
```python
max_poll_records=200,    # Fetch more per poll
fetch_min_wait_ms=100,   # Faster fetch
```

**Memory efficiency:**
```python
max_poll_records=50,
fetch_max_bytes=1048576,  # 1MB
```

---

## Monitoring

### Consumer Lag

```bash
# Check lag for consumer group
docker exec redpanda rpk group describe feature_writer_group --topic intelligence.journal

# Lag shows in "lag" column (messages behind)
```

**Grafana query:**
```promql
# Consumer lag by agent
persistence_consumer_lag_records{agent_id=~".*-writer"}
```

### Topic Throughput

```bash
# Topic stats
docker exec redpanda rpk topic stats <topic-name>
```

**Grafana query:**
```promql
# Messages per second
rate(stream_messages_read_total[5m])
```

---

## Troubleshooting

### Consumer Not Receiving Messages

```bash
# Check consumer is in group
docker exec redpanda rpk group list

# Check topic has messages
docker exec redpanda rpk topic describe <topic> --partition 0

# Check consumer offset
docker exec redpanda rpk group describe <group> --topic <topic>
```

### High Consumer Lag

```bash
# Check lag
docker exec redpanda rpk group describe <group> --topic <topic>

# Check consumer is running
systemctl status indicant-<consumer-service>

# Check for slow DB writes (writer lag)
journalctl -u indicant-<writer> | grep "batch written"
```

### Topic Not Found

```bash
# Verify topic exists
docker exec redpanda rpk topic list | grep <topic>

# Check topic name has correct env prefix
# Should be: dev.market.bars (not market.bars)
grep INDICAGENT_ENV .env
```

---

## Schema Evolution

### Current Schema

Topics use JSON schemas without Schema Registry:
- Schemas defined in `src/intelligence/schemas.py`
- `BarEvent`, `IntelligenceEvent`, `SignalEvent`, `LifecycleEvent`
- `LLMCallEvent`, `NarrativeEvent`

### Future: Schema Registry

Redpanda includes Schema Registry (port 18843). Planned for:
- Schema validation at produce time
- Backward/forward compatibility checking
- Schema evolution tracking

---

## See Also

- **Stream schemas:** `docs/reference/schemas/stream-schemas.md`
- **Data pipeline:** `docs/concepts/data-pipeline.md`
- **Deployment:** `docs/operations/infrastructure.md`
- **Infrastructure reference:** `docs/operations/infrastructure.md`
- **Redpanda docs:** https://docs.redpanda.com/
