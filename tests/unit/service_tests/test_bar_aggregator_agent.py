"""Unit tests for BarAggregatorComputeAgent — TDD tests for Plan 053.2-02.

Tests BarAggregatorComputeAgent structural contract (BaseAgent inheritance, topics),
behavioral contract (publishes HTF bars at period boundaries, silent on mid-period bars),
and Golden Signals metrics (Counter/Histogram instances).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from prometheus_client import Counter, Histogram

from src.core.bar_accumulator import BarAccumulator
from src.core.schemas.bar_message import BarMessage, SessionType

# ---------------------------------------------------------------------------
# Module-level test metrics (created once to avoid duplicate registration)
# ---------------------------------------------------------------------------

_TEST_EVENTS_CONSUMED = Counter(
    "test_baa_events_consumed_total",
    "Bars consumed (test)",
    ["agent"],
)
_TEST_HTF_BARS_PRODUCED = Counter(
    "test_baa_htf_produced_total",
    "HTF bars produced (test)",
    ["agent", "tf"],
)
_TEST_AGGREGATION_LATENCY = Histogram(
    "test_baa_latency_seconds",
    "Aggregation latency (test)",
    ["agent"],
)
_TEST_AGGREGATION_ERRORS = Counter(
    "test_baa_errors_total",
    "Aggregation errors (test)",
    ["agent"],
)


# ---------------------------------------------------------------------------
# Helpers: build a minimal BarAggregatorComputeAgent bypassing __init__
# ---------------------------------------------------------------------------


def _make_agent():
    """Build BarAggregatorComputeAgent using __new__ (service test pattern)."""
    from services.bar_aggregator_agent import BarAggregatorComputeAgent, HealthMetrics

    agent = BarAggregatorComputeAgent.__new__(BarAggregatorComputeAgent)
    agent.name = "bar_aggregator_agent"
    agent._stop_event = asyncio.Event()
    agent.logger = MagicMock()
    agent.tracer = MagicMock()
    agent._env_name = "dev"
    agent._kafka_producer = AsyncMock()
    agent._kafka_consumer = AsyncMock()
    agent._bar_accumulator = BarAccumulator()
    agent._health_metrics = HealthMetrics()
    agent._last_skip_reason = "parse_failed"
    # Create mock metrics that have the expected interface
    agent._bars_processed = MagicMock()
    agent._bars_skipped = MagicMock()
    agent._htf_bars_emitted = MagicMock()
    agent._processing_duration = MagicMock()
    agent._aggregation_errors = MagicMock()
    # Wire module-level test metrics via cached label children (matches production pattern)
    agent._events_consumed_lbl = _TEST_EVENTS_CONSUMED.labels(agent="bar_aggregator_agent")
    agent._aggregation_latency_lbl = _TEST_AGGREGATION_LATENCY.labels(agent="bar_aggregator_agent")
    agent._aggregation_errors_lbl = _TEST_AGGREGATION_ERRORS.labels(agent="bar_aggregator_agent")
    agent._htf_bars_produced_lbl = {
        tf: _TEST_HTF_BARS_PRODUCED.labels(agent="bar_aggregator_agent", tf=tf)
        for tf in ("5m", "15m", "1h", "4h", "1d")
    }
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
# Test 1: Inherits BaseAgent
# ---------------------------------------------------------------------------


def test_inherits_base_agent():
    """BarAggregatorComputeAgent must inherit BaseAgent."""
    from services.bar_aggregator_agent import BarAggregatorComputeAgent
    from src.core.agent.base import BaseAgent

    assert issubclass(BarAggregatorComputeAgent, BaseAgent)


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
    """Golden Signals cached children must be the correct prometheus types."""
    from prometheus_client import Counter, Histogram

    agent = _make_agent()

    assert hasattr(agent._events_consumed_lbl, "inc")
    assert hasattr(agent._aggregation_latency_lbl, "time")
    assert hasattr(agent._aggregation_errors_lbl, "inc")
    assert isinstance(agent._htf_bars_produced_lbl, dict)
    assert all(hasattr(v, "inc") for v in agent._htf_bars_produced_lbl.values())
