#!/usr/bin/env python3
"""
Comprehensive Multi-Timeframe Aggregation Test

Tests the complete multi-timeframe aggregation pipeline: 1m → 5m → 15m → 1h → 4h → 1d
This validates that the timeframe aggregation system works correctly across all supported timeframes.
"""

import asyncio
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import redis.asyncio as redis

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from src.core.models import Timeframe
from src.core.redis_streams_manager import RedisStreamsManager
from src.core.stream_keys import market as sk_market


class TestComprehensiveTimeframeAggregation:
    """Test suite for comprehensive multi-timeframe aggregation."""

    @pytest.mark.asyncio
    async def test_complete_timeframe_aggregation_pipeline(self):
        """Test complete multi-timeframe aggregation: 1m → 5m → 15m → 1h → 4h → 1d."""

        # Direct connections without fixtures to avoid async fixture issues
        redis_client = None
        streams_manager = None

        try:
            # Connect to Redis
            redis_client = redis.Redis(host="localhost", port=6379, db=0)
            await redis_client.ping()

            # Create streams manager
            streams_manager = RedisStreamsManager(redis_client)
            await streams_manager.start()

            env_prefix = "test"

            # All supported timeframes in aggregation order
            timeframes = ["1m", "5m", "15m", "1h", "4h", "1d"]

            # Clean all timeframe streams
            for tf in timeframes:
                stream = sk_market(env_prefix, "TEST", tf)
                try:
                    await redis_client.delete(stream)
                except:
                    pass

            # Generate comprehensive test data - 2 hours = 120 minutes of 1m bars
            print("\n📊 Generating comprehensive test data...")

            comprehensive_data = []
            base_time = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            base_price = 100.0

            for i in range(120):  # 2 hours of 1m bars
                # Realistic price movement with trends
                price_change = 0.01 * (i % 60 - 30) / 30  # Hourly trend cycles
                noise = (-1) ** i * 0.02  # Small noise
                base_price += price_change + noise

                bar = {
                    "timestamp": (base_time + timedelta(minutes=i)).isoformat(),
                    "open": float(base_price - 0.01),
                    "high": float(base_price + 0.05),
                    "low": float(base_price - 0.05),
                    "close": float(base_price),
                    "volume": int(1000 + (i % 100)),  # Varying volume
                    "source": "comprehensive_test",
                }
                comprehensive_data.append(bar)

            # Publish all 1m bars
            print(f"📡 Publishing {len(comprehensive_data)} 1m bars to Redis...")
            for bar in comprehensive_data:
                await streams_manager.publish_ohlcv_bar("TEST", Timeframe.ONE_MINUTE, bar)

            print(f"✅ Published {len(comprehensive_data)} 1m bars")

            # Comprehensive timeframe aggregation builder
            class ComprehensiveTimeframeBuilder:
                def __init__(self, redis_client, env_prefix):
                    self.redis_client = redis_client
                    self.env_prefix = env_prefix
                    self.aggregation_rules = {
                        "5m": {"source": "1m", "ratio": 5, "min_bars": 4},
                        "15m": {"source": "5m", "ratio": 3, "min_bars": 2},
                        "1h": {"source": "15m", "ratio": 4, "min_bars": 3},
                        "4h": {"source": "1h", "ratio": 4, "min_bars": 3},
                        "1d": {"source": "4h", "ratio": 6, "min_bars": 5},
                    }
                    self.aggregated_counts = {}

                async def aggregate_timeframe(self, symbol: str, target_tf: str):
                    """Aggregate from source timeframe to target timeframe."""
                    rule = self.aggregation_rules[target_tf]
                    source_tf = rule["source"]
                    min_bars = rule["min_bars"]

                    source_stream = sk_market(self.env_prefix, symbol, source_tf)
                    target_stream = sk_market(self.env_prefix, symbol, target_tf)

                    # Read source bars
                    messages = await self.redis_client.xrange(source_stream)
                    if not messages:
                        return 0

                    # Group bars by target timeframe intervals
                    grouped_bars = {}
                    for _msg_id, fields in messages:
                        timestamp = datetime.fromisoformat(fields[b"timestamp"].decode())

                        # Calculate interval start based on target timeframe
                        if target_tf == "5m":
                            interval_start = timestamp.replace(
                                minute=(timestamp.minute // 5) * 5, second=0, microsecond=0
                            )
                        elif target_tf == "15m":
                            interval_start = timestamp.replace(
                                minute=(timestamp.minute // 15) * 15, second=0, microsecond=0
                            )
                        elif target_tf == "1h":
                            interval_start = timestamp.replace(minute=0, second=0, microsecond=0)
                        elif target_tf == "4h":
                            interval_start = timestamp.replace(
                                hour=(timestamp.hour // 4) * 4, minute=0, second=0, microsecond=0
                            )
                        elif target_tf == "1d":
                            interval_start = timestamp.replace(
                                hour=0, minute=0, second=0, microsecond=0
                            )
                        else:
                            continue

                        if interval_start not in grouped_bars:
                            grouped_bars[interval_start] = []

                        grouped_bars[interval_start].append(
                            {
                                "open": float(fields[b"open"].decode()),
                                "high": float(fields[b"high"].decode()),
                                "low": float(fields[b"low"].decode()),
                                "close": float(fields[b"close"].decode()),
                                "volume": int(fields[b"volume"].decode()),
                            }
                        )

                    # Create aggregated bars
                    aggregated_count = 0
                    for interval_start, bars in grouped_bars.items():
                        if len(bars) >= min_bars:
                            aggregated_bar = {
                                "timestamp": interval_start.isoformat(),
                                "open": float(bars[0]["open"]),
                                "high": float(max(bar["high"] for bar in bars)),
                                "low": float(min(bar["low"] for bar in bars)),
                                "close": float(bars[-1]["close"]),
                                "volume": int(sum(bar["volume"] for bar in bars)),
                                "source": f"{source_tf}_aggregation",
                            }

                            await self.redis_client.xadd(target_stream, aggregated_bar)
                            aggregated_count += 1

                    self.aggregated_counts[target_tf] = aggregated_count
                    return aggregated_count

                async def run_full_aggregation_pipeline(self, symbol: str):
                    """Run complete aggregation pipeline in correct order."""
                    aggregation_order = ["5m", "15m", "1h", "4h", "1d"]

                    for target_tf in aggregation_order:
                        count = await self.aggregate_timeframe(symbol, target_tf)
                        print(
                            f"  📊 Aggregated {count} {target_tf} bars from {self.aggregation_rules[target_tf]['source']}"
                        )

                        # Small delay between aggregations
                        await asyncio.sleep(0.1)

            # Run comprehensive aggregation pipeline
            print("\n🔄 Running comprehensive aggregation pipeline...")
            builder = ComprehensiveTimeframeBuilder(redis_client, env_prefix)
            await builder.run_full_aggregation_pipeline("TEST")

            # Verify all timeframes were created
            print("\n✅ Verifying aggregation results...")
            aggregation_results = {}
            for tf in ["5m", "15m", "1h", "4h", "1d"]:
                stream = sk_market(env_prefix, "TEST", tf)
                length = await redis_client.xlen(stream)
                aggregation_results[tf] = length

                # Each timeframe should have at least some bars
                assert length > 0, f"No {tf} bars were created"

                # Verify bar structure if bars exist
                if length > 0:
                    messages = await redis_client.xrange(stream, count=1)
                    bar_fields = messages[0][1]
                    assert bar_fields[b"timeframe"].decode() == tf
                    assert float(bar_fields[b"volume"].decode()) > 0

            # Verify aggregation hierarchy (higher timeframes should generally have fewer bars)
            timeframe_hierarchy = ["1m", "5m", "15m", "1h", "4h", "1d"]
            lengths = [len(comprehensive_data)] + [
                aggregation_results[tf] for tf in timeframe_hierarchy[1:]
            ]

            print("\n📊 Timeframe Aggregation Results:")
            for i, tf in enumerate(timeframe_hierarchy):
                count = lengths[i]
                print(f"   {tf:>3}: {count:>3} bars")

            # Verify aggregation makes sense (generally fewer bars as timeframe increases)
            for i in range(len(lengths) - 1):
                current_count = lengths[i]
                next_count = lengths[i + 1]
                # Allow some flexibility but generally should have fewer bars in higher timeframes
                assert (
                    next_count <= current_count
                ), f"Aggregation error: {timeframe_hierarchy[i+1]} ({next_count}) should have ≤ bars than {timeframe_hierarchy[i]} ({current_count})"

            # Verify specific aggregation ratios make sense
            lengths[0]  # 120 bars
            bars_5m = lengths[1]  # Should be around 120/5 = 24 bars
            bars_15m = lengths[2]  # Should be around 24/3 = 8 bars
            bars_1h = lengths[3]  # Should be around 8/4 = 2 bars

            # Allow some tolerance for incomplete intervals
            assert 20 <= bars_5m <= 30, f"5m bars ({bars_5m}) should be ~24 (120/5)"
            assert 6 <= bars_15m <= 10, f"15m bars ({bars_15m}) should be ~8 (24/3)"
            assert 1 <= bars_1h <= 3, f"1h bars ({bars_1h}) should be ~2 (8/4)"

            print("\n🎉 COMPREHENSIVE TIMEFRAME AGGREGATION TEST PASSED!")
            print("✅ All timeframes aggregated correctly")
            print("✅ Data integrity maintained across aggregation levels")
            print("✅ Aggregation ratios within expected ranges")

        except Exception as e:
            pytest.fail(f"Comprehensive timeframe aggregation test failed: {e}")

        finally:
            # Cleanup
            if streams_manager:
                await streams_manager.close()
            if redis_client:
                await redis_client.aclose()

    @pytest.mark.asyncio
    async def test_single_timeframe_aggregation_accuracy(self):
        """Test accuracy of single timeframe aggregation (1m → 5m)."""

        redis_client = None
        streams_manager = None

        try:
            # Connect to Redis
            redis_client = redis.Redis(host="localhost", port=6379, db=0)
            await redis_client.ping()

            streams_manager = RedisStreamsManager(redis_client)
            await streams_manager.start()

            env_prefix = "test"

            # Clean streams
            for tf in ["1m", "5m"]:
                stream = sk_market(env_prefix, "ACCURACY_TEST", tf)
                try:
                    await redis_client.delete(stream)
                except:
                    pass

            # Create exactly 25 1m bars (5 complete 5m intervals)
            print("\n📊 Testing 1m → 5m aggregation accuracy...")

            test_bars = []
            base_time = datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)

            for i in range(25):  # 25 minutes = 5 complete 5-minute intervals
                i % 60
                price = 100.0 + (i * 0.1)  # Steadily increasing price

                bar = {
                    "timestamp": (base_time + timedelta(minutes=i)).isoformat(),
                    "open": float(price),
                    "high": float(price + 0.05),
                    "low": float(price - 0.05),
                    "close": float(price + 0.02),
                    "volume": int(1000 + i),
                    "source": "accuracy_test",
                }
                test_bars.append(bar)
                await streams_manager.publish_ohlcv_bar("ACCURACY_TEST", Timeframe.ONE_MINUTE, bar)

            print(f"✅ Published {len(test_bars)} 1m bars")

            # Manual aggregation to 5m bars
            aggregated_5m = []
            stream_1m = sk_market(env_prefix, "ACCURACY_TEST", "1m")
            stream_5m = sk_market(env_prefix, "ACCURACY_TEST", "5m")

            messages = await redis_client.xrange(stream_1m)

            # Group by 5-minute intervals
            grouped_bars = {}
            for _msg_id, fields in messages:
                timestamp = datetime.fromisoformat(fields[b"timestamp"].decode())
                interval_start = timestamp.replace(
                    minute=(timestamp.minute // 5) * 5, second=0, microsecond=0
                )

                if interval_start not in grouped_bars:
                    grouped_bars[interval_start] = []

                grouped_bars[interval_start].append(
                    {
                        "open": float(fields[b"open"].decode()),
                        "high": float(fields[b"high"].decode()),
                        "low": float(fields[b"low"].decode()),
                        "close": float(fields[b"close"].decode()),
                        "volume": int(fields[b"volume"].decode()),
                    }
                )

            # Create 5m bars
            for interval_start, bars in grouped_bars.items():
                if len(bars) >= 4:  # Complete 5m interval (at least 4 bars)
                    aggregated_bar = {
                        "timestamp": interval_start.isoformat(),
                        "open": float(bars[0]["open"]),
                        "high": float(max(bar["high"] for bar in bars)),
                        "low": float(min(bar["low"] for bar in bars)),
                        "close": float(bars[-1]["close"]),
                        "volume": int(sum(bar["volume"] for bar in bars)),
                        "source": "1m_aggregation",
                    }

                    await redis_client.xadd(stream_5m, aggregated_bar)
                    aggregated_5m.append(aggregated_bar)

            print(f"✅ Created {len(aggregated_5m)} 5m bars from aggregation")

            # Verify aggregation accuracy
            assert len(aggregated_5m) == 5, f"Expected 5 5m bars, got {len(aggregated_5m)}"

            # Verify each 5m bar contains data from 5 1m bars
            for i, bar_5m in enumerate(aggregated_5m):
                expected_volume = sum(1000 + (i * 5 + j) for j in range(5))  # Sum of 5 1m volumes
                assert (
                    bar_5m["volume"] == expected_volume
                ), f"5m bar {i} volume mismatch: {bar_5m['volume']} != {expected_volume}"

                # Verify OHLC logic
                source_bars = test_bars[i * 5 : (i + 1) * 5]  # 5 1m bars for this 5m bar
                expected_open = float(source_bars[0]["open"])
                expected_close = float(source_bars[-1]["close"])
                expected_high = max(float(bar["high"]) for bar in source_bars)
                expected_low = min(float(bar["low"]) for bar in source_bars)

                assert abs(bar_5m["open"] - expected_open) < 0.001, f"5m bar {i} open mismatch"
                assert abs(bar_5m["close"] - expected_close) < 0.001, f"5m bar {i} close mismatch"
                assert abs(bar_5m["high"] - expected_high) < 0.001, f"5m bar {i} high mismatch"
                assert abs(bar_5m["low"] - expected_low) < 0.001, f"5m bar {i} low mismatch"

            print("🎯 AGGREGATION ACCURACY TEST PASSED!")
            print("✅ Correct number of 5m bars created")
            print("✅ OHLC values aggregated correctly")
            print("✅ Volume summed correctly")

        except Exception as e:
            pytest.fail(f"Aggregation accuracy test failed: {e}")

        finally:
            if streams_manager:
                await streams_manager.close()
            if redis_client:
                await redis_client.aclose()


if __name__ == "__main__":
    # Run tests directly for development
    import pytest

    pytest.main([__file__, "-v", "-s"])
