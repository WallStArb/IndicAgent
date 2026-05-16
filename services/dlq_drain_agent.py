#!/usr/bin/env python3
"""DLQDrainAgent — continuous consumer of all DLQ topics, writes to dlq_events.

Subscribes to all 15 active DLQ topics as a single consumer group. Parses each
message as a DLQPayload, then inserts into the dlq_events hypertable. All events
are preserved — no dedup (burst errors from same agent/topic must not be silently
dropped).

Purpose: DLQ messages become queryable history (was: write-only black hole).
One consumer, one table, one source of DLQ truth.

Architecture:
    L9 consumer (alongside signal_auditor, parity_auditor, alerting_agent):
      1. Subscribe to all 15 DLQ topics via dlq_drain_consumer group
      2. For each message: parse DLQPayload, upsert to dlq_events
      3. Emit structured log per event (dlq_drained)
      4. Skip unparseable messages with log warning (no crash)
"""

from __future__ import annotations

import asyncio
from datetime import UTC

import _path_bootstrap  # noqa: F401 — project root on sys.path
import asyncpg
import structlog

from src.core.agent.base import BaseAgent
from src.core.database_manager import create_pool as create_db_pool
from src.core.kafka_utils import KafkaConsumerClient
from src.core.schemas.dlq_payload import DLQPayload
from src.core.service_utils import setup_service_logging
from src.core.stream_keys import (
    topic_bar_aggregator_dlq,
    topic_bar_writer_dlq,
    topic_feature_writer_dlq,
    topic_gap_fill_dlq,
    topic_health_events_dlq,
    topic_intelligence_pipeline_dlq,
    topic_lifecycle_writer_dlq,
    topic_llm_writer_dlq,
    topic_ml_orchestrator_dlq,
    topic_roll_dlq,
    topic_signal_dlq,
    topic_signal_lineage_dlq,
    topic_signal_tracker_dlq,
    topic_signal_writer_dlq,
    topic_transform_graduation_dlq,
)

logger = structlog.get_logger(__name__)

CONSUMER_GROUP: str = "dlq_drain_consumer"

_INSERT_SQL: str = """
INSERT INTO dlq_events
    (routed_at, agent, source_topic, dlq_topic, error_type, error_message, payload, retry_count)
VALUES
    ($1, $2, $3, $4, $5, $6, $7, $8)
"""


class DLQDrainAgent(BaseAgent):
    """Continuous Kafka consumer draining all 15 DLQ topics into dlq_events.

    Follows BaseAgent lifecycle contract (setup/_run/stop). No timer loop —
    processes messages as they arrive. Consumer group: dlq_drain_consumer.
    """

    def __init__(self) -> None:
        super().__init__(name="dlq_drain_agent", max_idle_seconds=600)

        self._pool: asyncpg.Pool | None = None
        self._consumer: KafkaConsumerClient | None = None

    def _build_topics(self) -> list[str]:
        """Return all 15 active DLQ topic names for this environment."""
        env = self.settings.env_name
        return [
            topic_roll_dlq(env),
            topic_signal_dlq(env),
            topic_bar_aggregator_dlq(env),
            topic_bar_writer_dlq(env),
            topic_feature_writer_dlq(env),
            topic_signal_writer_dlq(env),
            topic_lifecycle_writer_dlq(env),
            topic_intelligence_pipeline_dlq(env),
            topic_signal_tracker_dlq(env),
            topic_llm_writer_dlq(env),
            topic_transform_graduation_dlq(env),
            topic_signal_lineage_dlq(env),
            topic_ml_orchestrator_dlq(env),
            topic_gap_fill_dlq(env),
            topic_health_events_dlq(env),
        ]

    async def _setup(self) -> None:
        """Create DB pool and subscribe consumer to all 15 DLQ topics."""
        await super()._setup()
        self._pool = await create_db_pool(self.settings.database_url)
        topics = self._build_topics()
        self._consumer = KafkaConsumerClient(
            *topics,
            bootstrap_servers=self.settings.kafka_bootstrap_servers,
            group_id=CONSUMER_GROUP,
            auto_offset_reset="earliest",
        )
        await self._consumer.start()
        self.logger.info("dlq_drain_started", topic_count=len(topics))

    async def _run(self) -> None:
        """Main consume loop — process DLQ messages until stop event."""
        assert self._consumer is not None
        assert self._pool is not None

        async for dlq_topic, _key, payload in self._consumer.messages():
            if self._stop_event.is_set():
                break

            await self._drain_message(dlq_topic, payload)

    async def _drain_message(self, dlq_topic: str, raw: dict) -> None:
        """Parse raw payload as DLQPayload and upsert to dlq_events."""
        assert self._pool is not None

        try:
            msg = DLQPayload.model_validate(raw)
        except Exception as exc:
            self.logger.warning(
                "dlq_drain_parse_failed",
                dlq_topic=dlq_topic,
                error=str(exc),
                raw_preview=str(raw)[:200],
            )
            return

        routed_at = msg.timestamp if msg.timestamp.tzinfo else msg.timestamp.replace(tzinfo=UTC)

        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    _INSERT_SQL,
                    routed_at,
                    msg.agent,
                    msg.source_topic,
                    dlq_topic,
                    msg.error_type,
                    msg.error_message,
                    msg.payload,
                    msg.retry_count,
                )
        except Exception as exc:
            self.logger.error(
                "dlq_drain_db_write_failed",
                dlq_topic=dlq_topic,
                agent=msg.agent,
                error=str(exc),
            )
            return

        self.logger.info(
            "dlq_drained",
            agent=msg.agent,
            source_topic=msg.source_topic,
            dlq_topic=dlq_topic,
            error_type=msg.error_type,
            error_message=msg.error_message[:120],
        )

    async def stop(self) -> None:
        """Drain in-flight messages, close consumer and pool."""
        self.logger.info("dlq_drain_stopping")
        self._stop_event.set()
        if self._consumer is not None:
            await self._consumer.stop()
        if self._pool is not None:
            await self._pool.close()
        await super().stop()


# ── Entrypoint ────────────────────────────────────────────────────────────────


async def main() -> None:
    setup_service_logging("logs/dlq_drain_agent.log")
    agent = DLQDrainAgent()
    await agent.start()


if __name__ == "__main__":
    asyncio.run(main())
