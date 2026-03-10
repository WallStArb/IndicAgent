"""Core dataclasses for Redis Streams Manager."""

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class StreamMessage:
    """Enhanced stream message for Redis Streams with validation."""

    stream_id: str
    data: dict[str, Any]
    timestamp: datetime
    retry_count: int = 0
    source_node: str | None = None
    checksum: str | None = field(init=False)

    def __post_init__(self):
        """Calculate message checksum for integrity validation."""
        message_str = json.dumps(self.data, sort_keys=True, default=str)
        self.checksum = hashlib.md5(message_str.encode()).hexdigest()


@dataclass
class ConsumerGroup:
    """Enhanced Redis Streams consumer group configuration."""

    group_name: str
    stream_pattern: str
    consumer_name: str
    callback: Callable[[StreamMessage], None]
    max_retries: int = 3
    retry_delay: float = 1.0
    dead_letter_stream: str | None = None
    health_check_interval: float = 30.0
    last_heartbeat: datetime = field(default_factory=datetime.now)


@dataclass
class StreamsConfig:
    """High-performance configuration for Redis Streams Manager."""

    # Connection performance
    max_connections: int = 100
    connection_timeout: float = 2.0
    socket_keepalive: bool = True
    socket_keepalive_options: dict = field(
        default_factory=lambda: {
            "TCP_KEEPIDLE": 1,
            "TCP_KEEPINTVL": 1,
            "TCP_KEEPCNT": 3,
        }
    )

    # Processing performance
    max_retries: int = 2
    retry_backoff_base: float = 0.1
    retry_backoff_cap: float = 5.0
    default_maxlen: int = 100000
    batch_size: int = 500
    block_timeout: int = 100

    # Advanced performance features
    use_pipeline: bool = True
    pipeline_size: int = 1000
    enable_prefetch: bool = True
    prefetch_count: int = 10000
    use_threading: bool = True
    thread_pool_size: int = 8

    # Resilience
    compression_threshold: int = 512
    enable_metrics: bool = True
    circuit_breaker_threshold: int = 3
    circuit_breaker_timeout: float = 10.0
    memory_threshold_mb: int = 500
    adaptive_maxlen: bool = True

    # Ultra-fast mode settings
    enable_ultra_fast_mode: bool = False
    disable_ack: bool = False
    use_memory_only: bool = False


@dataclass
class CircuitBreakerState:
    """Circuit breaker state for Redis operations."""

    failure_count: int = 0
    last_failure_time: datetime | None = None
    state: str = "CLOSED"  # CLOSED, OPEN, HALF_OPEN


@dataclass
class StreamMetrics:
    """Performance metrics for streams."""

    messages_published: int = 0
    messages_consumed: int = 0
    messages_failed: int = 0
    bytes_transferred: int = 0
    last_activity: datetime = field(default_factory=datetime.now)
    avg_processing_time: float = 0.0
    peak_memory_usage: int = 0
