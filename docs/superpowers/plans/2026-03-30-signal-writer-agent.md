# SignalWriterAgent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the dead `signal_generator_agent` with a thin `SignalWriterAgent` that persists all I7 signals to `signal_ledger`, eliminating the double-I7-compute anti-pattern and restoring DB-ignorant separation of concerns.

**Architecture:** `intelligence_pipeline_agent` (ComputeAgent) publishes all ranked I7 signals to a new `intelligence.i7.signals` topic after each bar. `SignalWriterAgent` (WriterAgent) subscribes to that topic, converts signal dicts to `LedgerEntry` objects, and batch-inserts to `signal_ledger`. `signal_generator_agent` is retired. The winner signal routing is also fixed: currently incorrectly publishing to `topic_intelligence`; corrected to `topic_signals_aggregated` so `signal_tracker_agent` receives it.

**Tech Stack:** Python 3.13, asyncio, aiokafka via `KafkaConsumerClient`, asyncpg via `DatabaseManager`, `SignalLedgerRepository`, `LedgerEntry`, `BaseAgent`, structlog, Prometheus.

---

## File Map

| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `src/core/stream_keys.py` | Add `topic_intelligence_i7_signals()` |
| Modify | `services/intelligence_pipeline_agent.py` | Publish all ranked signals to new topic; fix winner → `topic_signals_aggregated` |
| Create | `services/signal_writer_agent.py` | WriterAgent: consume → `LedgerEntry` → `signal_ledger` |
| Create | `production/systemd/indicagent-signal-writer.service` | Systemd unit reference template |
| Create | `tests/unit/service_tests/test_signal_writer_agent.py` | Unit tests |
| Archive | `services/signal_generator_agent.py` → `services/_archived_signal_generator_agent.py` | Retirement |

---

## Task 1: Add `topic_intelligence_i7_signals` to stream_keys.py

**Files:**
- Modify: `src/core/stream_keys.py`

- [ ] **Step 1: Add the topic function after `topic_intelligence_journal`**

In `src/core/stream_keys.py`, after the `topic_intelligence_journal` function (around line 157):

```python
def topic_intelligence_i7_signals(env_name: str) -> str:
    """Kafka topic carrying all ranked I7 signals per bar (pre-ledger write).

    Published by IntelligencePipelineComputeAgent after each bar's I7 run.
    Consumed by SignalWriterAgent for signal_ledger persistence.
    Payload schema: {symbol, tf, bar_ts, computed_at, signals: list[dict]}
    """
    return f"{env_prefix(env_name)}intelligence.i7.signals"
```

- [ ] **Step 2: Run tests to confirm no regressions**

