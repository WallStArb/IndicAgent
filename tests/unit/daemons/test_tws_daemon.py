"""Tests for services/tws_daemon — Kafka-native TWS daemon (Phase 30, Plan 02)."""

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_rtb_loop_publishes_5s_price_tick_for_display():
    """_rtb_loop must publish each 5s bar close to market.ticks for dashboard display."""
    from collections import defaultdict
    from datetime import datetime, timezone

    from services.tws_daemon import TwsDaemon

    daemon = TwsDaemon.__new__(TwsDaemon)
    daemon.env_name = "dev"
    daemon.running = True
    daemon.bars_processed = 0
    daemon.ticks_processed = 0
    daemon.m_bars = MagicMock()
    daemon.m_ticks = MagicMock()
    daemon.seen_bar_timestamps = defaultdict(set)
    daemon.seen_bar_timestamps_order = defaultdict(list)
    mock_rm = MagicMock()
    mock_rm.check_roll = MagicMock(return_value=False)
    mock_rm.should_skip_symbol = MagicMock(return_value=False)
    daemon._roll_monitor = mock_rm

    kafka_producer = AsyncMock()
    kafka_producer.publish = AsyncMock()
    daemon._kafka_producer = kafka_producer

    class FakeRTB:
        time = datetime(2026, 3, 21, 14, 0, 5, tzinfo=timezone.utc)
        open_ = 5500.0; high = 5505.0; low = 5498.0; close = 5503.0; volume = 50.0

    async def fake_stream(symbols):
        yield "ES", FakeRTB()

    provider_mock = MagicMock()
    provider_mock.stream_real_time_bars = fake_stream
    daemon.provider = provider_mock
    daemon.contracts = [{"symbol": "ES"}]

    await daemon._rtb_loop()

    tick_calls = [c for c in kafka_producer.publish.call_args_list
                  if "ticks" in str(c.args[0])]
    assert len(tick_calls) == 1
    tick_data = tick_calls[0].args[1]
    assert tick_data["symbol"] == "ES"
    assert tick_data["price"] == "5503.0"


@pytest.mark.asyncio
async def test_emit_bar_dedup_guard_prevents_double_publish():
    """_emit_bar must not re-publish a bar with the same timestamp."""
    from collections import defaultdict
    from datetime import datetime, timezone

    from services.tws_daemon import TwsDaemon

    daemon = TwsDaemon.__new__(TwsDaemon)
    daemon.env_name = "dev"
    daemon.bars_processed = 0
    daemon.m_bars = MagicMock()
    daemon.seen_bar_timestamps = defaultdict(set)
    daemon.seen_bar_timestamps_order = defaultdict(list)
    mock_rm = MagicMock()
    mock_rm.check_roll = MagicMock(return_value=False)
    mock_rm.should_skip_symbol = MagicMock(return_value=False)
    daemon._roll_monitor = mock_rm

    kafka_producer = AsyncMock()
    kafka_producer.publish = AsyncMock()
    daemon._kafka_producer = kafka_producer

    bar_minute = datetime(2026, 3, 21, 14, 0, 0, tzinfo=timezone.utc)
    state = {
        "bar_minute": bar_minute,
        "open": 5500.0, "high": 5510.0, "low": 5498.0,
        "close": 5505.0, "volume": 1000.0,
    }

    # First call — should publish
    await daemon._emit_bar("ES", state)
    assert kafka_producer.publish.call_count == 1

    # Second call with same timestamp — should NOT publish
    await daemon._emit_bar("ES", state)
    assert kafka_producer.publish.call_count == 1  # still 1


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


@pytest.mark.asyncio
async def test_ibkr_stream_real_time_bars_yields_symbol_bar_tuple():
    """stream_real_time_bars must yield (symbol, bar) tuples via async iterator."""
    import asyncio
    from datetime import datetime, timezone
    from unittest.mock import MagicMock

    class FakeRTB:
        time = datetime(2026, 3, 21, 14, 0, 5, tzinfo=timezone.utc)
        open_ = 5500.0
        high = 5505.0
        low = 5498.0
        close = 5503.0
        volume = 50.0
        wap = 5501.5
        count = 12

    # FakeEvent correctly captures the callback registered via +=
    class FakeEvent:
        def __init__(self):
            self._cb = None
        def __iadd__(self, cb):
            self._cb = cb
            return self
        def __isub__(self, cb):
            return self

    fake_event = FakeEvent()
    fake_bars = MagicMock()
    fake_bars.updateEvent = fake_event

    ib_mock = MagicMock()
    ib_mock.reqRealTimeBars.return_value = fake_bars

    from src.providers.ibkr import IBKRProvider
    provider = IBKRProvider.__new__(IBKRProvider)
    provider._ib = ib_mock
    provider._qualified_contracts = {"ES": MagicMock(secType="FUT")}
    provider._rtb_queue = None
    provider._loop = None

    results = []

    async def consume():
        async for sym, bar in provider.stream_real_time_bars(["ES"]):
            results.append((sym, bar))
            break  # consume one then stop

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)  # let iterator start and register callback

    # Simulate IBKR pushing a 5s bar via the registered callback
    assert fake_event._cb is not None, "updateEvent callback not registered"
    fake_event._cb([FakeRTB()], True)  # (bars_list, hasNewBar)

    await asyncio.wait_for(task, timeout=1.0)
    assert len(results) == 1
    sym, bar = results[0]
    assert sym == "ES"
    assert bar.close == 5503.0


