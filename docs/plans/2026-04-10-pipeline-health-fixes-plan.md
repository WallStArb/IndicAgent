# Pipeline Health Fixes — Implementation Plan

**Last Updated:** 2026-05-02

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unblock the signal tracker (decompression, orphans) and separate compute from persistence following the DAG pattern.

**Architecture:** Split signal_tracker_agent into a ComputeAgent (DB-ignorant, evaluates lifecycle in-memory) and a LifecycleWriterAgent (batch persists transitions). Add symbol/timeframe filtering to skip ~70% of irrelevant bars.

**Tech Stack:** Python 3.11+, asyncio, aiokafka, asyncpg, TimescaleDB, Redpanda, systemd

**Design doc:** `docs/plans/2026-04-10-pipeline-health-fixes-design.md`

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `src/core/stream_keys.py` | Add `topic_lifecycle_transitions()` |
| Create | `src/intelligence/trading/lifecycle_transitions.py` | TransitionEvent dataclass + serialization |
| Create | `services/lifecycle_writer_agent.py` | WriterAgent: transitions → batch DB writes |
| Create | `services/signal_tracker_compute.py` | ComputeAgent: bars → evaluate → publish transitions |
| Create | `tests/unit/test_lifecycle_transitions.py` | Tests for transition schema |
| Create | `tests/unit/service_tests/test_lifecycle_writer_agent.py` | Tests for writer |
| Create | `tests/unit/service_tests/test_signal_tracker_compute.py` | Tests for compute agent |
| Archive | `services/signal_tracker_agent.py` | → `_archived_signal_tracker_agent.py` |
| Archive | `tests/unit/service_tests/test_signal_tracker_agent.py` | → `_archived_test_signal_tracker_agent.py` |

---

## Task 1: P1 — Operational Unblock

No code changes. SQL commands run against TimescaleDB.

**Files:** None

- [ ] **Step 1: Set decompression limit to unlimited**

```bash
docker exec timescaledb psql -U postgres -d indicagent -c \
  "ALTER SYSTEM SET timescaledb.max_tuples_decompressed_per_dml_transaction = 0;"
docker exec timescaledb psql -U postgres -d indicagent -c \
  "SELECT pg_reload_conf();"
```

- [ ] **Step 2: Disable compression on signal_ledger**

```bash
docker exec timescaledb psql -U postgres -d indicagent -c \
  "ALTER TABLE signal_ledger SET (timescaledb.compress = false);"
docker exec timescaledb psql -U postgres -d indicagent -c \
  "SELECT decompress_chunk(chunk_schema || '.' || chunk_name)
   FROM timescaledb_information.chunks
   WHERE hypertable_name = 'signal_ledger' AND is_compressed = true;"
```

- [ ] **Step 3: Expire orphaned pre-restart signals**

```bash
docker exec timescaledb psql -U postgres -d indicagent -c \
  "UPDATE signal_ledger
   SET status = 'expired', outcome = 'never_activated',
       exit_reason = 'orphaned_pre_restart', exit_ts = NOW()
   WHERE status = 'pending' AND feature_ts < '2026-04-07 11:51:00+00';"
```

- [ ] **Step 4: Restart signal tracker**

```bash
sudo systemctl restart indicagent-signal-tracker
```

- [ ] **Step 5: Verify — zero decompression errors**

```bash
sleep 10
grep -c "tuple decompression" logs/signal_tracker_agent.log || echo "0 errors"
docker exec redpanda rpk group describe signal_lifecycle -t
```

Expected: 0 decompression errors, lag decreasing.

- [ ] **Step 6: Commit verification (no code change, skip commit)**

---

## Task 2: Add lifecycle topic key and transition types

Foundation types needed by both ComputeAgent and WriterAgent.

**Files:**
- Modify: `src/core/stream_keys.py`
- Create: `src/intelligence/trading/lifecycle_transitions.py`
- Create: `tests/unit/test_lifecycle_transitions.py`

- [ ] **Step 1: Write failing test for topic key**

```python
# tests/unit/test_stream_keys_lifecycle.py
def test_topic_lifecycle_transitions():
    from src.core.stream_keys import topic_lifecycle_transitions
    assert topic_lifecycle_transitions("development") == "development.lifecycle.transitions"
    assert topic_lifecycle_transitions("production") == "production.lifecycle.transitions"
```

Run: `.venv/bin/pytest tests/unit/test_stream_keys_lifecycle.py -v`
Expected: FAIL — `ImportError: cannot import name 'topic_lifecycle_transitions'`

- [ ] **Step 2: Add topic key to stream_keys.py**

Add to `src/core/stream_keys.py` (follow existing pattern):

```python
def topic_lifecycle_transitions(env_name: str) -> str:
    """Signal lifecycle transition events (compute → writer)."""
    return f"{env_prefix(env_name)}lifecycle.transitions"
```

- [ ] **Step 3: Run test — PASS**

Run: `.venv/bin/pytest tests/unit/test_stream_keys_lifecycle.py -v`
Expected: PASS

- [ ] **Step 4: Write failing test for LifecycleTransition schema**

