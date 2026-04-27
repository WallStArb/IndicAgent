# Phase 74: BarNormalizerAgent - canonical grid completeness service for the data layer - Pattern Map

**Mapped:** 2026-04-26
**Files analyzed:** 3
**Analogs found:** 3 / 3

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `services/bar_aggregator_agent.py` | agent (compute) | event-driven | `services/intelligence_pipeline_agent.py` | exact |
| `src/core/stream_keys.py` | utility (config) | request-response | `src/core/stream_keys.py` | self-reference |
| `production/scripts/kafka_init_topics.py` | config (infrastructure) | request-response | `production/scripts/kafka_init_topics.py` | self-reference |

## Pattern Assignments

### `services/bar_aggregator_agent.py` (agent, event-driven)

**Analog:** `services/intelligence_pipeline_agent.py` (state checkpointing pattern)

**Role:** Modify existing `BarAggregatorComputeAgent` to add state checkpointing capability. The agent consumes 1m bars from `market.bars`, accumulates HTF bars via `BarAccumulator`, and publishes to `market.bars.htf`. New capability: persist `BarAccumulator` state to compacted Kafka topic on every bar, restore from checkpoint on startup.

**Data Flow:** event-driven (Kafka consumer → in-memory compute → Kafka producer + checkpoint topic)

**Imports pattern** (lines 1-56):
```python
from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import time

from prometheus_client import Counter, Gauge, Histogram

from src.core.agent.base import BaseAgent
from src.core.bar_accumulator import BarAccumulator
from src.core.bar_normalizer import SOURCE_UNKNOWN
from src.core.kafka_utils import KafkaConsumerClient, KafkaProducerClient
from src.core.schemas.bar_message import BarMessage, SessionType
from src.core.stream_keys import (
    message_key,
    topic_bar_aggregator_dlq,
    topic_market_bars,
    topic_market_bars_htf,
)
```

**Add new import for state checkpointing** (after line 46):
```python
from src.core.state_serializer import StateSerializer
```

**State checkpoint encoding pattern** (from intelligence_pipeline_agent.py lines 1580-1596):
```python
async def _checkpoint_state(self, bar: BarMessage) -> None:
    """Encode current state and enqueue to compacted state topic."""
    state = {
        "_plugin_states": self._plugin_states,
        "_kalman_state": self._kalman_state,
        "_tod_priors": self._tod_priors,
        "_bar_history": self._bar_history._data,
        "_last_bar_offset": self._last_bar_offset,
        "_setup_last_fire": self._setup_last_fire,
    }
    encoded = StateSerializer.encode(state)
    checkpoint_key = f"{_AGENT_VERSION}:{bar.symbol}:{bar.tf}"
    self._enqueue(
        topic_intelligence_pipeline_state(self.settings.env_name),
        checkpoint_key,
        encoded,
    )
```

**Adapt for bar aggregator:**
```python
async def _checkpoint_state(self, bar: BarMessage) -> None:
    """Encode BarAccumulator state and enqueue to compacted state topic."""
    # Extract serializable state from BarAccumulator
    state = {
        "_accumulators": self._bar_accumulator._accumulators,
        "_last_session_boundary_log": self._bar_accumulator._last_session_boundary_log,
    }
    encoded = StateSerializer.encode(state)
    checkpoint_key = f"{bar.symbol}:{bar.tf}"  # No version prefix needed for bar aggregator
    await self._kafka_producer.publish(
        topic_bar_aggregator_state(self.settings.env_name),
        checkpoint_key,
        encoded,
    )
```