```bash
.venv/bin/pytest tests/unit/ -v -x -q 2>&1 | tail -20
```

Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git add src/core/stream_keys.py
git commit -m "feat(streams): add topic_intelligence_i7_signals for SignalWriterAgent"
```

---

## Task 2: Modify `_run_i7` — publish all signals, fix winner routing

**Files:**
- Modify: `services/intelligence_pipeline_agent.py`
- Modify import section of same file

Context: `_run_i7` is around line 1032. Currently it:
1. Runs plugins → `raw_signals`
2. Applies quality/regime/TOD/calibration gates
3. Ranks → selects winner
4. **BUG:** enqueues winner to `topic_intelligence` (wrong — that carries IntelligenceEvents)
5. **MISSING:** never publishes all signals for ledger persistence

- [ ] **Step 1: Add the new topic import to the existing import block**

Find the block near the top of `services/intelligence_pipeline_agent.py` that imports from `src.core.stream_keys`. Add `topic_intelligence_i7_signals` and `topic_signals_aggregated`:

```python
from src.core.stream_keys import (
    # ... existing imports ...
    topic_intelligence_i7_signals,
    topic_signals_aggregated,
)
```

- [ ] **Step 2: Verify existing imports to avoid duplicates**

```bash
grep -n "topic_signals_aggregated\|topic_intelligence_i7_signals\|from src.core.stream_keys" services/intelligence_pipeline_agent.py | head -20
```

Only add what's missing. `topic_signals_aggregated` may already be imported — check first.

- [ ] **Step 3: Replace the tail of `_run_i7` (winner enqueue + end of function)**

Locate the block starting at `if winner:` near the end of `_run_i7`. Replace from `ranked = rank_signals(...)` to the end of the function:

```python
        ranked = rank_signals(calibrated, self._perf_weights)
        winner = select_winner([s for s in ranked if s.get("regime_eligible", True)])
        winner_plugin = winner.get("setup_plugin") if winner else None

        # Annotate each ranked signal with ledger metadata
        num_signals = len(ranked)
        for rank_idx, sig in enumerate(ranked, start=1):
            sig["composite_rank"] = rank_idx
            sig["num_signals_bar"] = num_signals
            sig["was_selected"] = (
                winner_plugin is not None
                and sig.get("setup_plugin") == winner_plugin
                and sig.get("regime_eligible", True)
            )
            sig["status"] = (
                "pending" if sig.get("regime_eligible", True) else "regime_suppressed"
            )
            # is_shadow: check plugin class attribute
            plugin_inst = self._plugin_cache.get(sig.get("setup_plugin", ""))
            sig["is_shadow"] = bool(
                plugin_inst is not None and getattr(plugin_inst, "IS_SHADOW", False)
            )

        # Publish ALL ranked signals for SignalWriterAgent → signal_ledger
        self._enqueue(
            topic_intelligence_i7_signals(self._settings.env_name),
            message_key(symbol, tf),
            {
                "symbol": symbol,
                "tf": tf,
                "bar_ts": bar.ts.isoformat(),
                "computed_at": datetime.now(UTC).isoformat(),
                "signals": ranked,
            },
        )

        # Publish winner to signals.aggregated for signal_tracker_agent
        if winner:
            self._signals_selected.inc()
            self._enqueue(
                topic_signals_aggregated(self._settings.env_name),
                message_key(symbol, tf),
                winner,
            )
```

Note: `bar` is available in `_run_i7` via its signature `(self, bar: BarMessage, event: IntelligenceEvent, tiered: dict)`.

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/unit/ -v -x -q 2>&1 | tail -20
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add services/intelligence_pipeline_agent.py
git commit -m "fix(pipeline): publish all I7 signals to i7.signals topic; fix winner → signals.aggregated"
```

---

## Task 3: Create `SignalWriterAgent`

**Files:**
- Create: `services/signal_writer_agent.py`

This is a pure WriterAgent: no plugin execution, no regime logic, no I7 compute. Consume → deserialize → `LedgerEntry` → batch insert.

- [ ] **Step 1: Write the failing test first** (see Task 4 — write tests before implementing)

Skip ahead to Task 4, write the structural test, then return here.

- [ ] **Step 2: Create `services/signal_writer_agent.py`**

