# Phase 74: BarNormalizerAgent - canonical grid completeness service for the data layer - Research

**Researched:** 2026-04-26
**Domain:** Data persistence, state checkpointing, bar aggregation
**Confidence:** HIGH

## Summary

Phase 74 addresses critical gaps in the data layer's HTF (higher-timeframe) bar persistence architecture. The current `BarAggregatorComputeAgent` maintains `BarAccumulator` state purely in-memory, creating two vulnerabilities identified in the Kafka→DB pipeline audit (M3, H5):

1. **Data loss on outage**: Any restart longer than the 3-day HTF retention window permanently loses partial bars for all in-progress HTF periods
2. **Stale state on restart**: Consumer restart reuses in-memory accumulator state with offsets that may be aged out, causing HTF bar duplication or suppression

The solution implements state checkpointing following the `IntelligencePipelineComputeAgent` pattern: persist accumulator state to a compacted Kafka topic on every 1m bar, restore from checkpoint on startup, and reset aggregator if no valid checkpoint exists.

**Primary recommendation:** Create state checkpointing for `BarAggregatorComputeAgent` using the existing `StateSerializer` and compacted topic pattern from the intelligence pipeline.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| HTF bar aggregation | Frontend Server (BarAggregatorComputeAgent) | — | In-memory compute, consumes market.bars, produces market.bars.htf |
| State persistence | CDN / Static (Compacted Kafka topic) | — | Durable state store, compacted to keep only latest per key |
| State restoration | Frontend Server (startup) | — | Reads checkpoint before consuming new bars |
| Grid completeness validation | API / Backend (BarAuditorAgent) | — | Separate concern, reads market_data_ohlcv |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `aiokafka` | (existing) | Kafka consumer/producer for state topic | Project standard for all Kafka I/O |
| `asyncpg` | (existing) | Not used — state stays in Kafka | Follows DAG discipline (no DB in compute path) |
| `msgpack` | (existing) | Binary serialization via StateSerializer | Already used by intelligence pipeline |
| `pydantic` | (existing) | State schema validation | Project standard for typed events |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `prometheus_client` | (existing) | State checkpoint metrics | Track checkpoint frequency, restore success/failure |
| `structlog` | (existing) | Structured logging | Standard logging across all agents |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Compacted Kafka topic | Redis / PostgreSQL | Kafka is already infrastructure; Redis adds operational complexity; PostgreSQL violates DAG discipline (no DB in compute) |
| StateSerializer (msgpack) | JSON | msgpack is more compact and faster; already validated in production |

**Installation:**
No new packages required — all dependencies already in `requirements.txt`.

**Version verification:** N/A — using existing pinned versions.

## Architecture Patterns

### System Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│ Runtime Flow (Before Phase 74)                                  │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  market.bars (1m)                                               │
│       │                                                         │
│       ▼                                                         │
│  ┌─────────────────────┐                                        │
│  │ BarAggregator       │  ← In-memory BarAccumulator per symbol  │
│  │ ComputeAgent        │    (lost on restart)                   │
│  │                     │                                        │
│  │ ┌─────────────────┐│  ← Partial HTF bars in progress        │
│  │ │ BarAccumulator  ││    (5m, 15m, 1h, 4h, 1d)              │
│  │ │ state (memory)  ││                                        │
│  │ └─────────────────┘│                                        │
│  └─────────────────────┘                                        │
│       │                                                         │
│       ▼                                                         │
│  market.bars.htf (HTF bars emitted on period close)             │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│ Runtime Flow (After Phase 74)                                   │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  market.bars (1m)                                               │
│       │                                                         │
│       ▼                                                         │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ BarAggregatorComputeAgent                                 │  │
│  │                                                            │  │
│  │  ┌─────────────────────────────────────────────────────┐  │  │
│  │  │ ON STARTUP:                                         │  │  │
│  │  │   1. Subscribe to market.bars                       │  │  │
│  │  │   2. Consume state topic (earliest)                 │  │  │
│  │  │   3. Restore BarAccumulator per symbol+tf           │  │  │
│  │  │   4. If no checkpoint: start fresh                 │  │  │
│  │  └─────────────────────────────────────────────────────┘  │  │
│  │                                                            │  │
│  │  ┌─────────────────────────────────────────────────────┐  │  │
│  │  │ PER BAR (after processing):                         │  │  │
│  │  │   1. Accumulate 1m bar into BarAccumulator          │  │  │
│  │  │   2. Emit HTF bars on period close                  │  │  │
│  │  │   3. Checkpoint state → compacted topic             │  │  │
│  │  │      key = "symbol:tf"                              │  │  │
│  │  │      value = BarAccumulator state dict              │  │  │
│  │  └─────────────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────────────┘  │
│       │                                                         │
│       ▼                                                         │
│  market.bars.htf (HTF bars)                                     │
│                                                                  │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ Compacted State Topic                                     │  │
│  │   topic_bar_aggregator_state(env)                         │  │
│  │   Key: symbol:tf (e.g., "ES:5m")                          │  │
│  │   Value: msgpack-encoded BarAccumulator state            │  │
│  │   Retention: compacted (keeps latest per key)             │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Recommended Project Structure