@pytest.mark.asyncio
async def test_rtb_loop_aggregates_5s_bars_to_1m():
    """_rtb_loop must emit a 1m bar to Kafka when a new minute starts.

    IBKR RealTimeBar.time is the bar CLOSE time. First bar of a minute closes
    at :05, last at :60 (= start of next minute, triggers emit of prior minute).
    """
    from collections import defaultdict
    from datetime import datetime, timezone
    from unittest.mock import AsyncMock, MagicMock

    from services.tws_daemon import TwsDaemon

    daemon = TwsDaemon.__new__(TwsDaemon)
    daemon.env_name = "dev"
    daemon.running = True
    daemon.bars_processed = 0
    daemon.ticks_processed = 0
    daemon.m_bars = MagicMock()
    daemon.m_ticks = MagicMock()
    daemon.seen_bar_timestamps = defaultdict(set)
    daemon.seen_bar_timestamps_order = defaultdict(list)
    mock_rm = MagicMock()
    mock_rm.check_roll = MagicMock(return_value=False)
    mock_rm.should_skip_symbol = MagicMock(return_value=False)
    daemon._roll_monitor = mock_rm

    kafka_producer = AsyncMock()
    kafka_producer.publish = AsyncMock()
    daemon._kafka_producer = kafka_producer

    # 11 bars closing at :05..:55 in minute 14:00, then Bar60 (14:01:00) triggers emit
    class FakeRTB:
        def __init__(self, minute, second, o, h, low, c, vol):
            self.time = datetime(2026, 3, 21, 14, minute, second, tzinfo=timezone.utc)
            self.open_ = o; self.high = h; self.low = low
            self.close = c; self.volume = float(vol)

    bars_min0 = [FakeRTB(0, s, 5500.0, 5510.0, 5498.0, 5505.0, 100.0)
                 for s in range(5, 60, 5)]  # 11 bars at :05..:55

    class Bar60:
        time = datetime(2026, 3, 21, 14, 1, 0, tzinfo=timezone.utc)
        open_ = 5505.0; high = 5510.0; low = 5498.0; close = 5506.0; volume = 100.0

    class Bar65:
        time = datetime(2026, 3, 21, 14, 1, 5, tzinfo=timezone.utc)
        open_ = 5506.0; high = 5508.0; low = 5504.0; close = 5507.0; volume = 50.0

    all_bars = bars_min0 + [Bar60(), Bar65()]

    async def fake_stream(symbols):
        for bar in all_bars:
            yield "ES", bar

    provider_mock = MagicMock()
    provider_mock.stream_real_time_bars = fake_stream
    daemon.provider = provider_mock
    daemon.contracts = [{"symbol": "ES"}]

    await daemon._rtb_loop()

    # Exactly 1 bar published to market.bars (completed minute :00)
    bar_publishes = [c for c in kafka_producer.publish.call_args_list
                     if "bars" in str(c.args[0])]
    assert len(bar_publishes) == 1

    bar_data = bar_publishes[0].args[1]
    assert bar_data["symbol"] == "ES"
    assert bar_data["timeframe"] == "1m"
    assert float(bar_data["open"]) == 5500.0    # first bar open
    assert float(bar_data["high"]) == 5510.0    # max high
    assert float(bar_data["low"]) == 5498.0     # min low
    assert float(bar_data["close"]) == 5506.0   # last bar close (Bar60, which triggered the emit)
    assert float(bar_data["volume"]) == 1200.0  # 11×100 + 100 (Bar60) = 1200
    assert bar_data["source"] == "authoritative"


def test_timeframes_builder_no_redis_asyncio_import():
    """services/timeframes_builder_service.py must not import redis.asyncio after migration."""
    import ast
    from pathlib import Path

    source = (
        Path(__file__).parent.parent.parent.parent / "services" / "timeframes_builder_service.py"
    ).read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and "redis" in node.module:
            if "asyncio" in node.module:
                pytest.fail(
                    f"redis.asyncio import found in timeframes_builder_service.py: {node.module}"
                )
        if isinstance(node, ast.Import):
            for alias in node.names:
                if "redis.asyncio" in alias.name:
                    pytest.fail(f"redis.asyncio import found: {alias.name}")