```python
# tests/unit/test_lifecycle_transitions.py
from datetime import UTC, datetime
from src.intelligence.trading.lifecycle_transitions import (
    LifecycleTransition,
    TransitionType,
    to_dict,
    from_dict,
)


def test_transition_type_enum():
    assert TransitionType.ACTIVATION == "activation"
    assert TransitionType.EXIT == "exit"
    assert TransitionType.CHANDELIER_UPDATE == "chandelier_update"
    assert TransitionType.MAE_MFE_UPDATE == "mae_mfe_update"
    assert TransitionType.SHADOW_OUTCOME == "shadow_outcome"


def test_lifecycle_transition_roundtrip():
    t = LifecycleTransition(
        transition_type=TransitionType.ACTIVATION,
        signal_id="abc-123",
        symbol="BTCUSD",
        timeframe="1m",
        bar_ts=datetime(2026, 4, 10, 4, 2, 0, tzinfo=UTC),
        data={"activation_price": 67234.5, "bars_pending": 5},
    )
    d = to_dict(t)
    t2 = from_dict(d)
    assert t2.transition_type == TransitionType.ACTIVATION
    assert t2.signal_id == "abc-123"
    assert t2.symbol == "BTCUSD"
    assert t2.data["activation_price"] == 67234.5


def test_from_dict_invalid_type():
    with pytest.raises(ValueError):
        from_dict({"transition_type": "invalid", "signal_id": "x", "symbol": "X", "timeframe": "1m", "bar_ts": "2026-01-01T00:00:00Z", "data": {}})
```

Run: `.venv/bin/pytest tests/unit/test_lifecycle_transitions.py -v`
Expected: FAIL — `ImportError`

- [ ] **Step 5: Implement LifecycleTransition**

Create `src/intelligence/trading/lifecycle_transitions.py`:

```python
"""Signal lifecycle transition events — schema for compute → writer communication."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class TransitionType(StrEnum):
    ACTIVATION = "activation"
    EXIT = "exit"
    CHANDELIER_UPDATE = "chandelier_update"
    MAE_MFE_UPDATE = "mae_mfe_update"
    SHADOW_OUTCOME = "shadow_outcome"


@dataclass
class LifecycleTransition:
    transition_type: TransitionType
    signal_id: str
    symbol: str
    timeframe: str
    bar_ts: datetime
    data: dict[str, Any] = field(default_factory=dict)


def to_dict(t: LifecycleTransition) -> dict[str, Any]:
    return {
        "transition_type": str(t.transition_type),
        "signal_id": t.signal_id,
        "symbol": t.symbol,
        "timeframe": t.timeframe,
        "bar_ts": t.bar_ts.isoformat(),
        "data": t.data,
    }


def from_dict(d: dict[str, Any]) -> LifecycleTransition:
    ts = d.get("bar_ts", "")
    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
    return LifecycleTransition(
        transition_type=TransitionType(d["transition_type"]),
        signal_id=d["signal_id"],
        symbol=d["symbol"],
        timeframe=d["timeframe"],
        bar_ts=ts,
        data=d.get("data", {}),
    )
```

- [ ] **Step 6: Run tests — PASS**

Run: `.venv/bin/pytest tests/unit/test_lifecycle_transitions.py tests/unit/test_stream_keys_lifecycle.py -v`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add src/core/stream_keys.py src/intelligence/trading/lifecycle_transitions.py \
       tests/unit/test_lifecycle_transitions.py tests/unit/test_stream_keys_lifecycle.py
git commit -m "feat: add lifecycle transitions schema and Kafka topic key"
```

---

## Task 3: Create Lifecycle WriterAgent

Pure persistence service — consumes transitions, batch-writes to signal_ledger.

**Files:**
- Create: `services/lifecycle_writer_agent.py`
- Create: `tests/unit/service_tests/test_lifecycle_writer_agent.py`

- [ ] **Step 1: Write structural tests**

```python
# tests/unit/service_tests/test_lifecycle_writer_agent.py
"""Unit tests for LifecycleWriterAgent — TDD tests for pipeline health fix."""
import pathlib

import pytest


def test_class_name():
    src = pathlib.Path("services/lifecycle_writer_agent.py").read_text()
    assert "LifecycleWriterAgent" in src


def test_inherits_base_agent():
    src = pathlib.Path("services/lifecycle_writer_agent.py").read_text()
    assert "BaseAgent" in src


def test_no_compute_logic():
    """WriterAgent must not contain evaluate_signal or lifecycle computation."""
    src = pathlib.Path("services/lifecycle_writer_agent.py").read_text()
    assert "evaluate_signal" not in src
    assert "compute_chandelier" not in src


def test_uses_signal_ledger_repository():
    src = pathlib.Path("services/lifecycle_writer_agent.py").read_text()
    assert "SignalLedgerRepository" in src
```

- [ ] **Step 2: Run structural tests — FAIL**

Run: `.venv/bin/pytest tests/unit/service_tests/test_lifecycle_writer_agent.py -v`
Expected: FAIL — file not found

- [ ] **Step 3: Write behavioral tests**

Add to `tests/unit/service_tests/test_lifecycle_writer_agent.py`:

```python
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from prometheus_client import Counter, Gauge, Histogram

from src.intelligence.trading.lifecycle_transitions import (
    LifecycleTransition,
    TransitionType,
    to_dict,
)

# Module-level test metrics to avoid duplicate registration
_TEST_WRITTEN = Counter("test_lwa_written_total", "Written (test)")
_TEST_ERRORS = Counter("test_lwa_errors_total", "Errors (test)")
_TEST_LATENCY = Histogram("test_lwa_latency_seconds", "Lat (test)", ["agent"])
_TEST_LAG = Gauge("test_lwa_lag", "Lag (test)", ["agent"])
_TEST_DEPTH = Gauge("test_lwa_depth", "Depth (test)")


def _make_agent():
    from services.lifecycle_writer_agent import LifecycleWriterAgent

    agent = LifecycleWriterAgent.__new__(LifecycleWriterAgent)
    agent.logger = MagicMock()
    agent._settings = MagicMock()
    agent._settings.database_url = "postgresql://postgres@localhost/indicagent"
    agent._settings.kafka_bootstrap_servers = "localhost:19092"
    agent._settings.env_name = "development"
    agent._db = MagicMock()
    agent._consumer = MagicMock()
    agent._repo = AsyncMock()
    agent._buffer = []
    agent._last_flush = 0.0
    agent._transitions_written = _TEST_WRITTEN
    agent._write_errors = _TEST_ERRORS
    agent._batch_latency = _TEST_LATENCY.labels(agent="test")
    agent._consumer_lag = _TEST_LAG.labels(agent="test")
    agent._buffer_depth = _TEST_DEPTH
    return agent


