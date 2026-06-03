#!/usr/bin/env python3
"""Lifecycle Writer Agent — persists signal lifecycle transitions to signal_ledger.

Consumes lifecycle.transitions Kafka topic, buffers transitions,
groups by type, and batch-writes to signal_ledger via execute_batch().

WriterAgent role: DB-only, zero compute. No lifecycle evaluation.
Consumer group: lifecycle_writer_group
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict

import _path_bootstrap  # noqa: F401 — project root on sys.path

from src.core.agent.base_writer import BaseWriter
from src.core.database_manager import DatabaseManager
from src.core.kafka_utils import KafkaConsumerClient
from src.core.service_utils import parse_iso_ts
from src.core.stream_keys import (
    topic_lifecycle_transitions,
    topic_lifecycle_writer_dlq,
)
from src.intelligence.trading.lifecycle_transitions import from_dict
from src.observability.metrics import (
    LIFECYCLE_WRITER_IDEMPOTENT_SKIP_TOTAL,
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
        "market_entry_at",
        "market_entry_exit_at",
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


class LifecycleWriter(BaseWriter):
    """WriterAgent: lifecycle.transitions -> signal_ledger batch updates."""

    BATCH_SIZE = 100
    FLUSH_INTERVAL_SECS = 5.0
    MAX_BUFFER_SIZE = 10_000

    def __init__(self) -> None:
        super().__init__(
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
        self._batch_latency_attrs = {"agent_id": self._agent_label}

    def _topic_name(self) -> str:
        return topic_lifecycle_transitions(self.settings.env_name)

    @property
    def _consumer_group(self) -> str:
        return CONSUMER_GROUP

    def _dlq_topic(self) -> str | None:
        """Route unparseable lifecycle payloads to DLQ."""
        return topic_lifecycle_writer_dlq(self.settings.env_name)

    def _parse_payload(self, payload: dict) -> tuple[list, list]:
        try:
            from_dict(payload)
        except (ValueError, KeyError):
            return [], [payload]
        return [payload], []

    # ------------------------------------------------------------------
    # Exit-specific idempotency guard
    # ------------------------------------------------------------------

    # Idempotency guard SQL: WHERE signal_id = $1 AND exit_at IS NULL
    # "First writer wins" — replay auditor and live tracker can both emit
    # EXIT transitions; only the first one that finds exit_at IS NULL wins.
    # The second write is a no-op (UPDATE 0 rows) and increments the counter.
    _EXIT_IDEMPOTENT_SQL = """
UPDATE signal_outcomes
   SET status = $2,
       exit_at = $3,
       exit_price = $4,
       exit_reason = $5,
       pnl_ticks = $6,
       pnl_r = $7,
       pnl_dollars = $8,
       signal_quality = $9,
       mae = $10,
       mfe = $11,
       bars_in_trade = $12,
       outcome = $13
 WHERE signal_id = $1::uuid
   AND exit_at IS NULL
"""

    def _exit_to_params(self, entry: dict) -> tuple:
        """Map exit transition dict to positional params for _EXIT_IDEMPOTENT_SQL.

        Positions must match the $N placeholders in _EXIT_IDEMPOTENT_SQL exactly.
        """
        return (
            entry.get("signal_id"),  # $1 signal_id::uuid (WHERE clause)
            entry.get("status"),  # $2 status::text
            entry.get("exit_at"),  # $3 exit_at::timestamptz
            entry.get("exit_price"),  # $4 exit_price::numeric
            entry.get("exit_reason"),  # $5 exit_reason::text
            entry.get("pnl_ticks"),  # $6 pnl_ticks::numeric
            entry.get("pnl_r"),  # $7 pnl_r::numeric
            entry.get("pnl_dollars"),  # $8 pnl_dollars::numeric
            entry.get("signal_quality"),  # $9 signal_quality::numeric
            entry.get("mae"),  # $10 mae::numeric
            entry.get("mfe"),  # $11 mfe::numeric
            entry.get("bars_in_trade"),  # $12 bars_in_trade::integer
            entry.get("outcome"),  # $13 outcome::text
        )

    async def _flush_exit_items(self, items: list[dict]) -> None:
        """Write exit transitions one-at-a-time to detect idempotent skips.

        Uses WHERE exit_at IS NULL guard so a second writer (replay auditor
        vs. live tracker) is always a safe no-op.  When asyncpg returns
        "UPDATE 0" the skip counter is incremented and a warning logged.
        """
        if self._db is None:
            raise RuntimeError("LifecycleWriter._db not initialized — _setup() not called")
        for entry in items:
            result: str = await self._db.execute_command(
                self._EXIT_IDEMPOTENT_SQL,
                *self._exit_to_params(entry),
            )
            if result.endswith(" 0"):
                LIFECYCLE_WRITER_IDEMPOTENT_SKIP_TOTAL.add(1)
                self.logger.info(
                    "lifecycle_writer_idempotent_skip",
                    signal_id=entry.get("signal_id"),
                    note="exit_at already set; first writer wins",
                )

    async def _flush_batch(self, batch: list) -> None:
        """Group buffered transitions by type, batch-write each group."""
        t0 = time.perf_counter()
        if self._repo is None:
            raise RuntimeError("LifecycleWriter._repo not initialized — _setup() not called")

        groups: dict[str, list[dict]] = defaultdict(list)
        for item in batch:
            entry = {"signal_id": item["signal_id"], **item["data"]}
            _ensure_datetimes(entry)
            groups[item["transition_type"]].append(entry)

        for ttype, items in groups.items():
            if ttype == "exit":
                await self._flush_exit_items(items)
            else:
                await self._repo.batch_execute(ttype, items)

        self._transitions_written.add(len(batch))
        PERSISTENCE_BATCH_LATENCY.record(time.perf_counter() - t0, self._batch_latency_attrs)
        self.logger.info(
            "lifecycle_writer.flushed",
            count=len(batch),
            groups=list(groups.keys()),
        )

    async def _setup(self) -> None:
        self._db = DatabaseManager(self.settings.database_url)
        await self._db.initialize()
        self._repo = SignalLedgerRepository(self._db)

        self._create_consumer()
        await self._consumer.start()
        self._last_flush = time.monotonic()
        self.logger.info("lifecycle_writer.started", topic=self._topic_name())

    def _on_message_consumed(self, payload: dict) -> None:
        self._events_consumed.add(1)

    async def _teardown(self) -> None:
        await super()._teardown()
        if self._consumer:
            await self._consumer.stop()
        if self._db:
            await self._db.close()


if __name__ == "__main__":
    agent = LifecycleWriter()
    asyncio.run(agent.start())