**State checkpoint restore pattern** (from intelligence_pipeline_agent.py lines 719-796):
```python
async def _restore_state_checkpoint(self) -> bool:
    """Consume compacted state topic and restore all five state fields."""
    state_topic = topic_intelligence_pipeline_state(self.settings.env_name)
    consumer = None
    try:
        consumer = KafkaConsumerClient(
            state_topic,
            bootstrap_servers=self.settings.kafka_bootstrap_servers,
            group_id=f"{self._consumer_group}_state_restore",
            auto_offset_reset="earliest",
        )
        await consumer.start()

        result: list[bool] = [False]

        async def _drain() -> None:
            async for _topic, key_str, payload in consumer.messages():
                if not key_str or not key_str.startswith(f"{_AGENT_VERSION}:"):
                    self._state_checkpoint_fallback_total.inc()
                    continue
                try:
                    if isinstance(payload, dict):
                        raw = _msgpack.packb(payload, use_bin_type=True)
                        state = StateSerializer.decode(raw)
                    else:
                        state = StateSerializer.decode(payload)
                except Exception:
                    self._state_checkpoint_failures_total.inc()
                    continue

                parts = key_str.split(":")
                if len(parts) != 3:
                    continue
                _, symbol, tf = parts

                if "_plugin_states" in state:
                    for k, v in state["_plugin_states"].items():
                        self._plugin_states[_restore_tuple_key(k)] = v
                if "_kalman_state" in state:
                    for k, v in state["_kalman_state"].items():
                        self._kalman_state[_restore_tuple_key(k)] = v
                if "_tod_priors" in state:
                    for k, v in state["_tod_priors"].items():
                        self._tod_priors[_restore_tuple_key(k)] = v
                if "_bar_history" in state:
                    for k, v in state["_bar_history"].items():
                        self._bar_history._data[k] = v
                if "_last_bar_offset" in state:
                    for k, v in state["_last_bar_offset"].items():
                        self._last_bar_offset[_restore_tuple_key(k)] = v
                if "_setup_last_fire" in state:
                    for k, v in state["_setup_last_fire"].items():
                        self._setup_last_fire[_restore_tuple_key(k)] = v
                result[0] = True

        try:
            await asyncio.wait_for(_drain(), timeout=5.0)
        except TimeoutError:
            pass  # normal — drained all available messages

        restored_any = result[0]
        if restored_any and self._last_bar_offset:
            self._state_offset_reset_total.inc()
            self.logger.info("state.restored", offsets=self._last_bar_offset)

        return restored_any

    except Exception as exc:
        self.logger.warning("state.restore_failed", error=str(exc))
        self._state_checkpoint_failures_total.inc()
        return False
    finally:
        if consumer is not None:
            try:
                await consumer.stop()
            except Exception:
                pass
```

**Adapt for bar aggregator:**
```python
async def _restore_state_checkpoint(self) -> bool:
    """Consume compacted state topic and restore BarAccumulator state."""
    state_topic = topic_bar_aggregator_state(self.settings.env_name)
    consumer = None
    try:
        consumer = KafkaConsumerClient(
            state_topic,
            bootstrap_servers=self.settings.kafka_bootstrap_servers,
            group_id="bar_aggregator_state_restore",
            auto_offset_reset="earliest",
        )
        await consumer.start()

        result: list[bool] = [False]

        async def _drain() -> None:
            async for _topic, key_str, payload in consumer.messages():
                if not key_str:
                    continue
                try:
                    if isinstance(payload, dict):
                        raw = _msgpack.packb(payload, use_bin_type=True)
                        state = StateSerializer.decode(raw)
                    else:
                        state = StateSerializer.decode(payload)
                except Exception:
                    self.logger.warning("state.decode_failed", key=key_str)
                    continue

                # Restore BarAccumulator state
                if "_accumulators" in state:
                    for k, v in state["_accumulators"].items():
                        self._bar_accumulator._accumulators[k] = v
                if "_last_session_boundary_log" in state:
                    for k, v in state["_last_session_boundary_log"].items():
                        self._bar_accumulator._last_session_boundary_log[k] = v
                result[0] = True

        try:
            await asyncio.wait_for(_drain(), timeout=5.0)
        except TimeoutError:
            pass  # normal — drained all available messages

        restored_any = result[0]
        if restored_any:
            self.logger.info(
                "bar_aggregator.state.restored",
                accumulators=len(self._bar_accumulator._accumulators),
            )

        return restored_any

    except Exception as exc:
        self.logger.warning("bar_aggregator.state.restore_failed", error=str(exc))
        return False
    finally:
        if consumer is not None:
            try:
                await consumer.stop()
            except Exception:
                pass
```

**Startup integration pattern** (from intelligence_pipeline_agent.py lines 639-646):
```python
# 3. Restore state from checkpoint topic
restored = await self._restore_state_checkpoint()

# 4. Fallback to BarHistorySeeder if checkpoint miss
if not restored:
    self._state_checkpoint_fallback_total.inc()
    self.logger.info("state.checkpoint_miss — seeding via BarHistorySeeder")
    await self._seed_bar_history_from_db()
```