```python
#!/usr/bin/env python3
"""Signal Writer Agent — persists all I7 signals to signal_ledger hypertable.

Subscribes to intelligence.i7.signals (published by IntelligencePipelineComputeAgent
after each bar's I7 run). Converts signal dicts to LedgerEntry objects and
batch-inserts to signal_ledger via SignalLedgerRepository.

WriterAgent role: DB-only, zero compute. No plugin execution.
Consumer group: signal_writer_group
Metrics port: 9119
"""

from __future__ import annotations

import asyncio
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.config.settings import Settings
from src.core.agent.base import BaseAgent
from src.core.database_manager import DatabaseManager
from src.core.kafka_utils import KafkaConsumerClient
from src.core.service_utils import setup_service_logging
from src.core.stream_keys import topic_intelligence_i7_signals
from src.observability.metrics import (
    PERSISTENCE_BATCH_LATENCY,
    PERSISTENCE_CONSUMER_LAG,
    counter,
    gauge,
)
from src.persistence.repository.signal_ledger_repository import (
    LedgerEntry,
    SignalLedgerRepository,
    SignalStatus,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CONSUMER_GROUP = "signal_writer_group"
BATCH_SIZE = 100          # flush after this many LedgerEntry rows
FLUSH_INTERVAL_SECS = 5.0 # or after this many seconds, whichever comes first


class SignalWriterAgent(BaseAgent):
    """WriterAgent: intelligence.i7.signals → signal_ledger."""

    def __init__(self) -> None:
        super().__init__(name="signal_writer_agent", metrics_port=9119)
        setup_service_logging("signal_writer_agent")

        self._settings = Settings()
        self._db: DatabaseManager | None = None
        self._consumer: KafkaConsumerClient | None = None
        self._repo: SignalLedgerRepository | None = None

        # Metrics — Golden Signals
        self._events_consumed = counter(
            "signal_writer_events_consumed_total",
            "Kafka messages consumed",
        )
        self._signals_written = counter(
            "signal_writer_signals_written_total",
            "LedgerEntry rows inserted",
        )
        self._write_errors = counter(
            "signal_writer_write_errors_total",
            "Failed batch inserts",
        )
        self._batch_latency = PERSISTENCE_BATCH_LATENCY.labels(
            agent="signal_writer_agent"
        )
        self._consumer_lag = PERSISTENCE_CONSUMER_LAG.labels(
            agent="signal_writer_agent"
        )
        self._buffer_depth = gauge(
            "signal_writer_buffer_depth",
            "Pending LedgerEntry rows awaiting flush",
        )

    async def _setup(self) -> None:
        self._db = DatabaseManager(self._settings.database_url)
        await self._db.initialize()
        self._repo = SignalLedgerRepository(self._db)

        self._consumer = KafkaConsumerClient(
            topic_intelligence_i7_signals(self._settings.env_name),
            bootstrap_servers=self._settings.kafka_bootstrap_servers,
            group_id=CONSUMER_GROUP,
            auto_offset_reset="earliest",
        )
        await self._consumer.start()
        self.logger.info(
            "signal_writer.started",
            topic=topic_intelligence_i7_signals(self._settings.env_name),
        )

    async def _run(self) -> None:
        buffer: list[LedgerEntry] = []
        last_flush = time.monotonic()

        async for _topic, _key, payload in self._consumer.messages():
            if not isinstance(payload, dict):
                continue
            self._events_consumed.inc()

            entries = _payload_to_ledger_entries(payload)
            buffer.extend(entries)
            self._buffer_depth.set(len(buffer))

            now = time.monotonic()
            if len(buffer) >= BATCH_SIZE or (now - last_flush) >= FLUSH_INTERVAL_SECS:
                await self._flush(buffer)
                buffer.clear()
                last_flush = now
                self._buffer_depth.set(0)

    async def _flush(self, buffer: list[LedgerEntry]) -> None:
        if not buffer:
            return
        t0 = time.perf_counter()
        try:
            await self._repo.insert_signals(buffer)
            self._signals_written.inc(len(buffer))
            self._batch_latency.observe(time.perf_counter() - t0)
            self.logger.info("signal_writer.flushed", count=len(buffer))
        except Exception as exc:
            self._write_errors.inc()
            self.logger.error("signal_writer.flush_error", error=str(exc))

    async def _teardown(self) -> None:
        if self._consumer:
            await self._consumer.stop()
        if self._db:
            await self._db.close()


def _payload_to_ledger_entries(payload: dict) -> list[LedgerEntry]:
    """Convert an intelligence.i7.signals payload to a list of LedgerEntry objects."""
    symbol = payload.get("symbol", "")
    tf = payload.get("tf", "")
    signals: list[dict] = payload.get("signals", [])
    computed_at = _parse_ts(payload.get("computed_at"))
    bar_ts = _parse_ts(payload.get("bar_ts")) or computed_at

    if not signals:
        return []

    entries: list[LedgerEntry] = []
    num_signals = len(signals)
    for sig in signals:
        status = (
            SignalStatus.REGIME_SUPPRESSED
            if sig.get("status") == "regime_suppressed"
            else SignalStatus.PENDING
        )
        entries.append(
            LedgerEntry(
                signal_id=str(sig.get("signal_id") or uuid4()),
                timestamp=bar_ts,
                symbol=symbol,
                timeframe=tf,
                setup_plugin=str(sig.get("setup_plugin", "unknown")),
                signal_type=str(sig.get("signal_type", "unknown")),
                direction=int(sig.get("direction", 0)),
                entry_price=float(sig.get("entry_price", 0.0)),
                stop_loss=float(sig.get("stop_loss", 0.0)),
                targets=[float(t) for t in (sig.get("targets") or [])],
                confidence=float(sig.get("confidence", 0.0)),
                confluence_score=float(sig.get("confluence_score", 0.0)),
                regime_context=str(sig.get("regime_context", "")),
                supporting_factors=list(sig.get("supporting_factors") or []),
                was_selected=bool(sig.get("was_selected", False)),
                num_signals_bar=int(sig.get("num_signals_bar", num_signals)),
                num_agreeing=0,
                num_conflicting=0,
                resolution_method="in_process",
                composite_rank=int(sig.get("composite_rank", 0)),
                status=status,
                feature_ts=bar_ts,
                feature_tf=tf,
                signal_computed_at=computed_at,
                hmm_regime_at_fire=sig.get("hmm_regime_at_fire"),
                regime_type_at_fire=str(sig.get("regime_type", "")) or None,
                is_shadow=bool(sig.get("is_shadow", False)),
                pre_quality_confidence=sig.get("pre_quality_confidence"),
                pre_calibration_confidence=sig.get("pre_calibration_confidence"),
            )
        )
    return entries


def _parse_ts(value: str | None) -> datetime | None:
    """Parse ISO-8601 timestamp string to timezone-aware UTC datetime."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)
    except (ValueError, TypeError):
        return None


if __name__ == "__main__":
    agent = SignalWriterAgent()
    asyncio.run(agent.run())
```