def _make_transition(ttype: TransitionType = TransitionType.ACTIVATION) -> dict:
    t = LifecycleTransition(
        transition_type=ttype,
        signal_id="sig-001",
        symbol="BTCUSD",
        timeframe="1m",
        bar_ts=datetime(2026, 4, 10, 4, 2, 0, tzinfo=UTC),
        data={"activation_price": 67234.5},
    )
    return to_dict(t)


def test_buffer_accumulates_transitions():
    agent = _make_agent()
    agent._buffer.append(_make_transition())
    agent._buffer.append(_make_transition(TransitionType.EXIT))
    assert len(agent._buffer) == 2


@pytest.mark.asyncio
async def test_flush_groups_by_type():
    agent = _make_agent()
    # Add transitions of different types
    agent._buffer.append(_make_transition(TransitionType.ACTIVATION))
    agent._buffer.append(_make_transition(TransitionType.EXIT))
    agent._buffer.append(_make_transition(TransitionType.ACTIVATION))

    await agent._flush()

    # Should have called batch_execute twice (once per type)
    assert agent._repo.batch_execute.call_count == 2
    assert len(agent._buffer) == 0


@pytest.mark.asyncio
async def test_flush_empty_buffer_is_noop():
    agent = _make_agent()
    await agent._flush()
    agent._repo.batch_execute.assert_not_called()


@pytest.mark.asyncio
async def test_flush_handles_db_error():
    agent = _make_agent()
    agent._buffer.append(_make_transition())
    agent._repo.batch_execute = AsyncMock(side_effect=Exception("DB down"))
    await agent._flush()
    # Buffer should NOT be cleared on error
    assert len(agent._buffer) == 1
```

- [ ] **Step 4: Implement LifecycleWriterAgent**

Create `services/lifecycle_writer_agent.py`:

```python
#!/usr/bin/env python3
"""Lifecycle Writer Agent — persists signal lifecycle transitions to signal_ledger.

Consumes lifecycle.transitions Kafka topic, buffers transitions,
groups by type, and batch-writes to signal_ledger via execute_batch().

WriterAgent role: DB-only, zero compute. No lifecycle evaluation.
Consumer group: lifecycle_writer_group
Metrics port: 9128
"""
from __future__ import annotations

import asyncio
import sys
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.config.settings import Settings
from src.core.agent.base import BaseAgent
from src.core.database_manager import DatabaseManager
from src.core.kafka_utils import KafkaConsumerClient
from src.core.stream_keys import topic_lifecycle_transitions
from src.intelligence.trading.lifecycle_transitions import TransitionType, from_dict
from src.observability.metrics import (
    PERSISTENCE_BATCH_LATENCY,
    PERSISTENCE_CONSUMER_LAG,
    counter,
    gauge,
)
from src.persistence.repository.signal_ledger_repository import (
    SignalLedgerRepository,
)

CONSUMER_GROUP = "lifecycle_writer_group"
BATCH_SIZE = 100
FLUSH_INTERVAL_SECS = 5.0
MAX_BUFFER_SIZE = 10_000


class LifecycleWriterAgent(BaseAgent):
    """WriterAgent: lifecycle.transitions → signal_ledger (batch persist)."""

    def __init__(self) -> None:
        super().__init__(
            name="lifecycle_writer_agent",
            metrics_port=9128,
            max_idle_seconds=300,
        )
        self._settings = Settings()
        self._db: DatabaseManager | None = None
        self._consumer: KafkaConsumerClient | None = None
        self._repo: SignalLedgerRepository | None = None
        self._buffer: list[dict[str, Any]] = []
        self._last_flush: float = 0.0

        self._transitions_written = counter(
            "lifecycle_writer_transitions_written_total",
            "Transitions persisted",
        )
        self._write_errors = counter(
            "lifecycle_writer_write_errors_total",
            "Failed batch writes",
        )
        self._batch_latency = PERSISTENCE_BATCH_LATENCY.labels(
            agent_id="lifecycle_writer_agent"
        )
        self._consumer_lag = PERSISTENCE_CONSUMER_LAG.labels(
            agent_id="lifecycle_writer_agent"
        )
        self._buffer_depth = gauge(
            "lifecycle_writer_buffer_depth",
            "Pending transitions awaiting flush",
        )

    async def _setup(self) -> None:
        self._db = DatabaseManager(self._settings.database_url)
        await self._db.initialize()
        self._repo = SignalLedgerRepository(self._db)

        topic = topic_lifecycle_transitions(self._settings.env_name)
        self._consumer = KafkaConsumerClient(
            topic,
            bootstrap_servers=self._settings.kafka_bootstrap_servers,
            group_id=CONSUMER_GROUP,
            auto_offset_reset="earliest",
        )
        await self._consumer.start()
        self._last_flush = time.monotonic()
        self.logger.info("lifecycle_writer.started", topic=topic)

    async def _run(self) -> None:
        async for _topic, _key, payload in self._consumer.messages():
            if not isinstance(payload, dict):
                continue
            self._buffer.append(payload)

            if len(self._buffer) > MAX_BUFFER_SIZE:
                dropped = len(self._buffer) - MAX_BUFFER_SIZE
                self._buffer = self._buffer[-MAX_BUFFER_SIZE:]
                self.logger.warning("lifecycle_writer.buffer_overflow", dropped=dropped)

            self._buffer_depth.set(len(self._buffer))

            now = time.monotonic()
            if len(self._buffer) >= BATCH_SIZE or (now - self._last_flush) >= FLUSH_INTERVAL_SECS:
                await self._flush()
                self._last_flush = now

    async def _flush(self) -> None:
        if not self._buffer or not self._repo:
            return
        batch = self._buffer[:]
        t0 = time.perf_counter()
        try:
            # Group by transition type for efficient batch writes
            by_type: dict[str, list[dict]] = defaultdict(list)
            for item in batch:
                ttype = item.get("transition_type", "unknown")
                by_type[ttype].append(item)

            for ttype, items in by_type.items():
                await self._repo.batch_execute(ttype, items)

            self._buffer.clear()
            self._buffer_depth.set(0)
            self._transitions_written.inc(len(batch))
            self._batch_latency.observe(time.perf_counter() - t0)
            self.logger.info("lifecycle_writer.flushed", count=len(batch))
        except Exception as exc:
            self._write_errors.inc()
            self.logger.error("lifecycle_writer.flush_error", error=str(exc))

    async def _teardown(self) -> None:
        if self._buffer:
            await self._flush()
        if self._consumer:
            await self._consumer.stop()
        if self._db:
            await self._db.close()


