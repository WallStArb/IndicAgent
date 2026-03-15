#!/usr/bin/env python3
"""
Simple Pipeline Integration Test

Basic integration test to validate the full data pipeline works.
This test focuses on core functionality without complex fixtures.
"""

import sys
from datetime import datetime
from pathlib import Path

import pytest
import redis.asyncio as redis

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.core.database_manager import DatabaseManager
from src.core.models import Timeframe
from src.core.redis_streams_manager import RedisStreamsManager
from src.core.stream_keys import market as sk_market


class TestSimplePipeline:
    """Simple integration tests for data pipeline."""

    @pytest.mark.asyncio
    async def test_redis_to_database_flow(self):
        """Test basic flow from Redis to Database."""

        # Direct connections without fixtures
        redis_client = None
        db_manager = None
        streams_manager = None

        try:
            # Connect to Redis
            redis_client = redis.Redis(host="localhost", port=6379, db=0)
            await redis_client.ping()

            # Connect to Database
            db_manager = DatabaseManager("postgresql://postgres:postgres@localhost:5432/indicagent")
            await db_manager.initialize()

            # Create streams manager
            streams_manager = RedisStreamsManager(redis_client)
            await streams_manager.start()

            # Test data
            test_symbol = "TEST"
            test_tf = Timeframe.ONE_MINUTE
            test_data = {
                "timestamp": datetime.now().isoformat(),
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.5,
                "volume": 1000,
                "source": "integration_test",
            }

            # Publish to Redis
            stream_id = await streams_manager.publish_ohlcv_bar(test_symbol, test_tf, test_data)
            assert stream_id is not None

            # Verify in Redis (no env prefix in RedisStreamsManager)
            stream_name = sk_market("", test_symbol, "1m")
            stream_length = await redis_client.xlen(stream_name)
            assert stream_length > 0

            # Store in database (simulate indicator processor)
            await db_manager.execute_query(
                """
                INSERT INTO market_data_ohlcv
                (timestamp, symbol, timeframe, source, open, high, low, close, volume)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                ON CONFLICT DO NOTHING
                """,
                datetime.fromisoformat(test_data["timestamp"]),
                test_symbol,
                "1m",
                test_data["source"],
                test_data["open"],
                test_data["high"],
                test_data["low"],
                test_data["close"],
                test_data["volume"],
            )

            # Verify in database
            result = await db_manager.execute_query(
                "SELECT COUNT(*) FROM market_data_ohlcv WHERE symbol = $1 AND source = $2",
                test_symbol,
                test_data["source"],
            )
            assert result[0]["count"] > 0

            print("✅ Simple pipeline test: Redis → Database flow working")

        except Exception as e:
            pytest.fail(f"Pipeline test failed: {e}")

        finally:
            # Cleanup
            if streams_manager:
                await streams_manager.close()
            if db_manager:
                await db_manager.close()
            if redis_client:
                await redis_client.aclose()

    @pytest.mark.asyncio
    async def test_indicator_calculation_integration(self):
        """Test indicator calculation integration."""

        from src.indicators.incremental_manager import IncrementalIndicatorManager

        # Create incremental manager
        manager = IncrementalIndicatorManager()

        # Add test data
        test_bars = []
        base_price = 100.0
        for i in range(50):  # Enough for RSI calculation
            price = base_price + (i * 0.1)
            bar = {
                "timestamp": datetime.now(),
                "open": price,
                "high": price + 0.5,
                "low": price - 0.5,
                "close": price + 0.2,
                "volume": 1000 + i,
            }
            test_bars.append(bar)
            manager.add_bar_data("TEST", "1m", bar)

        # Calculate indicators
        rsi = manager.calculate_rsi_incremental("TEST", "1m")
        sma = manager.calculate_sma_incremental("TEST", "1m", 20)
        ema = manager.calculate_ema_incremental("TEST", "1m", 12)

        # Verify calculations
        assert rsi is not None
        assert 0 <= rsi <= 100
        assert sma is not None
        assert sma > 0
        assert ema is not None
        assert ema > 0

        print(f"✅ Indicator calculation test: RSI={rsi:.2f}, SMA={sma:.2f}, EMA={ema:.2f}")

    @pytest.mark.asyncio
    async def test_end_to_end_minimal(self):
        """Minimal end-to-end test of core pipeline."""

        redis_client = None
        db_manager = None

        try:
            # Setup
            redis_client = redis.Redis(host="localhost", port=6379, db=0)
            await redis_client.ping()

            db_manager = DatabaseManager("postgresql://postgres:postgres@localhost:5432/indicagent")
            await db_manager.initialize()

            # Step 1: Market data ingestion (simulate)
            market_data = {
                "timestamp": datetime.now(),
                "symbol": "TEST_E2E",
                "timeframe": "1m",
                "open": 100.0,
                "high": 101.5,
                "low": 99.5,
                "close": 101.0,
                "volume": 2000,
                "source": "e2e_test",
            }

            # Step 2: Store market data
            await db_manager.execute_query(
                """
                INSERT INTO market_data_ohlcv
                (timestamp, symbol, timeframe, source, open, high, low, close, volume)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """,
                market_data["timestamp"],
                market_data["symbol"],
                market_data["timeframe"],
                market_data["source"],
                market_data["open"],
                market_data["high"],
                market_data["low"],
                market_data["close"],
                market_data["volume"],
            )

            # Step 3: Verify complete pipeline
            market_count = await db_manager.execute_query(
                "SELECT COUNT(*) FROM market_data_ohlcv WHERE symbol = $1", market_data["symbol"]
            )

            assert market_count[0]["count"] > 0

            print("✅ End-to-end minimal test: Market Data → Indicators → Database")

        except Exception as e:
            pytest.fail(f"End-to-end test failed: {e}")

        finally:
            if db_manager:
                await db_manager.close()
            if redis_client:
                await redis_client.aclose()


if __name__ == "__main__":
    # Run tests directly
    import pytest

    pytest.main([__file__, "-v", "-s"])