- [ ] **Step 3: Run the tests written in Task 4**

```bash
.venv/bin/pytest tests/unit/service_tests/test_signal_writer_agent.py -v
```

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add services/signal_writer_agent.py
git commit -m "feat(agent): add SignalWriterAgent — intelligence.i7.signals → signal_ledger"
```

---

## Task 4: Write unit tests for SignalWriterAgent

**Files:**
- Create: `tests/unit/service_tests/test_signal_writer_agent.py`

Write these BEFORE implementing Task 3 Step 2 (TDD).

- [ ] **Step 1: Create test file**

```python
"""Unit tests for SignalWriterAgent.

Uses ServiceClass.__new__(ServiceClass) pattern to bypass __init__ (per CLAUDE.md).
Tests structural contract, _payload_to_ledger_entries conversion, and flush behavior.
"""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
from prometheus_client import Counter, Gauge, Histogram

# Module-level test metrics to avoid duplicate registration
_TEST_EVENTS = Counter("test_swa_events_total", "Events (test)")
_TEST_SIGNALS = Counter("test_swa_signals_total", "Signals (test)")
_TEST_ERRORS = Counter("test_swa_errors_total", "Errors (test)")
_TEST_LATENCY = Histogram("test_swa_latency_seconds", "Latency (test)", ["agent"])
_TEST_LAG = Gauge("test_swa_lag", "Lag (test)", ["agent"])
_TEST_DEPTH = Gauge("test_swa_depth", "Depth (test)")