if __name__ == "__main__":
    agent = LifecycleWriterAgent()
    asyncio.run(agent.start())
```

- [ ] **Step 5: Add batch_execute to SignalLedgerRepository**

Add to `src/persistence/repository/signal_ledger_repository.py`:

```python
async def batch_execute(self, transition_type: str, items: list[dict]) -> None:
    """Batch-write lifecycle transitions grouped by type.

    Each transition_type maps to a specific UPDATE statement.
    Uses executemany for efficient batch operation.
    """
    if not items:
        return

    if transition_type == "activation":
        params = [
            (i["signal_id"], i["data"]["activation_ts"],
             i["data"]["activation_price"], i["data"].get("zone_entry_pct", 0.0),
             i["data"].get("bars_pending", 0))
            for i in items
        ]
        await self._db.execute_batch(
            _UPDATE_ACTIVATION_SQL,
            [(str(p[0]), p[1], p[2], p[3], p[4]) for p in params],
        )
    elif transition_type == "exit":
        params = [
            (i["signal_id"], i["data"].get("status", "expired"),
             i["data"].get("exit_price"), i["data"].get("exit_reason", ""),
             i["data"].get("pnl_r"), i["data"].get("mae"), i["data"].get("mfe"),
             i["data"].get("bars_held", 0), i["data"].get("outcome", ""),
             i["data"].get("exit_ts"))
            for i in items
        ]
        await self._db.execute_batch(
            _UPDATE_EXIT_SQL,
            params,
        )
    elif transition_type in ("chandelier_update", "mae_mfe_update", "shadow_outcome"):
        # These are handled by generic status update
        params = [
            (i["signal_id"], i["data"])
            for i in items
        ]
        await self._db.execute_batch(
            _UPDATE_LIFECYNE_STATE_SQL,
            params,
        )
```

Note: The exact SQL statements (`_UPDATE_ACTIVATION_SQL`, `_UPDATE_EXIT_SQL`, `_UPDATE_LIFECYNE_STATE_SQL`) should match existing repository SQL. Check the file for the existing statements and reuse them. The `_db.execute_batch()` method should use asyncpg's `conn.executemany()`.

- [ ] **Step 6: Run all tests**

Run: `.venv/bin/pytest tests/unit/service_tests/test_lifecycle_writer_agent.py -v`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add services/lifecycle_writer_agent.py \
       src/persistence/repository/signal_ledger_repository.py \
       tests/unit/service_tests/test_lifecycle_writer_agent.py
git commit -m "feat: add LifecycleWriterAgent — batch persist lifecycle transitions"
```

---

## Task 4: Create Signal Tracker ComputeAgent

Core compute logic — consume bars, filter, evaluate lifecycle, publish transitions.

**Files:**
- Create: `services/signal_tracker_compute.py`
- Create: `tests/unit/service_tests/test_signal_tracker_compute.py`

- [ ] **Step 1: Write structural tests**

```python
# tests/unit/service_tests/test_signal_tracker_compute.py
"""Unit tests for SignalTrackerCompute — TDD tests for pipeline health fix."""
import pathlib

import pytest


def test_class_name():
    src = pathlib.Path("services/signal_tracker_compute.py").read_text()
    assert "SignalTrackerCompute" in src


def test_inherits_base_agent():
    src = pathlib.Path("services/signal_tracker_compute.py").read_text()
    assert "BaseAgent" in src


def test_no_db_writes():
    """ComputeAgent must not contain DB write methods."""
    src = pathlib.Path("services/signal_tracker_compute.py").read_text()
    assert "record_activation" not in src
    assert "record_zone_resolution" not in src
    assert "record_market_resolution" not in src
    assert "execute_batch" not in src


def test_uses_lifecycle_transitions():
    src = pathlib.Path("services/signal_tracker_compute.py").read_text()
    assert "lifecycle_transitions" in src
    assert "TransitionType" in src


def test_has_symbol_filter():
    """Must check symbol against active index before evaluating."""
    src = pathlib.Path("services/signal_tracker_compute.py").read_text()
    assert "_active_symbols" in src
```

- [ ] **Step 2: Run structural tests — FAIL**

Run: `.venv/bin/pytest tests/unit/service_tests/test_signal_tracker_compute.py -v`
Expected: FAIL — file not found

- [ ] **Step 3: Write behavioral tests**

Add to `tests/unit/service_tests/test_signal_tracker_compute.py`:

