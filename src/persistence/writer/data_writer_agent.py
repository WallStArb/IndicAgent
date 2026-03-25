"""DataWriterAgent — generic batch writer for persistence.

Consumes journal events from Kafka and performs bulk inserts into storage.
Decouples hot-path generation from database I/O using a Repository pattern.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import structlog

from src.core.kafka_utils import KafkaConsumerClient
from src.persistence.logic.stream_merger import StreamMerger

logger = structlog.get_logger(__name__)

class DataWriterAgent:
    """Generic agent for batch-persistence of intelligence journals."""

    def __init__(
        self,
        repository: Any,
        topic_builder: Callable[[str], str],
        env_name: str,
        kafka_bootstrap: str,
        group_id: str,
    ):
        self._repo = repository
        self._topic = topic_builder(env_name)
        self._kafka_bootstrap = kafka_bootstrap
        self._group_id = group_id
        self._merger = StreamMerger()
        self._consumer: KafkaConsumerClient | None = None
        self._msg_count: int = 0

    async def start(self) -> None:
        """Start the consumer loop."""
        self._consumer = KafkaConsumerClient(
            self._topic,
            bootstrap_servers=self._kafka_bootstrap,
            group_id=self._group_id,
            auto_offset_reset="earliest",
        )
        await self._consumer.start()
        logger.info("DataWriterAgent started", topic=self._topic)
        await self._run_consumer_loop()

    async def _run_consumer_loop(self) -> None:
        """Consume, merge, and persist batch records."""
        if not self._consumer:
            return

        async for topic, key, payload in self._consumer.messages():
            try:
                # 1. Ingest into convergence gate
                # topic format: dev.intelligence.i{N} -> we extract 'i{N}'
                tier = topic.split(".")[-1]
                key_str = key.decode() if isinstance(key, bytes) else str(key)
                merged_record = self._merger.ingest(tier, key_str, payload)

                # 2. Persist if complete
                if merged_record:
                    await self._repo.insertBatch(merged_record)
                    await self._consumer.commit()

                # 3. Check TTL expirations every 100 messages to avoid per-message overhead
                self._msg_count += 1
                if self._msg_count % 100 == 0:
                    expired = self._merger.check_expired()
                    for record in expired:
                        try:
                            await self._repo.insertBatch(record)
                        except Exception as e:
                            logger.error("Failed to persist expired record", error=str(e))

            except Exception as e:
                logger.error("Persistence error", error=str(e), key=key)

    async def stop(self) -> None:
        if self._consumer:
            await self._consumer.stop()
