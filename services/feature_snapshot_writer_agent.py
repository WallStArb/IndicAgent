#!/usr/bin/env python3
"""FeatureSnapshotWriterAgent — shadow persistence for parity validation.

Consumes BarIntelligenceRecord from intelligence.journal under consumer group
'feature_snapshot_writer_group' (separate from 'feature_writer_group') and writes
to feature_snapshots_shadow. ParityAuditorAgent (Phase 52.5) will compare both
tables to certify that FeatureRepository produces identical results to
FeatureWriterService before primary-write cutover.

Architecture:
    intelligence.journal topic
      ├── feature_writer_group         -> intelligence_features       (existing primary)
      └── feature_snapshot_writer_group -> feature_snapshots_shadow   (this agent)

Design invariant: this agent is intentionally thin — no business logic.
All param-building is delegated to _record_to_insert_params() from feature_writer_service.

Renaissance principle: Shadow before cutover. Earn the right through proof.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from pydantic import ValidationError

from services.feature_writer_service import _build_expiry_map, _record_to_insert_params
from src.config.settings import Settings
from src.core.agent.base import BaseAgent
from src.core.database_manager import DatabaseManager
from src.core.kafka_utils import KafkaConsumerClient
from src.core.service_utils import setup_service_logging
from src.core.stream_keys import topic_intelligence_journal, topic_system_events
from src.intelligence.schemas import BarIntelligenceRecord
from src.observability.metrics import (
    PERSISTENCE_BATCH_LATENCY,
    PERSISTENCE_CONSUMER_LAG,
    counter,
    start_metrics_server,
)
from src.persistence.repository.feature_repository import FeatureRepository

# ── Module-level constants ────────────────────────────────────────────────────

CONSUMER_GROUP: str = "feature_snapshot_writer_group"
CONSUMER_TOPIC_FN = topic_intelligence_journal
SHADOW_TABLE: str = "feature_snapshots_shadow"
BATCH_SIZE: int = 50
FLUSH_INTERVAL_SECS: float = 5.0
METRICS_PORT: int = 9119


class FeatureSnapshotWriterAgent(BaseAgent):
    """Shadow writer: intelligence.journal -> feature_snapshots_shadow.

    Inherits BaseAgent for standard Renaissance lifecycle (SIGTERM drain,
    structlog binding, consumer lag reporter).
    """

    def __init__(self) -> None:
        super().__init__(name="FeatureSnapshotWriterAgent")

        setup_service_logging("logs/feature_snapshot_writer_agent.log")

        self._settings = Settings()
        self._env_name = self._settings.env_name.strip()
        self._kafka_bootstrap = self._settings.kafka_bootstrap_servers

        self._expiry_map: dict = {}
        self._buffer: list[tuple] = []
        self._last_flush = datetime.now(UTC)

        self._db: DatabaseManager | None = None
        self._repo: FeatureRepository | None = None
        self._consumer: KafkaConsumerClient | None = None

        self._events_consumed = counter(
            "feature_snapshot_writer_events_consumed_total",
            "BarIntelligenceRecords consumed by FeatureSnapshotWriterAgent",
        )
        self._shadow_writes = counter(
            "feature_snapshot_writer_shadow_writes_total",
            "Rows written to feature_snapshots_shadow",
        )
        self._parse_errors = counter(
            "feature_snapshot_writer_parse_errors_total",
            "BarIntelligenceRecord parse failures",
        )
        self._write_errors = counter(
            "feature_snapshot_writer_write_errors_total",
            "Shadow write failures",
        )

    def _parse_record(self, raw: bytes | str) -> BarIntelligenceRecord | None:
        """Parse raw Kafka message to BarIntelligenceRecord. Returns None on failure."""
        try:
            return BarIntelligenceRecord.model_validate_json(raw)
        except (ValidationError, ValueError) as exc:
            self.logger.warning("snapshot_writer_parse_failed", error=str(exc))
            self._parse_errors.inc()
            return None

    async def _flush(self) -> None:
        """Flush buffered insert params to the shadow table."""
        if not self._buffer or self._repo is None:
            return
        batch = self._buffer[:]
        self._buffer.clear()
        t0 = datetime.now(UTC)
        for params in batch:
            try:
                await self._repo.insert(params)
                self._shadow_writes.inc()
            except Exception as exc:
                self.logger.error("shadow_write_failed", error=str(exc))
                self._write_errors.inc()
        duration = (datetime.now(UTC) - t0).total_seconds()
        PERSISTENCE_BATCH_LATENCY.labels(agent_id="feature_snapshot_writer").observe(duration)
        PERSISTENCE_CONSUMER_LAG.labels(agent_id="feature_snapshot_writer").set(len(self._buffer))
        self._last_flush = datetime.now(UTC)

    async def _report_consumer_lag(self) -> None:
        """Report consumer lag (buffer size proxy) until stop event."""
        while not self._stop_event.is_set():
            PERSISTENCE_CONSUMER_LAG.labels(agent_id="feature_snapshot_writer").set(len(self._buffer))
            await asyncio.sleep(15)

    async def _run(self) -> None:
        """Main consumer loop — reads intelligence.journal, writes to shadow table."""
        assert self._consumer is not None
        _journal_topic = topic_intelligence_journal(self._env_name)

        async for topic, _key, payload in self._consumer.messages():
            if self._stop_event.is_set():
                break
            try:
                if topic != _journal_topic:
                    continue  # skip system.events on this consumer

                raw = payload if isinstance(payload, (bytes, str)) else str(payload)
                record = self._parse_record(raw)
                if record is None:
                    continue

                params = _record_to_insert_params(record, self._expiry_map)
                self._buffer.append(params)
                self._events_consumed.inc()

                now = datetime.now(UTC)
                if (
                    len(self._buffer) >= BATCH_SIZE
                    or (now - self._last_flush).total_seconds() >= FLUSH_INTERVAL_SECS
                ):
                    await self._flush()

            except asyncio.CancelledError:
                break
            except Exception as exc:
                self.logger.error("consume_loop_error", error=str(exc))

    async def start(self) -> None:
        """Initialize connections, then run the BaseAgent lifecycle."""
        self.logger.info("FeatureSnapshotWriterAgent starting", shadow_table=SHADOW_TABLE)
        start_metrics_server(port=METRICS_PORT)

        # Build expiry map (same as FeatureWriterService)
        try:
            self._expiry_map = _build_expiry_map(self._settings)
            self.logger.info("expiry_map_built", contracts=len(self._expiry_map))
        except Exception as exc:
            self.logger.warning("expiry_map_failed", error=str(exc))

        # DB connection -> shadow repository
        self._db = DatabaseManager(self._settings.database_url)
        await self._db.initialize()
        self._repo = FeatureRepository(self._db, table_name=SHADOW_TABLE)

        # Kafka consumer — distinct group so offsets are tracked independently
        self._consumer = KafkaConsumerClient(
            topic_intelligence_journal(self._env_name),
            topic_system_events(self._env_name),
            bootstrap_servers=self._kafka_bootstrap,
            group_id=CONSUMER_GROUP,
            auto_offset_reset="earliest",
            enable_auto_commit=False,
        )
        await self._consumer.start()
        self.logger.info(
            "snapshot_writer_consumer_started",
            topic=topic_intelligence_journal(self._env_name),
            group=CONSUMER_GROUP,
        )

        # Delegate to BaseAgent lifecycle (registers signal handlers, lag reporter,
        # calls _run(), calls stop() in finally)
        await super().start()

    async def stop(self) -> None:
        """Drain buffer, close Kafka and DB connections."""
        self.logger.info("FeatureSnapshotWriterAgent stopping")
        self._stop_event.set()
        await self._flush()  # drain in-flight batch before exit
        if self._consumer:
            await self._consumer.stop()
        if self._db:
            await self._db.close()
        await super().stop()


async def main() -> None:
    agent = FeatureSnapshotWriterAgent()
    await agent.start()


if __name__ == "__main__":
    asyncio.run(main())
