#!/usr/bin/env python3
"""
Generic Redis Streams Consumer - Modular base class for all stream consumers

This provides a reusable foundation for consuming Redis Streams across different
client types (WebSocket, trading systems, analytics, external APIs).

Version: 1.0.0
Last Updated: 2025-08-04
Status: Production Ready ✅
"""

import asyncio
import json
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

import redis.asyncio as redis
import structlog

logger = structlog.get_logger(__name__)


class RedisStreamConsumer(ABC):
    """
    Generic Redis Streams consumer base class.

    Provides reusable Redis Streams consumption patterns that can be extended
    for different client types (WebSocket, trading systems, analytics, etc.).

    Features:
    - Consumer group management
    - Automatic message acknowledgment
    - Error handling and retry logic
    - Configurable stream patterns
    - Performance metrics
    """

    def __init__(
        self,
        redis_client: redis.Redis,
        streams: list[str],
        consumer_group: str,
        consumer_name: str,
        block_timeout: int = 1000,
        batch_size: int = 10,
    ):
        """
        Initialize Redis Streams consumer.

        Args:
            redis_client: Redis client instance
            streams: List of stream patterns to consume from
            consumer_group: Consumer group name for this consumer type
            consumer_name: Unique name for this consumer instance
            block_timeout: Block timeout in milliseconds
            batch_size: Number of messages to read per batch
        """
        self.redis_client = redis_client
        self.streams = streams
        self.consumer_group = consumer_group
        self.consumer_name = consumer_name
        self.block_timeout = block_timeout
        self.batch_size = batch_size

        # State management
        self.is_running = False
        self.consumption_task: asyncio.Task | None = None

        # Metrics
        self.messages_processed = 0
        self.messages_failed = 0
        self.last_message_time: datetime | None = None

        self.logger = logger.bind(consumer_group=consumer_group, consumer_name=consumer_name)

    async def start(self) -> None:
        """Start the stream consumption process."""
        if self.is_running:
            self.logger.warning("Consumer already running")
            return

        self.logger.info("Starting Redis Streams consumer")

        try:
            # Create consumer groups for all streams
            await self._create_consumer_groups()

            # Start consumption task
            self.is_running = True
            self.consumption_task = asyncio.create_task(self._consumption_loop())

            self.logger.info("✅ Redis Streams consumer started successfully")

        except Exception as e:
            self.logger.error("Failed to start consumer", error=str(e))
            self.is_running = False
            raise

    async def stop(self) -> None:
        """Stop the stream consumption process."""
        if not self.is_running:
            return

        self.logger.info("Stopping Redis Streams consumer")

        self.is_running = False

        if self.consumption_task:
            self.consumption_task.cancel()
            try:
                await self.consumption_task
            except asyncio.CancelledError:
                pass

        self.logger.info("✅ Redis Streams consumer stopped")

    async def _create_consumer_groups(self) -> None:
        """Create consumer groups for all streams."""
        for stream_pattern in self.streams:
            try:
                # For pattern streams, we need to get actual stream names
                if "*" in stream_pattern:
                    # Get all matching streams
                    matching_streams = await self._get_matching_streams(stream_pattern)
                    for stream_name in matching_streams:
                        await self._create_single_consumer_group(stream_name)
                else:
                    await self._create_single_consumer_group(stream_pattern)

            except Exception as e:
                self.logger.warning(
                    "Failed to create consumer group", stream=stream_pattern, error=str(e)
                )

    async def _create_single_consumer_group(self, stream_name: str) -> None:
        """Create consumer group for a single stream."""
        try:
            await self.redis_client.xgroup_create(
                name=stream_name,
                groupname=self.consumer_group,
                id="$",  # Start from new messages
                mkstream=True,
            )
            self.logger.debug("Created consumer group", stream=stream_name)

        except redis.ResponseError as e:
            if "BUSYGROUP" in str(e):
                # Consumer group already exists, that's fine
                self.logger.debug("Consumer group already exists", stream=stream_name)
            else:
                raise

    async def _get_matching_streams(self, pattern: str) -> list[str]:
        """Get all stream names matching a pattern."""
        # Convert Redis Streams pattern to Redis key pattern
        key_pattern = pattern.replace(":", "*")

        # Get all matching keys
        keys = await self.redis_client.keys(key_pattern)

        # Filter to only actual streams (check if they exist as streams)
        stream_names = []
        for key in keys:
            try:
                # Check if key is a stream by trying to get stream info
                await self.redis_client.xinfo_stream(
                    key.decode() if isinstance(key, bytes) else key
                )
                stream_names.append(key.decode() if isinstance(key, bytes) else key)
            except redis.ResponseError:
                # Not a stream, skip
                continue

        return stream_names

    async def _consumption_loop(self) -> None:
        """Main consumption loop."""
        self.logger.info("Starting consumption loop")

        while self.is_running:
            try:
                # Get current matching streams (handles dynamic stream creation)
                current_streams = await self._get_current_streams()

                if not current_streams:
                    # No streams available yet, wait and retry
                    await asyncio.sleep(1)
                    continue

                # Read from streams
                messages = await self.redis_client.xreadgroup(
                    groupname=self.consumer_group,
                    consumername=self.consumer_name,
                    streams=current_streams,
                    count=self.batch_size,
                    block=self.block_timeout,
                    noack=False,
                )

                # Process messages
                for stream_name, stream_messages in messages:
                    await self._process_stream_messages(
                        stream_name.decode() if isinstance(stream_name, bytes) else stream_name,
                        stream_messages,
                    )

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Error in consumption loop", error=str(e))
                await asyncio.sleep(1)  # Brief pause before retry

    async def _get_current_streams(self) -> dict[str, str]:
        """Get current streams dictionary for xreadgroup."""
        streams_dict = {}

        for stream_pattern in self.streams:
            if "*" in stream_pattern:
                matching_streams = await self._get_matching_streams(stream_pattern)
                for stream_name in matching_streams:
                    streams_dict[stream_name] = ">"  # Read new messages
            else:
                streams_dict[stream_pattern] = ">"

        return streams_dict

    async def _process_stream_messages(self, stream_name: str, messages: list[tuple]) -> None:
        """Process messages from a single stream."""
        for message_id, fields in messages:
            try:
                # Decode message
                decoded_fields = {
                    k.decode() if isinstance(k, bytes) else k: (
                        v.decode() if isinstance(v, bytes) else v
                    )
                    for k, v in fields.items()
                }

                # Convert to structured message
                message_data = {
                    "stream": stream_name,
                    "message_id": (
                        message_id.decode() if isinstance(message_id, bytes) else message_id
                    ),
                    "timestamp": datetime.now().isoformat(),
                    "data": decoded_fields,
                }

                # Process message via abstract method
                await self.process_message(message_data)

                # Acknowledge successful processing
                await self.redis_client.xack(stream_name, self.consumer_group, message_id)

                # Update metrics
                self.messages_processed += 1
                self.last_message_time = datetime.now()

            except Exception as e:
                self.logger.error(
                    "Failed to process message",
                    stream=stream_name,
                    message_id=message_id,
                    error=str(e),
                )
                self.messages_failed += 1

    @abstractmethod
    async def process_message(self, message: dict[str, Any]) -> None:
        """
        Process a single message from Redis Streams.

        Must be implemented by subclasses to define specific processing logic.

        Args:
            message: Structured message containing stream, message_id, timestamp, data
        """
        pass

    def get_metrics(self) -> dict[str, Any]:
        """Get consumer performance metrics."""
        return {
            "consumer_group": self.consumer_group,
            "consumer_name": self.consumer_name,
            "is_running": self.is_running,
            "messages_processed": self.messages_processed,
            "messages_failed": self.messages_failed,
            "last_message_time": (
                self.last_message_time.isoformat() if self.last_message_time else None
            ),
            "success_rate": (
                self.messages_processed / (self.messages_processed + self.messages_failed)
                if (self.messages_processed + self.messages_failed) > 0
                else 0
            ),
            "streams": self.streams,
        }


