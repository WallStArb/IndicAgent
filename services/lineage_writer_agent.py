"""lineage_writer_agent.py — persists signal lineage events from Kafka to TimescaleDB.

Consumes topic_signal_lineage() published by LineageRecorder.
Replaces GraduationWriterAgent's write path and swarm_writer_agent's shadow write path.
"""
import asyncio

from src.config.settings import Settings
from src.core.agent.base_writer import BaseWriterAgent
from src.core.stream_keys import topic_signal_lineage, topic_signal_lineage_dlq


class LineageWriterAgent(BaseWriterAgent):
    """Consumes signal lineage events and persists to signal_lineage hypertable."""

    batch_size = 100
    flush_interval_s = 2.0

    def _topic_name(self) -> str:
        return topic_signal_lineage(self.env_name)

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
            rows.append((
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
            ))

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
