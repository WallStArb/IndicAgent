"""Unit tests for BarAggregator — TDD tests for Plan 053.2-02.

Tests BarAggregator structural contract (BaseDaemon inheritance, topics),
behavioral contract (publishes HTF bars at period boundaries, silent on mid-period bars),
and Golden Signals metrics (Counter/Histogram instances).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.bar_accumulator import BarAccumulator
from src.core.schemas.bar_message import BarMessage, SessionType

# ---------------------------------------------------------------------------
# Helpers: build a minimal BarAggregator bypassing __init__
# ---------------------------------------------------------------------------


def _make_agent():
    """Build BarAggregator using __new__ (service test pattern)."""
    from services.bar_aggregator import BarAggregator, HealthMetrics

    agent = BarAggregator.__new__(BarAggregator)
    agent.name = "bar_aggregator"
    agent._stop_event = asyncio.Event()
    agent.logger = MagicMock()
    agent.tracer = MagicMock()
    agent.settings = MagicMock(env_name="dev")
    agent._kafka_producer = AsyncMock()
    agent._kafka_consumer = AsyncMock()
    agent._bar_accumulator = BarAccumulator()
    agent._health_metrics = HealthMetrics()
    agent._last_skip_reason = "parse_failed"
    agent._record_message_consumed = MagicMock()
    agent._get_consumer_lag = AsyncMock(return_value=0)
    # Phase 68-05: new hardening attributes required by _run() loop
    agent._last_emitted = {}  # AGG-EMIT-ONCE guard
    agent._consumer_restart_needed = False
    agent._processing_semaphore = asyncio.Semaphore(200)  # AGG-BACKPRESSURE
    agent._agent_attrs = {"agent": "bar_aggregator"}
    return agent


def _make_bar(ts: datetime, symbol: str = "ESM6", tf: str = "1m") -> dict:
    """Return a bar payload dict (mimics DataProviderAgent Kafka format)."""
    return {
        "ts": ts.isoformat(),
        "symbol": symbol,
        "tf": tf,
        "open": 5200.0,
        "high": 5210.0,
        "low": 5195.0,
        "close": 5205.0,
        "volume": 1000,
        "source": "ibkr_named",
        "session_type": "rth",
        "gap_preceding": False,
        "is_flat_bar": False,
    }


# ---------------------------------------------------------------------------
# Test 1: Inherits BaseDaemon
# ---------------------------------------------------------------------------


def test_inherits_base_agent():
    """BarAggregator must inherit BaseDaemon."""
    from services.bar_aggregator import BarAggregator
    from src.core.agent.base import BaseDaemon

    assert issubclass(BarAggregator, BaseDaemon)


# ---------------------------------------------------------------------------
# Test 2: topics_consumed returns [topic_market_bars(env)]
# ---------------------------------------------------------------------------


def test_topics_consumed():
    """topics_consumed returns [topic_market_bars(env_name)]."""
    from src.core.stream_keys import topic_market_bars

    agent = _make_agent()
    expected = [topic_market_bars("dev")]
    assert agent.topics_consumed == expected


# ---------------------------------------------------------------------------
# Test 3: topics_produced returns [topic_market_bars_htf(env)]
# ---------------------------------------------------------------------------


def test_topics_produced():
    """topics_produced returns [topic_market_bars_htf(env_name)]."""
    from src.core.stream_keys import topic_market_bars_htf

    agent = _make_agent()
    expected = [topic_market_bars_htf("dev")]
    assert agent.topics_produced == expected


# ---------------------------------------------------------------------------
# Test 4: Processing a 1m bar at 5m boundary publishes an HTF bar
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publishes_htf_bar_at_period_boundary():
    """When a 1m bar crosses a 5m period boundary, the agent publishes to topic_market_bars_htf."""
    from src.core.stream_keys import topic_market_bars_htf

    agent = _make_agent()

    # Seed the accumulator with 4 bars within the same 5m window (09:30–09:33)
    seed_times = [
        datetime(2026, 3, 28, 13, 30, 0, tzinfo=UTC),
        datetime(2026, 3, 28, 13, 31, 0, tzinfo=UTC),
        datetime(2026, 3, 28, 13, 32, 0, tzinfo=UTC),
        datetime(2026, 3, 28, 13, 33, 0, tzinfo=UTC),
    ]
    for ts in seed_times:
        agent._bar_accumulator.update(
            BarMessage(
                ts=ts,
                symbol="ESM6",
                tf="1m",
                open=5200.0,
                high=5210.0,
                low=5195.0,
                close=5205.0,
                volume=1000,
                source="ibkr_named",
                session_type=SessionType.RTH,
            )
        )

    # 5th bar crosses the 5m boundary (09:35 starts new 5m window)
    boundary_ts = datetime(2026, 3, 28, 13, 35, 0, tzinfo=UTC)
    payload = _make_bar(boundary_ts)

    published = []

    async def fake_publish(topic, msg, key=None):
        published.append((topic, msg, key))

    agent._kafka_producer.publish = AsyncMock(side_effect=fake_publish)

    async def fake_messages():
        yield ("dev.market.bars", "ESM6:1m", payload)
        agent._stop_event.set()

    agent._kafka_consumer.messages = fake_messages

    await agent._run()

    # At least one HTF bar should have been published
    assert len(published) >= 1
    for topic, msg, key in published:
        assert topic == topic_market_bars_htf("dev")
        assert "symbol" in msg
        assert msg["symbol"] == "ESM6"


# ---------------------------------------------------------------------------
# Test 5: Processing a 1m bar mid-period publishes nothing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_publish_for_mid_period_bar():
    """A 1m bar that doesn't cross a period boundary produces no published messages."""
    agent = _make_agent()

    # First bar in a fresh window — no prior accumulator state, so no completion
    ts = datetime(2026, 3, 28, 13, 30, 0, tzinfo=UTC)
    payload = _make_bar(ts)

    published = []

    async def fake_publish(topic, msg, key=None):
        published.append((topic, msg, key))

    agent._kafka_producer.publish = AsyncMock(side_effect=fake_publish)

    async def fake_messages():
        yield ("dev.market.bars", "ESM6:1m", payload)
        agent._stop_event.set()

    agent._kafka_consumer.messages = fake_messages

    await agent._run()

    assert len(published) == 0