def _make_agent():
    """Build a minimal SignalWriterAgent bypassing __init__."""
    from services.signal_writer_agent import SignalWriterAgent

    agent = SignalWriterAgent.__new__(SignalWriterAgent)
    agent.logger = MagicMock()
    agent.running = True
    agent._settings = MagicMock()
    agent._settings.database_url = "postgresql://postgres@localhost/indicagent"
    agent._settings.kafka_bootstrap_servers = "localhost:19092"
    agent._settings.env_name = "development"
    agent._db = MagicMock()
    agent._consumer = MagicMock()
    agent._repo = MagicMock()
    agent._repo.insert_signals = AsyncMock()
    agent._events_consumed = _TEST_EVENTS
    agent._signals_written = _TEST_SIGNALS
    agent._write_errors = _TEST_ERRORS
    agent._batch_latency = _TEST_LATENCY.labels(agent="test")
    agent._consumer_lag = _TEST_LAG.labels(agent="test")
    agent._buffer_depth = _TEST_DEPTH
    return agent


def _make_payload(n_signals: int = 2, winner_idx: int = 0) -> dict:
    """Build a minimal intelligence.i7.signals payload."""
    signals = []
    for i in range(n_signals):
        signals.append({
            "signal_id": f"sig_{i}",
            "setup_plugin": f"trad_Plugin{i}",
            "signal_type": "long",
            "direction": 1,
            "entry_price": 5000.0 + i,
            "stop_loss": 4990.0,
            "targets": [5020.0],
            "confidence": 0.6 - i * 0.1,
            "confluence_score": 0.7,
            "regime_context": "trending",
            "supporting_factors": ["rsi_cross"],
            "was_selected": i == winner_idx,
            "num_signals_bar": n_signals,
            "composite_rank": i + 1,
            "status": "pending",
            "is_shadow": False,
            "pre_quality_confidence": 0.65,
            "pre_calibration_confidence": 0.62,
            "regime_type": "trend",
        })
    return {
        "symbol": "ES",
        "tf": "1m",
        "bar_ts": "2026-03-30T12:00:00+00:00",
        "computed_at": "2026-03-30T12:00:01+00:00",
        "signals": signals,
    }


# ---------------------------------------------------------------------------
# Structural contract
# ---------------------------------------------------------------------------

class TestSignalWriterAgentStructure:
    def test_consumer_group_constant(self):
        from services.signal_writer_agent import CONSUMER_GROUP
        assert CONSUMER_GROUP == "signal_writer_group"

    def test_batch_size_and_flush_interval_defined(self):
        from services.signal_writer_agent import BATCH_SIZE, FLUSH_INTERVAL_SECS
        assert BATCH_SIZE > 0
        assert FLUSH_INTERVAL_SECS > 0


# ---------------------------------------------------------------------------
# _payload_to_ledger_entries conversion
# ---------------------------------------------------------------------------

