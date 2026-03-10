"""
Plugin State Manager - Redis-based state persistence for plugins and LangGraph workflows

This module provides comprehensive state management for:
- Plugin incremental calculations (RSI, MACD, indicators)
- LangGraph workflow state persistence
- Circuit breaker state tracking
- Event-driven workflow context

Features:
- Redis-based persistence with TTL
- In-memory caching for performance
- Automatic state serialization/deserialization
- State size monitoring and cleanup
- Cross-service state sharing

Version: 1.0.0
Last Updated: 2025-08-17
Status: Production Ready ✅
"""

import json
import time
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any

import redis.asyncio as redis
import structlog

# Import metrics
from src.observability.metrics import LANGGRAPH_STATE_SIZE_GAUGE, PLUGIN_STATE_SIZE_GAUGE

logger = structlog.get_logger(__name__)


@dataclass
class StateMetadata:
    """Metadata for state entries."""

    plugin_name: str
    symbol: str
    timeframe: str
    created_at: datetime
    updated_at: datetime
    size_bytes: int
    version: str = "1.0"
    state_type: str = "plugin"  # plugin, langgraph_workflow, circuit_breaker


class PluginStateManager:
    """Manages plugin and workflow state persistence using Redis."""

    def __init__(self, redis_client: redis.Redis, env_prefix: str):
        self.redis = redis_client
        self.env_prefix = env_prefix
        self.state_cache = defaultdict(dict)  # In-memory cache for performance
        self.cache_ttl = 3600  # 1 hour cache TTL
        self.redis_ttl = 86400  # 24 hour Redis TTL

        # Performance tracking
        self.cache_hits = 0
        self.cache_misses = 0
        self.total_operations = 0

        # State cleanup settings
        self.max_cache_entries = 10000
        self.cleanup_interval = 300  # 5 minutes
        self.last_cleanup = time.time()

    async def save_plugin_state(
        self,
        plugin_name: str,
        symbol: str,
        timeframe: str,
        state: dict[str, Any],
        state_type: str = "plugin",
    ) -> bool:
        """Save plugin state to Redis with TTL and caching."""
        try:
            start_time = time.time()

            # Create state metadata
            now = datetime.now()
            metadata = StateMetadata(
                plugin_name=plugin_name,
                symbol=symbol,
                timeframe=timeframe,
                created_at=now,
                updated_at=now,
                size_bytes=0,
                state_type=state_type,
            )

            # Prepare complete state object
            complete_state = {
                "metadata": asdict(metadata),
                "state": state,
                "timestamp": now.isoformat(),
            }

            # Calculate size
            serialized = json.dumps(complete_state, default=str)
            metadata.size_bytes = len(serialized)
            complete_state["metadata"]["size_bytes"] = metadata.size_bytes

            # Update serialized with size info
            serialized = json.dumps(complete_state, default=str)

            key = self._get_state_key(plugin_name, symbol, timeframe, state_type)

            # Save to Redis with TTL
            await self.redis.set(key, serialized, ex=self.redis_ttl)

            # Update cache
            cache_key = f"{plugin_name}:{symbol}:{timeframe}:{state_type}"
            self.state_cache[cache_key] = {
                "state": state,
                "metadata": metadata,
                "cached_at": time.time(),
            }

            # Update metrics
            if state_type == "plugin":
                PLUGIN_STATE_SIZE_GAUGE.labels(
                    plugin_name=plugin_name, symbol=symbol, timeframe=timeframe
                ).set(metadata.size_bytes)
            elif state_type == "langgraph_workflow":
                LANGGRAPH_STATE_SIZE_GAUGE.labels(
                    workflow_name=plugin_name,  # workflow name passed as plugin_name
                    symbol=symbol,
                    timeframe=timeframe,
                ).set(metadata.size_bytes)

            duration = time.time() - start_time
            logger.debug(
                "State saved successfully",
                plugin=plugin_name,
                symbol=symbol,
                timeframe=timeframe,
                state_type=state_type,
                size_bytes=metadata.size_bytes,
                duration_ms=round(duration * 1000, 2),
            )

            self.total_operations += 1

            # Periodic cache cleanup
            await self._periodic_cleanup()

            return True

        except Exception as e:
            logger.error(
                "Failed to save state",
                plugin=plugin_name,
                symbol=symbol,
                timeframe=timeframe,
                state_type=state_type,
                error=str(e),
            )
            return False

    async def restore_plugin_state(
        self, plugin_name: str, symbol: str, timeframe: str, state_type: str = "plugin"
    ) -> dict[str, Any] | None:
        """Restore plugin state from cache or Redis."""
        try:
            start_time = time.time()
            cache_key = f"{plugin_name}:{symbol}:{timeframe}:{state_type}"

            # Check cache first
            if cache_key in self.state_cache:
                cached_entry = self.state_cache[cache_key]
                cache_age = time.time() - cached_entry["cached_at"]

                # Return if cache is still valid
                if cache_age < self.cache_ttl:
                    self.cache_hits += 1
                    self.total_operations += 1

                    logger.debug(
                        "State restored from cache",
                        plugin=plugin_name,
                        symbol=symbol,
                        timeframe=timeframe,
                        state_type=state_type,
                        cache_age_seconds=round(cache_age, 2),
                    )

                    return cached_entry["state"]
                else:
                    # Cache expired, remove entry
                    del self.state_cache[cache_key]

            # Load from Redis
            key = self._get_state_key(plugin_name, symbol, timeframe, state_type)
            data = await self.redis.get(key)

            self.cache_misses += 1
            self.total_operations += 1

            if not data:
                logger.debug(
                    "No state found in Redis",
                    plugin=plugin_name,
                    symbol=symbol,
                    timeframe=timeframe,
                    state_type=state_type,
                )
                return None

            # Deserialize state
            try:
                complete_state = json.loads(data)
                state = complete_state.get("state", {})
                metadata = complete_state.get("metadata", {})

                # Update cache
                self.state_cache[cache_key] = {
                    "state": state,
                    "metadata": metadata,
                    "cached_at": time.time(),
                }

                duration = time.time() - start_time
                logger.debug(
                    "State restored from Redis",
                    plugin=plugin_name,
                    symbol=symbol,
                    timeframe=timeframe,
                    state_type=state_type,
                    size_bytes=metadata.get("size_bytes", 0),
                    duration_ms=round(duration * 1000, 2),
                )

                return state

            except json.JSONDecodeError as e:
                logger.error(
                    "Failed to deserialize state",
                    plugin=plugin_name,
                    symbol=symbol,
                    timeframe=timeframe,
                    state_type=state_type,
                    error=str(e),
                )
                # Clean up corrupted data
                await self.redis.delete(key)
                return None

        except Exception as e:
            logger.error(
                "Failed to restore state",
                plugin=plugin_name,
                symbol=symbol,
                timeframe=timeframe,
                state_type=state_type,
                error=str(e),
            )
            return None

    async def save_langgraph_workflow_state(
        self, workflow_name: str, symbol: str, timeframe: str, workflow_state: dict[str, Any]
    ) -> bool:
        """Save LangGraph workflow state with specific handling."""
        return await self.save_plugin_state(
            plugin_name=workflow_name,
            symbol=symbol,
            timeframe=timeframe,
            state=workflow_state,
            state_type="langgraph_workflow",
        )

    async def restore_langgraph_workflow_state(
        self, workflow_name: str, symbol: str, timeframe: str
    ) -> dict[str, Any] | None:
        """Restore LangGraph workflow state."""
        return await self.restore_plugin_state(
            plugin_name=workflow_name,
            symbol=symbol,
            timeframe=timeframe,
            state_type="langgraph_workflow",
        )

    async def clear_plugin_state(
        self, plugin_name: str, symbol: str, timeframe: str, state_type: str = "plugin"
    ) -> bool:
        """Clear plugin state from Redis and cache."""
        try:
            key = self._get_state_key(plugin_name, symbol, timeframe, state_type)
            await self.redis.delete(key)

            cache_key = f"{plugin_name}:{symbol}:{timeframe}:{state_type}"
            self.state_cache.pop(cache_key, None)

            logger.debug(
                "State cleared",
                plugin=plugin_name,
                symbol=symbol,
                timeframe=timeframe,
                state_type=state_type,
            )

            return True

        except Exception as e:
            logger.error(
                "Failed to clear state",
                plugin=plugin_name,
                symbol=symbol,
                timeframe=timeframe,
                state_type=state_type,
                error=str(e),
            )
            return False

    async def list_plugin_states(
        self, plugin_name: str | None = None, state_type: str | None = None
    ) -> list[dict[str, Any]]:
        """List all plugin states with optional filtering."""
        try:
            pattern = f"{self.env_prefix}state:*"
            keys = await self.redis.keys(pattern)

            states = []
            for key in keys:
                try:
                    data = await self.redis.get(key)
                    if data:
                        complete_state = json.loads(data)
                        metadata = complete_state.get("metadata", {})

                        # Apply filters
                        if plugin_name and metadata.get("plugin_name") != plugin_name:
                            continue
                        if state_type and metadata.get("state_type") != state_type:
                            continue

                        states.append(
                            {
                                "key": key.decode() if isinstance(key, bytes) else key,
                                "metadata": metadata,
                                "size_bytes": metadata.get("size_bytes", 0),
                            }
                        )

                except Exception as e:
                    logger.warning("Failed to parse state entry", key=key, error=str(e))
                    continue

            return sorted(states, key=lambda x: x["metadata"].get("updated_at", ""))

        except Exception as e:
            logger.error("Failed to list states", error=str(e))
            return []

    async def cleanup_expired_states(self, max_age_hours: int = 48) -> int:
        """Clean up expired states and return count of cleaned entries."""
        try:
            cutoff_time = datetime.now() - timedelta(hours=max_age_hours)

            pattern = f"{self.env_prefix}state:*"
            keys = await self.redis.keys(pattern)

            cleaned_count = 0
            for key in keys:
                try:
                    data = await self.redis.get(key)
                    if data:
                        complete_state = json.loads(data)
                        metadata = complete_state.get("metadata", {})
                        updated_at_str = metadata.get("updated_at")

                        if updated_at_str:
                            updated_at = datetime.fromisoformat(updated_at_str)
                            if updated_at < cutoff_time:
                                await self.redis.delete(key)
                                cleaned_count += 1

                                # Remove from cache if present
                                for cache_key in list(self.state_cache.keys()):
                                    if key.decode().endswith(cache_key.replace(":", "_")):
                                        del self.state_cache[cache_key]
                                        break

                except Exception as e:
                    logger.warning("Failed to check state expiry", key=key, error=str(e))
                    continue

            logger.info(
                "Cleaned up expired states",
                cleaned_count=cleaned_count,
                max_age_hours=max_age_hours,
            )

            return cleaned_count

        except Exception as e:
            logger.error("Failed to cleanup expired states", error=str(e))
            return 0

    def _get_state_key(self, plugin_name: str, symbol: str, timeframe: str, state_type: str) -> str:
        """Generate Redis key for state storage."""
        return f"{self.env_prefix}state:{state_type}:{plugin_name}:{symbol}:{timeframe}"

    async def _periodic_cleanup(self):
        """Periodic cache cleanup to prevent memory issues."""
        current_time = time.time()

        # Clean cache if too large (always trigger in tests)
        if len(self.state_cache) > self.max_cache_entries:
            # Remove oldest entries
            sorted_cache = sorted(self.state_cache.items(), key=lambda x: x[1].get("cached_at", 0))

            target_size = int(self.max_cache_entries * 0.8)
            entries_to_remove = len(self.state_cache) - target_size

            for i in range(entries_to_remove):
                cache_key = sorted_cache[i][0]
                del self.state_cache[cache_key]

            logger.info(
                "Cache cleanup performed",
                removed_entries=entries_to_remove,
                remaining_entries=len(self.state_cache),
            )

        self.last_cleanup = current_time

    async def get_state_summary(self) -> dict[str, Any]:
        """Get comprehensive state management summary for monitoring."""
        try:
            # Cache statistics
            cache_hit_rate = (self.cache_hits / max(self.total_operations, 1)) * 100

            # Group cached states by type
            plugin_states = 0
            workflow_states = 0
            circuit_breaker_states = 0

            for cache_key in self.state_cache.keys():
                if ":plugin" in cache_key:
                    plugin_states += 1
                elif ":langgraph_workflow" in cache_key:
                    workflow_states += 1
                elif ":circuit_breaker" in cache_key:
                    circuit_breaker_states += 1

            # Redis statistics
            pattern = f"{self.env_prefix}state:*"
            redis_keys = await self.redis.keys(pattern)

            summary = {
                "cache_statistics": {
                    "total_operations": self.total_operations,
                    "cache_hits": self.cache_hits,
                    "cache_misses": self.cache_misses,
                    "cache_hit_rate_percent": round(cache_hit_rate, 2),
                    "cached_entries": len(self.state_cache),
                },
                "state_counts": {
                    "plugin_states_cached": plugin_states,
                    "workflow_states_cached": workflow_states,
                    "circuit_breaker_states_cached": circuit_breaker_states,
                    "total_redis_keys": len(redis_keys),
                },
                "performance": {
                    "max_cache_entries": self.max_cache_entries,
                    "cache_ttl_seconds": self.cache_ttl,
                    "redis_ttl_seconds": self.redis_ttl,
                    "last_cleanup_ago_seconds": int(time.time() - self.last_cleanup),
                },
            }

            return summary

        except Exception as e:
            logger.error("Failed to generate state summary", error=str(e))
            return {"error": str(e)}

    async def health_check(self) -> dict[str, Any]:
        """Perform health check on state management system."""
        try:
            start_time = time.time()

            # Test Redis connectivity
            test_key = f"{self.env_prefix}health_check_test"
            test_value = {"timestamp": datetime.now().isoformat(), "test": True}

            await self.redis.set(test_key, json.dumps(test_value), ex=60)
            retrieved = await self.redis.get(test_key)
            await self.redis.delete(test_key)

            redis_healthy = retrieved is not None
            roundtrip_time = time.time() - start_time

            # Get summary
            summary = await self.get_state_summary()

            return {
                "status": "healthy" if redis_healthy else "unhealthy",
                "redis_connectivity": redis_healthy,
                "roundtrip_time_ms": round(roundtrip_time * 1000, 2),
                "summary": summary,
            }

        except Exception as e:
            return {"status": "unhealthy", "error": str(e), "redis_connectivity": False}
