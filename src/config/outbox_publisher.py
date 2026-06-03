"""OutboxPublisher — transactional outbox publisher for OPS config changes.

Polls config_outbox for pending rows and publishes them to topic_config_updates (Kafka).
Updates outbox status with exponential backoff retry semantics.

Design notes:
- Agent overrides _config_layer = "INFRA" so it does NOT subscribe to config updates,
  avoiding a circular dependency on the topic it publishes to.
- Uses FOR UPDATE SKIP LOCKED for horizontal scaling (multiple dispatcher instances safe).
- Adaptive polling: 100ms when backlog exists, exponential backoff up to 2000ms when idle.
- Published event payload matches topic_config_updates docstring schema (schema_version=1).

Phase 109 Plan 02.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import UTC, datetime

import asyncpg
import structlog

from src.config.settings import get_settings
from src.core.agent.base import BaseDaemon
from src.core.database_manager import create_pool
from src.core.kafka_utils import KafkaProducerClient
from src.core.service_utils import format_iso_ts
from src.core.stream_keys import topic_config_updates
from src.observability.metrics import (
    CONFIG_OUTBOX_PENDING,
    CONFIG_OUTBOX_PUBLISH_LATENCY_SECONDS,
)

logger = structlog.get_logger(__name__)

# Adaptive polling bounds (milliseconds)
_POLL_MIN_MS: int = 100
_POLL_MAX_MS: int = 2000
_CLAIM_BATCH_SIZE: int = 100


class OutboxPublisher(BaseDaemon):
    """Polls config_outbox and publishes pending rows to topic_config_updates.

    Adaptive polling: resets to 100ms on non-empty batch; doubles toward 2000ms on empty.
    Transactional outbox: claim (pending->publishing), publish, confirm (->published) or
    requeue (->pending + retry_count++ + next_attempt_at with exponential backoff).
    """

    # Do NOT subscribe to config updates — this agent publishes them (avoids circular dep).
    _config_layer: str = "INFRA"

    def __init__(self) -> None:
        settings = get_settings()
        super().__init__(name="outbox_dispatcher_agent", settings=settings)
        self._producer: KafkaProducerClient | None = None
        self._db_pool: asyncpg.Pool | None = None

    @property
    def topics_consumed(self) -> list[str]:
        """No Kafka consumption — polls DB directly."""
        return []

    async def _setup(self) -> None:
        """Initialize DB pool and Kafka producer."""
        self._db_pool = await create_pool(
            self.settings.database_url,
            pool_name="outbox_dispatcher",
        )
        self._producer = KafkaProducerClient(
            bootstrap_servers=self.settings.kafka_bootstrap_servers,
        )
        await self._producer.start()
        self.logger.info("outbox_dispatcher.setup_complete")

    async def _teardown(self) -> None:
        """Stop Kafka producer and close DB pool."""
        if self._producer:
            await self._producer.stop()
            self._producer = None
        if self._db_pool:
            await self._db_pool.close()
            self._db_pool = None
        self.logger.info("outbox_dispatcher.teardown_complete")

    async def _run(self) -> None:
        """Adaptive poll loop: claim pending rows, publish to Kafka, update status."""
        assert self._db_pool is not None, "DB pool not initialized"
        assert self._producer is not None, "Kafka producer not initialized"

        topic = topic_config_updates(self.env_name)
        current_backoff_ms = _POLL_MIN_MS

        while not self._stop_event.is_set():
            rows_processed = await self._poll_and_publish(topic)

            if rows_processed > 0:
                # Reset backoff when work was found
                current_backoff_ms = _POLL_MIN_MS
            else:
                # Exponential backoff when idle
                current_backoff_ms = min(current_backoff_ms * 2, _POLL_MAX_MS)

            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=current_backoff_ms / 1000.0,
                )
            except TimeoutError:
                pass  # normal — just means stop_event not set during sleep

    async def _poll_and_publish(self, topic: str) -> int:
        """Claim, publish, and confirm one batch of outbox rows. Returns count processed."""
        assert self._db_pool is not None

        async with self._db_pool.acquire() as conn:
            async with conn.transaction():
                # Claim pending rows with SKIP LOCKED for safe horizontal scaling
                rows = await conn.fetch(
                    """
                    UPDATE config_outbox
                    SET status = 'publishing'
                    WHERE id IN (
                        SELECT id FROM config_outbox
                        WHERE status = 'pending'
                          AND (next_attempt_at IS NULL OR next_attempt_at <= NOW())
                        ORDER BY id
                        FOR UPDATE SKIP LOCKED
                        LIMIT $1
                    )
                    RETURNING id, config_key, config_value, version, retry_count
                    """,
                    _CLAIM_BATCH_SIZE,
                )

                if not rows:
                    return 0

                # Fetch schema metadata for value_type and is_secret
                keys = [r["config_key"] for r in rows]
                schema_rows = await conn.fetch(
                    "SELECT config_key, value_type, is_secret "
                    "FROM config_schema "
                    "WHERE config_key = ANY($1::text[])",
                    keys,
                )
                schema_map = {
                    r["config_key"]: {
                        "value_type": r["value_type"],
                        "is_secret": r["is_secret"],
                    }
                    for r in schema_rows
                }

                for row in rows:
                    await self._publish_row(conn, topic, row, schema_map)

        return len(rows)

    async def _publish_row(
        self,
        conn: asyncpg.Connection,
        topic: str,
        row: asyncpg.Record,
        schema_map: dict[str, dict],
    ) -> None:
        """Publish a single outbox row to Kafka; update status on success or failure."""
        row_id: int = row["id"]
        config_key: str = row["config_key"]
        config_value: str = row["config_value"]
        version: int = row["version"]
        retry_count: int = row["retry_count"]

        schema_info = schema_map.get(config_key, {})
        value_type: str = schema_info.get("value_type", "string")
        is_secret: bool = schema_info.get("is_secret", False)

        payload = {
            "schema_version": 1,
            "config_key": config_key,
            "config_value": config_value,
            "value_type": value_type,
            "version": version,
            "changed_at": format_iso_ts(datetime.now(UTC)),
            "changed_by": "system",
            "operation": "set",
            "reason": None,
            "redacted": is_secret,
            "correlation_id": str(uuid.uuid4()),
        }

        t0 = time.monotonic()
        try:
            await self._producer.publish(topic, msg=payload, key=config_key)
            elapsed = time.monotonic() - t0

            # Mark as published
            await conn.execute(
                "UPDATE config_outbox SET status = 'published' WHERE id = $1",
                row_id,
            )
            CONFIG_OUTBOX_PENDING.add(-1, {})
            CONFIG_OUTBOX_PUBLISH_LATENCY_SECONDS.record(elapsed, {})
            self.logger.info(
                "outbox_dispatcher.published",
                config_key=config_key,
                version=version,
                latency_ms=round(elapsed * 1000, 2),
            )
        except Exception as error:
            # Exponential backoff: delay = 2^min(retry_count, 6) seconds (max 64s)
            backoff_s = 2 ** min(retry_count, 6)
            await conn.execute(
                """
                UPDATE config_outbox
                SET status = 'pending',
                    retry_count = retry_count + 1,
                    next_attempt_at = NOW() + ($1 * INTERVAL '1 second')
                WHERE id = $2
                """,
                backoff_s,
                row_id,
            )
            self.logger.error(
                "outbox_dispatcher.publish_failed",
                config_key=config_key,
                version=version,
                retry_count=retry_count,
                next_attempt_s=backoff_s,
                error=str(error),
            )
