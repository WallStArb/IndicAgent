"""Consuming mixin for Redis Streams."""

import asyncio
import json
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

import redis.asyncio as redis
import structlog

from ..stream_models_core import ConsumerGroup, StreamMessage

logger = structlog.get_logger(__name__)


class ConsumingMixin:
    """Mixin providing message consuming capabilities."""

    async def create_consumer_group(
        self,
        group_name: str,
        stream_pattern: str,
        consumer_name: str,
        callback: Callable[[StreamMessage], None],
        max_retries: int = None,
        dead_letter_stream: str = None,
    ) -> bool:
        """
        Create a consumer group for processing streams.

        Args:
            group_name: Consumer group name (e.g., "indicators_group")
            stream_pattern: Stream pattern to consume (e.g., "market:*")
            consumer_name: This consumer's name (e.g., "worker1")
            callback: Function to process messages
        """
        try:
            consumer_group = ConsumerGroup(
                group_name=group_name,
                stream_pattern=stream_pattern,
                consumer_name=consumer_name,
                callback=callback,
                max_retries=max_retries or self.config.max_retries,
                dead_letter_stream=dead_letter_stream or f"{group_name}_dlq",
            )

            self.consumer_groups[group_name] = consumer_group

            # Get all streams matching pattern
            streams = await self._get_streams_by_pattern(stream_pattern)
            logger.info(
                f"Found {len(streams)} streams matching pattern '{stream_pattern}': {streams}"
            )

            if not streams:
                logger.warning(f"No streams found for pattern: {stream_pattern}")
                return False

            # Create consumer group for each stream
            for stream_name in streams:
                try:
                    await self.redis_client.xgroup_create(
                        stream_name, group_name, id="$", mkstream=True
                    )
                    logger.debug(f"Created consumer group {group_name} for {stream_name}")
                except redis.ResponseError as e:
                    if "BUSYGROUP" in str(e):
                        logger.debug(
                            f"Consumer group {group_name} already exists for {stream_name}"
                        )
                        await self.redis_client.xgroup_setid(stream_name, group_name, "$")
                    else:
                        raise

            # Start consumer task
            logger.info(f"Starting consumer task for group: {group_name}")
            consumer_task = asyncio.create_task(self._consume_messages(consumer_group))
            self.active_consumers[group_name] = consumer_task
            logger.info(f"Consumer task started successfully for group: {group_name}")

            logger.info(f"Created consumer group: {group_name} for pattern: {stream_pattern}")
            return True

        except Exception as e:
            logger.error(f"Failed to create consumer group {group_name}", error=str(e))
            return False

    async def _get_streams_by_pattern(self, pattern: str) -> list[str]:
        """High-performance stream discovery with caching."""
        try:
            current_time = time.time()

            # Check cache first (TTL: 10 seconds for high-frequency patterns)
            if pattern in self._stream_cache:
                cache_time = self._cache_ttl.get(pattern, 0)
                if current_time - cache_time < 10:  # 10-second cache
                    logger.debug(f"Cache hit for pattern: {pattern}")
                    return self._stream_cache[pattern]

            logger.debug(f"Cache miss, discovering streams for pattern: {pattern}")

            # For exact stream names (no wildcards), just check if it exists
            if "*" not in pattern and "?" not in pattern and "[" not in pattern:
                exists = await self.redis_client.exists(pattern)
                result = [pattern] if exists else []
            else:
                # Use SCAN instead of KEYS for better performance
                result = await self._scan_streams(pattern)

            # Cache the result
            self._stream_cache[pattern] = result
            self._cache_ttl[pattern] = current_time

            logger.debug(f"Found {len(result)} streams for pattern {pattern}")
            return result

        except Exception as e:
            logger.error(f"Failed to get streams for pattern {pattern}", error=str(e))
            return []

    async def _scan_streams(self, pattern: str) -> list[str]:
        """Use SCAN for efficient stream discovery."""
        try:
            streams = []
            cursor = 0

            while True:
                cursor, keys = await self.redis_client.scan(
                    cursor=cursor, match=pattern, count=1000  # Large count for efficiency
                )
                streams.extend(keys)

                if cursor == 0:
                    break

            return streams

        except Exception as e:
            logger.error(f"SCAN failed for pattern {pattern}", error=str(e))
            # Fallback to KEYS if SCAN fails
            return await self.redis_client.keys(pattern)

    async def _consume_messages(self, consumer_group: ConsumerGroup) -> None:
        """Enhanced message consumer with dead letter queues and comprehensive error handling."""
        group_name = consumer_group.group_name
        consumer_name = consumer_group.consumer_name
        callback = consumer_group.callback

        logger.info(f"Starting enhanced consumer: {consumer_name} in group: {group_name}")

        try:
            while self._is_running:
                try:
                    # Update heartbeat
                    consumer_group.last_heartbeat = datetime.now()

                    # Skip if circuit breaker is open
                    if self._is_circuit_breaker_open():
                        await asyncio.sleep(5)
                        continue

                    # Get streams for this pattern
                    streams = await self._get_streams_by_pattern(consumer_group.stream_pattern)

                    if not streams:
                        await asyncio.sleep(self.config.block_timeout / 1000)
                        continue

                    # Prepare stream dict for XREADGROUP
                    stream_dict = {stream: ">" for stream in streams}

                    # Read messages from all streams with retry
                    async def _read_operation(sd=stream_dict):
                        return await self.redis_client.xreadgroup(
                            group_name,
                            consumer_name,
                            sd,
                            count=self.config.batch_size,
                            block=self.config.block_timeout,
                        )

                    messages = await self._execute_with_retry(_read_operation)

                    if messages:
                        logger.debug(f"Received {len(messages)} stream messages")
                        self.metrics.messages_consumed += len(messages)

                    # Process each message with enhanced error handling
                    for stream_name, stream_messages in messages:
                        for message_id, fields in stream_messages:
                            await self._process_single_message(
                                stream_name, message_id, fields, consumer_group, callback
                            )

                except redis.RedisError as e:
                    logger.error(f"Redis error in consumer {consumer_name}", error=str(e))
                    await self._handle_circuit_breaker_failure(e)
                    await asyncio.sleep(self.config.retry_backoff_base)
                except Exception as e:
                    logger.error(f"Unexpected error in consumer {consumer_name}", error=str(e))
                    await asyncio.sleep(self.config.retry_backoff_base)

        except asyncio.CancelledError:
            logger.info(f"Consumer {consumer_name} cancelled")
        except Exception as e:
            logger.error(f"Consumer {consumer_name} failed", error=str(e))
        finally:
            logger.info(f"Consumer {consumer_name} stopped")

    async def _process_single_message(
        self,
        stream_name: str,
        message_id: str,
        fields: dict,
        consumer_group: ConsumerGroup,
        callback: Callable,
    ):
        """Process a single message with retry logic and dead letter queue support."""
        start_time = datetime.now()

        try:
            # Handle fields - Redis returns dict when decode_responses=True
            if isinstance(fields, dict):
                data = fields
            else:
                # Convert fields list to dict (alternating key-value pairs)
                data = {}
                if len(fields) % 2 != 0:
                    logger.warning(f"Odd number of fields in message {message_id}: {fields}")
                    return

                for i in range(0, len(fields), 2):
                    if i + 1 < len(fields):
                        key = fields[i]
                        value = fields[i + 1]
                        data[key] = value
                    else:
                        logger.warning(f"Missing value for key {fields[i]} in message {message_id}")
                        break

            # Decompress data if needed
            if "_compressed" in data and data["_compressed"] == "gzip":
                try:
                    import base64

                    compressed_data = base64.b64decode(data["data"])
                    data["data"] = self._decompress_data(compressed_data)
                    del data["_compressed"]
                except Exception as e:
                    logger.warning(f"Failed to decompress message {message_id}", error=str(e))

            # Create standard stream message
            stream_message = StreamMessage(
                stream_id=message_id, data=data, timestamp=datetime.now()
            )

            # Process message with callback
            await callback(stream_message)

            # Acknowledge message on success
            await self.redis_client.xack(stream_name, consumer_group.group_name, message_id)

            # Update processing time metrics
            processing_time = (datetime.now() - start_time).total_seconds()
            self.metrics.avg_processing_time = (self.metrics.avg_processing_time * 0.9) + (
                processing_time * 0.1
            )

        except Exception as e:
            # Get retry count from message or initialize
            retry_count = int(data.get("_retry_count", 0))

            if retry_count < consumer_group.max_retries:
                # Increment retry count and delay
                data["_retry_count"] = str(retry_count + 1)
                delay = consumer_group.retry_delay * (2**retry_count)

                logger.warning(
                    "Message processing failed, will retry",
                    message_id=message_id,
                    retry_count=retry_count + 1,
                    max_retries=consumer_group.max_retries,
                    delay=delay,
                    error=str(e),
                )

                # Sleep and don't acknowledge (Redis will retry)
                await asyncio.sleep(delay)

            else:
                # Max retries exceeded, send to dead letter queue
                logger.error(
                    "Message processing failed permanently, sending to DLQ",
                    message_id=message_id,
                    stream_name=stream_name,
                    error=str(e),
                )

                await self._send_to_dead_letter_queue(
                    consumer_group.dead_letter_stream, stream_name, message_id, data, str(e)
                )

                # Acknowledge to remove from main stream
                await self.redis_client.xack(stream_name, consumer_group.group_name, message_id)

            self.metrics.messages_failed += 1

    async def _send_to_dead_letter_queue(
        self, dlq_stream: str, original_stream: str, message_id: str, data: dict, error: str
    ):
        """Send failed message to dead letter queue for manual inspection."""
        try:
            dlq_data = {
                "original_stream": original_stream,
                "original_message_id": message_id,
                "error": error,
                "failed_at": datetime.now().isoformat(),
                "original_data": json.dumps(data),
            }

            await self.redis_client.xadd(dlq_stream, dlq_data, maxlen=10000)
            logger.info(f"Message sent to DLQ: {dlq_stream}")

        except Exception as e:
            logger.error("Failed to send message to DLQ", error=str(e))

    def _wrap_websocket_callback(self, websocket_callback: Callable) -> Callable:
        """
        Wrap a WebSocket callback to convert StreamMessage to WebSocket format.

        The WebSocket callback expects a dict with keys: stream_id, stream_name, timestamp, data
        But RedisStreamsManager passes StreamMessage objects.
        """

        async def wrapper(stream_message):
            try:
                # Convert StreamMessage to WebSocket format
                ws_message = {
                    "stream_id": (
                        stream_message.stream_id
                        if hasattr(stream_message, "stream_id")
                        else str(stream_message.timestamp)
                    ),
                    "stream_name": (
                        str(stream_message.stream_key)
                        if hasattr(stream_message, "stream_key")
                        else "unknown"
                    ),
                    "timestamp": (
                        stream_message.timestamp.isoformat()
                        if hasattr(stream_message, "timestamp")
                        else datetime.now().isoformat()
                    ),
                    "data": stream_message.data if hasattr(stream_message, "data") else {},
                }

                await websocket_callback(ws_message)

            except Exception as e:
                logger.error(f"Error in WebSocket callback wrapper: {e}")

        return wrapper

    async def subscribe_to_stream(self, stream_name: str, callback: Callable) -> bool:
        """
        Subscribe to a single stream for WebSocket live data.

        Args:
            stream_name: Exact stream name (e.g., "market:ES:1m")
            callback: Async callback function for messages

        Returns:
            bool: True if subscription successful
        """
        try:
            # Check if stream exists
            exists = await self.redis_client.exists(stream_name)
            if not exists:
                logger.warning(f"Stream does not exist: {stream_name}")
                return False

            # Generate unique consumer group name for this WebSocket subscription
            group_name = f"websocket_{stream_name}_{id(callback)}"
            consumer_name = f"ws_consumer_{id(callback)}"

            # Create consumer group using the existing method
            success = await self.create_consumer_group(
                group_name=group_name,
                stream_pattern=stream_name,  # Exact stream name, not pattern
                consumer_name=consumer_name,
                callback=self._wrap_websocket_callback(callback),
            )

            if success:
                logger.info(f"WebSocket subscribed to stream: {stream_name}")
                return True
            else:
                logger.error(
                    f"Failed to create consumer group for WebSocket subscription: {stream_name}"
                )
                return False

        except Exception as e:
            logger.error(f"Error subscribing to stream {stream_name}: {e}")
            return False

    async def unsubscribe_from_stream(self, stream_name: str):
        """
        Unsubscribe from a stream (WebSocket compatibility method).

        This finds and stops the consumer group associated with the stream.
        """
        try:
            # Find consumer groups that match this stream
            groups_to_stop = []
            for group_name, consumer_group in list(self.consumer_groups.items()):
                if consumer_group.stream_pattern == stream_name:
                    groups_to_stop.append(group_name)

            # Stop the consumer groups
            for group_name in groups_to_stop:
                if group_name in self.active_consumers:
                    task = self.active_consumers[group_name]
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                    del self.active_consumers[group_name]

                if group_name in self.consumer_groups:
                    del self.consumer_groups[group_name]

                logger.info(f"Unsubscribed from stream: {stream_name} (group: {group_name})")

        except Exception as e:
            logger.error(f"Error unsubscribing from stream {stream_name}: {e}")

    async def read_from_consumer_group(
        self,
        stream_name: str,
        group_name: str,
        consumer_name: str,
        count: int = 10,
        block: int = 1000,
    ) -> list[Any]:
        """
        Read messages from a consumer group (compatibility method for indicator streamer).

        Args:
            stream_name: Name of the stream to read from
            group_name: Consumer group name
            consumer_name: Consumer name within the group
            count: Maximum number of messages to read
            block: Block timeout in milliseconds

        Returns:
            List of messages from the stream
        """
        try:
            # Ensure consumer group exists
            try:
                await self.redis_client.xgroup_create(stream_name, group_name, "$", mkstream=True)
            except Exception:
                pass  # Group probably already exists

            # Read messages using XREADGROUP
            messages = await self.redis_client.xreadgroup(
                group_name, consumer_name, {stream_name: ">"}, count=count, block=block
            )

            # Convert to expected format
            result = []
            for _stream, stream_messages in messages:
                for message_id, fields in stream_messages:
                    # Convert message to expected format
                    message = type("Message", (), {"id": message_id, "data": fields})()
                    result.append(message)

            return result

        except Exception as e:
            logger.error(
                f"Error reading from consumer group {group_name} on {stream_name}", error=str(e)
            )
            return []

    async def recover_idle_messages(
        self,
        stream_name: str,
        group_name: str,
        consumer_name: str,
        min_idle_ms: int = 15000,
        count: int = 500,
    ) -> int:
        """Recover idle (stuck) messages using XAUTOCLAIM when available.

        Returns the number of reclaimed messages.
        """
        reclaimed = 0
        try:
            start_id = "0-0"
            while True:
                try:
                    res = await self.redis_client.xautoclaim(
                        stream_name, group_name, consumer_name, min_idle_ms, start_id, count=count
                    )
                except Exception:
                    break
                if not res or len(res[1]) == 0:
                    break
                entries = res[1]
                for _msg_id, _fields in entries:
                    reclaimed += 1
                start_id = res[0] or start_id
            return reclaimed
        except Exception as e:
            logger.warning(
                "XAUTOCLAIM recovery failed", stream=stream_name, group=group_name, error=str(e)
            )
            return reclaimed

    async def acknowledge_message(self, stream_name: str, group_name: str, message_id: str):
        """
        Acknowledge message processing (compatibility method for indicator streamer).

        Args:
            stream_name: Name of the stream
            group_name: Consumer group name
            message_id: ID of the message to acknowledge
        """
        try:
            await self.redis_client.xack(stream_name, group_name, message_id)
        except Exception as e:
            logger.error(f"Error acknowledging message {message_id}", error=str(e))

    async def read_from_stream(self, stream_name: str, count: int = 1) -> list:
        """
        Compatibility method for API routes - reads latest messages from stream.

        Args:
            stream_name: Name of the Redis stream
            count: Number of messages to read

        Returns:
            List of StreamMessage objects
        """
        try:
            # Use xrevrange to get latest messages (newest first)
            raw_messages = await self.redis_client.xrevrange(stream_name, count=count)

            result = []
            for message_data in raw_messages:
                if len(message_data) >= 2:
                    message_id = message_data[0]
                    fields = message_data[1]

                    # Convert fields list to dict format
                    data = {}
                    if isinstance(fields, list):
                        for i in range(0, len(fields), 2):
                            if i + 1 < len(fields):
                                key = fields[i]
                                value = fields[i + 1]
                                data[key] = value
                    elif isinstance(fields, dict):
                        data = fields

                    # Create StreamMessage object
                    stream_msg = StreamMessage(
                        stream_id=message_id,
                        data=data,
                        timestamp=datetime.now(),
                        retry_count=0,
                    )
                    result.append(stream_msg)

            return result

        except Exception as e:
            logger.error(f"Error reading from stream {stream_name}", error=str(e))
            return []

    def _decompress_data(self, data):
        """Decompress data. No-op stub - returns data unchanged."""
        return data