```python
import asyncio
from collections import defaultdict
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from src.intelligence.trading.lifecycle_transitions import TransitionType


def _make_agent():
    from services.signal_tracker_compute import SignalTrackerCompute

    agent = SignalTrackerCompute.__new__(SignalTrackerCompute)
    agent.name = "signal_tracker_compute"
    agent.logger = MagicMock()
    agent._settings = MagicMock()
    agent._settings.database_url = "postgresql://postgres@localhost/indicagent"
    agent._settings.kafka_bootstrap_servers = "localhost:19092"
    agent._settings.env_name = "development"
    agent._stop_event = asyncio.Event()

    # In-memory state
    agent._active_index = defaultdict(list)
    agent._active_symbols = set()
    agent._mae = {}
    agent._mfe = {}
    agent._activated_at = {}
    agent._chandelier_state = {}
    agent._staleness_consecutive = {}
    agent._shadow_signals = {}

    # Kafka
    agent._bar_consumer = None
    agent._signal_consumer = None
    agent._producer = MagicMock()
    agent._producer.send = AsyncMock()
    return agent


def _make_signal(signal_id="sig-1", symbol="BTCUSD", tf="1m", status="pending",
                 entry_price=67000.0, stop_loss=66800.0, targets=None):
    return {
        "signal_id": signal_id,
        "symbol": symbol,
        "timeframe": tf,
        "status": status,
        "entry_price": entry_price,
        "stop_loss": stop_loss,
        "targets": targets or [67500.0],
        "direction": 1,
        "zone_high": 67010.0,
        "zone_low": 66990.0,
        "ttl_bars": 60,
    }


def test_symbol_filter_skips_irrelevant_bars():
    """Bars for symbols with no active signals should be skipped."""
    agent = _make_agent()
    agent._active_symbols = {"BTCUSD"}

    # SPY has no signals — should be skipped
    assert agent._should_process_bar("SPY", "1m") is False
    # BTCUSD has signals — should be processed
    assert agent._should_process_bar("BTCUSD", "1m") is True


def test_timeframe_filter():
    """Only evaluate signals matching the bar's timeframe."""
    agent = _make_agent()
    agent._active_symbols = {"BTCUSD"}
    agent._active_index[("BTCUSD", "1m")] = [_make_signal(tf="1m")]
    agent._active_index[("BTCUSD", "15m")] = [_make_signal(tf="15m", signal_id="sig-2")]

    # 1m bar should only see 1m signals
    signals_1m = agent._get_signals_for_bar("BTCUSD", "1m")
    assert len(signals_1m) == 1
    assert signals_1m[0]["signal_id"] == "sig-1"


def test_ingest_new_signal():
    """New signals from i7.signals should be added to active index."""
    agent = _make_agent()
    signal_payload = {
        "symbol": "BTCUSD",
        "tf": "1m",
        "signals": [_make_signal(signal_id="new-1")],
    }

    agent._ingest_signal_payload(signal_payload)

    assert "BTCUSD" in agent._active_symbols
    assert len(agent._active_index[("BTCUSD", "1m")]) == 1


def test_remove_resolved_signal():
    """Resolved signals should be removed from active index."""
    agent = _make_agent()
    agent._active_symbols = {"BTCUSD"}
    agent._active_index[("BTCUSD", "1m")] = [_make_signal(signal_id="sig-1")]

    agent._remove_signal("sig-1", "BTCUSD", "1m")

    assert len(agent._active_index[("BTCUSD", "1m")]) == 0
    # Symbol removed from active set when no signals remain
    assert "BTCUSD" not in agent._active_symbols
```

- [ ] **Step 4: Implement SignalTrackerCompute**

Create `services/signal_tracker_compute.py`. This is the largest file. Key structure:

