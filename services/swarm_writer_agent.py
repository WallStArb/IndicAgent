"""SwarmWriterAgent — persists AgentResult shadow predictions to alpha_multiplier_shadow.

Consumes: topic_swarm_results() — one AgentResult per message (fan-out from orchestrator)
Writes:   alpha_multiplier_shadow (asyncpg batch insert)
DLQ:      topic_swarm_writer_dlq() — malformed payloads or DB failures
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import asyncpg
import structlog

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.config.settings import Settings
from src.core.agent.base import BaseAgent
from src.core.kafka_utils import KafkaConsumerClient, KafkaProducerClient
from src.core.stream_keys import topic_swarm_results, topic_swarm_writer_dlq

logger = structlog.get_logger(__name__)

_INSERT_SQL = """
INSERT INTO alpha_multiplier_shadow
    (ts, signal_id, agent_id, symbol, tf, hmm_regime,
     path, predicted_multiplier, confidence, features)
VALUES
    ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
ON CONFLICT (signal_id, agent_id) DO NOTHING
"""

_BATCH_SIZE = 50
_FLUSH_INTERVAL_S = 2.0

_REQUIRED_FIELDS = frozenset(
    {"signal_id", "agent_id", "symbol", "tf", "ts", "multiplier", "confidence", "path"}
)


class SwarmWriterAgent(BaseAgent):
    """Consume AgentResult messages, batch-insert to alpha_multiplier_shadow."""

    def __init__(self) -> None:
        super().__init__(name="SwarmWriterAgent")
        self._settings = Settings()
        self._consumer: KafkaConsumerClient | None = None
        self._producer: KafkaProducerClient | None = None
        self._pool: asyncpg.Pool | None = None
        self._batch: list[dict] = []

    async def _setup(self) -> None:
        env = self._settings.env_name
        self._consumer = KafkaConsumerClient(
            topic_swarm_results(env),
            bootstrap_servers=self._settings.kafka_bootstrap_servers,
            group_id="swarm_writer_consumer",
            auto_offset_reset="earliest",
        )
        await self._consumer.start()

        self._producer = KafkaProducerClient(
            bootstrap_servers=self._settings.kafka_bootstrap_servers,
        )
        await self._producer.start()

        self._pool = await asyncpg.create_pool(self._settings.database_url)
        self.logger.info("swarm_writer_agent.started")

    async def _teardown(self) -> None:
        if self._batch:
            await self._write_batch(self._batch)
            self._batch = []
        if self._consumer:
            await self._consumer.stop()
        if self._producer:
            await self._producer.stop()
        if self._pool:
            await self._pool.close()

    async def _run(self) -> None:
        assert self._consumer is not None
        flush_task = asyncio.create_task(self._flush_loop())
        try:
            async for _topic, _key, payload in self._consumer.messages():
                self._record_message_consumed()
                await self._handle_message(payload)
        finally:
            flush_task.cancel()
            try:
                await flush_task
            except asyncio.CancelledError:
                pass

    async def _flush_loop(self) -> None:
        while True:
            await asyncio.sleep(_FLUSH_INTERVAL_S)
            if self._batch:
                batch, self._batch = self._batch, []
                await self._write_batch(batch)

    async def _handle_message(self, payload: Any) -> None:
        if not isinstance(payload, dict) or not _REQUIRED_FIELDS.issubset(payload.keys()):
            self.logger.warning("swarm_writer.malformed_payload", payload=str(payload)[:200])
            assert self._producer is not None
            await self._producer.publish(
                topic_swarm_writer_dlq(self._settings.env_name),
                {"error": "missing required fields", "raw": str(payload)[:500]},
            )
            return
        self._batch.append(payload)
        if len(self._batch) >= _BATCH_SIZE:
            batch, self._batch = self._batch, []
            await self._write_batch(batch)

    async def _write_batch(self, batch: list[dict]) -> None:
        assert self._pool is not None
        assert self._producer is not None
        try:
            rows = [
                (
                    datetime.fromisoformat(p["ts"]) if isinstance(p["ts"], str) else p["ts"],
                    p["signal_id"],
                    p["agent_id"],
                    p["symbol"],
                    p["tf"],
                    p.get("hmm_regime"),
                    p["path"],
                    float(p["multiplier"]),
                    float(p["confidence"]),
                    json.dumps(p["features"]) if p.get("features") else None,
                )
                for p in batch
            ]
            async with self._pool.acquire() as conn:
                await conn.executemany(_INSERT_SQL, rows)
            self.logger.info("swarm_writer.batch_written", count=len(rows))
        except Exception as exc:
            self.logger.exception("swarm_writer.db_error", error=str(exc), batch_size=len(batch))
            await self._producer.publish(
                topic_swarm_writer_dlq(self._settings.env_name),
                {"error": str(exc), "batch_size": len(batch)},
            )


def main() -> None:
    agent = SwarmWriterAgent()
    asyncio.run(agent.start())


if __name__ == "__main__":
    main()
