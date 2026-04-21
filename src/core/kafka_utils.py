"""
Kafka producer/consumer helpers for IndicAgent services.

Version: 1.0.0
Last Updated: 2026-03-14
Status: Current ✅

Provides KafkaProducerClient and KafkaConsumerClient — thin async wrappers
around AIOKafkaProducer and AIOKafkaConsumer that match the service lifecycle
patterns established by the existing Redis client usage.

Used during Phase 30 dual-run period (Plans 1-4) alongside stream_utils.py.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator

import structlog
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from opentelemetry import context as otel_context
from opentelemetry.propagate import extract, inject

logger = structlog.get_logger(__name__)


class _KafkaHeadersCarrier:
    """W3C traceparent carrier adapter for AIOKafka headers.

    OTel propagators require a carrier with get/set/keys methods.
    AIOKafka uses list[tuple[str, bytes]] for headers. This adapter
    bridges the two formats.
    """

    def __init__(self) -> None:
        self._headers: dict[str, str] = {}

    def get(self, key: str, default: list[str] | None = None) -> list[str] | None:
        val = self._headers.get(key)
        return [val] if val is not None else default

    def set(self, key: str, value: str) -> None:
        self._headers[key] = value

    def keys(self) -> list[str]:
        return list(self._headers.keys())

    def to_aiokafka_headers(self) -> list[tuple[str, bytes]]:
        return [(k, v.encode()) for k, v in self._headers.items()]


class KafkaProducerClient:
    """Thin wrapper around AIOKafkaProducer matching current service startup/shutdown patterns."""

    def __init__(self, bootstrap_servers: str) -> None:
        self._bootstrap = bootstrap_servers
        self._producer: AIOKafkaProducer | None = None

    async def start(self) -> None:
        """Create and start the underlying AIOKafkaProducer.

        Durability configuration:
          acks='all'                 wait for replica acks, not just leader
          enable_idempotence=True    exactly-once-per-partition producer semantics
                                     (aiokafka internally caps in-flight ≤5)
          compression_type='lz4'     ~60% bytes saved on JSON, negligible CPU
        """
        logger.info("KafkaProducerClient starting", bootstrap_servers=self._bootstrap)
        producer = AIOKafkaProducer(
            bootstrap_servers=self._bootstrap,
            acks="all",
            enable_idempotence=True,
            compression_type="lz4",
        )
        try:
            await producer.start()
        except Exception:
            await producer.stop()
            raise
        self._producer = producer
        logger.info("KafkaProducerClient started successfully")

    async def stop(self) -> None:
        """Flush pending sends and close the producer connection."""
        if self._producer:
            await self._producer.stop()

    async def publish(self, topic: str, msg: dict, key: str | None = None) -> None:
        """Publish a dict message to a Kafka topic with an optional routing key.

        Args:
            topic: Kafka topic name (e.g. "dev.indicators").
            msg: Message dict — serialized to JSON bytes internally.
            key: Optional partition routing key (e.g. "ES:1m") — encoded to bytes.
        """
        if self._producer is None:
            logger.error("KafkaProducerClient.publish called but producer is None!", topic=topic)
            raise RuntimeError("Kafka producer not started")

        value = json.dumps(msg).encode()
        key_bytes = key.encode() if key else None

        # Inject current trace context into Kafka headers (no-op if no TracerProvider)
        carrier = _KafkaHeadersCarrier()
        inject(carrier)
        headers = carrier.to_aiokafka_headers()

        try:
            await self._producer.send_and_wait(topic, value=value, key=key_bytes, headers=headers)  # type: ignore[union-attr]
        except Exception as e:
            logger.error("Kafka publish failed", topic=topic, key=key, error=str(e))
            raise


class KafkaConsumerClient:
    """Thin wrapper around AIOKafkaConsumer matching current service consumption patterns."""

    def __init__(
        self,
        *topics: str,
        bootstrap_servers: str,
        group_id: str,
        auto_offset_reset: str = "latest",
        enable_auto_commit: bool = True,
    ) -> None:
        self._consumer = AIOKafkaConsumer(
            *topics,
            bootstrap_servers=bootstrap_servers,
            group_id=group_id,
            auto_offset_reset=auto_offset_reset,
            enable_auto_commit=enable_auto_commit,
        )

    async def start(self) -> None:
        """Subscribe to topics and start the consumer."""
        await self._consumer.start()

    async def stop(self) -> None:
        """Commit pending offsets, leave consumer group, and close the connection."""
        await self._consumer.stop()

    async def commit(self) -> None:
        """Manually commit offsets for all assigned partitions.

        Only relevant when enable_auto_commit=False.
        """
        await self._consumer.commit()

    async def seek_to_beginning(self) -> None:
        """Seek all assigned partitions to the earliest offset.

        Call after start() to replay all topic history regardless of any previously
        committed offsets. For a subscribed consumer the seek is applied once
        partitions are assigned by the group coordinator.
        """
        await self._consumer.seek_to_beginning()

    async def seek_to_end(self) -> None:
        """Seek all assigned partitions to the latest offset.

        Call after start() to skip all historical messages and consume only new
        messages, regardless of any previously committed offsets.
        """
        await self._consumer.seek_to_end()

    async def skip_lag_if_needed(self, max_lag: int) -> int:
        """Seek to end if total committed lag exceeds max_lag.

        Call after start(). Triggers a short poll to force partition assignment,
        then checks end_offset - position for each partition. If total lag
        exceeds max_lag, seeks all partitions to end and logs the skip.

        Returns the lag found (0 if already caught up or assignment failed).
        Why: live pipeline services seed state from DB at startup; old Kafka
        messages are redundant and cause hours-long reprocessing after restarts.
        """
        partitions = self._consumer.assignment()
        if not partitions:
            await self._consumer.getmany(timeout_ms=2000, max_records=1)
            partitions = self._consumer.assignment()
        if not partitions:
            return 0

        total_lag = await self._calculate_lag(partitions)

        if total_lag > max_lag:
            await self._consumer.seek_to_end()
            # Commit after seek so manual-commit consumers (enable_auto_commit=False)
            # persist the new position — otherwise Redpanda still shows full lag on
            # next restart and the consumer reprocesses from the old committed offset.
            await self._consumer.commit()

            # Verify the seek actually persisted by re-checking lag
            post_seek_lag = await self._calculate_lag(partitions)

            if post_seek_lag > max_lag:
                logger.critical(
                    "kafka_consumer.lag_skip_failed",
                    pre_seek_lag=total_lag,
                    post_seek_lag=post_seek_lag,
                    max_lag=max_lag,
                    error="seek_to_end+commit did not persist — consumer will reprocess from old offset",
                )
                raise RuntimeError(
                    f"skip_lag_if_needed failed: lag was {total_lag}, still {post_seek_lag} after seek_to_end+commit. "
                    "Check Redpanda connectivity and consumer group state."
                )

            logger.info(
                "kafka_consumer.lag_skip",
                lag=total_lag,
                max_lag=max_lag,
                action="seeked_to_end_verified",
                post_seek_lag=post_seek_lag,
            )

        return total_lag

    async def _calculate_lag(self, partitions: set) -> int:
        """Calculate total lag across partitions.

        Returns sum of (end_offset - current_position) for all assigned partitions.
        Returns 0 if partition assignment fails or position queries fail.
        """
        end_offsets = await self._consumer.end_offsets(list(partitions))
        total_lag = 0
        for tp, end_offset in end_offsets.items():
            try:
                current = await self._consumer.position(tp)
                total_lag += max(0, end_offset - current)
            except Exception as e:
                logger.warning(
                    "kafka_consumer.position_failed",
                    topic_partition=tp,
                    error=str(e),
                )
        return total_lag

    async def getmany(
        self, *, timeout_ms: int = 0, max_records: int = 100
    ) -> dict:
        """Non-blocking batch fetch — thin delegation to AIOKafkaConsumer.getmany().

        Returns {TopicPartition: [ConsumerRecord, ...]} immediately with any
        buffered messages (when timeout_ms=0). Used by agents that need to drain
        messages without blocking (e.g. BarAuditorAgent contract cache invalidation).
        """
        return await self._consumer.getmany(
            timeout_ms=timeout_ms, max_records=max_records
        )

    async def messages(self) -> AsyncGenerator[tuple[str, str | None, dict]]:
        """Yield (topic, key, payload_dict) tuples from subscribed topics.

        Yields:
            A 3-tuple of:
              - topic (str): The Kafka topic the message arrived on.
              - key (str | None): Decoded message key (e.g. "ES:1m"), or None if no key.
              - payload (dict): Decoded JSON payload dict.
        """
        async for msg in self._consumer:
            topic = msg.topic
            key = msg.key.decode() if msg.key else None
            try:
                payload = json.loads(msg.value)
            except Exception as e:
                logger.error(
                    "Kafka message decode failed",
                    topic=topic,
                    key=key,
                    value_type=type(msg.value).__name__,
                    error=str(e),
                    value_preview=msg.value[:200] if msg.value else None,
                )
                continue

            # Extract trace context from Kafka headers (no-op if no traceparent)
            carrier = _KafkaHeadersCarrier()
            for header_key, header_val in msg.headers or []:
                carrier.set(header_key, header_val.decode())
            ctx = extract(carrier)
            token = otel_context.attach(ctx)
            try:
                yield topic, key, payload
            finally:
                otel_context.detach(token)