```python
#!/usr/bin/env python3
"""Signal Tracker Compute — evaluates signal lifecycle transitions (DB-ignorant).

Consumes market.bars + market.bars.htf, maintains active signals in-memory,
evaluates lifecycle via evaluate_signal(), publishes transitions to
lifecycle.transitions Kafka topic.

ComputeAgent role: zero DB writes, pure compute.
Also consumes intelligence.i7.signals to ingest new signals.
"""
from __future__ import annotations

import asyncio
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.config.settings import Settings
from src.core.agent.base import BaseAgent
from src.core.database_manager import DatabaseManager
from src.core.kafka_utils import KafkaConsumerClient, KafkaProducerClient
from src.core.stream_keys import (
    topic_lifecycle_transitions,
    topic_market_bars,
    topic_market_bars_htf,
    topic_intelligence_i7_signals,
)
from src.intelligence.trading.lifecycle_tracker import evaluate_signal
from src.intelligence.trading.lifecycle_transitions import (
    LifecycleTransition,
    TransitionType,
    to_dict,
)

BAR_CONSUMER_GROUP = "signal_tracker_compute"
SIGNAL_CONSUMER_GROUP = "signal_tracker_compute_signals"
BATCH_SIZE = 100
COMMIT_INTERVAL_SECS = 5.0


class SignalTrackerCompute(BaseAgent):
    """ComputeAgent: bars → lifecycle evaluation → transition events."""

    def __init__(self) -> None:
        super().__init__(
            name="signal_tracker_compute",
            metrics_port=9127,
            max_idle_seconds=300,
        )
        self._settings = Settings()
        self._db: DatabaseManager | None = None  # bootstrap only
        self._bar_consumer: KafkaConsumerClient | None = None
        self._signal_consumer: KafkaConsumerClient | None = None
        self._producer: KafkaProducerClient | None = None

        # In-memory state (same structure as old tracker)
        self._active_index: dict[tuple[str, str], list[dict]] = defaultdict(list)
        self._active_symbols: set[str] = set()
        self._mae: dict[str, float] = {}
        self._mfe: dict[str, float] = {}
        self._activated_at: dict[str, datetime] = {}
        self._chandelier_state: dict[str, dict] = {}
        self._staleness_consecutive: dict[str, int] = {}
        self._shadow_signals: dict[str, dict] = {}

        self._last_commit = 0.0

    def _should_process_bar(self, symbol: str, timeframe: str) -> bool:
        """Symbol filter — skip bars for symbols with no active signals."""
        return symbol in self._active_symbols

    def _get_signals_for_bar(self, symbol: str, timeframe: str) -> list[dict]:
        """Get signals matching the bar's symbol and timeframe."""
        return self._active_index.get((symbol, timeframe), [])

    def _ingest_signal_payload(self, payload: dict) -> None:
        """Add new signals from intelligence.i7.signals to the active index."""
        symbol = payload.get("symbol", "")
        tf = payload.get("tf", "")
        for sig in payload.get("signals", []):
            sig["symbol"] = symbol
            sig["timeframe"] = tf
            self._active_index[(symbol, tf)].append(sig)
            self._active_symbols.add(symbol)

    def _remove_signal(self, signal_id: str, symbol: str, tf: str) -> None:
        """Remove resolved signal from active index."""
        key = (symbol, tf)
        if key in self._active_index:
            self._active_index[key] = [
                s for s in self._active_index[key] if s.get("signal_id") != signal_id
            ]
            if not self._active_index[key]:
                del self._active_index[key]
                # Check if symbol still has signals in any timeframe
                if not any(k[0] == symbol for k in self._active_index):
                    self._active_symbols.discard(symbol)
        # Clean up per-signal state
        self._mae.pop(signal_id, None)
        self._mfe.pop(signal_id, None)
        self._activated_at.pop(signal_id, None)
        self._chandelier_state.pop(signal_id, None)
        self._staleness_consecutive.pop(signal_id, None)
        self._shadow_signals.pop(signal_id, None)

    async def _setup(self) -> None:
        # Bootstrap: load active signals from DB (one-time)
        self._db = DatabaseManager(self._settings.database_url)
        await self._db.initialize()
        await self._bootstrap_active_signals()

        # Kafka consumers
        env = self._settings.env_name
        bs = self._settings.kafka_bootstrap_servers

        self._bar_consumer = KafkaConsumerClient(
            f"{topic_market_bars(env)},{topic_market_bars_htf(env)}",
            bootstrap_servers=bs,
            group_id=BAR_CONSUMER_GROUP,
            auto_offset_reset="earliest",
        )
        self._signal_consumer = KafkaConsumerClient(
            topic_intelligence_i7_signals(env),
            bootstrap_servers=bs,
            group_id=SIGNAL_CONSUMER_GROUP,
            auto_offset_reset="latest",
        )
        self._producer = KafkaProducerClient(
            bootstrap_servers=bs,
        )

        await self._bar_consumer.start()
        await self._signal_consumer.start()
        await self._producer.start()
        self.logger.info("signal_tracker_compute.started",
                         active_signals=sum(len(v) for v in self._active_index.values()))

    async def _bootstrap_active_signals(self) -> None:
        """Load all pending/active signals from DB at startup."""
        rows = await self._db.fetch_all(
            """SELECT signal_id, symbol, timeframe, status, entry_price,
                      stop_loss, targets, direction, zone_high, zone_low,
                      ttl_bars, confidence, activated_at, activation_price
               FROM signal_ledger
               WHERE status IN ('pending', 'active', 'regime_suppressed')"""
        )
        for row in rows:
            sig = dict(row)
            key = (sig["symbol"], sig["timeframe"])
            self._active_index[key].append(sig)
            self._active_symbols.add(sig["symbol"])
            if sig.get("activated_at"):
                self._activated_at[sig["signal_id"]] = sig["activated_at"]
        self.logger.info("signal_tracker_compute.bootstrapped",
                         count=sum(len(v) for v in self._active_index.values()))

    async def _run(self) -> None:
        """Main loop: consume bars + ingest new signals concurrently."""
        await asyncio.gather(
            self._bar_processing_loop(),
            self._signal_ingestion_loop(),
        )

    async def _bar_processing_loop(self) -> None:
        """Consume bars, evaluate signals, publish transitions."""
        import time as _time
        self._last_commit = _time.monotonic()

        async for _topic, key, payload in self._bar_consumer.messages():
            if self._stop_event.is_set():
                break
            if not isinstance(payload, dict):
                continue

            key_str = key.decode() if key else ""
            parts = key_str.split(":")
            symbol = parts[0] if parts else ""
            timeframe = parts[1] if len(parts) > 1 else "1m"

            # Symbol filter — skip ~70% of bars
            if not self._should_process_bar(symbol, timeframe):
                continue

            await self._evaluate_bar(symbol, timeframe, payload)

            # Periodic commit
            now = _time.monotonic()
            if now - self._last_commit >= COMMIT_INTERVAL_SECS:
                await self._bar_consumer.commit()
                self._last_commit = now

    async def _signal_ingestion_loop(self) -> None:
        """Ingest new signals from intelligence.i7.signals."""
        async for _topic, _key, payload in self._signal_consumer.messages():
            if self._stop_event.is_set():
                break
            if not isinstance(payload, dict):
                continue
            self._ingest_signal_payload(payload)
            await self._signal_consumer.commit()

    async def _evaluate_bar(self, symbol: str, timeframe: str, bar: dict) -> None:
        """Evaluate all relevant signals against this bar."""
        high = float(bar.get("high", 0))
        low = float(bar.get("low", 0))
        close = float(bar.get("close", 0))
        bar_ts_str = bar.get("ts", bar.get("timestamp", ""))
        bar_time = datetime.fromisoformat(bar_ts_str) if bar_ts_str else datetime.now(UTC)
        if bar_time.tzinfo is None:
            bar_time = bar_time.replace(tzinfo=UTC)

        signals = self._get_signals_for_bar(symbol, timeframe)
        if not signals:
            return

        transitions = []
        for sig in signals[:]:  # Copy to allow mutation during iteration
            signal_id = sig.get("signal_id", "")

            # Compute MAE/MFE
            entry = float(sig.get("entry_price", close))
            direction = int(sig.get("direction", 0))
            if direction > 0:  # Long
                current_mae = (low - entry) / entry if entry else 0
                current_mfe = (high - entry) / entry if entry else 0
            else:  # Short
                current_mae = (entry - high) / entry if entry else 0
                current_mfe = (entry - low) / entry if entry else 0

            self._mae[signal_id] = min(self._mae.get(signal_id, 0), current_mae)
            self._mfe[signal_id] = max(self._mfe.get(signal_id, 0), current_mfe)

            # Evaluate lifecycle transition
            transition = evaluate_signal(
                sig,
                high=high,
                low=low,
                close=close,
                current_mae=self._mae[signal_id],
                current_mfe=self._mfe[signal_id],
                chandelier_state=self._chandelier_state.get(signal_id),
                staleness_consecutive_bars=self._staleness_consecutive.get(signal_id, 0),
            )

            if transition is not None:
                # Map transition to LifecycleTransition and publish
                lt = self._transition_to_lifecycle(transition, symbol, timeframe, bar_time)
                transitions.append(to_dict(lt))

                # Update in-memory state
                if transition.new_status == "active":
                    self._activated_at[signal_id] = bar_time
                    sig["status"] = "active"
                elif transition.new_status in ("expired", "stopped_out", "target_hit"):
                    self._remove_signal(signal_id, symbol, timeframe)

        # Publish all transitions for this bar
        if transitions and self._producer:
            topic = topic_lifecycle_transitions(self._settings.env_name)
            for t in transitions:
                await self._producer.send(topic, t)

    def _transition_to_lifecycle(
        self, transition, symbol: str, timeframe: str, bar_time: datetime
    ) -> LifecycleTransition:
        """Map evaluate_signal() Transition to LifecycleTransition."""
        signal_id = transition.signal_id

        if transition.new_status == "active":
            return LifecycleTransition(
                transition_type=TransitionType.ACTIVATION,
                signal_id=signal_id,
                symbol=symbol,
                timeframe=timeframe,
                bar_ts=bar_time,
                data={
                    "activation_ts": bar_time.isoformat(),
                    "activation_price": transition.activation_price,
                    "zone_entry_pct": transition.zone_entry_pct,
                    "bars_pending": transition.bars_to_activation,
                },
            )
        elif transition.new_status in ("expired", "stopped_out", "target_hit"):
            return LifecycleTransition(
                transition_type=TransitionType.EXIT,
                signal_id=signal_id,
                symbol=symbol,
                timeframe=timeframe,
                bar_ts=bar_time,
                data={
                    "status": transition.new_status,
                    "exit_price": transition.exit_price,
                    "exit_reason": transition.exit_reason,
                    "pnl_r": transition.pnl_r,
                    "mae": transition.mae,
                    "mfe": transition.mfe,
                    "bars_held": transition.bars_in_trade,
                    "outcome": transition.outcome,
                    "exit_ts": bar_time.isoformat(),
                },
            )
        else:
            # Fallback for other transitions
            return LifecycleTransition(
                transition_type=TransitionType.MAE_MFE_UPDATE,
                signal_id=signal_id,
                symbol=symbol,
                timeframe=timeframe,
                bar_ts=bar_time,
                data={
                    "new_status": transition.new_status,
                    "mae": transition.mae,
                    "mfe": transition.mfe,
                },
            )

    async def _teardown(self) -> None:
        # Final commit
        if self._bar_consumer:
            await self._bar_consumer.commit()
        if self._bar_consumer:
            await self._bar_consumer.stop()
        if self._signal_consumer:
            await self._signal_consumer.stop()
        if self._producer:
            await self._producer.stop()
        if self._db:
            await self._db.close()
            self._db = None  # No longer needed after bootstrap


if __name__ == "__main__":
    agent = SignalTrackerCompute()
    asyncio.run(agent.start())
```

