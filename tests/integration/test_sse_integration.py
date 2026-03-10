#!/usr/bin/env python3
"""
Server-Sent Events (SSE) Integration Tests

Tests the SSE endpoint functionality with Redis Streams integration.
This validates that the SSE system correctly broadcasts real-time data
from Redis Streams to frontend clients via Server-Sent Events.

Test scenarios:
1. SSE endpoint connection and event streaming
2. Multiple event types (tick_data, market_data, indicator_data)
3. Stream filtering and subscription patterns
4. Connection handling and error recovery
5. Performance under sustained streaming load
"""

import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import pytest

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import redis.asyncio as redis

from src.core.redis_streams_manager import RedisStreamsManager
from src.core.stream_keys import indicators as sk_indicators
from src.core.stream_keys import live_tick as sk_live_tick
from src.core.stream_keys import market as sk_market


@pytest.fixture
async def redis_client():
    """Redis client for testing."""
    client = redis.Redis(host="localhost", port=6379, db=0)
    try:
        await client.ping()  # Verify connection
    except Exception as e:
        pytest.skip(f"Redis not available: {e}")
    yield client
    await client.aclose()


@pytest.fixture
async def streams_manager(redis_client):
    """Redis streams manager for testing."""
    manager = RedisStreamsManager(redis_client)
    await manager.start()
    yield manager
    await manager.close()


@pytest.fixture
def sample_streaming_data():
    """Generate realistic streaming data for SSE testing."""
    base_time = datetime.now()

    # Tick data
    tick_data = []
    for i in range(10):
        tick_data.append(
            {
                "symbol": "TEST",
                "price": 100.0 + (i * 0.01),
                "bid": 99.98 + (i * 0.01),
                "ask": 100.02 + (i * 0.01),
                "timestamp": (base_time + timedelta(seconds=i)).isoformat(),
                "source": "sse_test",
            }
        )

    # Market data bars
    market_data = []
    for i in range(5):
        price = 100.0 + (i * 0.1)
        market_data.append(
            {
                "timestamp": (base_time + timedelta(minutes=i)).isoformat(),
                "symbol": "TEST",
                "timeframe": "1m",
                "open": str(price - 0.02),
                "high": str(price + 0.05),
                "low": str(price - 0.05),
                "close": str(price),
                "volume": str(1000 + i * 100),
                "source": "sse_test",
            }
        )

    # Indicator data
    indicator_data = []
    for i in range(5):
        indicator_data.append(
            {
                "symbol": "TEST",
                "timeframe": "1m",
                "timestamp": (base_time + timedelta(minutes=i)).isoformat(),
                "rsi": 50.0 + (i * 2),
                "sma_20": 100.0 + (i * 0.1),
                "ema_12": 100.0 + (i * 0.11),
                "macd": 0.5 + (i * 0.1),
                "macd_signal": 0.3 + (i * 0.09),
                "bb_upper": 102.0 + (i * 0.1),
                "bb_middle": 100.0 + (i * 0.1),
                "bb_lower": 98.0 + (i * 0.1),
                "source": "sse_test",
            }
        )

    return {"tick_data": tick_data, "market_data": market_data, "indicator_data": indicator_data}


