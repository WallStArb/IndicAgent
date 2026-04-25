#!/usr/bin/env python3
"""Graduation Writer Agent — persists graduation evaluation results to transform_graduation.

Consumes topic_transform_graduation Kafka topic, batches upserts into the
transform_graduation table.

WriterAgent role: DB-only, zero compute.
Consumer group: graduation_writer_group
Metrics port: 9136
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.core.agent.base_writer import BaseWriterAgent
from src.core.database_manager import DatabaseManager
from src.core.kafka_utils import KafkaConsumerClient
from src.core.service_utils import setup_service_logging
from src.core.stream_keys import (
    topic_transform_graduation,
    topic_transform_graduation_dlq,
)
from src.observability.metrics import (
    PERSISTENCE_BATCH_LATENCY,
    counter,
)
from src.persistence.repository.transform_graduation_repository import (
    TransformGraduationRepository,
)

CONSUMER_GROUP = "graduation_writer_group"

_REQUIRED_KEYS = (
    "transform_id",
    "transform_version",
    "segment_key",
    "n",
    "is_graduated",
    "evaluated_at",
    "expires_at",
)


class GraduationWriterAgent(BaseWriterAgent):
    """WriterAgent: topic_transform_graduation -> transform_graduation upserts."""

    BATCH_SIZE = 50
    FLUSH_INTERVAL_SECS = 5.0
    MAX_BUFFER_SIZE = 1_000

    def __init__(self) -> None:
        super().__init__(
            name="graduation_writer_agent",
            metrics_port=9136,
            max_idle_seconds=300,
        )
        self._db: DatabaseManager | None = None
        self._consumer: KafkaConsumerClient | None = None
        self._repo: TransformGraduationRepository | None = None

        self._events_consumed = counter(
            "graduation_writer_events_consumed_total",
            "Kafka messages consumed",
        )
        self._rows_written = counter(
            "graduation_writer_rows_written_total",
            "Graduation rows upserted",
        )
        self._write_errors = counter(
            "graduation_writer_write_errors_total",
            "Failed batch writes",
        )
        self._batch_latency = PERSISTENCE_BATCH_LATENCY.labels(agent_id="graduation_writer_agent")

    def _topic_name(self) -> str:
        return topic_transform_graduation(self.settings.env_name)

    @property
    def _consumer_group(self) -> str:
        return CONSUMER_GROUP

    def _dlq_topic(self) -> str | None:
        return topic_transform_graduation_dlq(self.settings.env_name)

    def _parse_payload(self, payload: dict) -> list | None:
        if not isinstance(payload, dict):
            return None
        if not all(k in payload for k in _REQUIRED_KEYS):
            return None
        return [payload]

    async def _flush_batch(self, batch: list) -> None:
        t0 = time.perf_counter()
        assert self._repo is not None
        try:
            await self._repo.batch_upsert(batch)
            self._rows_written.inc(len(batch))
        except Exception:
            self._write_errors.inc()
            raise
        finally:
            self._batch_latency.observe(time.perf_counter() - t0)
        self.logger.info("graduation_writer.flushed", count=len(batch))

    async def _setup(self) -> None:
        setup_service_logging("logs/graduation_writer_agent.log")
        self._db = DatabaseManager(self.settings.database_url)
        await self._db.initialize()
        self._repo = TransformGraduationRepository(self._db)
        self._create_consumer()
        await self._consumer.start()
        self._last_flush = time.monotonic()
        self.logger.info("graduation_writer.started", topic=self._topic_name())

    def _on_message_consumed(self, payload: dict) -> None:
        self._events_consumed.inc()

    async def _teardown(self) -> None:
        await super()._teardown()
        if self._consumer:
            await self._consumer.stop()
        if self._db:
            await self._db.close()


if __name__ == "__main__":
    agent = GraduationWriterAgent()
    asyncio.run(agent.start())