**Adapt for bar aggregator (insert in `_setup()` after Kafka setup, before consumer start):**
```python
# Restore state from checkpoint topic
restored = await self._restore_state_checkpoint()
if not restored:
    self.logger.info("bar_aggregator.state.checkpoint_miss — starting fresh")
```

**Per-bar checkpoint call pattern** (from intelligence_pipeline_agent.py lines 971-976):
```python
# 7. State checkpoint (best-effort — non-serializable state is skipped)
try:
    await self._checkpoint_state(bar)
except Exception:
    self._state_checkpoint_failures_total.inc()
```

**Adapt for bar aggregator (insert in `_run()` main loop after bar processing, after line 403):**
```python
# State checkpoint (best-effort)
try:
    await self._checkpoint_state(bar)
except Exception as exc:
    self.logger.warning("bar_aggregator.checkpoint_failed", error=str(exc))
```

**Metrics pattern** (from intelligence_pipeline_agent.py lines 535-542):
```python
self._state_checkpoint_fallback_total = counter(
    "intelligence_pipeline_state_checkpoint_fallback_total",
    "State checkpoint fallback to BarHistorySeeder",
)
self._state_checkpoint_failures_total = counter(
    "intelligence_pipeline_state_checkpoint_failures_total",
    "State checkpoint encode/decode failures",
)
self._state_offset_reset_total = counter(
    "intelligence_pipeline_state_offset_reset_total",
    "Consumer offset resets after checkpoint restore",
)
```

**Add to `__init__()`:**
```python
self._state_checkpoint_restored_total = counter(
    "bar_aggregator_state_checkpoint_restored_total",
    "State checkpoint successful restores",
)
self._state_checkpoint_failures_total = counter(
    "bar_aggregator_state_checkpoint_failures_total",
    "State checkpoint encode/decode failures",
)
```

**Error handling pattern** (from intelligence_pipeline_agent.py lines 971-976):
```python
# 7. State checkpoint (best-effort — non-serializable state is skipped)
try:
    await self._checkpoint_state(bar)
except Exception:
    self._state_checkpoint_failures_total.inc()
```

**Key differences from intelligence pipeline:**
1. **No version prefix in key:** BarAggregator state schema is stable, use `"{symbol}:{tf}"` not `"v1:{symbol}:{tf}"`
2. **No fallback to DB seeder:** Bar aggregator starts fresh on checkpoint miss (no historical seed needed)
3. **Simpler state structure:** Only `BarAccumulator._accumulators` dict, not 5 separate state fields
4. **Checkpoint frequency:** Every 1m bar that modifies accumulator state (intelligence pipeline checkpoints every bar)

---

### `src/core/stream_keys.py` (utility, request-response)

**Analog:** Self-reference (add new function following existing pattern)

**Role:** Add new topic function for bar aggregator state checkpoint topic

**New function pattern** (insert after line 56, after `topic_market_bars_htf()`):
```python
def topic_bar_aggregator_state(env_name: str) -> str:
    """Kafka compacted topic for BarAggregatorComputeAgent state checkpoints.

    Key format: {symbol}:{tf} (e.g., 'ESM6:5m')
    Value: msgpack-encoded BarAccumulator state dict (_accumulators, _last_session_boundary_log)
    Topic config: cleanup.policy=compact, min.cleanable.dirty.ratio=0.1,
                  segment.ms=3600000 — set on topic creation, not in code.
    """
    return f"{env_prefix(env_name)}bar.aggregator.state"
```

**Validation:** Follows exact pattern of `topic_intelligence_pipeline_state()` (lines 188-198)

---

### `production/scripts/kafka_init_topics.py` (config, request-response)

**Analog:** Self-reference (add compacted topic spec following existing pattern)

**Role:** Add compacted topic specification for bar aggregator state

**Compacted topic pattern** (lines 80-85):
```python
# Compacted topics (state snapshots — key-based retention)
_COMPACTED_TOPICS: list[tuple[str, int]] = [
    # (suffix, num_partitions)
    ("intelligence.pipeline.state", 1),
    ("market.events.contract_update", 1),
]
```