```
src/core/
├── bar_accumulator.py          # Existing BarAccumulator class (READ-ONLY)
├── state_serializer.py         # Existing StateSerializer (reuse)

services/
├── bar_aggregator_agent.py     # Existing BarAggregatorComputeAgent
│                                # Modify to add checkpointing
├── indicagent-bar-aggregator-compute.service  # Existing systemd unit

src/core/stream_keys.py
├── topic_bar_aggregator_state()  # NEW function
```

### Pattern 1: State Checkpointing (from IntelligencePipelineComputeAgent)

**What:** Every time the agent processes a bar and updates accumulator state, serialize that state and publish to a compacted Kafka topic. On startup, consume the entire topic (from earliest) to restore the latest state per key.

**When to use:** Any compute agent with in-memory state that would cause data loss or corruption if restarted. Pattern is already proven in `intelligence_pipeline_agent.py`.

**Example:**
```python
# Source: services/intelligence_pipeline_agent.py (verified)

async def _checkpoint_state(self, bar: BarMessage) -> None:
    """Encode current state and enqueue to compacted state topic."""
    state = {
        "_plugin_states": self._plugin_states,
        "_kalman_state": self._kalman_state,
        # ... other state fields
    }
    encoded = StateSerializer.encode(state)
    checkpoint_key = f"{_AGENT_VERSION}:{bar.symbol}:{bar.tf}"
    self._enqueue(
        topic_intelligence_pipeline_state(self.settings.env_name),
        checkpoint_key,
        encoded,
    )

async def _restore_state_checkpoint(self) -> bool:
    """Consume compacted state topic and restore all five state fields."""
    state_topic = topic_intelligence_pipeline_state(self.settings.env_name)
    consumer = KafkaConsumerClient(
        state_topic,
        group_id=f"{self._consumer_group}_state_restore",
        auto_offset_reset="earliest",  # Read all checkpoints
    )
    await consumer.start()

    async for _topic, key_str, payload in consumer.messages():
        if not key_str.startswith(f"{_AGENT_VERSION}:"):
            continue
        state = StateSerializer.decode(payload)
        # Restore state fields
        self._plugin_states.update(state["_plugin_states"])
        # ... etc
```

### Pattern 2: Compacted Topic Pattern

**What:** Kafka topic with `cleanup.policy=compact` retains only the latest value per key. Old values are garbage-collected. Perfect for state snapshots where only the current state matters.

**When to use:** State stores, caches, latest-value tables. Not suitable for event streams or time-series.

**Example:**
```python
# From production/scripts/kafka_init_topics.py (verified pattern)

_HOT_MS = 2 * 60 * 60 * 1000  # 2 hours
_COMPACTED = "compact"  # Special value for compaction

topics = [
    ("intelligence.pipeline.state", _COMPACTED),
    ("bar.aggregator.state", _COMPACTED),  # NEW for Phase 74
]
```

### Pattern 3: Key Schema for Compacted Topics

**What:** Keys must include all dimensions that determine state identity. For intelligence pipeline: `"{version}:{symbol}:{tf}"`. For bar aggregator: `"{symbol}:{tf}"` (no version needed if schema is stable).

**When to use:** Any compacted topic. Keys must be stable — if key format changes, old checkpoints become orphaned.

**Example:**
```python
# Intelligence pipeline key (from intelligence_pipeline_agent.py)
checkpoint_key = f"{_AGENT_VERSION}:{bar.symbol}:{bar.tf}"

# Bar aggregator key (proposed for Phase 74)
checkpoint_key = f"{symbol}:{tf}"  # e.g., "ES:5m", "NQ:1h"
```

### Anti-Patterns to Avoid

- **Checkpointing on every bar for every timeframe**: Would publish 5 checkpoints per bar (one per TF). Excessive load. **Fix:** Only checkpoint modified accumulators (the TFs that actually received the bar).
- **Blocking consume on restore**: If state topic has millions of messages, startup takes forever. **Fix:** Compaction ensures only latest per key; consumer drains quickly.
- **Version conflicts in state**: Deploying new code with incompatible state schema breaks restore. **Fix:** Include version in key (like intelligence pipeline) OR do schema migration (complex). For Phase 74, version in key is safer.
Appended section: Architectural Responsibility Map through Anti-Patterns