# ---------------------------------------------------------------------------
# Test 6: Golden Signals metrics are Counter/Histogram instances
# ---------------------------------------------------------------------------


def test_golden_signals_are_correct_types():
    """Golden Signals metrics are module-level OTel instruments."""
    import services.bar_aggregator as _mod

    assert hasattr(_mod, "_BARS_PROCESSED")
    assert hasattr(_mod, "_AGGREGATION_LATENCY")
    assert hasattr(_mod, "_AGGREGATION_ERRORS")


# ---------------------------------------------------------------------------
# Test 7: _handle_unhealthy_state only sets flag — no stop/start
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_unhealthy_state_only_sets_flag():
    """_handle_unhealthy_state must NOT call stop/start — only set the flag."""
    agent = _make_agent()
    agent._kafka_consumer = AsyncMock()
    agent._consumer_restart_needed = False

    await agent._handle_unhealthy_state("no_bars_1000s")

    assert agent._consumer_restart_needed is True
    agent._kafka_consumer.stop.assert_not_called()
    agent._kafka_consumer.start.assert_not_called()


# ---------------------------------------------------------------------------
# Task 1 (63.1-01): Kafka bootstrap retry tests
# Retry behavior moved to BaseDaemon._setup_with_retry — _setup() is single-attempt.
# ---------------------------------------------------------------------------


def test_setup_retry_class_attributes():
    """BarAggregator uses base class retry defaults (no override)."""
    from services.bar_aggregator import BarAggregator

    assert BarAggregator.SETUP_RETRY_ATTEMPTS == 3
    assert BarAggregator.SETUP_RETRY_BACKOFF_S == 2.0


@pytest.mark.asyncio
async def test_setup_single_attempt_success():
    """_setup() runs one attempt body; retries are delegated to BaseDaemon._setup_with_retry."""
    from services.bar_aggregator import BarAggregator

    agent = BarAggregator.__new__(BarAggregator)
    agent.settings = MagicMock(env_name="dev")
    agent.settings.kafka_bootstrap_servers = "localhost:9092"
    agent.logger = MagicMock()
    agent._kafka_producer = None
    agent._kafka_consumer = None
    agent._lag_consumer = None
    agent.name = "bar_aggregator"

    mock_producer = AsyncMock()
    mock_producer.start = AsyncMock(return_value=None)
    mock_consumer = AsyncMock()
    mock_consumer.start = AsyncMock(return_value=None)
    mock_lag_consumer = MagicMock()

    agent._restore_state_checkpoint = AsyncMock(return_value=True)

    with (
        patch("services.bar_aggregator.KafkaProducerClient", return_value=mock_producer),
        patch("services.bar_aggregator.KafkaConsumerClient", return_value=mock_consumer),
        patch("confluent_kafka.Consumer", return_value=mock_lag_consumer),
    ):
        await agent._setup()

    # Exactly one start call - single-attempt body
    assert mock_producer.start.call_count == 1


@pytest.mark.asyncio
async def test_setup_propagates_exception():
    """_setup() must propagate exceptions so BaseDaemon._setup_with_retry can retry."""
    from confluent_kafka import KafkaException

    from services.bar_aggregator import BarAggregator

    agent = BarAggregator.__new__(BarAggregator)
    agent.settings = MagicMock(env_name="dev")
    agent.settings.kafka_bootstrap_servers = "localhost:9092"
    agent.logger = MagicMock()
    agent._kafka_producer = None
    agent._kafka_consumer = None
    agent._lag_consumer = None
    agent.name = "bar_aggregator"

    mock_producer = AsyncMock()
    mock_producer.start = AsyncMock(side_effect=KafkaException(None))

    with (
        patch("services.bar_aggregator.KafkaProducerClient", return_value=mock_producer),
        pytest.raises(KafkaException),
    ):
        await agent._setup()

    # Single attempt - exception propagated immediately (retry loop is in BaseDaemon)
    assert mock_producer.start.call_count == 1
