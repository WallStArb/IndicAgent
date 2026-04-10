#!/usr/bin/env python3
"""Lifecycle Writer Agent — persists signal lifecycle transitions to signal_ledger.

Consumes lifecycle.transitions Kafka topic, buffers transitions,
groups by type, and batch-writes to signal_ledger via execute_batch().

WriterAgent role: DB-only, zero compute. No lifecycle evaluation.
Consumer group: lifecycle_writer_consumer
Metrics port: 9128
"""

from __future__ import annotations

import asyncio
import sys
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.config.settings import Settings
from src.core.agent.base import BaseAgent
from src.core.database_manager import DatabaseManager
from src.core.kafka_utils import KafkaConsumerClient
from src.core.stream_keys import topic_lifecycle_transitions
from src.intelligence.trading.lifecycle_transitions import from_dict
from src.observability.metrics import (
    PERSISTENCE_BATCH_LATENCY,
    PERSISTENCE_CONSUMER_LAG,
    counter,
    gauge,
)
from src.persistence.repository.signal_ledger_repository import (
    SignalLedgerRepository,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CONSUMER_GROUP = "lifecycle_writer_consumer"
BATCH_SIZE = 100  # flush after this many transitions
FLUSH_INTERVAL_SECS = 5.0  # or after this many seconds, whichever comes first
MAX_BUFFER_SIZE = 10_000  # drop oldest transitions if buffer exceeds this

# Fields that asyncpg expects as Python datetime, not ISO strings
_TIMESTAMP_FIELDS = frozenset({
    "activated_at", "exit_at", "shadow_tracking_start_ts",
})


def _ensure_datetimes(entry: dict) -> None:
    """Convert ISO timestamp strings to datetime objects for asyncpg.

    Kafka JSON serialization turns datetime objects into ISO strings.
    asyncpg requires Python datetime objects for timestamptz columns.
    """
    for key in _TIMESTAMP_FIELDS:
        val = entry.get(key)
        if isinstance(val, str):
            dt = datetime.fromisoformat(val)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            entry[key] = dt


class LifecycleWriterAgent(BaseAgent):
    """WriterAgent: lifecycle.transitions → signal_ledger batch updates."""

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
        self._buffer: list[dict] = []
        self._last_flush: float = 0.0

        # Metrics — Golden Signals
        self._events_consumed = counter(
            "lifecycle_writer_events_consumed_total",
            "Kafka messages consumed",
        )
        self._transitions_written = counter(
            "lifecycle_writer_transitions_written_total",
            "Transition rows batch-written",
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
            self._record_message_consumed()
            self._events_consumed.inc()

            try:
                from_dict(payload)
            except (ValueError, KeyError) as exc:
                await self._send_to_dlq(payload, exc)
                continue

            self._buffer.append(payload)

            # Memory safety: drop oldest transitions if buffer exceeds limit
            if len(self._buffer) > MAX_BUFFER_SIZE:
                dropped = len(self._buffer) - MAX_BUFFER_SIZE
                self._buffer = self._buffer[-MAX_BUFFER_SIZE:]
                self.logger.warning(
                    "lifecycle_writer.buffer_overflow", dropped=dropped
                )

            self._buffer_depth.set(len(self._buffer))

            now = time.monotonic()
            if len(self._buffer) >= BATCH_SIZE or (
                now - self._last_flush
            ) >= FLUSH_INTERVAL_SECS:
                await self._flush()
                self._last_flush = now

    async def _flush(self) -> None:
        """Group buffered transitions by type, batch-write each group."""
        if not self._buffer:
            return
        batch = self._buffer[:]
        t0 = time.perf_counter()

        # Group by transition_type — merge signal_id into data for batch_execute
        groups: dict[str, list[dict]] = defaultdict(list)
        for item in batch:
            entry = {"signal_id": item["signal_id"], **item["data"]}
            _ensure_datetimes(entry)
            groups[item["transition_type"]].append(entry)

        try:
            for ttype, items in groups.items():
                await self._repo.batch_execute(ttype, items)
            self._buffer.clear()
            self._buffer_depth.set(0)
            self._transitions_written.inc(len(batch))
            self._batch_latency.observe(time.perf_counter() - t0)
            self.logger.info(
                "lifecycle_writer.flushed",
                count=len(batch),
                groups=list(groups.keys()),
            )
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