class TestPayloadToLedgerEntries:
    def test_returns_one_entry_per_signal(self):
        from services.signal_writer_agent import _payload_to_ledger_entries
        payload = _make_payload(n_signals=3)
        entries = _payload_to_ledger_entries(payload)
        assert len(entries) == 3

    def test_empty_signals_returns_empty(self):
        from services.signal_writer_agent import _payload_to_ledger_entries
        entries = _payload_to_ledger_entries({"symbol": "ES", "tf": "1m", "signals": []})
        assert entries == []

    def test_winner_entry_was_selected_true(self):
        from services.signal_writer_agent import _payload_to_ledger_entries
        payload = _make_payload(n_signals=2, winner_idx=0)
        entries = _payload_to_ledger_entries(payload)
        assert entries[0].was_selected is True
        assert entries[1].was_selected is False

    def test_regime_suppressed_status_mapped(self):
        from services.signal_writer_agent import _payload_to_ledger_entries
        from src.persistence.repository.signal_ledger_repository import SignalStatus
        payload = _make_payload(n_signals=1)
        payload["signals"][0]["status"] = "regime_suppressed"
        entries = _payload_to_ledger_entries(payload)
        assert entries[0].status == SignalStatus.REGIME_SUPPRESSED

    def test_pending_status_mapped(self):
        from services.signal_writer_agent import _payload_to_ledger_entries
        from src.persistence.repository.signal_ledger_repository import SignalStatus
        payload = _make_payload(n_signals=1)
        payload["signals"][0]["status"] = "pending"
        entries = _payload_to_ledger_entries(payload)
        assert entries[0].status == SignalStatus.PENDING

    def test_missing_signal_id_gets_uuid(self):
        from services.signal_writer_agent import _payload_to_ledger_entries
        payload = _make_payload(n_signals=1)
        del payload["signals"][0]["signal_id"]
        entries = _payload_to_ledger_entries(payload)
        # Must be a valid UUID string
        UUID(entries[0].signal_id)

    def test_bar_ts_parsed_as_utc_datetime(self):
        from services.signal_writer_agent import _payload_to_ledger_entries
        payload = _make_payload(n_signals=1)
        entries = _payload_to_ledger_entries(payload)
        assert isinstance(entries[0].timestamp, datetime)
        assert entries[0].timestamp.tzinfo is not None

    def test_symbol_tf_propagated(self):
        from services.signal_writer_agent import _payload_to_ledger_entries
        payload = _make_payload(n_signals=1)
        entries = _payload_to_ledger_entries(payload)
        assert entries[0].symbol == "ES"
        assert entries[0].timeframe == "1m"
        assert entries[0].feature_tf == "1m"

    def test_attribution_fields_preserved(self):
        from services.signal_writer_agent import _payload_to_ledger_entries
        payload = _make_payload(n_signals=1)
        entries = _payload_to_ledger_entries(payload)
        assert entries[0].pre_quality_confidence == pytest.approx(0.65)
        assert entries[0].pre_calibration_confidence == pytest.approx(0.62)

    def test_is_shadow_propagated(self):
        from services.signal_writer_agent import _payload_to_ledger_entries
        payload = _make_payload(n_signals=1)
        payload["signals"][0]["is_shadow"] = True
        entries = _payload_to_ledger_entries(payload)
        assert entries[0].is_shadow is True

    def test_num_signals_bar_set_from_payload(self):
        from services.signal_writer_agent import _payload_to_ledger_entries
        payload = _make_payload(n_signals=3)
        entries = _payload_to_ledger_entries(payload)
        assert all(e.num_signals_bar == 3 for e in entries)

    def test_composite_rank_set(self):
        from services.signal_writer_agent import _payload_to_ledger_entries
        payload = _make_payload(n_signals=2)
        entries = _payload_to_ledger_entries(payload)
        assert entries[0].composite_rank == 1
        assert entries[1].composite_rank == 2


# ---------------------------------------------------------------------------
# Flush behavior
# ---------------------------------------------------------------------------

class TestSignalWriterAgentFlush:
    @pytest.mark.asyncio
    async def test_flush_calls_insert_signals(self):
        from services.signal_writer_agent import _payload_to_ledger_entries
        agent = _make_agent()
        payload = _make_payload(n_signals=2)
        entries = _payload_to_ledger_entries(payload)
        await agent._flush(entries)
        agent._repo.insert_signals.assert_called_once_with(entries)

    @pytest.mark.asyncio
    async def test_flush_empty_buffer_is_noop(self):
        agent = _make_agent()
        await agent._flush([])
        agent._repo.insert_signals.assert_not_called()

    @pytest.mark.asyncio
    async def test_flush_error_increments_counter(self):
        agent = _make_agent()
        agent._repo.insert_signals = AsyncMock(side_effect=Exception("db down"))
        from services.signal_writer_agent import _payload_to_ledger_entries
        entries = _payload_to_ledger_entries(_make_payload(n_signals=1))
        before = _TEST_ERRORS._value.get()
        await agent._flush(entries)
        assert _TEST_ERRORS._value.get() > before


# ---------------------------------------------------------------------------
# _parse_ts helper
# ---------------------------------------------------------------------------

