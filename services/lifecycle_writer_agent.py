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
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.core.agent.base_writer import BaseWriterAgent
from src.core.database_manager import DatabaseManager
from src.core.kafka_utils import KafkaConsumerClient
from src.core.service_utils import parse_iso_ts
from src.core.stream_keys import (
    topic_lifecycle_transitions,
    topic_lifecycle_writer_dlq,
)
from src.intelligence.trading.lifecycle_transitions import from_dict
from src.observability.metrics import (
    PERSISTENCE_BATCH_LATENCY,
    counter,
)
from src.persistence.repository.signal_ledger_repository import (
    SignalLedgerRepository,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CONSUMER_GROUP = "lifecycle_writer_group"

# Fields that asyncpg expects as Python datetime, not ISO strings
_TIMESTAMP_FIELDS = frozenset(
    {
        "activated_at",
        "exit_at",
        "shadow_tracking_start_ts",
    }
)


def _ensure_datetimes(entry: dict) -> None:
    """Convert ISO timestamp strings to datetime objects for asyncpg.

    Kafka JSON serialization turns datetime objects into ISO strings.
    asyncpg requires Python datetime objects for timestamptz columns.
    """
    for key in _TIMESTAMP_FIELDS:
        val = entry.get(key)
        if val is not None:
            entry[key] = parse_iso_ts(val)


class LifecycleWriterAgent(BaseWriterAgent):
    """WriterAgent: lifecycle.transitions -> signal_ledger batch updates."""

    BATCH_SIZE = 100
    FLUSH_INTERVAL_SECS = 5.0
    MAX_BUFFER_SIZE = 10_000

    def __init__(self) -> None:
        super().__init__(
            name="lifecycle_writer_agent",
            metrics_port=9128,
            max_idle_seconds=300,
        )

        self._db: DatabaseManager | None = None
        self._consumer: KafkaConsumerClient | None = None
        self._repo: SignalLedgerRepository | None = None

        # Metrics — Golden Signals (writer-specific)
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
        self._batch_latency = PERSISTENCE_BATCH_LATENCY.labels(agent_id="lifecycle_writer_agent")

    def _topic_name(self) -> str:
        return topic_lifecycle_transitions(self.settings.env_name)

    @property
    def _consumer_group(self) -> str:
        return CONSUMER_GROUP

    def _dlq_topic(self) -> str | None:
        """Route unparseable lifecycle payloads to DLQ."""
        return topic_lifecycle_writer_dlq(self.settings.env_name)

    def _parse_payload(self, payload: dict) -> list | None:
        try:
            from_dict(payload)
        except (ValueError, KeyError):
            return None
        return [payload]

    async def _flush_batch(self, batch: list) -> None:
        """Group buffered transitions by type, batch-write each group."""
        t0 = time.perf_counter()
        assert self._repo is not None

        # Group by transition_type — merge signal_id into data for batch_execute
        groups: dict[str, list[dict]] = defaultdict(list)
        for item in batch:
            entry = {"signal_id": item["signal_id"], **item["data"]}
            _ensure_datetimes(entry)
            groups[item["transition_type"]].append(entry)

        for ttype, items in groups.items():
            await self._repo.batch_execute(ttype, items)

        self._transitions_written.inc(len(batch))
        self._batch_latency.observe(time.perf_counter() - t0)
        self.logger.info(
            "lifecycle_writer.flushed",
            count=len(batch),
            groups=list(groups.keys()),
        )

    async def _setup(self) -> None:
        self._db = DatabaseManager(self.settings.database_url)
        await self._db.initialize()
        self._repo = SignalLedgerRepository(self._db)

        topic = self._topic_name()
        self._consumer = KafkaConsumerClient(
            topic,
            bootstrap_servers=self.settings.kafka_bootstrap_servers,
            group_id=CONSUMER_GROUP,
            auto_offset_reset="earliest",
            enable_auto_commit=False,
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

            rows = self._parse_payload(payload)
            if rows is not None:
                self._buffer_rows(rows)
            else:
                # Parse failed — route to DLQ for analysis
                await self._maybe_route_to_dlq(payload, Exception("Parse failed"))

            self._consumer_lag.set(len(self._buffer))
            await self.maybe_flush()


    async def _teardown(self) -> None:
        await super()._teardown()
        if self._consumer:
            await self._consumer.stop()
        if self._db:
            await self._db.close()


if __name__ == "__main__":
    agent = LifecycleWriterAgent()
    asyncio.run(agent.start())
