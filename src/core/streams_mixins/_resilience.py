"""Resilience mixin for Redis Streams (circuit breaker, retry, connection warming)."""

import asyncio
import builtins
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

import structlog
from redis.exceptions import ConnectionError, RedisError, TimeoutError

logger = structlog.get_logger(__name__)


class ResilienceMixin:
    """Mixin providing circuit breaker, retry, and connection pre-warming."""

    async def _handle_circuit_breaker_failure(self, error: Exception):
        """Handle circuit breaker state transitions."""
        self.circuit_breaker.failure_count += 1
        self.circuit_breaker.last_failure_time = datetime.now()

        if (
            self.circuit_breaker.failure_count >= self.config.circuit_breaker_threshold
            and self.circuit_breaker.state == "CLOSED"
        ):
            self.circuit_breaker.state = "OPEN"
            logger.error(
                "Circuit breaker OPENED due to failures",
                failure_count=self.circuit_breaker.failure_count,
                error=str(error),
            )

    def _is_circuit_breaker_open(self) -> bool:
        """Check if circuit breaker allows operations."""
        if self.circuit_breaker.state == "CLOSED":
            return False

        if self.circuit_breaker.state == "OPEN":
            if (
                self.circuit_breaker.last_failure_time
                and datetime.now() - self.circuit_breaker.last_failure_time
                > timedelta(seconds=self.config.circuit_breaker_timeout)
            ):
                self.circuit_breaker.state = "HALF_OPEN"
                logger.info("Circuit breaker transitioning to HALF_OPEN")
                return False
            return True

        return False  # HALF_OPEN allows limited operations

    async def _execute_with_retry(self, operation: Callable, *args, **kwargs) -> Any:
        """Bulletproof Redis operation with intelligent retry and fallback."""
        if self._is_circuit_breaker_open():
            raise ConnectionError("Circuit breaker is OPEN")

        last_exception = None
        start_time = time.time()

        for attempt in range(self.config.max_retries + 1):
            try:
                # Add operation timeout to prevent hanging
                result = await asyncio.wait_for(
                    operation(*args, **kwargs), timeout=self.config.connection_timeout * 3
                )

                # Reset circuit breaker on success
                if self.circuit_breaker.state in ["HALF_OPEN", "OPEN"]:
                    self.circuit_breaker.state = "CLOSED"
                    self.circuit_breaker.failure_count = 0
                    logger.info("Circuit breaker CLOSED after successful operation")

                # Update performance metrics
                operation_time = time.time() - start_time
                self.metrics.avg_processing_time = (self.metrics.avg_processing_time * 0.95) + (
                    operation_time * 0.05
                )

                return result

            except builtins.TimeoutError:
                last_exception = ConnectionError(
                    f"Operation timeout after {self.config.connection_timeout * 3}s"
                )
                logger.error(
                    f"Operation timeout on attempt {attempt + 1}",
                    operation=operation.__name__ if hasattr(operation, "__name__") else "unknown",
                )

            except (ConnectionError, TimeoutError, RedisError) as e:
                last_exception = e

                # Immediate failure for certain critical errors
                if "READONLY" in str(e) or "NOPERM" in str(e):
                    logger.error(f"Critical Redis error, failing immediately: {e}")
                    await self._handle_circuit_breaker_failure(e)
                    break

                if attempt < self.config.max_retries:
                    # Ultra-fast exponential backoff
                    delay = min(
                        self.config.retry_backoff_base * (1.5**attempt),
                        self.config.retry_backoff_cap,
                    )

                    logger.warning(
                        f"Redis operation failed, ultra-fast retry in {delay:.3f}s",
                        attempt=attempt + 1,
                        max_retries=self.config.max_retries,
                        error=str(e),
                    )

                    await asyncio.sleep(delay)
                else:
                    await self._handle_circuit_breaker_failure(e)

        raise last_exception

    async def _prewarm_connections(self):
        """Pre-warm connection pools for optimal performance."""
        try:
            # Create multiple concurrent connections to warm up the pool
            warmup_tasks = []
            for _i in range(min(10, self.config.max_connections // 2)):
                task = asyncio.create_task(self.redis_client.ping())
                warmup_tasks.append(task)

            await asyncio.gather(*warmup_tasks, return_exceptions=True)
            logger.info("Connection pool pre-warmed successfully")

        except Exception as e:
            logger.warning("Connection pre-warming failed", error=str(e))
