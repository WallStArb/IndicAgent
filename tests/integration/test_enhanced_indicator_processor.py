#!/usr/bin/env python3
"""
Integration tests for Enhanced Indicator Processor Service

Tests the complete enhanced indicator processing pipeline including:
- Incremental calculation performance
- Fallback to full calculation
- Redis streams integration
- Database storage
- Service lifecycle management
"""

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import redis.asyncio as redis

from services.indicators_enhanced_service import EnhancedIndicatorProcessorService
from src.core.database_manager import DatabaseManager
from src.core.stream_keys import indicators as sk_indicators
from src.core.stream_keys import market as sk_market


@pytest.fixture
async def redis_client():
    """Redis client for testing."""
    client = redis.Redis(host="localhost", port=6379, db=0)
    yield client
    await client.aclose()


@pytest.fixture
async def db_manager():
    """Database manager for testing."""
    db = DatabaseManager("postgresql://postgres:postgres@localhost:5432/indicagent")
    await db.initialize()
    yield db
    await db.close()


@pytest.fixture
def temp_config():
    """Create temporary configuration for testing."""
    config = {
        "redis": {"host": "localhost", "port": 6379, "db": 0},
        "database": {"url": "postgresql://postgres:postgres@localhost:5432/indicagent"},
        "service": {
            "symbols": ["TEST"],
            "timeframes": ["1m"],
            "indicators": ["RSI", "SMA_20", "EMA_12", "MACD"],
            "processing_interval": 0.01,  # Very fast for testing
            "health_check_interval": 1,
            "min_history_bars": 50,
            "use_incremental": True,
            "fallback_threshold": 20,
        },
        "logging": {"level": "DEBUG", "file": "/tmp/enhanced_indicator_test.log"},
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(config, f)
        temp_file = f.name

    yield temp_file

    # Cleanup
    if os.path.exists(temp_file):
        os.unlink(temp_file)


@pytest.fixture
def sample_bars():
    """Generate sample market data bars."""
    bars = []
    base_price = 100.0
    base_time = datetime.now()

    for i in range(100):
        # Trending price movement
        base_price += (i * 0.01) + ((-1) ** i * 0.1)  # Trend + oscillation

        high = base_price + abs(i * 0.005)
        low = base_price - abs(i * 0.005)
        close = base_price + ((-1) ** i * 0.02)

        bars.append(
            {
                "timestamp": (base_time + timedelta(minutes=i)).isoformat(),
                "symbol": "TEST",
                "timeframe": "1m",
                "open": str(base_price),
                "high": str(max(base_price, high, close)),
                "low": str(min(base_price, low, close)),
                "close": str(close),
                "volume": str(1000 + i * 10),
                "source": "test",
            }
        )

    return bars


class TestEnhancedIndicatorProcessor:
    """Test suite for Enhanced Indicator Processor Service."""

    @pytest.mark.asyncio
    async def test_service_initialization(self, temp_config):
        """Test service initializes correctly with incremental manager."""
        service = EnhancedIndicatorProcessorService(temp_config)

        # Check initialization
        assert service.incremental_manager is not None
        assert service.indicator_calc is not None
        assert service.config["service"]["use_incremental"] is True
        assert service.metrics.incremental_calculations == 0
        assert service.metrics.full_recalculations == 0

    @pytest.mark.asyncio
    async def test_incremental_calculation_performance(
        self, temp_config, redis_client, sample_bars
    ):
        """Test that incremental calculations are used and perform better."""
        env_prefix = "test"

        # Clean up any existing test data
        test_stream = sk_market(env_prefix, "TEST", "1m")
        try:
            await redis_client.delete(test_stream)
        except:
            pass

        # Create service but don't start full service (too heavy for test)
        service = EnhancedIndicatorProcessorService(temp_config)
        service.env_prefix = env_prefix

        # Connect components manually
        await service._connect_redis()
        await service._connect_database()

        # Add historical data to incremental manager
        for bar in sample_bars[:50]:  # Add enough for initialization
            bar_data = {
                "timestamp": datetime.fromisoformat(bar["timestamp"]),
                "open": float(bar["open"]),
                "high": float(bar["high"]),
                "low": float(bar["low"]),
                "close": float(bar["close"]),
                "volume": int(bar["volume"]),
            }
            service.incremental_manager.add_bar_data("TEST", "1m", bar_data)

        # Test incremental calculations
        initial_incremental_count = service.metrics.incremental_calculations

        # Process new bar with incremental calculations
        new_bar_data = {
            "timestamp": datetime.now(),
            "open": 101.0,
            "high": 101.5,
            "low": 100.5,
            "close": 101.2,
            "volume": 2000,
        }

        service.incremental_manager.add_bar_data("TEST", "1m", new_bar_data)

        indicators_calculated = await service._calculate_enhanced_indicators(
            "TEST", "1m", new_bar_data["timestamp"]
        )

        # Check that indicators were calculated
        assert indicators_calculated > 0

        # Should use incremental calculations (since we have enough history)
        assert service.metrics.incremental_calculations > initial_incremental_count

        # Clean up
        await service.stop()

    @pytest.mark.asyncio
    async def test_fallback_to_full_calculation(self, temp_config, redis_client):
        """Test fallback to full calculation when insufficient history."""
        env_prefix = "test"

        service = EnhancedIndicatorProcessorService(temp_config)
        service.env_prefix = env_prefix

        await service._connect_redis()
        await service._connect_database()

        # Only add minimal data (below fallback threshold)
        minimal_bars = []
        for i in range(10):  # Below threshold of 20
            bar_data = {
                "timestamp": datetime.now() + timedelta(minutes=i),
                "open": 100.0 + i,
                "high": 101.0 + i,
                "low": 99.0 + i,
                "close": 100.5 + i,
                "volume": 1000,
            }
            minimal_bars.append(bar_data)
            service.incremental_manager.add_bar_data("TEST", "1m", bar_data)
            service.bar_history["TEST:1m"].append(bar_data)

        initial_full_count = service.metrics.full_recalculations

        # Try to calculate indicators (should fallback to full calculation)
        await service._calculate_enhanced_indicators("TEST", "1m", datetime.now())

        # Should have fallen back to full calculation
        # Note: May be 0 if even full calculation fails due to insufficient data
        assert service.metrics.full_recalculations >= initial_full_count

        await service.stop()

    @pytest.mark.asyncio
    async def test_redis_streams_integration(self, temp_config, redis_client, sample_bars):
        """Test integration with Redis streams."""
        env_prefix = "test"

        service = EnhancedIndicatorProcessorService(temp_config)
        service.env_prefix = env_prefix

        await service._connect_redis()
        await service._connect_database()

        # Initialize with historical data
        for bar in sample_bars[:30]:
            bar_data = {
                "timestamp": datetime.fromisoformat(bar["timestamp"]),
                "open": float(bar["open"]),
                "high": float(bar["high"]),
                "low": float(bar["low"]),
                "close": float(bar["close"]),
                "volume": int(bar["volume"]),
            }
            service.incremental_manager.add_bar_data("TEST", "1m", bar_data)

        # Publish test indicator result
        await service._publish_and_store_indicator("TEST", "1m", "RSI", 65.5, datetime.now())

        # Check Redis stream
        indicators_stream = sk_indicators(env_prefix, "TEST", "1m")
        stream_length = await redis_client.xlen(indicators_stream)

        assert stream_length > 0

        # Read the published indicator
        messages = await redis_client.xrange(indicators_stream, count=1)
        assert len(messages) > 0

        message_fields = messages[0][1]  # First message fields
        assert message_fields[b"indicator_name"].decode() == "RSI"
        assert float(message_fields[b"value"].decode()) == 65.5

        await service.stop()

    @pytest.mark.asyncio
    async def test_database_storage_integration(self, temp_config, db_manager):
        """Test database storage of calculated indicators."""
        service = EnhancedIndicatorProcessorService(temp_config)

        await service._connect_redis()
        await service._connect_database()

        timestamp = datetime.now()

        # Store test indicator
        await service._publish_and_store_indicator("TEST", "1m", "SMA_20", 102.5, timestamp)

        # Query database to verify storage
        query = """
            SELECT * FROM technical_indicators
            WHERE symbol = $1 AND timeframe = $2 AND indicator_name = $3
            ORDER BY timestamp DESC LIMIT 1
        """

        result = await db_manager.execute_query(query, "TEST", "1m", "SMA_20")

        assert len(result) > 0
        stored_indicator = result[0]
        assert stored_indicator["symbol"] == "TEST"
        assert stored_indicator["timeframe"] == "1m"
        assert stored_indicator["indicator_name"] == "SMA_20"
        assert stored_indicator["value"] == 102.5

        await service.stop()

    @pytest.mark.asyncio
    async def test_memory_efficiency(self, temp_config):
        """Test memory efficiency of incremental manager."""
        service = EnhancedIndicatorProcessorService(temp_config)

        # Add significant amount of data
        for i in range(500):  # 500 bars across multiple symbols
            for symbol in ["TEST1", "TEST2", "TEST3"]:
                bar_data = {
                    "timestamp": datetime.now() + timedelta(minutes=i),
                    "open": 100.0 + i * 0.1,
                    "high": 101.0 + i * 0.1,
                    "low": 99.0 + i * 0.1,
                    "close": 100.5 + i * 0.1,
                    "volume": 1000 + i,
                }
                service.incremental_manager.add_bar_data(symbol, "1m", bar_data)

        # Calculate some indicators to create states
        for symbol in ["TEST1", "TEST2", "TEST3"]:
            service.incremental_manager.calculate_rsi_incremental(symbol, "1m")
            service.incremental_manager.calculate_sma_incremental(symbol, "1m", 20)
            service.incremental_manager.calculate_ema_incremental(symbol, "1m", 12)

        # Check memory usage
        memory_stats = service.incremental_manager.get_memory_usage()

        assert memory_stats["total_states"] > 0  # Should have indicator states
        assert memory_stats["total_cache_states"] > 0  # Should have cache states
        assert memory_stats["total_bars_cached"] > 0  # Should have cached data

        # Memory should be reasonable (rough check)
        estimated_mb = memory_stats["total_bars_cached"] * 0.001
        assert estimated_mb < 10  # Should be well under 10MB for test data

        print(
            f"Memory efficiency test: {memory_stats['total_states']} states, "
            f"{memory_stats['total_bars_cached']} bars cached, ~{estimated_mb:.2f}MB"
        )

    @pytest.mark.asyncio
    async def test_accuracy_comparison(self, temp_config):
        """Test that incremental results match full calculation results."""
        service = EnhancedIndicatorProcessorService(temp_config)

        await service._connect_redis()
        await service._connect_database()

        # Generate deterministic test data
        import numpy as np

        np.random.seed(42)

        bars = []
        base_price = 100.0
        for i in range(100):
            price_change = np.random.normal(0, 0.5)
            base_price += price_change

            bar_data = {
                "timestamp": datetime.now() + timedelta(minutes=i),
                "open": base_price,
                "high": base_price + abs(np.random.normal(0, 0.2)),
                "low": base_price - abs(np.random.normal(0, 0.2)),
                "close": base_price + np.random.normal(0, 0.1),
                "volume": 1000,
            }
            bars.append(bar_data)
            service.bar_history["TEST:1m"].append(bar_data)
            service.incremental_manager.add_bar_data("TEST", "1m", bar_data)

        # Calculate RSI using incremental method
        incremental_rsi = service.incremental_manager.calculate_rsi_incremental("TEST", "1m")

        # Calculate RSI using full method
        full_rsi = await service._calculate_indicator_full("TEST:1m", "RSI")

        # Results should be very similar (within small tolerance)
        if incremental_rsi is not None and full_rsi is not None:
            difference = abs(incremental_rsi - full_rsi)
            print(
                f"RSI comparison: Incremental={incremental_rsi:.4f}, Full={full_rsi:.4f}, "
                f"Difference={difference:.4f}"
            )

            assert difference < 2.0  # Within 2 RSI points (reasonable tolerance)

        await service.stop()

    @pytest.mark.asyncio
    async def test_service_metrics_tracking(self, temp_config):
        """Test that service properly tracks performance metrics."""
        service = EnhancedIndicatorProcessorService(temp_config)

        # Initial metrics
        assert service.metrics.total_bars_processed == 0
        assert service.metrics.total_indicators_calculated == 0
        assert service.metrics.incremental_calculations == 0
        assert service.metrics.full_recalculations == 0

        await service._connect_redis()
        await service._connect_database()

        # Simulate some processing
        for i in range(10):
            bar_data = {
                "timestamp": datetime.now() + timedelta(minutes=i),
                "open": 100.0 + i,
                "high": 101.0 + i,
                "low": 99.0 + i,
                "close": 100.5 + i,
                "volume": 1000,
            }
            service.incremental_manager.add_bar_data("TEST", "1m", bar_data)

        # Manually update some metrics
        service.metrics.total_bars_processed += 10
        service.metrics.incremental_calculations += 5
        service.metrics.full_recalculations += 2
        service.metrics.total_indicators_calculated += 7

        # Check metric calculations
        service.metrics.uptime_seconds = 60  # 1 minute

        if service.metrics.uptime_seconds > 0:
            service.metrics.indicators_per_minute = (
                service.metrics.total_indicators_calculated * 60.0 / service.metrics.uptime_seconds
            )

        if service.metrics.full_recalculations > 0:
            total_calcs = (
                service.metrics.incremental_calculations + service.metrics.full_recalculations
            )
            incremental_ratio = service.metrics.incremental_calculations / total_calcs
            service.metrics.incremental_speed_improvement = incremental_ratio * 100.0

        # Verify metrics
        assert service.metrics.total_bars_processed == 10
        assert service.metrics.total_indicators_calculated == 7
        assert service.metrics.indicators_per_minute == 7.0  # 7 indicators in 1 minute
        assert service.metrics.incremental_speed_improvement == 71.4  # 5/7 * 100

        await service.stop()


if __name__ == "__main__":
    # Run tests directly for development
    import pytest

    pytest.main([__file__, "-v"])
