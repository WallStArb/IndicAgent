#!/usr/bin/env python3
"""DLQDrain — continuous consumer of all DLQ topics, writes to dlq_events.

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
from collections import defaultdict
from datetime import UTC, datetime, timedelta

import _path_bootstrap  # noqa: F401 — project root on sys.path
import asyncpg
import structlog

from src.core.agent.base import BaseDaemon
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
from src.observability.metrics import DLQ_QUARANTINE_TOTAL

logger = structlog.get_logger(__name__)

CONSUMER_GROUP: str = "dlq_drain_consumer"

# Legacy pre-107.5 DLQ messages used a flat format without the DLQPayload envelope.
# Identify them by the absence of the required envelope fields.
_LEGACY_FIELDS = frozenset(
    {"agent", "source_topic", "error_type", "error_message", "payload", "timestamp"}
)


def _is_legacy_format(raw: dict) -> bool:
    return not _LEGACY_FIELDS.intersection(raw.keys())


_INSERT_SQL: str = """
INSERT INTO dlq_events
    (routed_at, agent, source_topic, dlq_topic, error_type, error_message, payload, retry_count, quarantined)
VALUES
    ($1, $2, $3, $4, $5, $6, $7, $8, $9)
"""


class DLQDrain(BaseDaemon):
    """Continuous Kafka consumer draining all 15 DLQ topics into dlq_events.

    Follows BaseDaemon lifecycle contract (setup/_run/stop). No timer loop -
    processes messages as they arrive. Consumer group: dlq_drain_consumer.
    """

    def __init__(self) -> None:
        super().__init__(max_idle_seconds=600)

        self._pool: asyncpg.Pool | None = None
        self._consumer: KafkaConsumerClient | None = None
        # In-memory rolling 24h occurrence counter keyed by (agent, source_topic, error_type).
        # Value: (count, window_start). Window resets when window_start age exceeds 24h.
        self._quarantine_counts: dict[tuple, tuple[int, datetime]] = defaultdict(
            lambda: (0, datetime.now(UTC))
        )
        # Quarantine fires when count > _DLQ_MAX_RETRIES (i.e. the 4th occurrence within the 24h window).
        self._DLQ_MAX_RETRIES: int = 3

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

    async def _seed_quarantine_counts_from_db(self) -> None:
        """Populate _quarantine_counts from the last 24h of dlq_events rows.

        Called once at startup after self._pool is initialized. Ensures a restart
        cannot reset a poison-pill counter back to zero.
        """
        assert self._pool is not None
        try:
            async with self._pool.acquire() as conn:
                rows = await conn.fetch("""
                    SELECT agent, source_topic, error_type,
                           COUNT(*) AS cnt,
                           MIN(routed_at) AS window_start
                    FROM dlq_events
                    WHERE routed_at > now() - interval '24 hours'
                    GROUP BY agent, source_topic, error_type
                    """)
            for row in rows:
                window_start = row["window_start"]
                # asyncpg returns timestamptz as tz-aware datetime; guard against naive just in case
                if window_start.tzinfo is None:
                    window_start = window_start.replace(tzinfo=UTC)
                self._quarantine_counts[(row["agent"], row["source_topic"], row["error_type"])] = (
                    int(row["cnt"]),
                    window_start,
                )
            self.logger.info(
                "dlq_drain.quarantine_seed",
                seeded_keys=len(self._quarantine_counts),
            )
        except Exception as e:
            # Missing seed is degraded mode, not fatal; counters rebuild from live traffic.
            self.logger.warning("dlq_drain.quarantine_seed_failed", error=str(e))

    async def _setup(self) -> None:
        """Create DB pool, seed quarantine counts, subscribe consumer to all 15 DLQ topics."""
        await super()._setup()
        self._pool = await create_db_pool(self.settings.database_url)
        await self._seed_quarantine_counts_from_db()
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
        """Main consume loop - process DLQ messages until stop event."""
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
            if _is_legacy_format(raw):
                # Pre-107.5 messages lack the DLQPayload envelope. Already failed,
                # no retry value - discard with a single structured audit log.
                self.logger.info(
                    "dlq_legacy_discarded",
                    dlq_topic=dlq_topic,
                    symbol=raw.get("symbol"),
                    error=raw.get("error"),
                )
            else:
                self.logger.warning(
                    "dlq_drain_parse_failed",
                    dlq_topic=dlq_topic,
                    error=str(exc),
                    raw_preview=str(raw)[:200],
                )
            return

        routed_at = msg.timestamp if msg.timestamp.tzinfo else msg.timestamp.replace(tzinfo=UTC)

        # Rolling 24h quarantine count keyed by (agent, source_topic, error_type).
        key = (msg.agent, msg.source_topic, msg.error_type)
        count, window_start = self._quarantine_counts[key]
        now = datetime.now(UTC)
        if now - window_start > timedelta(hours=24):
            count, window_start = 0, now
        count += 1
        self._quarantine_counts[key] = (count, window_start)
        quarantined = count > self._DLQ_MAX_RETRIES
        if quarantined:
            DLQ_QUARANTINE_TOTAL.add(1, {"agent": msg.agent, "error_type": msg.error_type})

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
                    quarantined,
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


# -- Entrypoint ----------------------------------------------------------------


async def main() -> None:
    setup_service_logging("logs/dlq_drain.log")
    agent = DLQDrain()
    await agent.start()


if __name__ == "__main__":
    asyncio.run(main())
