"""Factory and context manager for Redis Streams Manager."""

from contextlib import asynccontextmanager

import structlog
from redis.asyncio import ConnectionPool, Redis

from .stream_models_core import StreamsConfig

logger = structlog.get_logger(__name__)


class RedisStreamsManagerFactory:
    """Factory for creating optimized Redis Streams Manager instances."""

    @staticmethod
    async def create_production_manager(
        redis_url: str = "redis://localhost:6379/0", custom_config: StreamsConfig | None = None
    ):
        """Create a production-ready Redis Streams Manager."""
        from .redis_streams_manager import RedisStreamsManager

        # Production-optimized configuration
        config = custom_config or StreamsConfig(
            max_connections=200,
            connection_timeout=1.0,
            max_retries=2,
            retry_backoff_base=0.05,
            retry_backoff_cap=2.0,
            default_maxlen=1000000,
            batch_size=1000,
            block_timeout=50,
            compression_threshold=256,
            enable_metrics=True,
            circuit_breaker_threshold=5,
            circuit_breaker_timeout=30.0,
            memory_threshold_mb=2000,
            adaptive_maxlen=True,
            use_pipeline=True,
            pipeline_size=500,
            enable_prefetch=True,
            prefetch_count=50000,
            use_threading=True,
            thread_pool_size=16,
        )

        # Create connection pool
        pool = ConnectionPool.from_url(
            redis_url,
            max_connections=config.max_connections,
            socket_timeout=config.connection_timeout,
            socket_connect_timeout=config.connection_timeout,
            socket_keepalive=config.socket_keepalive,
            socket_keepalive_options=config.socket_keepalive_options,
            retry_on_timeout=True,
            health_check_interval=30,
            decode_responses=True,
        )

        redis_client = Redis(connection_pool=pool)
        manager = RedisStreamsManager(redis_client, config)

        # Clean up any orphaned connections from previous runs
        await manager.cleanup_orphaned_connections()

        # Initialize and test connection
        from redis.exceptions import ConnectionError

        if not await manager.initialize():
            raise ConnectionError("Failed to initialize Redis Streams Manager")

        logger.info("Production Redis Streams Manager created successfully", config=config)

        return manager

    @staticmethod
    async def create_development_manager(
        redis_url: str = "redis://localhost:6379/0",
    ):
        """Create a development-friendly Redis Streams Manager."""
        from .redis_streams_manager import RedisStreamsManager

        config = StreamsConfig(
            max_connections=10,
            connection_timeout=5.0,
            max_retries=2,
            retry_backoff_base=0.5,
            retry_backoff_cap=5.0,
            default_maxlen=1000,
            batch_size=10,
            block_timeout=1000,
            compression_threshold=2048,
            enable_metrics=True,
            circuit_breaker_threshold=3,
            circuit_breaker_timeout=30.0,
            memory_threshold_mb=50,
            adaptive_maxlen=False,
        )

        pool = ConnectionPool.from_url(
            redis_url, max_connections=config.max_connections, decode_responses=True
        )

        redis_client = Redis(connection_pool=pool)
        manager = RedisStreamsManager(redis_client, config)

        await manager.initialize()

        logger.info("Development Redis Streams Manager created")
        return manager

    @staticmethod
    async def create_testing_manager(
        redis_url: str = "redis://localhost:6379/1",
    ):
        """Create a Redis Streams Manager optimized for testing."""
        from .redis_streams_manager import RedisStreamsManager

        config = StreamsConfig(
            max_connections=5,
            connection_timeout=2.0,
            max_retries=1,
            retry_backoff_base=0.1,
            retry_backoff_cap=1.0,
            default_maxlen=100,
            batch_size=5,
            block_timeout=100,
            compression_threshold=10000,
            enable_metrics=False,
            circuit_breaker_threshold=2,
            circuit_breaker_timeout=5.0,
            memory_threshold_mb=10,
            adaptive_maxlen=False,
        )

        pool = ConnectionPool.from_url(
            redis_url, max_connections=config.max_connections, decode_responses=True
        )

        redis_client = Redis(connection_pool=pool)
        manager = RedisStreamsManager(redis_client, config)

        # Skip health checks for faster test startup
        manager._is_running = True

        logger.info("Testing Redis Streams Manager created")
        return manager


@asynccontextmanager
async def redis_streams_manager(
    environment: str = "development",
    redis_url: str | None = None,
    custom_config: StreamsConfig | None = None,
):
    """Context manager for Redis Streams Manager with automatic cleanup."""

    redis_url = redis_url or "redis://localhost:6379/0"

    if environment == "production":
        manager = await RedisStreamsManagerFactory.create_production_manager(
            redis_url, custom_config
        )
    elif environment == "testing":
        manager = await RedisStreamsManagerFactory.create_testing_manager(redis_url)
    else:
        manager = await RedisStreamsManagerFactory.create_development_manager(redis_url)

    try:
        await manager.start()
        yield manager
    finally:
        await manager.stop()
        logger.info(f"Redis Streams Manager cleanup completed for {environment}")
