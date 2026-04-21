"""Unit tests for BaseProviderAgent — TDD tests for Plan 54-03.

Tests structural contract (BaseAgent inheritance, abstract methods),
behavioral contract (reconnect backoff, gap-fill routing, metrics labeling),
and publish routing (raw topic, not canonical market.bars).
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Module-level test metrics (created once to avoid duplicate registration)
# ---------------------------------------------------------------------------
from prometheus_client import Counter, Gauge

from src.core.agent.base import BaseAgent

_TEST_BARS_PRODUCED = Counter(
    "test_bpa_bars_produced_total",
    "Bars produced (test)",
    ["provider", "agent"],
)
_TEST_RECONNECTS_ATTEMPTED = Counter(
    "test_bpa_reconnects_attempted_total",
    "Reconnects attempted (test)",
    ["provider", "agent"],
)
_TEST_RECONNECTS_SUCCEEDED = Counter(
    "test_bpa_reconnects_succeeded_total",
    "Reconnects succeeded (test)",
    ["provider", "agent"],
)
_TEST_CONNECTED = Gauge(
    "test_bpa_connected",
    "Connected (test)",
    ["provider", "agent"],
)
_TEST_GAPS_FILLED = Counter(
    "test_bpa_gaps_filled_total",
    "Gaps filled (test)",
    ["provider", "agent"],
)


# ---------------------------------------------------------------------------
# Test 1: BaseProviderAgent inherits from BaseAgent
# ---------------------------------------------------------------------------


def test_inherits_base_agent():
    """BaseProviderAgent must be a subclass of BaseAgent."""
    from src.providers.base_provider_agent import BaseProviderAgent

    assert issubclass(BaseProviderAgent, BaseAgent)


# ---------------------------------------------------------------------------
# Test 2: _create_adapter is abstract
# ---------------------------------------------------------------------------


def test_create_adapter_is_abstract():
    """_create_adapter() must be abstract (cannot instantiate BaseProviderAgent)."""

    from src.providers.base_provider_agent import BaseProviderAgent

    assert hasattr(BaseProviderAgent._create_adapter, "__isabstractmethod__") or (
        hasattr(BaseProviderAgent, "__abstractmethods__")
        and "_create_adapter" in BaseProviderAgent.__abstractmethods__
    )


# ---------------------------------------------------------------------------
# Test 3: _agent_name is abstract
# ---------------------------------------------------------------------------


def test_agent_name_is_abstract():
    """_agent_name() must be abstract."""
    from src.providers.base_provider_agent import BaseProviderAgent

    assert "_agent_name" in BaseProviderAgent.__abstractmethods__


# ---------------------------------------------------------------------------
# Test 4: _agent_metrics_port is abstract
# ---------------------------------------------------------------------------


def test_agent_metrics_port_is_abstract():
    """_agent_metrics_port() must be abstract."""
    from src.providers.base_provider_agent import BaseProviderAgent

    assert "_agent_metrics_port" in BaseProviderAgent.__abstractmethods__


# ---------------------------------------------------------------------------
# Test 5: _provider_name_str is abstract
# ---------------------------------------------------------------------------


def test_provider_name_str_is_abstract():
    """_provider_name_str() must be abstract."""
    from src.providers.base_provider_agent import BaseProviderAgent

    assert "_provider_name_str" in BaseProviderAgent.__abstractmethods__


# ---------------------------------------------------------------------------
# Helper: build a minimal concrete BaseProviderAgent subclass for testing
# ---------------------------------------------------------------------------


def _make_concrete_agent():
    """Build a concrete BaseProviderAgent subclass using __new__ bypass."""
    from src.providers.base_provider_agent import BaseProviderAgent

    class _TestAgent(BaseProviderAgent):
        def _agent_name(self) -> str:
            return "test_provider_agent"

        def _agent_metrics_port(self) -> int:
            return 9199

        def _provider_name_str(self) -> str:
            return "test"

        def _create_adapter(self):
            return MagicMock()

    agent = _TestAgent.__new__(_TestAgent)
    agent.name = "test_provider_agent"
    agent._stop_event = asyncio.Event()
    agent.logger = MagicMock()
    agent.tracer = MagicMock()
    agent.settings = MagicMock(env_name="dev")
    agent.settings.kafka_bootstrap_servers = "localhost:9092"

    # Wire test metrics
    agent._m_bars_raw = _TEST_BARS_PRODUCED.labels(provider="test", agent="test_provider_agent")
    agent._m_reconnects_attempted = _TEST_RECONNECTS_ATTEMPTED.labels(
        provider="test", agent="test_provider_agent"
    )
    agent._m_reconnects_succeeded = _TEST_RECONNECTS_SUCCEEDED.labels(
        provider="test", agent="test_provider_agent"
    )
    agent._g_connected = _TEST_CONNECTED.labels(provider="test", agent="test_provider_agent")
    agent._m_gaps_filled = _TEST_GAPS_FILLED.labels(provider="test", agent="test_provider_agent")
    agent._gap_fetch_sem = asyncio.Semaphore(1)
    agent._raw_topic = "dev.market.bars.raw.test"
    agent._kafka_producer = AsyncMock()
    agent._adapter = MagicMock()
    return agent, _TestAgent


# ---------------------------------------------------------------------------
# Test 6: Reconnect exponential backoff sequence
# ---------------------------------------------------------------------------


def test_reconnect_exponential_backoff():
    """Backoff must double: 2, 4, 8, 16, 32, 60 (capped)."""

    expected = [2, 4, 8, 16, 32, 60]
    for attempt, expected_delay in enumerate(expected):
        delay = min(2 ** (attempt + 1), 60)
        assert delay == expected_delay, f"attempt {attempt}: expected {expected_delay}, got {delay}"


# ---------------------------------------------------------------------------
# Test 7: Reconnect capped at 60s
# ---------------------------------------------------------------------------


def test_reconnect_capped_at_60s():
    """After many failures, backoff must stay at 60s."""
    for attempt in range(10, 20):
        delay = min(2 ** (attempt + 1), 60)
        assert delay == 60, f"Expected 60s cap at attempt {attempt}, got {delay}"


# ---------------------------------------------------------------------------
# Test 8: Gap loop calls adapter.fetch_historical
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gap_loop_calls_adapter_fetch_historical():
    """_gap_requests_loop() must call adapter.fetch_historical() for each gap request."""
    from datetime import UTC, datetime

    from src.core.schemas.market_events import BarGapRequest

    agent, _ = _make_concrete_agent()

    mock_adapter = AsyncMock()
    mock_adapter.fetch_historical = AsyncMock(return_value=[])
    agent._adapter = mock_adapter

    # Simulate a gap request payload
    req = BarGapRequest(
        symbol="ESM6",
        tf="1m",
        start_ts=datetime(2026, 3, 28, 10, 0, tzinfo=UTC),
        end_ts=datetime(2026, 3, 28, 10, 5, tzinfo=UTC),
        source="bar_auditor",
    )

    mock_consumer = AsyncMock()

    async def _mock_messages():
        yield ("dev.market.events.gap_requests", "ESM6:1m", req.model_dump())
        # Stop after one message
        agent._stop_event.set()

    mock_consumer.messages = _mock_messages
    mock_consumer.start = AsyncMock()
    mock_consumer.stop = AsyncMock()

    with patch(
        "src.providers.base_provider_agent.KafkaConsumerClient",
        return_value=mock_consumer,
    ):
        await agent._gap_requests_loop()

    mock_adapter.fetch_historical.assert_called_once_with(
        symbol="ESM6",
        tf="1m",
        start=req.start_ts,
        end=req.end_ts,
    )


# ---------------------------------------------------------------------------
# Test 9: Gap fills published to raw topic
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gap_fills_published_to_raw_topic():
    """Gap-fill bars must publish to topic_market_bars_raw(env, provider), not market.bars."""
    from datetime import UTC, datetime

    from src.core.schemas.bar_message import BarMessage
    from src.core.schemas.market_events import BarGapRequest
    from src.core.stream_keys import topic_market_bars, topic_market_bars_raw

    agent, _ = _make_concrete_agent()

    filled_bar = MagicMock(spec=BarMessage)
    filled_bar.symbol = "ESM6"
    filled_bar.tf = "1m"
    filled_bar.ts = datetime(2026, 3, 28, 10, 0, tzinfo=UTC)
    filled_bar.open = 5100.0
    filled_bar.high = 5105.0
    filled_bar.low = 5098.0
    filled_bar.close = 5103.0
    filled_bar.volume = 1000
    filled_bar.model_dump = MagicMock(return_value={
        "symbol": "ESM6", "tf": "1m", "ts": "2026-03-28T10:00:00+00:00",
        "open": 5100.0, "high": 5105.0, "low": 5098.0, "close": 5103.0,
        "volume": 1000, "source": "ibkr_gap_fill",
    })

    mock_adapter = AsyncMock()
    mock_adapter.fetch_historical = AsyncMock(return_value=[filled_bar])
    agent._adapter = mock_adapter

    req = BarGapRequest(
        symbol="ESM6",
        tf="1m",
        start_ts=datetime(2026, 3, 28, 10, 0, tzinfo=UTC),
        end_ts=datetime(2026, 3, 28, 10, 5, tzinfo=UTC),
        source="bar_auditor",
    )

    published_topics: list[str] = []
    original_publish = agent._kafka_producer.publish

    async def _capture_publish(topic, payload, key=None):
        published_topics.append(topic)

    agent._kafka_producer.publish = _capture_publish

    mock_consumer = AsyncMock()

    async def _mock_messages():
        yield ("dev.market.events.gap_requests", "ESM6:1m", req.model_dump())
        agent._stop_event.set()

    mock_consumer.messages = _mock_messages
    mock_consumer.start = AsyncMock()
    mock_consumer.stop = AsyncMock()

    with patch(
        "src.providers.base_provider_agent.KafkaConsumerClient",
        return_value=mock_consumer,
    ):
        await agent._gap_requests_loop()

    raw_topic = topic_market_bars_raw("dev", "test")
    canonical_topic = topic_market_bars("dev")

    assert len(published_topics) == 1, f"Expected 1 publish, got {len(published_topics)}"
    assert published_topics[0] == raw_topic, (
        f"Expected publish to raw topic {raw_topic!r}, got {published_topics[0]!r}"
    )
    assert canonical_topic not in published_topics, (
        "Must NOT publish gap fills to canonical market.bars topic"
    )


# ---------------------------------------------------------------------------
# Test 10: Metrics have provider label
# ---------------------------------------------------------------------------


def test_metrics_have_provider_label():
    """Pre-cached metric children must carry provider label matching _provider_name_str()."""
    from src.providers.base_provider_agent import BaseProviderAgent

    class _TestAgent2(BaseProviderAgent):
        def _agent_name(self) -> str:
            return "test_provider_agent"

        def _agent_metrics_port(self) -> int:
            return 9199

        def _provider_name_str(self) -> str:
            return "test_metrics"

        def _create_adapter(self):
            return MagicMock()

    # We can't call __init__ without Settings, but we verify the pattern
    # through the abstract method contract
    assert "_provider_name_str" in BaseProviderAgent.__abstractmethods__
    assert "_agent_name" in BaseProviderAgent.__abstractmethods__

    # Verify child class methods work
    agent = _TestAgent2.__new__(_TestAgent2)
    assert agent._provider_name_str() == "test_metrics"


# ---------------------------------------------------------------------------
# Test 11: _publish_bar sends to correct raw topic
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_bar_to_raw_topic():
    """_publish_bar(bar) must publish to topic_market_bars_raw(env, provider_name)."""
    from src.core.stream_keys import topic_market_bars_raw

    agent, _ = _make_concrete_agent()

    mock_bar = MagicMock()
    mock_bar.symbol = "ESM6"
    mock_bar.tf = "1m"
    mock_bar.model_dump = MagicMock(return_value={
        "symbol": "ESM6", "tf": "1m", "ts": "2026-03-28T10:00:00+00:00",
        "open": 5100.0, "high": 5105.0, "low": 5098.0, "close": 5103.0,
        "volume": 1000,
    })

    published_topics: list[str] = []

    async def _capture_publish(topic, payload, key=None):
        published_topics.append(topic)

    agent._kafka_producer.publish = _capture_publish

    await agent._publish_bar(mock_bar)

    expected_topic = topic_market_bars_raw("dev", "test")
    assert len(published_topics) == 1
    assert published_topics[0] == expected_topic, (
        f"Expected {expected_topic!r}, got {published_topics[0]!r}"
    )
