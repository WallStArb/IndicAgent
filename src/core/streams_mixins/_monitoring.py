"""Monitoring mixin for Redis Streams."""

import asyncio
from datetime import datetime
from typing import Any

import structlog

from ..stream_models_core import StreamMessage

logger = structlog.get_logger(__name__)


class MonitoringMixin:
    """Mixin providing stream monitoring, info, and health capabilities."""

    async def get_stream_info(self, stream_name: str) -> dict[str, Any]:
        """Get information about a stream."""
        try:
            info = await self.redis_client.xinfo_stream(stream_name)
            return {
                "length": info.get(b"length", 0),
                "first_entry_id": info.get(b"first-entry", [None])[0],
                "last_entry_id": info.get(b"last-entry", [None])[0],
                "groups": info.get(b"groups", 0),
            }
        except Exception as e:
            logger.error(f"Failed to get stream info for {stream_name}", error=str(e))
            return {}

    async def get_consumer_group_info(self, stream_name: str, group_name: str) -> dict[str, Any]:
        """Get information about a consumer group."""
        try:
            groups = await self.redis_client.xinfo_groups(stream_name)
            for group in groups:
                if group.get(b"name", b"").decode() == group_name:
                    return {
                        "consumers": group.get(b"consumers", 0),
                        "pending": group.get(b"pending", 0),
                        "last_delivered_id": group.get(b"last-delivered-id", b"").decode(),
                    }
            return {}
        except Exception as e:
            logger.error(
                f"Failed to get group info for {group_name} on {stream_name}", error=str(e)
            )
            return {}

    async def get_pending_messages(self, stream_name: str, group_name: str) -> list[dict]:
        """Get pending (unacknowledged) messages for a consumer group."""
        try:
            pending = await self.redis_client.xpending(stream_name, group_name)
            if pending:
                return [
                    {
                        "count": pending[0],
                        "first_id": pending[1].decode() if pending[1] else None,
                        "last_id": pending[2].decode() if pending[2] else None,
                    }
                ]
            return []
        except Exception as e:
            logger.error(
                f"Failed to get pending messages for {group_name} on {stream_name}", error=str(e)
            )
            return []

    async def get_performance_metrics(self) -> dict[str, Any]:
        """Get comprehensive performance metrics."""
        return {
            "messages_published": self.metrics.messages_published,
            "messages_consumed": self.metrics.messages_consumed,
            "messages_failed": self.metrics.messages_failed,
            "bytes_transferred": self.metrics.bytes_transferred,
            "avg_processing_time": self.metrics.avg_processing_time,
            "peak_memory_usage": self.metrics.peak_memory_usage,
            "circuit_breaker_state": self.circuit_breaker.state,
            "circuit_breaker_failures": self.circuit_breaker.failure_count,
            "active_consumers": len(self.active_consumers),
            "consumer_groups": len(self.consumer_groups),
            "last_activity": self.metrics.last_activity.isoformat(),
            "cache_size": len(self._message_cache),
            "uptime": (datetime.now() - self.metrics.last_activity).total_seconds(),
        }

    async def get_redis_info(self) -> dict[str, Any]:
        """
        Get comprehensive Redis 7.0+ info with latest metrics.

        Returns:
            Dict with Redis info, memory usage, latency, and performance metrics
        """
        try:
            # Basic Redis info
            info = await self.redis_client.info()

            # Redis 7.0+ specific metrics
            try:
                memory_info = await self.redis_client.memory_usage()
            except Exception:
                memory_info = "Not available"

            try:
                latency_info = await self.redis_client.latency_histogram()
            except Exception:
                latency_info = "Not available"

            # Client information
            client_list = await self.redis_client.client_list()

            # Slowlog for performance monitoring
            slowlog = await self.redis_client.slowlog_get(10)

            performance_metrics = await self.get_performance_metrics()

            return {
                "info": info,
                "memory": memory_info,
                "latency": latency_info,
                "client_list": client_list,
                "slowlog": slowlog,
                "streams_count": len(await self._get_all_streams()),
                "performance_metrics": performance_metrics,
            }
        except Exception as e:
            logger.error(f"Failed to get Redis info: {e}")
            return {}

    async def get_latest_message(self, stream_name: str) -> StreamMessage | None:
        """
        Get the latest message from a stream.

        Args:
            stream_name: Name of the stream

        Returns:
            Latest StreamMessage if available, None otherwise
        """
        try:
            # Use XREVRANGE to get the most recent message
            messages = await self.redis_client.xrevrange(stream_name, count=1)

            if not messages:
                return None

            message_id, fields = messages[0]

            # Convert fields to dict
            data = {}
            for i in range(0, len(fields), 2):
                key = fields[i].decode() if isinstance(fields[i], bytes) else fields[i]
                value = (
                    fields[i + 1].decode() if isinstance(fields[i + 1], bytes) else fields[i + 1]
                )
                data[key] = value

            return StreamMessage(
                stream_id=message_id.decode() if isinstance(message_id, bytes) else message_id,
                data=data,
                timestamp=datetime.now(),
            )

        except Exception as e:
            logger.error(f"Failed to get latest message from {stream_name}", error=str(e))
            return None

    async def get_stream_history(
        self,
        stream_name: str,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 100,
    ) -> list[StreamMessage]:
        """
        Get historical messages from a stream with time filtering.

        Args:
            stream_name: Name of the stream
            since: Start time for messages (defaults to 24 hours ago)
            until: End time for messages (defaults to now)
            limit: Maximum number of messages to return

        Returns:
            List of StreamMessage objects
        """
        try:
            # Convert datetime to Redis stream IDs if provided
            start_id = "-"  # Beginning of stream
            end_id = "+"  # End of stream

            if since:
                start_timestamp = int(since.timestamp() * 1000)
                start_id = f"{start_timestamp}-0"

            if until:
                end_timestamp = int(until.timestamp() * 1000)
                end_id = f"{end_timestamp}-0"

            # Get messages in the time range
            messages = await self.redis_client.xrange(
                stream_name, min=start_id, max=end_id, count=limit
            )

            # Convert to StreamMessage objects
            stream_messages = []
            for message_id, fields in messages:
                # Convert fields to dict
                data = {}
                for i in range(0, len(fields), 2):
                    key = fields[i].decode() if isinstance(fields[i], bytes) else fields[i]
                    value = (
                        fields[i + 1].decode()
                        if isinstance(fields[i + 1], bytes)
                        else fields[i + 1]
                    )
                    data[key] = value

                # Extract timestamp from Redis stream ID (format: timestamp-sequence)
                timestamp_ms = (
                    int(message_id.decode().split("-")[0])
                    if isinstance(message_id, bytes)
                    else int(message_id.split("-")[0])
                )
                message_timestamp = datetime.fromtimestamp(timestamp_ms / 1000)

                stream_message = StreamMessage(
                    stream_id=message_id.decode() if isinstance(message_id, bytes) else message_id,
                    data=data,
                    timestamp=message_timestamp,
                )
                stream_messages.append(stream_message)

            return stream_messages

        except Exception as e:
            logger.error(f"Failed to get stream history for {stream_name}", error=str(e))
            return []

    async def _get_all_streams(self) -> list[str]:
        """Get all stream keys using Redis 7.0+ SCAN."""
        try:
            streams = []
            cursor = 0
            pattern = "market:*"

            while True:
                cursor, keys = await self.redis_client.scan(cursor=cursor, match=pattern, count=100)
                streams.extend(keys)

                if cursor == 0:
                    break

            return streams
        except Exception as e:
            logger.error(f"Failed to get streams: {e}")
            return []

    async def cleanup_orphaned_connections(self):
        """Clean up orphaned connections and consumer groups."""
        try:
            # Get all consumer groups from Redis
            all_streams = await self._get_all_streams()
            orphaned_groups = []

            for stream_name in all_streams:
                try:
                    groups_info = await self.redis_client.xinfo_groups(stream_name)
                    for group_info in groups_info:
                        group_name = (
                            group_info[b"name"].decode()
                            if isinstance(group_info[b"name"], bytes)
                            else group_info[b"name"]
                        )

                        # Check if this is a WebSocket consumer group that may be orphaned
                        if group_name.startswith("websocket_") or group_name.startswith(
                            "ws_consumer_"
                        ):
                            # Check if there are consumers in this group
                            consumers_info = await self.redis_client.xinfo_consumers(
                                stream_name, group_name
                            )
                            if not consumers_info:  # No active consumers
                                orphaned_groups.append((stream_name, group_name))

                except Exception as e:
                    logger.debug(f"Could not check consumer groups for stream {stream_name}: {e}")

            # Clean up orphaned groups
            for stream_name, group_name in orphaned_groups:
                try:
                    await self.redis_client.xgroup_destroy(stream_name, group_name)
                    logger.info(
                        f"Cleaned up orphaned consumer group: {group_name} from {stream_name}"
                    )
                except Exception as e:
                    logger.warning(f"Failed to clean up orphaned group {group_name}: {e}")

            logger.info(f"Cleaned up {len(orphaned_groups)} orphaned consumer groups")

        except Exception as e:
            logger.error(f"Error during orphaned connection cleanup: {e}")

    async def _monitor_health(self):
        """Background health monitoring loop. Placeholder for future implementation."""
        while True:
            await asyncio.sleep(60)
