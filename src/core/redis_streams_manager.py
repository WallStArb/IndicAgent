"""
Redis Streams Manager - Native Redis Streams for data processing pipeline.

This replaces the complex RedisStreamsManager with native Redis Streams for:
- Sequential data processing: OHLCV -> Indicators -> Signals -> AI Insights
- Guaranteed message delivery with persistence and acknowledgment
- Consumer groups for automatic load balancing and failover
- Automatic retry for failed message processing

Use this instead of custom streaming infrastructure.
"""

import asyncio
import builtins
from collections import deque
from concurrent.futures import ThreadPoolExecutor

import redis.asyncio as redis
import structlog
from redis.asyncio import ConnectionPool, Redis

from .redis_streams_factory import RedisStreamsManagerFactory, redis_streams_manager
from .stream_models_core import (
    CircuitBreakerState,
    ConsumerGroup,
    StreamMessage,
    StreamMetrics,
    StreamsConfig,
)
from .streams_mixins._consuming import ConsumingMixin
from .streams_mixins._monitoring import MonitoringMixin
from .streams_mixins._publishing import PublishingMixin
from .streams_mixins._resilience import ResilienceMixin

logger = structlog.get_logger(__name__)

# Version information
__version__ = "2.0.0"
__last_updated__ = "2026-02-09"
__status__ = "Enhanced Production Ready"


class RedisStreamsManager(
    ResilienceMixin,
    PublishingMixin,
    ConsumingMixin,
    MonitoringMixin,
):
    """
    Native Redis Streams manager for data processing pipeline.

    Replaces 5,000+ lines of custom streaming code with native Redis operations.
    Provides guaranteed message delivery, consumer groups, and automatic retry.
    """

    def __init__(self, redis_client: Redis, config: StreamsConfig | None = None):
        self.redis_client = redis_client
        self.config = config or StreamsConfig()
        self.consumer_groups: dict[str, ConsumerGroup] = {}
        self.active_consumers: dict[str, asyncio.Task] = {}
        self._is_running = False
        self._connection_pool: ConnectionPool | None = None

        # Enhanced state management
        self.circuit_breaker = CircuitBreakerState()
        self.metrics = StreamMetrics()
        self._message_cache: dict = {}  # For deduplication
        self._health_check_task: asyncio.Task | None = None

        # High-performance additions
        self._stream_cache: dict[str, list[str]] = {}  # Cache stream discoveries
        self._cache_ttl: dict[str, float] = {}  # Cache expiration times
        self._pipeline: redis.Redis | None = None
        self._thread_pool: ThreadPoolExecutor | None = None
        self._prefetch_queues: dict[str, deque] = {}  # Pre-fetched messages
        self._active_prefetch_tasks: dict[str, asyncio.Task] = {}
        # Idle recovery background tasks (XAUTOCLAIM-based)
        self._recovery_tasks: dict[str, asyncio.Task] = {}

        # Connection pooling for different operations
        self._read_pool: ConnectionPool | None = None
        self._write_pool: ConnectionPool | None = None

        # Initialize connection pool
        self._setup_connection_pool()

    def _setup_connection_pool(self):
        """Setup high-performance Redis connection pools."""
        try:
            # Setup thread pool for CPU-intensive operations
            if self.config.use_threading:
                self._thread_pool = ThreadPoolExecutor(
                    max_workers=self.config.thread_pool_size, thread_name_prefix="redis_streams"
                )

            # Setup pipeline for batch operations
            if self.config.use_pipeline:
                self._pipeline = self.redis_client.pipeline()

            logger.info(
                "High-performance Redis setup completed",
                max_connections=self.config.max_connections,
                threading=self.config.use_threading,
                pipeline=self.config.use_pipeline,
            )

        except Exception as e:
            logger.warning("High-performance setup warning, using defaults", error=str(e))

    async def initialize(self):
        """Initialize high-performance streams manager with pre-warming."""
        try:
            # Pre-warm connections
            await self._prewarm_connections()

            # Test Redis connection with pipelining
            if self.config.use_pipeline and self._pipeline:
                await self._pipeline.ping()
                await self._pipeline.execute()
            else:
                await self.redis_client.ping()

            # Start background health monitoring
            self._health_check_task = asyncio.create_task(self._monitor_health())

            logger.info("High-performance Redis Streams manager initialized", config=self.config)
            return True

        except Exception as e:
            logger.error("Failed to initialize high-performance streams manager", error=str(e))
            return False

    async def start(self):
        """Start the streams manager."""
        self._is_running = True
        logger.info("Redis Streams manager started")

    async def stop(self):
        """Stop the streams manager with graceful cleanup."""
        self._is_running = False

        # Stop health monitoring first
        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass

        # Stop all consumer tasks gracefully
        if self.active_consumers:
            logger.info(f"Stopping {len(self.active_consumers)} consumer tasks")
            for group_name, task in self.active_consumers.items():
                task.cancel()
                logger.debug(f"Cancelled consumer task: {group_name}")

            # Wait for cleanup with timeout
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self.active_consumers.values(), return_exceptions=True),
                    timeout=10.0,
                )
                logger.info("All consumer tasks stopped gracefully")
            except builtins.TimeoutError:
                logger.warning("Some consumers did not stop gracefully within timeout")

        # Clear all tracking structures
        self.active_consumers.clear()
        self.consumer_groups.clear()
        self._message_cache.clear()

        # Close connection pool if we created one
        if self._connection_pool:
            try:
                await self._connection_pool.disconnect()
                logger.info("Connection pool disconnected")
            except Exception as e:
                logger.warning(f"Error disconnecting connection pool: {e}")

        # Close main Redis connection
        try:
            await self.redis_client.close()
            logger.info("Redis client connection closed")
        except Exception as e:
            logger.warning(f"Error closing Redis client: {e}")

        # Clean up high-performance resources
        if self._thread_pool:
            self._thread_pool.shutdown(wait=True)

        # Stop prefetch tasks
        for task in self._active_prefetch_tasks.values():
            task.cancel()

        if self._active_prefetch_tasks:
            await asyncio.gather(*self._active_prefetch_tasks.values(), return_exceptions=True)

        # Clear caches
        self._stream_cache.clear()
        self._cache_ttl.clear()
        self._prefetch_queues.clear()

        logger.info(
            "High-performance Redis Streams manager stopped",
            final_metrics=await self.get_performance_metrics(),
        )

    async def close(self):
        """Compatibility alias for graceful shutdown."""
        await self.stop()


# Re-export everything for backward compatibility
__all__ = [
    "RedisStreamsManager",
    "StreamMessage",
    "ConsumerGroup",
    "StreamsConfig",
    "CircuitBreakerState",
    "StreamMetrics",
    "RedisStreamsManagerFactory",
    "redis_streams_manager",
]
