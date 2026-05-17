"""lineage_writer_agent.py — persists signal lineage events from Kafka to TimescaleDB.

Consumes topic_signal_lineage() published by LineageRecorder.
Replaces GraduationWriterAgent's write path and swarm_writer_agent's shadow write path.
"""

import asyncio
import time

import asyncpg

from src.config.settings import Settings
from src.core.agent.base_writer import BaseWriterAgent
from src.core.ai.lineage import LineageEvent
from src.core.database_manager import create_pool as create_db_pool
from src.core.service_utils import parse_iso_ts
from src.core.stream_keys import topic_signal_lineage, topic_signal_lineage_dlq


class LineageWriterAgent(BaseWriterAgent):
    """Consumes signal lineage events and persists to signal_lineage hypertable."""

    payload_model = LineageEvent

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

    def _parse_payload(self, payload: LineageEvent) -> list | None:
        """Receive already-validated LineageEvent from base; return as single-item list."""
        return [payload]

    def _to_row(self, event: LineageEvent) -> tuple:
        """Map LineageEvent fields to positional INSERT params.

        Positions must match the INSERT INTO signal_lineage SQL exactly.
        """
        return (
            parse_iso_ts(event.ts),  # $1 ts::timestamptz
            str(event.signal_id),  # $2 signal_id::uuid
            event.event_type,  # $3 event_type::text
            event.source,  # $4 source::text
            event.dag_order,  # $5 dag_order::int
            event.multiplier,  # $6 multiplier::float
            event.metadata,  # $7 metadata::jsonb
            event.is_shadow,  # $8 is_shadow::bool
            event.symbol,  # $9 symbol::text
            event.tf,  # $10 tf::text
        )

    async def _flush_batch(self, batch: list[LineageEvent]) -> None:
        """Batch insert lineage events into signal_lineage."""
        if not batch:
            return
        rows = [self._to_row(e) for e in batch]

        async with self._pool.acquire() as conn:
            await conn.executemany(
                """INSERT INTO signal_lineage
                   (ts, signal_id, event_type, source, dag_order, multiplier, metadata, is_shadow, symbol, tf)
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