class TestParseTs:
    def test_parses_iso_with_tz(self):
        from services.signal_writer_agent import _parse_ts
        result = _parse_ts("2026-03-30T12:00:00+00:00")
        assert result.tzinfo is not None
        assert result.year == 2026

    def test_naive_gets_utc(self):
        from services.signal_writer_agent import _parse_ts
        result = _parse_ts("2026-03-30T12:00:00")
        assert result.tzinfo is not None

    def test_none_returns_none(self):
        from services.signal_writer_agent import _parse_ts
        assert _parse_ts(None) is None

    def test_invalid_returns_none(self):
        from services.signal_writer_agent import _parse_ts
        assert _parse_ts("not-a-date") is None
```

- [ ] **Step 2: Run tests — expect failures (TDD red phase)**

```bash
.venv/bin/pytest tests/unit/service_tests/test_signal_writer_agent.py -v 2>&1 | tail -20
```

Expected: `ModuleNotFoundError` or `ImportError` — `signal_writer_agent` doesn't exist yet.

- [ ] **Step 3: Implement Task 3 Step 2, then run tests again**

```bash
.venv/bin/pytest tests/unit/service_tests/test_signal_writer_agent.py -v 2>&1 | tail -30
```

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add tests/unit/service_tests/test_signal_writer_agent.py
git commit -m "test(signal-writer): TDD tests for SignalWriterAgent"
```

---

## Task 5: Create systemd unit and install

**Files:**
- Create: `production/systemd/indicagent-signal-writer.service` (reference template)

- [ ] **Step 1: Create the reference template**

```bash
cat > production/systemd/indicagent-signal-writer.service << 'EOF'
[Unit]
Description=IndicAgent Signal Writer Agent — I7 signals → signal_ledger
After=network.target docker.service
Wants=docker.service

[Service]
Type=simple
User=bg
WorkingDirectory=/home/bg/dev/indicagent
ExecStart=/home/bg/dev/indicagent/.venv/bin/python services/signal_writer_agent.py
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=indicagent-signal-writer
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF
```

- [ ] **Step 2: Install and enable**

```bash
echo '***REDACTED-SUDO-PASSWORD***' | /usr/bin/sudo.ws -S cp production/systemd/indicagent-signal-writer.service /etc/systemd/system/
echo '***REDACTED-SUDO-PASSWORD***' | /usr/bin/sudo.ws -S systemctl daemon-reload
echo '***REDACTED-SUDO-PASSWORD***' | /usr/bin/sudo.ws -S systemctl enable indicagent-signal-writer
echo '***REDACTED-SUDO-PASSWORD***' | /usr/bin/sudo.ws -S systemctl start indicagent-signal-writer
sleep 3
echo '***REDACTED-SUDO-PASSWORD***' | /usr/bin/sudo.ws -S systemctl status indicagent-signal-writer --no-pager | grep -E "Active:|Main PID"
```

Expected: `Active: active (running)`

- [ ] **Step 3: Verify it consumes and writes**

```bash
sleep 30
docker exec timescaledb psql -U postgres -d indicagent -c \
  "SELECT count(*) FROM signal_ledger WHERE feature_ts > NOW() - INTERVAL '5 minutes';"
```

Expected: count > 0 (assuming intelligence pipeline is producing bars).

- [ ] **Step 4: Commit**

```bash
git add production/systemd/indicagent-signal-writer.service
git commit -m "ops(signal-writer): add systemd unit for SignalWriterAgent"
```

---

## Task 6: Retire signal_generator_agent

- [ ] **Step 1: Stop and disable the service**

```bash
echo '***REDACTED-SUDO-PASSWORD***' | /usr/bin/sudo.ws -S systemctl stop indicagent-signal-generator
echo '***REDACTED-SUDO-PASSWORD***' | /usr/bin/sudo.ws -S systemctl disable indicagent-signal-generator
echo '***REDACTED-SUDO-PASSWORD***' | /usr/bin/sudo.ws -S systemctl status indicagent-signal-generator --no-pager | grep Active
```

Expected: `Active: inactive (dead)`

- [ ] **Step 2: Archive the service file**

