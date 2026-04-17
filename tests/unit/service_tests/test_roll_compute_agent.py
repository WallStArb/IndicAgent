"""Unit tests for RollComputeAgent — TDD tests for Plan 053.3-03.

Tests RollComputeAgent structural contract (BaseAgent inheritance, topics),
behavioral contract (publishes RollEvent on confirmed roll, skips on no roll),
Golden Signals metrics (Counter instances), and RollMonitor cohabitation.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from prometheus_client import Counter, Histogram

# Module-level test metrics (created once to avoid duplicate registration)
_TEST_EVENTS_CONSUMED = Counter(
    "test_roll_events_consumed_total",
    "Bars consumed (test)",
    ["agent"],
)
_TEST_ROLLS_DETECTED = Counter(
    "test_roll_rolls_detected_total",
    "Roll events detected (test)",
    ["agent"],
)
_TEST_DETECTION_LATENCY = Histogram(
    "test_roll_detection_latency_seconds",
    "Roll detection latency (test)",
    ["agent"],
)
_TEST_DETECTION_ERRORS = Counter(
    "test_roll_detection_errors_total",
    "Roll detection errors (test)",
    ["agent"],
)


# ---------------------------------------------------------------------------
# Helpers: build a minimal RollComputeAgent bypassing __init__
# ---------------------------------------------------------------------------


def _make_agent():
    """Build RollComputeAgent using __new__ (service test pattern)."""
    from services.roll_compute_agent import RollComputeAgent, RollMonitor

    agent = RollComputeAgent.__new__(RollComputeAgent)
    agent.name = "roll_compute_agent"
    agent._stop_event = asyncio.Event()
    agent.logger = MagicMock()
    agent.tracer = MagicMock()
    agent.settings = MagicMock(env_name="dev")
    agent._kafka_producer = AsyncMock()
    agent._kafka_consumer = AsyncMock()
    agent._symbol_to_base = {"ESM6": "ES"}
    agent._roll_monitor = MagicMock(spec=RollMonitor)
    # Wire module-level test metrics (no duplicate registration)
    # Metrics are module-level in production; bind test-named labels for __new__ fixture
    agent._events_consumed_lbl = _TEST_EVENTS_CONSUMED.labels(agent="roll_compute_agent")
    agent._rolls_detected_lbl = _TEST_ROLLS_DETECTED.labels(agent="roll_compute_agent")
    agent._detection_latency_lbl = _TEST_DETECTION_LATENCY.labels(agent="roll_compute_agent")
    agent._detection_errors_lbl = _TEST_DETECTION_ERRORS.labels(agent="roll_compute_agent")
    return agent


# ---------------------------------------------------------------------------
# Test 1: Class structure
# ---------------------------------------------------------------------------


def test_inherits_base_agent():
    """RollComputeAgent must inherit BaseAgent."""
    from services.roll_compute_agent import RollComputeAgent
    from src.core.agent.base import BaseAgent

    assert issubclass(RollComputeAgent, BaseAgent)


def test_roll_monitor_class_exists():
    """RollMonitor class must exist in roll_compute_agent module."""
    from services.roll_compute_agent import RollMonitor

    assert RollMonitor is not None


def test_no_on_roll_confirmed_on_agent():
    """_on_roll_confirmed must NOT exist on RollComputeAgent (DB writes dropped)."""
    from services.roll_compute_agent import RollComputeAgent

    assert not hasattr(RollComputeAgent, "_on_roll_confirmed")


# ---------------------------------------------------------------------------
# Test 2: Topic manifest
# ---------------------------------------------------------------------------


def test_topics_consumed():
    """topics_consumed returns [topic_market_bars(env_name)]."""
    from src.core.stream_keys import topic_market_bars

    agent = _make_agent()
    expected = [topic_market_bars("dev")]
    assert agent.topics_consumed == expected


def test_topics_produced():
    """topics_produced returns [topic_roll_events(env_name)]."""
    from src.core.stream_keys import topic_roll_events

    agent = _make_agent()
    expected = [topic_roll_events("dev")]
    assert agent.topics_produced == expected


# ---------------------------------------------------------------------------
# Test 3: RollEvent published on confirmed roll
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publishes_roll_event_on_confirmed_roll():
    """When check_roll returns True, agent publishes a RollEvent with volume_zscore > 0."""

    from src.core.stream_keys import topic_roll_events

    agent = _make_agent()

    # Mock roll monitor to confirm a roll
    agent._roll_monitor.update_volume = MagicMock()
    agent._roll_monitor.check_roll = MagicMock(return_value=True)
    agent._roll_monitor._last_volume_zscore = -2.5
    agent._roll_monitor._last_confirmation_count = 3

    # Capture published messages
    published = []

    async def fake_publish(topic, msg, key=None):
        published.append((topic, msg))

    agent._kafka_producer.publish = AsyncMock(side_effect=fake_publish)

    # Simulate a single bar message
    bar_ts = datetime(2026, 3, 28, 15, 0, tzinfo=UTC).isoformat()
    payload = {
        "symbol": "ESM6",
        "volume": 10000.0,
        "timestamp": bar_ts,
        "open": 5200.0,
        "high": 5210.0,
        "low": 5195.0,
        "close": 5205.0,
        "timeframe": "1m",
    }

    # Patch _kafka_consumer to yield one message then stop
    stop_after_one = True

    async def fake_messages():
        yield ("dev.market.bars", "ESM6:1m", payload)

    agent._kafka_consumer.messages = fake_messages

    # Set stop event after run starts to avoid infinite loop
    agent._stop_event.set()

    # Run the _run loop — it should process the one message and stop
    # Override stop_event to let one message through
    agent._stop_event = asyncio.Event()

    async def run_with_stop():
        # patch messages() to yield one item then set stop
        original_messages = agent._kafka_consumer.messages

        async def messages_then_stop():
            async for item in original_messages():
                yield item
            agent._stop_event.set()

        agent._kafka_consumer.messages = messages_then_stop
        await agent._run()

    await run_with_stop()

    assert len(published) == 1
    topic_published, msg_dict = published[0]
    assert topic_published == topic_roll_events("dev")
    # RollEvent fields
    assert "symbol" in msg_dict
    assert "volume_zscore" in msg_dict
    assert "confirmation_count" in msg_dict
    assert msg_dict["volume_zscore"] == -2.5
    assert msg_dict["confirmation_count"] == 3


@pytest.mark.asyncio
async def test_no_publish_when_no_roll():
    """When check_roll returns False, no message is published."""
    agent = _make_agent()

    agent._roll_monitor.update_volume = MagicMock()
    agent._roll_monitor.check_roll = MagicMock(return_value=False)
    agent._roll_monitor._last_volume_zscore = 0.5
    agent._roll_monitor._last_confirmation_count = 0

    published = []

    async def fake_publish(topic, msg, key=None):
        published.append((topic, msg))

    agent._kafka_producer.publish = AsyncMock(side_effect=fake_publish)

    bar_ts = datetime(2026, 3, 28, 15, 0, tzinfo=UTC).isoformat()
    payload = {
        "symbol": "ESM6",
        "volume": 50000.0,
        "timestamp": bar_ts,
        "open": 5200.0,
        "high": 5210.0,
        "low": 5195.0,
        "close": 5205.0,
        "timeframe": "1m",
    }

    agent._stop_event = asyncio.Event()

    async def messages_then_stop():
        yield ("dev.market.bars", "ESM6:1m", payload)
        agent._stop_event.set()

    agent._kafka_consumer.messages = messages_then_stop
    await agent._run()

    assert len(published) == 0


# ---------------------------------------------------------------------------
# Test 4: Golden Signals
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publishes_calendar_roll_event_when_scheduler_fires():
    """When CalendarRollScheduler.check_calendar_roll returns True, agent publishes
    a RollEvent with detection_method='calendar' and volume_zscore=0.0."""

    agent = _make_agent()
    agent._roll_monitor.update_volume = MagicMock()
    agent._roll_monitor.check_roll = MagicMock(return_value=False)

    # Inject a mock calendar scheduler that fires once
    from unittest.mock import MagicMock as MM
    calendar_scheduler = MM()
    calendar_scheduler.check_calendar_roll = MagicMock(return_value=True)
    agent._calendar_scheduler = calendar_scheduler

    published = []

    async def fake_publish(topic, msg, key=None):
        published.append((topic, msg))

    agent._kafka_producer.publish = AsyncMock(side_effect=fake_publish)

    bar_ts = datetime(2026, 6, 16, 14, 30, tzinfo=UTC).isoformat()
    payload = {
        "symbol": "ESM6",
        "volume": 50000.0,
        "timestamp": bar_ts,
        "open": 5200.0,
        "high": 5210.0,
        "low": 5195.0,
        "close": 5205.0,
        "timeframe": "1m",
    }

    agent._stop_event = asyncio.Event()

    async def messages_then_stop():
        yield ("dev.market.bars", "ESM6:1m", payload)
        agent._stop_event.set()

    agent._kafka_consumer.messages = messages_then_stop
    await agent._run()

    # One event published: the calendar roll
    assert len(published) == 1
    _topic, msg = published[0]
    assert msg["detection_method"] == "calendar"
    assert msg["volume_zscore"] == 0.0
    assert msg["confirmation_count"] == 0


@pytest.mark.asyncio
async def test_volume_roll_event_has_detection_method_volume():
    """Volume-detected roll event has detection_method='volume'."""

    agent = _make_agent()
    agent._roll_monitor.update_volume = MagicMock()
    agent._roll_monitor.check_roll = MagicMock(return_value=True)
    agent._roll_monitor._last_volume_zscore = -2.8
    agent._roll_monitor._last_confirmation_count = 3

    from unittest.mock import MagicMock as MM
    calendar_scheduler = MM()
    calendar_scheduler.check_calendar_roll = MagicMock(return_value=False)
    agent._calendar_scheduler = calendar_scheduler

    published = []

    async def fake_publish(topic, msg, key=None):
        published.append((topic, msg))

    agent._kafka_producer.publish = AsyncMock(side_effect=fake_publish)

    bar_ts = datetime(2026, 6, 14, 14, 30, tzinfo=UTC).isoformat()
    payload = {
        "symbol": "ESM6",
        "volume": 1000.0,
        "timestamp": bar_ts,
        "open": 5200.0,
        "high": 5210.0,
        "low": 5195.0,
        "close": 5205.0,
        "timeframe": "1m",
    }

    agent._stop_event = asyncio.Event()

    async def messages_then_stop():
        yield ("dev.market.bars", "ESM6:1m", payload)
        agent._stop_event.set()

    agent._kafka_consumer.messages = messages_then_stop
    await agent._run()

    assert len(published) == 1
    _topic, msg = published[0]
    assert msg["detection_method"] == "volume"


def test_golden_signals_are_counter_instances():
    """events_consumed_total and rolls_detected_total must be Counter instances."""
    from prometheus_client import Counter

    from services.roll_compute_agent import _DETECTION_ERRORS, _EVENTS_CONSUMED, _ROLLS_DETECTED

    assert isinstance(_EVENTS_CONSUMED, Counter)
    assert isinstance(_ROLLS_DETECTED, Counter)
    assert isinstance(_DETECTION_ERRORS, Counter)


# ---------------------------------------------------------------------------
# Test 5: RollMonitor preserves PAPER_SKIP_CONTRACTS and PAPER_ACCOUNT_HOSTS
# ---------------------------------------------------------------------------


def test_paper_skip_contracts_accessible():
    """PAPER_SKIP_CONTRACTS class attribute must exist on RollMonitor."""
    from services.roll_compute_agent import RollMonitor

    assert hasattr(RollMonitor, "PAPER_SKIP_CONTRACTS")
    assert isinstance(RollMonitor.PAPER_SKIP_CONTRACTS, set)


def test_paper_account_hosts_accessible():
    """PAPER_ACCOUNT_HOSTS class attribute must exist on RollMonitor."""
    from services.roll_compute_agent import RollMonitor

    assert hasattr(RollMonitor, "PAPER_ACCOUNT_HOSTS")
    assert isinstance(RollMonitor.PAPER_ACCOUNT_HOSTS, set)


# ---------------------------------------------------------------------------
# Test 6: RollMonitor volume_zscore and confirmation_count capture
# ---------------------------------------------------------------------------


def test_roll_monitor_captures_zscore_before_reset():
    """RollMonitor._last_volume_zscore and _last_confirmation_count exist after init."""
    from unittest.mock import MagicMock

    from services.roll_compute_agent import RollMonitor

    s = MagicMock()
    s.ib_host = "192.168.1.158"
    s.roll_monitor_window_size = 100
    s.roll_monitor_threshold_default = 1.2
    s.roll_confirmation_bars = 3
    s.roll_monitor_cooldown_min = 30
    s.roll_monitor_postroll_bars = 10
    s.roll_time_of_day_gated = False

    rm = RollMonitor(s)
    assert hasattr(rm, "_last_volume_zscore")
    assert hasattr(rm, "_last_confirmation_count")
    assert isinstance(rm._last_volume_zscore, float)
    assert isinstance(rm._last_confirmation_count, int)