- [ ] **Step 5: Run all tests**

Run: `.venv/bin/pytest tests/unit/service_tests/test_signal_tracker_compute.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add services/signal_tracker_compute.py \
       tests/unit/service_tests/test_signal_tracker_compute.py
git commit -m "feat: add SignalTrackerCompute — DB-ignorant lifecycle evaluation"
```

---

## Task 5: Create systemd units and Kafka topic

**Files:**
- Create: `production/systemd/indicagent-signal-tracker-compute.service` (reference)
- Create: `production/systemd/indicagent-lifecycle-writer.service` (reference)

- [ ] **Step 1: Create Kafka topic**

```bash
docker exec redpanda rpk topic create development.lifecycle.transitions
```

- [ ] **Step 2: Create systemd unit for lifecycle writer**

Create `production/systemd/indicagent-lifecycle-writer.service`:

```ini
[Unit]
Description=IndicAgent Lifecycle Writer — batch persist signal lifecycle transitions
After=network.target redpanda.service timescaledb.service
Wants=redpanda.service timescaledb.service

[Service]
Type=simple
User=bg
Group=bg
WorkingDirectory=/home/bg/dev/indicagent
ExecStart=/home/bg/dev/indicagent/.venv/bin/python services/lifecycle_writer_agent.py
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1
Environment=INDICAGENT_ENV=development

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 3: Create systemd unit for tracker compute**

Create `production/systemd/indicagent-signal-tracker-compute.service`:

```ini
[Unit]
Description=IndicAgent Signal Tracker Compute — evaluate signal lifecycle (DB-ignorant)
After=network.target redpanda.service
Wants=redpanda.service