```bash
mv services/signal_generator_agent.py services/_archived_signal_generator_agent.py
```

- [ ] **Step 3: Run full test suite to confirm nothing breaks**

```bash
.venv/bin/pytest tests/unit/ -v -x -q 2>&1 | tail -20
```

Expected: all pass. If any test imports `signal_generator_agent` directly, update the import to point to the archived name or skip the test.

- [ ] **Step 4: Commit**

```bash
git add services/_archived_signal_generator_agent.py services/signal_generator_agent.py
git commit -m "chore: retire signal_generator_agent — replaced by SignalWriterAgent + unified pipeline I7"
```

---

## Task 7: Restart intelligence pipeline and verify end-to-end

- [ ] **Step 1: Restart the intelligence pipeline to pick up the new topic publish**

```bash
echo '***REDACTED-SUDO-PASSWORD***' | /usr/bin/sudo.ws -S systemctl restart indicagent-intelligence-pipeline
sleep 10
echo '***REDACTED-SUDO-PASSWORD***' | /usr/bin/sudo.ws -S systemctl status indicagent-intelligence-pipeline --no-pager | grep Active
```

- [ ] **Step 2: Verify `intelligence.i7.signals` topic has messages**

```bash
docker exec redpanda rpk topic consume development.intelligence.i7.signals -n 1 2>/dev/null | python3 -c "
import sys, json
data = json.load(sys.stdin)
val = data.get('value', {})
if isinstance(val, str):
    val = json.loads(val)
print('symbol:', val.get('symbol'))
print('tf:', val.get('tf'))
print('signal count:', len(val.get('signals', [])))
"
```

Expected: symbol, tf, and signal count printed.

- [ ] **Step 3: Verify signal_ledger is receiving rows**

```bash
sleep 60
docker exec timescaledb psql -U postgres -d indicagent -c \
  "SELECT symbol, feature_tf, count(*), max(feature_ts) as latest
   FROM signal_ledger
   WHERE feature_ts > NOW() - INTERVAL '10 minutes'
   GROUP BY symbol, feature_tf
   ORDER BY latest DESC
   LIMIT 10;"
```

Expected: rows with recent timestamps.

- [ ] **Step 4: Verify winner routing reaches signal_tracker**

```bash
tail -20 /home/bg/dev/indicagent/logs/signal_tracker_agent.log 2>/dev/null | grep -E '"event"'
```

Expected: signal activation or evaluation events.

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "feat(phase-57.1): SignalWriterAgent live — unified pipeline owns I7 end-to-end"
```

---

## Self-Review

**Spec coverage:**
- ✅ `topic_intelligence_i7_signals` added to stream_keys — Task 1
- ✅ All ranked signals (not just winner) published from `_run_i7` — Task 2
- ✅ Winner correctly routed to `topic_signals_aggregated` (fixes current bug) — Task 2
- ✅ `SignalWriterAgent` WriterAgent created, DB-ignorant compute preserved — Task 3
- ✅ `LedgerEntry` conversion covers all fields including Phase 57 attribution — Task 3
- ✅ `is_shadow` flag propagated from plugin class attribute — Task 2 + Task 3
- ✅ `regime_suppressed` signals preserved in ledger (not filtered) — Task 3
- ✅ TDD: tests written before implementation — Task 4
- ✅ Systemd unit installed — Task 5
- ✅ `signal_generator_agent` stopped, disabled, archived — Task 6
- ✅ End-to-end verification — Task 7

**Placeholder scan:** No TBDs, no "implement later", no "similar to Task N" — all code blocks are complete.

**Type consistency:** `LedgerEntry` fields match `src/persistence/repository/signal_ledger_repository.py` exactly. `SignalStatus.PENDING` / `SignalStatus.REGIME_SUPPRESSED` used (not raw strings). `DatabaseManager(url)` + `await db.initialize()` matches current API. `KafkaConsumerClient(*topics, bootstrap_servers=..., group_id=...)` matches current constructor.
