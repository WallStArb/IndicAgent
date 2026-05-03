"""lineage_writer_agent.py — persists signal lineage events from Kafka to TimescaleDB.

Consumes topic_signal_lineage() published by LineageRecorder.
Replaces GraduationWriterAgent's write path and swarm_writer_agent's shadow write path.
"""

import asyncio
import time

import asyncpg

from src.config.settings import Settings
from src.core.agent.base_writer import BaseWriterAgent
from src.core.database_manager import create_pool as create_db_pool
from src.core.stream_keys import topic_signal_lineage, topic_signal_lineage_dlq


class LineageWriterAgent(BaseWriterAgent):
    """Consumes signal lineage events and persists to signal_lineage hypertable."""

    batch_size = 100
    flush_interval_s = 2.0

    def __init__(self, **kwargs):
        super().__init__(name="lineage_writer_agent", **kwargs)
        self._pool: asyncpg.Pool | None = None

    async def _setup(self) -> None:
        self._pool = await create_db_pool(
            self.settings.database_url,
            min_size=2,
            max_size=5,
        )
        self._create_consumer()
        await self._consumer.start()
        self._last_flush = time.monotonic()
        self.logger.info("lineage_writer.started", topic=self._topic_name())

    async def _teardown(self) -> None:
        await super()._teardown()
        if self._consumer:
            await self._consumer.stop()
        if self._pool:
            await self._pool.close()

    def _topic_name(self) -> str:
        return topic_signal_lineage(self.env_name)

    @property
    def _consumer_group(self) -> str:
        return "lineage_writer_consumer"

    def _dlq_topic(self) -> str | None:
        return topic_signal_lineage_dlq(self.env_name)

    def _parse_payload(self, payload: dict) -> list | None:
        """Parse lineage event from Kafka message."""
        if not payload.get("signal_id") or not payload.get("event_type"):
            return None
        return [payload]

    async def _flush_batch(self, batch: list[dict]) -> None:
        """Batch insert lineage events into signal_lineage."""
        if not batch:
            return
        rows = []
        for event in batch:
            rows.append(
                (
                    event["ts"],
                    event["signal_id"],
                    event["event_type"],
                    event["source"],
                    event.get("dag_order"),
                    event.get("multiplier"),
                    event.get("metadata", {}),
                    event.get("is_shadow", True),
                    event.get("symbol", ""),
                    event.get("tf", ""),
                )
            )

        async with self._pool.acquire() as conn:
            await conn.executemany(
                """INSERT INTO signal_lineage
                   (ts, signal_id, event_type, source, dag_order, multiplier, metadata, is_shadow, symbol, tf) # noqa: E501
                   VALUES ($1::timestamptz, $2::uuid, $3, $4, $5, $6, $7::jsonb, $8, $9, $10)
                   ON CONFLICT DO NOTHING""",
                rows,
            )


def main() -> None:
    from src.core.service_utils import setup_service_logging

    settings = Settings()
    setup_service_logging("logs/lineage_writer_agent.log")

    agent = LineageWriterAgent(settings=settings)
    asyncio.run(agent.start())


if __name__ == "__main__":
    main()