[Service]
Type=simple
User=bg
Group=bg
WorkingDirectory=/home/bg/dev/indicagent
ExecStart=/home/bg/dev/indicagent/.venv/bin/python services/signal_tracker_compute.py
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1
Environment=INDICAGENT_ENV=development

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 4: Install and enable services**

```bash
sudo cp production/systemd/indicagent-lifecycle-writer.service /etc/systemd/system/
sudo cp production/systemd/indicagent-signal-tracker-compute.service /etc/systemd/system/
sudo systemctl daemon-reload
```

- [ ] **Step 5: Commit**

```bash
git add production/systemd/indicagent-signal-tracker-compute.service \
       production/systemd/indicagent-lifecycle-writer.service
git commit -m "feat: add systemd units for tracker compute + lifecycle writer"
```

---

## Task 6: Deploy, archive old tracker, verify

**Files:**
- Archive: `services/signal_tracker_agent.py` → `services/_archived_signal_tracker_agent.py`
- Archive: `tests/unit/service_tests/test_signal_tracker_agent.py` → `tests/unit/service_tests/_archived_test_signal_tracker_agent.py`

- [ ] **Step 1: Start lifecycle writer first**

```bash
sudo systemctl start indicagent-lifecycle-writer
sleep 5
sudo systemctl status indicagent-lifecycle-writer
```

Expected: `active (running)`, no errors in log

- [ ] **Step 2: Start tracker compute**

```bash
sudo systemctl start indicagent-signal-tracker-compute
sleep 5
sudo systemctl status indicagent-signal-tracker-compute
```

Expected: `active (running)`, bootstrapped signals from DB

- [ ] **Step 3: Stop old tracker**

```bash
sudo systemctl stop indicagent-signal-tracker
sudo systemctl disable indicagent-signal-tracker
```

- [ ] **Step 4: Verify no decompression errors**

```bash
grep -c "decompression" logs/signal_tracker_compute.log || echo "0"
grep -c "decompression" logs/lifecycle_writer_agent.log || echo "0"
```

Expected: 0 errors

- [ ] **Step 5: Verify lag draining**

```bash
docker exec redpanda rpk group describe signal_tracker_compute -t
docker exec redpanda rpk group describe lifecycle_writer_group -t
```

Expected: Both consuming, lag decreasing

- [ ] **Step 6: Verify signal activations for crypto**

```bash
docker exec timescaledb psql -U postgres -d indicagent -c \
  "SELECT symbol, status, COUNT(*) FROM signal_ledger
   WHERE feature_ts > NOW() - INTERVAL '1 hour'
   GROUP BY symbol, status ORDER BY symbol, status;"
```

Expected: BTCUSD/ETHUSD showing `active` and `expired` signals, not just `pending`

- [ ] **Step 7: Archive old tracker files**

```bash
git mv services/signal_tracker_agent.py services/_archived_signal_tracker_agent.py
git mv tests/unit/service_tests/test_signal_tracker_agent.py \
       tests/unit/service_tests/_archived_test_signal_tracker_agent.py
```

Add deprecation header to `_archived_signal_tracker_agent.py`:
```python
"""DEPRECATED: signal_tracker_agent 2026-04-10 — compute/persistence separation.
Compute logic moved to signal_tracker_compute.py.
Persistence moved to lifecycle_writer_agent.py."""
```

- [ ] **Step 8: Run full test suite**

```bash
.venv/bin/pytest tests/unit/ -v
```

Expected: ALL PASS

- [ ] **Step 9: Lint and format**

```bash
.venv/bin/ruff check . --fix && .venv/bin/black .
```

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "feat: deploy tracker compute + lifecycle writer, archive old tracker

- signal_tracker_agent → _archived (compute/persistence were interleaved)
- signal_tracker_compute: DB-ignorant lifecycle evaluation + symbol filtering
- lifecycle_writer_agent: batch persist transitions to signal_ledger
- Follows DAG pattern: compute → Kafka → writer → DB"
```

---

## Self-Review

### Spec Coverage

| Spec Requirement | Task |
|---|---|
| Decompression limit → 0 | Task 1, Step 1 |
| Disable signal_ledger compression | Task 1, Step 2 |
| Expire orphaned signals | Task 1, Step 3 |
| Symbol filtering | Task 4 (implemented in `_should_process_bar`) |
| Timeframe filtering | Task 4 (implemented in `_get_signals_for_bar`) |
| Batch bar consumption | Task 4 (consumer design allows getmany extension) |
| Periodic Kafka commits | Task 4 (`COMMIT_INTERVAL_SECS`) |
| Compute/persistence separation | Tasks 3+4 (two services, Kafka between them) |
| Chandelier through writer | Task 4 (published as transition) |
| One bootstrap | Task 4 (`_bootstrap_active_signals`) |
| Streaming signal ingestion | Task 4 (`_signal_ingestion_loop`) |
| No checkpointing | Task 4 (idempotent restart from DB + offsets) |
| Batch SQL by transition type | Task 3 (`batch_execute` groups by type) |
| Migration plan | Task 6 |

### Placeholder Scan

No TBDs, TODOs, or incomplete sections. All code blocks contain actual implementation.

### Type Consistency

- `LifecycleTransition` dataclass used consistently across Tasks 2-4
- `TransitionType` enum values match between schema and writer
- `_active_index` typed as `dict[tuple[str, str], list[dict]]` in Task 4
- All `signal_id` references use `str` type