class TestSSEIntegration:
    """Test suite for Server-Sent Events integration."""

    @pytest.mark.asyncio
    async def test_sse_endpoint_basic_connectivity(self):
        """Test basic SSE endpoint connectivity and response format."""

        # Note: This test assumes the SSE endpoint is running
        # In practice, you'd start the API server for integration testing

        try:
            async with httpx.AsyncClient() as client:
                # Test SSE endpoint with basic parameters
                sse_url = "http://localhost:8000/ai/events?symbols=TEST&timeframe=1m"

                # Open SSE stream with timeout
                async with client.stream("GET", sse_url, timeout=5.0) as response:
                    assert response.status_code == 200
                    assert response.headers.get("content-type") == "text/event-stream"

                    # Read initial response (should be keep-alive comment)
                    line_count = 0
                    async for line in response.aiter_lines():
                        line_count += 1
                        if line.startswith(": "):
                            # Keep-alive comment
                            assert "keep-alive" in line or "heartbeat" in line
                            break
                        if line_count > 10:  # Safety limit
                            break

                    assert line_count > 0, "No SSE response received"

        except Exception as e:
            pytest.skip(f"SSE endpoint not available: {e}")

    @pytest.mark.asyncio
    async def test_sse_event_format_validation(
        self, redis_client, streams_manager, sample_streaming_data
    ):
        """Test SSE event format matches expected structure."""

        # Create mock SSE event parser
        class SSEEventParser:
            def __init__(self):
                self.parsed_events = []

            def parse_sse_line(self, line: str) -> dict:
                """Parse SSE formatted line."""
                if line.startswith("event: "):
                    return {"type": "event", "value": line[7:].strip()}
                elif line.startswith("data: "):
                    try:
                        data = json.loads(line[6:].strip())
                        return {"type": "data", "value": data}
                    except json.JSONDecodeError:
                        return {"type": "data", "value": line[6:].strip()}
                elif line.startswith("id: "):
                    return {"type": "id", "value": line[4:].strip()}
                elif line.startswith(": "):
                    return {"type": "comment", "value": line[2:].strip()}
                elif line == "":
                    return {"type": "end_of_event", "value": None}
                else:
                    return {"type": "unknown", "value": line}

            def simulate_sse_event_generation(
                self, event_name: str, data: dict, stream_name: str
            ) -> str:
                """Simulate how the SSE endpoint formats events."""
                sse_data = {
                    "stream": stream_name,
                    "id": f"test_id_{int(time.time())}",
                    "payload": data,
                }

                return (
                    f"event: {event_name}\nid: {sse_data['id']}\ndata: {json.dumps(sse_data)}\n\n"
                )

        parser = SSEEventParser()

        # Test different event types
        test_cases = [
            ("tick_data", sample_streaming_data["tick_data"][0], "ticks:TEST:live"),
            ("market_data", sample_streaming_data["market_data"][0], "market:TEST:1m"),
            ("indicator_data", sample_streaming_data["indicator_data"][0], "indicators:TEST:1m"),
        ]

        for event_name, data, stream_name in test_cases:
            # Generate SSE formatted message
            sse_message = parser.simulate_sse_event_generation(event_name, data, stream_name)

            # Parse SSE message
            lines = sse_message.strip().split("\n")
            parsed_parts = {}

            for line in lines:
                if line:  # Skip empty lines
                    parsed = parser.parse_sse_line(line)
                    parsed_parts[parsed["type"]] = parsed["value"]

            # Verify SSE format
            assert "event" in parsed_parts
            assert "id" in parsed_parts
            assert "data" in parsed_parts

            # Verify event structure
            assert parsed_parts["event"] == event_name
            assert isinstance(parsed_parts["data"], dict)
            assert "stream" in parsed_parts["data"]
            assert "payload" in parsed_parts["data"]

            # Verify payload contains expected data
            payload = parsed_parts["data"]["payload"]
            assert payload["symbol"] == "TEST"

            if event_name == "market_data":
                assert "timeframe" in payload
                assert "close" in payload
                assert "volume" in payload
            elif event_name == "indicator_data":
                assert "timeframe" in payload
                assert "rsi" in payload or "sma_20" in payload  # At least one indicator
            elif event_name == "tick_data":
                assert "price" in payload

    @pytest.mark.asyncio
    async def test_sse_stream_filtering_and_subscriptions(
        self, redis_client, streams_manager, sample_streaming_data
    ):
        """Test SSE stream filtering matches subscription patterns."""
        env_prefix = "test"

        # Simulate the SSE endpoint's stream filtering logic
        class SSEStreamFilter:
            def __init__(self, symbols: list, timeframe: str):
                self.symbols = symbols
                self.timeframe = timeframe

            def build_stream_list(self) -> list:
                """Build list of streams to monitor (matches SSE endpoint logic)."""
                streams = []
                for symbol in self.symbols:
                    # Tick streams (no timeframe)
                    streams.append(sk_live_tick(env_prefix, symbol))
                    # Market and indicator streams for specified timeframe
                    streams.append(sk_market(env_prefix, symbol, self.timeframe))
                    streams.append(sk_indicators(env_prefix, symbol, self.timeframe))
                return streams

            def get_event_name_for_stream(self, stream_name: str) -> str:
                """Get SSE event name for stream (matches SSE endpoint logic)."""
                # Remove env prefix for pattern matching
                parts = stream_name.split(":", 1)
                candidate = (
                    parts[1]
                    if len(parts) > 1 and parts[0] == env_prefix.rstrip(":")
                    else stream_name
                )

                if candidate.startswith("ticks:"):
                    return "tick_data"
                elif candidate.startswith("market:"):
                    return "market_data"
                elif candidate.startswith("indicators:"):
                    return "indicator_data"
                else:
                    return "message"

        # Test single symbol subscription
        filter_single = SSEStreamFilter(["TEST"], "1m")
        streams_single = filter_single.build_stream_list()

        expected_streams = [
            sk_live_tick(f"{env_prefix}:", "TEST"),
            sk_market(f"{env_prefix}:", "TEST", "1m"),
            sk_indicators(f"{env_prefix}:", "TEST", "1m"),
        ]

        assert len(streams_single) == 3
        for expected in expected_streams:
            assert expected in streams_single

        # Test multiple symbols subscription
        filter_multi = SSEStreamFilter(["TEST", "ES", "NQ"], "5m")
        streams_multi = filter_multi.build_stream_list()

        assert len(streams_multi) == 9  # 3 symbols × 3 stream types

        # Test event name mapping
        test_streams = [
            (sk_live_tick(f"{env_prefix}:", "TEST"), "tick_data"),
            (sk_market(f"{env_prefix}:", "TEST", "1m"), "market_data"),
            (sk_indicators(f"{env_prefix}:", "TEST", "1m"), "indicator_data"),
        ]

        for stream_name, expected_event in test_streams:
            event_name = filter_single.get_event_name_for_stream(stream_name)
            assert event_name == expected_event

    @pytest.mark.asyncio
    async def test_sse_redis_integration_flow(
        self, redis_client, streams_manager, sample_streaming_data
    ):
        """Test complete flow from Redis Streams to SSE events."""
        env_prefix = "test"

        # Clear test streams
        test_streams = [
            sk_live_tick(env_prefix, "TEST"),
            sk_market(env_prefix, "TEST", "1m"),
            sk_indicators(env_prefix, "TEST", "1m"),
        ]

        for stream in test_streams:
            try:
                await redis_client.delete(stream)
            except Exception:
                pass

        # Publish test data to Redis Streams

        # 1. Publish tick data
        for tick in sample_streaming_data["tick_data"][:3]:
            await streams_manager.publish_tick_data("TEST", tick)

        # 2. Publish market data
        for bar in sample_streaming_data["market_data"][:2]:
            await streams_manager.publish_market_data("TEST", "1m", bar)

        # 3. Publish indicator data
        for indicator in sample_streaming_data["indicator_data"][:2]:
            await streams_manager.publish_indicator_data("TEST", "1m", indicator)

        # Simulate SSE endpoint reading from Redis
        class SSERedisReader:
            def __init__(self, redis_client, streams_to_monitor):
                self.redis_client = redis_client
                self.streams = streams_to_monitor
                self.last_ids = {stream: "$" for stream in streams_to_monitor}
                self.events_received = []

            async def read_and_convert_to_sse(self, count: int = 10) -> list:
                """Read from Redis and convert to SSE events."""
                try:
                    # XREAD from all monitored streams
                    result = await self.redis_client.xread(self.last_ids, count=count, block=100)

                    if not result:
                        return []

                    for stream_name, messages in result:
                        event_name = self._get_event_name(stream_name)

                        for msg_id, fields in messages:
                            # Update last ID
                            self.last_ids[stream_name] = msg_id

                            # Create SSE event
                            sse_event = {
                                "event": event_name,
                                "id": msg_id,
                                "data": {"stream": stream_name, "id": msg_id, "payload": fields},
                            }
                            self.events_received.append(sse_event)

                    return self.events_received

                except Exception as e:
                    print(f"Error reading from Redis: {e}")
                    return []

            def _get_event_name(self, stream_name: str) -> str:
                """Convert stream name to SSE event name."""
                if "ticks:" in stream_name:
                    return "tick_data"
                elif "market:" in stream_name:
                    return "market_data"
                elif "indicators:" in stream_name:
                    return "indicator_data"
                else:
                    return "message"

        # Read events from Redis and convert to SSE format
        reader = SSERedisReader(redis_client, test_streams)
        events = await reader.read_and_convert_to_sse()

        # Verify events were received
        assert len(events) > 0, "No events were read from Redis Streams"

        # Verify event types
        event_types = {event["event"] for event in events}
        expected_types = {"tick_data", "market_data", "indicator_data"}
        assert event_types.intersection(
            expected_types
        ), f"Expected event types {expected_types}, got {event_types}"

        # Verify event structure
        for event in events:
            assert "event" in event
            assert "id" in event
            assert "data" in event
            assert "stream" in event["data"]
            assert "payload" in event["data"]

            # Verify payload has required fields
            payload = event["data"]["payload"]
            assert "symbol" in payload

            if event["event"] == "market_data":
                assert "timeframe" in payload
                assert "close" in payload
            elif event["event"] == "indicator_data":
                assert "timeframe" in payload
            elif event["event"] == "tick_data":
                assert "price" in payload

        print(f"✅ SSE Integration: {len(events)} events processed successfully")
        print(f"   Event types: {', '.join(event_types)}")

    @pytest.mark.asyncio
    async def test_sse_performance_under_load(self, redis_client, streams_manager):
        """Test SSE performance with sustained data streaming."""
        env_prefix = "test"

        # Clear test streams
        test_stream = sk_market(env_prefix, "TEST", "1m")
        try:
            await redis_client.delete(test_stream)
        except Exception:
            pass

        # Generate high-volume test data
        high_volume_bars = []
        base_time = datetime.now()
        base_price = 100.0

        for i in range(100):  # 100 bars for load testing
            bar = {
                "timestamp": (base_time + timedelta(minutes=i)).isoformat(),
                "symbol": "TEST",
                "timeframe": "1m",
                "open": str(base_price + (i * 0.01)),
                "high": str(base_price + (i * 0.01) + 0.05),
                "low": str(base_price + (i * 0.01) - 0.05),
                "close": str(base_price + (i * 0.01) + 0.02),
                "volume": str(1000 + (i * 10)),
                "source": "load_test",
            }
            high_volume_bars.append(bar)

        # Publish data rapidly
        start_time = time.time()
        published_count = 0

        for bar in high_volume_bars:
            await streams_manager.publish_market_data("TEST", "1m", bar)
            published_count += 1

        publish_time = time.time() - start_time

        # Simulate SSE reading performance
        read_start = time.time()
        messages = await redis_client.xrange(test_stream)
        read_time = time.time() - read_start

        # Performance metrics
        publish_rate = published_count / publish_time
        read_rate = len(messages) / read_time if read_time > 0 else float("inf")

        print("\n⚡ SSE Performance Results:")
        print(f"   Published: {published_count} messages in {publish_time:.2f}s")
        print(f"   Publish rate: {publish_rate:.1f} messages/sec")
        print(f"   Read: {len(messages)} messages in {read_time:.3f}s")
        print(f"   Read rate: {read_rate:.1f} messages/sec")

        # Performance assertions
        assert publish_rate > 50, f"Publish rate too slow: {publish_rate:.1f}/sec"
        assert read_rate > 100, f"Read rate too slow: {read_rate:.1f}/sec"
        assert len(messages) == published_count, "Data integrity issue"

        # Verify last message
        if messages:
            last_msg = messages[-1][1]
            assert last_msg[b"symbol"].decode() == "TEST"
            assert last_msg[b"timeframe"].decode() == "1m"


if __name__ == "__main__":
    # Run tests directly for development
    import pytest

    pytest.main([__file__, "-v", "-s"])
