"""Tests for services/tws_daemon — Kafka-native TWS daemon (Phase 30, Plan 02)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_tws_daemon_publishes_bar_to_kafka():
    """TwsDaemon._fetch_bars_for_symbol must publish bar to topic_market_bars via KafkaProducerClient."""
    from services.tws_daemon import TwsDaemon

    daemon = TwsDaemon.__new__(TwsDaemon)
    daemon.settings = MagicMock()
    daemon.settings.env_name = "dev"
    daemon.settings.kafka_bootstrap_servers = "localhost:19092"
    daemon.env_name = "dev"
    daemon.contracts = [{"symbol": "ES"}]
    daemon.seen_bar_timestamps = {"ES": set()}
    daemon.seen_bar_timestamps_order = {"ES": []}
    daemon.bars_processed = 0
    daemon.m_bars = MagicMock()
    daemon.logger = MagicMock()

    kafka_producer = AsyncMock()
    kafka_producer.publish = AsyncMock()
    daemon._kafka_producer = kafka_producer

    from datetime import datetime

    class FakeBar:
        timestamp = datetime(2026, 3, 14, 10, 0, 0)
        open = 5500.0
        high = 5510.0
        low = 5495.0
        close = 5505.0
        volume = 1000

    provider_mock = AsyncMock()
    provider_mock.fetch_historical_bars = AsyncMock(return_value=[FakeBar()])
    daemon.provider = provider_mock
    daemon.async_redis = None

    await daemon._fetch_bars_for_symbol("ES", datetime(2026, 3, 14, 9, 58), datetime(2026, 3, 14, 10, 0))

    kafka_producer.publish.assert_called_once()
    call_args = kafka_producer.publish.call_args
    topic = call_args.args[0]
    assert topic == "dev.market.bars", f"Expected dev.market.bars, got {topic!r}"
    key = call_args.kwargs.get("key") or call_args.args[2]
    assert key == "ES:1m", f"Expected key ES:1m, got {key!r}"


@pytest.mark.asyncio
async def test_tws_daemon_publishes_tick_to_kafka():
    """TwsDaemon._tick_loop must publish ticks to topic_market_ticks via KafkaProducerClient."""
    from services.tws_daemon import TwsDaemon

    daemon = TwsDaemon.__new__(TwsDaemon)
    daemon.settings = MagicMock()
    daemon.settings.env_name = "dev"
    daemon.env_name = "dev"
    daemon.contracts = [{"symbol": "ES"}]
    daemon.running = True
    daemon.ticks_processed = 0
    daemon.dropped_ticks = 0
    daemon.m_ticks = MagicMock()
    daemon.m_dropped = MagicMock()
    daemon.m_dropped_by_reason = MagicMock()
    daemon.m_dropped_by_reason.labels = MagicMock(return_value=MagicMock())
    daemon.logger = MagicMock()

    kafka_producer = AsyncMock()
    kafka_producer.publish = AsyncMock()
    daemon._kafka_producer = kafka_producer

    class FakeTick:
        symbol = "ES"

        def model_dump(self, mode="python"):
            return {"symbol": "ES", "price": 5505.0, "bid": 5504.0, "ask": 5506.0}

    async def fake_stream_ticks(symbols):
        yield FakeTick()

    provider_mock = MagicMock()
    provider_mock.stream_ticks = fake_stream_ticks
    daemon.provider = provider_mock

    await daemon._tick_loop()

    kafka_producer.publish.assert_called_once()
    call_args = kafka_producer.publish.call_args
    topic = call_args.args[0]
    assert topic == "dev.market.ticks", f"Expected dev.market.ticks, got {topic!r}"
    key = call_args.kwargs.get("key") or call_args.args[2]
    assert key == "ES", f"Expected key ES, got {key!r}"


def test_tws_daemon_no_redis_asyncio_import():
    """services/tws_daemon.py must not import redis.asyncio (fully Kafka-native)."""
    import ast
    from pathlib import Path

    source = (Path(__file__).parent.parent.parent.parent / "services" / "tws_daemon.py").read_text()
    tree = ast.parse(source)
    redis_asyncio_imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and "redis" in node.module:
            redis_asyncio_imports.append(node.module)
        if isinstance(node, ast.Import):
            for alias in node.names:
                if "redis.asyncio" in alias.name:
                    redis_asyncio_imports.append(alias.name)
    assert not redis_asyncio_imports, f"redis.asyncio imports found: {redis_asyncio_imports}"


def test_timeframes_builder_no_redis_asyncio_import():
    """services/timeframes_builder_service.py must not import redis.asyncio after migration."""
    import ast
    from pathlib import Path

    source = (Path(__file__).parent.parent.parent.parent / "services" / "timeframes_builder_service.py").read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and "redis" in node.module:
            if "asyncio" in node.module:
                pytest.fail(f"redis.asyncio import found in timeframes_builder_service.py: {node.module}")
        if isinstance(node, ast.Import):
            for alias in node.names:
                if "redis.asyncio" in alias.name:
                    pytest.fail(f"redis.asyncio import found: {alias.name}")