class StreamMessageProcessor:
    """Helper class for common message processing patterns."""

    @staticmethod
    def parse_json_field(data: dict[str, str], field_name: str) -> dict[str, Any] | None:
        """Parse JSON from a message field."""
        try:
            field_value = data.get(field_name)
            if field_value:
                return json.loads(field_value)
            return None
        except (json.JSONDecodeError, TypeError):
            return None

    @staticmethod
    def extract_symbol_timeframe(stream_name: str) -> tuple[str | None, str | None]:
        """Extract symbol and timeframe from stream name."""
        try:
            # Pattern: data_type:SYMBOL:TIMEFRAME
            parts = stream_name.split(":")
            if len(parts) >= 3:
                return parts[1], parts[2]  # symbol, timeframe
            return None, None
        except Exception:
            return None, None

    @staticmethod
    def format_for_websocket(message: dict[str, Any]) -> dict[str, Any]:
        """Format message for WebSocket transmission."""
        stream_name = message.get("stream", "")
        message_data = message.get("data", {})

        # Get symbol and timeframe from stream name OR from data fields
        symbol, timeframe = StreamMessageProcessor.extract_symbol_timeframe(stream_name)
        if not symbol:
            symbol = message_data.get("symbol")
        if not timeframe:
            timeframe = message_data.get("timeframe")

        # Get message type from stream name OR from data fields
        message_type = (
            stream_name.split(":")[0] if ":" in stream_name else message_data.get("type", "unknown")
        )

        return {
            "type": message_type,
            "symbol": symbol,
            "timeframe": timeframe,
            "timestamp": message_data.get("timestamp") or message.get("timestamp"),
            "data": message_data,
            "message_id": message.get("message_id"),
        }