**Add new entry** (after line 83):
```python
_COMPACTED_TOPICS: list[tuple[str, int]] = [
    # (suffix, num_partitions)
    ("intelligence.pipeline.state", 1),
    ("bar.aggregator.state", 1),  # Phase 74: BarAggregator state checkpoints
    ("market.events.contract_update", 1),
]
```

**Topic creation validation:** Topic will be created via existing `_ensure_state_topic()` pattern in agent, or manually via:
```bash
docker exec redpanda rpk topic create dev.bar.aggregator.state \
  --partitions 1 \
  --replicas 1 \
  --topic-config cleanup.policy=compact \
  --topic-config retention.ms=604800000
```

---

## Shared Patterns

### State Checkpointing (StateSerializer + msgpack)
**Source:** `src/core/state_serializer.py`
**Apply to:** All agents with in-memory state that must survive restart

```python
from src.core.state_serializer import StateSerializer

# Encoding
state = {"_accumulators": {...}, "_last_session_boundary_log": {...}}
encoded = StateSerializer.encode(state)  # -> bytes

# Decoding
state = StateSerializer.decode(encoded)  # -> dict
```

**Type handling:**
- `dict`, `list`, `tuple` → recurse
- `int`, `float`, `str`, `bool`, `None` → pass-through
- `numpy.ndarray` → `{"__ndarray__": True, "data": [...], "dtype": str}`
- `Pydantic BaseModel` → `{"__pydantic__": "ClassName", "data": {...}}`
- `deque` → `{"__deque__": True, "data": [...], "maxlen": int}`

**BarAccumulator state contains only primitives + dict/list → no special registration needed**

### Compacted Topic Pattern
**Source:** `production/scripts/kafka_init_topics.py`
**Apply to:** All state checkpoint topics

- `cleanup.policy=compact` — keeps only latest value per key
- `min.cleanable.dirty.ratio=0.1` — compaction aggressiveness
- `retention.ms=604800000` (7 days) — safety net for unused keys
- `partitions=1` — state topics don't need parallelism

### Kafka Client Lifecycle
**Source:** `services/intelligence_pipeline_agent.py` lines 724-796
**Apply to:** All checkpoint restore operations

```python
consumer = KafkaConsumerClient(
    state_topic,
    bootstrap_servers=self.settings.kafka_bootstrap_servers,
    group_id=f"{self._consumer_group}_state_restore",
    auto_offset_reset="earliest",
)
await consumer.start()

try:
    async for _topic, key_str, payload in consumer.messages():
        # Process all messages (compaction ensures only latest per key)
        ...
    await asyncio.wait_for(_drain(), timeout=5.0)  # Prevent hang on topic with millions of messages
except TimeoutError:
    pass  # Normal — drained all available messages
finally:
    await consumer.stop()
```

### Best-Effort Checkpointing
**Source:** `services/intelligence_pipeline_agent.py` lines 971-976
**Apply to:** All per-bar checkpoint calls

```python
try:
    await self._checkpoint_state(bar)
except Exception:
    self._state_checkpoint_failures_total.inc()
    # Never crash on checkpoint failure — logging + metric is sufficient
```

**Rationale:** Checkpoint failure is non-critical (worst case: restart from scratch or stale state). Agent should continue processing bars even if checkpoint topic is unavailable.

---

## No Analog Found

None — all files have close matches in the codebase.

---

## Metadata

**Analog search scope:** `services/`, `src/core/`, `production/scripts/`
**Files scanned:** 3
**Pattern extraction date:** 2026-04-26

**Key architectural decisions:**
1. **Reuse StateSerializer:** No new serialization code — msgpack-based type tagging already handles primitive dict structures
2. **Compacted topic:** Not time-series — only latest state per (symbol, tf) matters
3. **No version prefix:** BarAccumulator schema is stable (unlike intelligence pipeline with 5 evolving state fields)
4. **Best-effort checkpointing:** Failure is non-critical — agent continues processing, metrics track health
5. **Restore on startup:** Consumer reads from `earliest`, drains all messages, restores latest per key via compaction
6. **No fallback seeder:** Unlike intelligence pipeline (BarHistorySeeder), bar aggregator starts fresh on checkpoint miss
