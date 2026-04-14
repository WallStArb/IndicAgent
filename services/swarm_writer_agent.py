"""SwarmWriterAgent — persists AgentResult shadow predictions to alpha_multiplier_shadow.

Consumes: topic_swarm_results() — one AgentResult per message (fan-out from orchestrator)
Writes:   alpha_multiplier_shadow (asyncpg batch insert)
DLQ:      topic_swarm_writer_dlq() — malformed payloads or DB failures
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

import asyncpg
import structlog

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.config.settings import Settings
from src.core.agent.base_writer import BaseWriterAgent
from src.core.kafka_utils import KafkaConsumerClient, KafkaProducerClient
from src.core.stream_keys import topic_swarm_results, topic_swarm_writer_dlq

logger = structlog.get_logger(__name__)


def _parse_ts(ts: str | datetime) -> datetime:
    """Parse timestamp string to UTC-aware datetime for asyncpg timestamptz columns."""
    if isinstance(ts, datetime):
        return ts if ts.tzinfo is not None else ts.replace(tzinfo=UTC)
    dt = datetime.fromisoformat(ts)
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


_INSERT_SQL = """
INSERT INTO alpha_multiplier_shadow
    (ts, signal_id, agent_id, symbol, tf, hmm_regime,
     path, predicted_multiplier, confidence, features)
VALUES
    ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
ON CONFLICT (signal_id, agent_id) DO NOTHING
"""

_REQUIRED_FIELDS = frozenset(
    {"signal_id", "agent_id", "symbol", "tf", "ts", "multiplier", "confidence", "path"}
)


class SwarmWriterAgent(BaseWriterAgent):
    """Consume AgentResult messages, batch-insert to alpha_multiplier_shadow."""

    BATCH_SIZE = 50
    FLUSH_INTERVAL_SECS = 2.0

    def __init__(self) -> None:
        super().__init__(name="SwarmWriterAgent")
        self._producer: KafkaProducerClient | None = None
        self._pool: asyncpg.Pool | None = None

    def _topic_name(self) -> str:
        return topic_swarm_results(self.settings.env_name)

    @property
    def _consumer_group(self) -> str:
        return "swarm_writer_consumer"

    def _parse_payload(self, payload: dict) -> list | None:
        if not isinstance(payload, dict) or not _REQUIRED_FIELDS.issubset(payload.keys()):
            return None
        return [payload]

    async def _flush_batch(self, batch: list) -> None:
        assert self._pool is not None
        assert self._producer is not None
        rows = [
            (
                _parse_ts(p["ts"]),
                p["signal_id"],
                p["agent_id"],
                p["symbol"],
                p["tf"],
                p.get("hmm_regime"),
                p["path"],
                float(p["multiplier"]),
                float(p["confidence"]),
                p.get("features"),  # asyncpg handles dict->JSONB natively
            )
            for p in batch
        ]
        async with self._pool.acquire() as conn:
            await conn.executemany(_INSERT_SQL, rows)
        self.logger.info("swarm_writer.batch_written", count=len(rows))

    def _dlq_topic(self) -> str | None:
        return topic_swarm_writer_dlq(self.settings.env_name)

    async def _setup(self) -> None:
        env = self.settings.env_name
        self._consumer = KafkaConsumerClient(
            topic_swarm_results(env),
            bootstrap_servers=self.settings.kafka_bootstrap_servers,
            group_id="swarm_writer_consumer",
            auto_offset_reset="earliest",
            enable_auto_commit=False,
        )
        await self._consumer.start()

        self._producer = KafkaProducerClient(
            bootstrap_servers=self.settings.kafka_bootstrap_servers,
        )
        await self._producer.start()

        self._pool = await asyncpg.create_pool(self.settings.database_url)
        self.logger.info("swarm_writer_agent.started")

    async def _run(self) -> None:
        assert self._consumer is not None
        async for _topic, _key, payload in self._consumer.messages():
            self._record_message_consumed()
            rows = self._parse_payload(payload)
            if rows is not None:
                self._buffer_rows(rows)
            else:
                # Parse failed — route to DLQ for analysis
                await self._maybe_route_to_dlq(payload, Exception("Parse failed"))

            await self.maybe_flush()

    async def _teardown(self) -> None:
        await super()._teardown()
        if self._consumer:
            await self._consumer.stop()
        if self._producer:
            await self._producer.stop()
        if self._pool:
            await self._pool.close()


def main() -> None:
    agent = SwarmWriterAgent()
    asyncio.run(agent.start())


if __name__ == "__main__":
    main()
