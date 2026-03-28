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

    def items(self) -> list[tuple[str, str]]:
        return list(self._headers.items())

    def to_aiokafka_headers(self) -> list[tuple[str, bytes]]:
        return [(k, v.encode()) for k, v in self._headers.items()]


class KafkaProducerClient:
    """Thin wrapper around AIOKafkaProducer matching current service startup/shutdown patterns."""

    def __init__(self, bootstrap_servers: str) -> None:
        self._bootstrap = bootstrap_servers
        self._producer: AIOKafkaProducer | None = None

    async def start(self) -> None:
        """Create and start the underlying AIOKafkaProducer."""
        logger.info("KafkaProducerClient starting", bootstrap_servers=self._bootstrap)
        self._producer = AIOKafkaProducer(bootstrap_servers=self._bootstrap)
        await self._producer.start()
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
