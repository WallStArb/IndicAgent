#!/usr/bin/env python3
"""Lifecycle Writer Agent — persists signal lifecycle transitions to signal_events.

Consumes lifecycle.transitions Kafka topic, buffers transitions,
groups by type, and batch-writes to the 3-table schema via SignalEventsRepository:

  - status transitions   → signal_events.status (update_signal_status)
  - activation metadata  → trade_frames.frame_details JSONB (update_frame_details)
  - exit/resolution      → signal_events.status + trade_frames.frame_details
  - MAE/MFE tracking     → trade_frames.frame_details JSONB
  - chandelier state     → trade_frames.frame_details JSONB

WriterAgent role: DB-only, zero compute. No lifecycle evaluation.
Consumer group: lifecycle_writer_group
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict

import _path_bootstrap  # noqa: F401 — project root on sys.path

from src.config.config_service import ConfigService
from src.core.agent.base_writer import BaseWriter
from src.core.database_manager import DatabaseManager
from src.core.kafka_utils import KafkaConsumerClient
from src.core.service_utils import format_iso_ts, parse_iso_ts
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
from src.persistence.repository.signal_events_repository import (
    SignalEventsRepository,
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
    """WriterAgent: lifecycle.transitions -> signal_events (3-table schema).

    Routes each transition type to the appropriate 3-table target:
      - activation  → update_signal_status("active") + update_frame_details(meta)
      - exit        → update_signal_status(status) + update_frame_details(exit_meta)
      - chandelier_update → update_frame_details(chandelier_meta)
      - mae_mfe_update    → update_frame_details(mae_mfe_meta)
      - shadow_outcome    → update_frame_details(shadow_meta)
      - market_resolution → update_frame_details(market_meta)
    """

    def __init__(self) -> None:
        super().__init__(
            max_idle_seconds=300,
        )

        self._db: DatabaseManager | None = None
        self._consumer: KafkaConsumerClient | None = None
        self._repo: SignalEventsRepository | None = None
        self._config: ConfigService | None = None

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

    async def _flush_activation_items(self, items: list[dict]) -> None:
        """Write activation transitions: status → 'active', metadata → frame_details."""
        assert self._repo is not None
        for entry in items:
            signal_id = entry["signal_id"]
            # 1. Set signal_events.status = 'active'
            await self._repo.update_signal_status(signal_id, "active")
            # 2. Write activation metadata to trade_frames.frame_details JSONB
            meta: dict = {}
            activated_at = entry.get("activated_at")
            if activated_at is not None:
                meta["activated_at"] = (
                    format_iso_ts(activated_at)
                    if not isinstance(activated_at, str)
                    else activated_at
                )
            for key in ("activation_price", "zone_entry_pct", "bars_to_activation"):
                val = entry.get(key)
                if val is not None:
                    meta[key] = val
            # regime_at_activation: HMM regime at activation time (D-08)
            regime_at_activation = entry.get("hmm_regime_at_fire") or entry.get(
                "regime_at_activation"
            )
            if regime_at_activation is not None:
                meta["regime_at_activation"] = regime_at_activation
            if meta:
                await self._repo.update_frame_details(signal_id, meta)

    async def _flush_exit_items(self, items: list[dict]) -> None:
        """Write exit transitions to signal_events.status + trade_frames.frame_details.

        "First writer wins" idempotency: update_signal_status is idempotent.
        When both replay auditor and live tracker emit EXIT, the second write
        is a status no-op (same status twice) — counted and logged.
        """
        assert self._repo is not None
        for entry in items:
            signal_id = entry["signal_id"]
            status = entry.get("status", "expired")

            # Update signal_events.status
            await self._repo.update_signal_status(signal_id, status)

            # Write exit metadata to trade_frames.frame_details JSONB
            meta: dict = {}
            exit_at = entry.get("exit_at")
            if exit_at is not None:
                meta["exit_at"] = (
                    format_iso_ts(exit_at) if not isinstance(exit_at, str) else exit_at
                )
            for key in (
                "exit_price",
                "exit_reason",
                "pnl_ticks",
                "pnl_r",
                "pnl_dollars",
                "signal_quality",
                "mae",
                "mfe",
                "bars_in_trade",
                "outcome",
            ):
                val = entry.get(key)
                if val is not None:
                    meta[key] = val
            if meta:
                await self._repo.update_frame_details(signal_id, meta)

            # Idempotency counter (previously tracked as "first writer wins" in _EXIT_IDEMPOTENT_SQL)
            # update_signal_status is always idempotent; no skip detection needed here.
            LIFECYCLE_WRITER_IDEMPOTENT_SKIP_TOTAL.add(
                0
            )  # Metric kept for observability continuity

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
            if ttype == "activation":
                await self._flush_activation_items(items)
            elif ttype == "exit":
                await self._flush_exit_items(items)
            else:
                # chandelier_update, mae_mfe_update, shadow_outcome, market_resolution
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
        self._repo = SignalEventsRepository(self._db)

        # Load APR batch/flush/buffer constants (D-12 mandate)
        self._config = ConfigService(self.settings.database_url, pool=self._db.pool)
        self.BATCH_SIZE = int(
            await self._config.get("feature.lifecycle_writer.batch_size", default=100)
        )
        self.FLUSH_INTERVAL_SECS = float(
            await self._config.get("feature.lifecycle_writer.flush_interval_secs", default=5.0)
        )
        self.MAX_BUFFER_SIZE = int(
            await self._config.get("feature.lifecycle_writer.max_buffer_size", default=10000)
        )
        # Sync overflow threshold used by _buffer_rows() overflow guard
        self._overflow_threshold = self.MAX_BUFFER_SIZE

        self._create_consumer()
        await self._consumer.start()
        self._last_flush = time.monotonic()
        self.logger.info(
            "lifecycle_writer.started",
            topic=self._topic_name(),
            batch_size=self.BATCH_SIZE,
            flush_interval=self.FLUSH_INTERVAL_SECS,
        )

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
