"""Unit tests for ProviderMergerAgent — TDD tests for Plan 54-04.

Tests ProviderMergerAgent structural contract (BaseAgent inheritance, consumer group),
routing contract (authoritative -> market.bars, non-authoritative dropped),
quality event contract (ProviderQualityEvent published per bar),
and failover/recovery contract (primary silence -> promote secondary).
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from prometheus_client import Counter, Histogram

from src.core.schemas.bar_message import BarMessage, SessionType

# ---------------------------------------------------------------------------
# Module-level test metrics (created once to avoid duplicate registration)
# ---------------------------------------------------------------------------

_TEST_MERGER_ROUTED = Counter(
    "test_merger_bars_routed_total",
    "Bars routed (test)",
    ["provider"],
)
_TEST_MERGER_DROPPED = Counter(
    "test_merger_bars_dropped_total",
    "Bars dropped (test)",
    ["provider"],
)
_TEST_MERGER_LATENCY = Histogram(
    "test_merger_bar_latency_seconds",
    "Bar latency (test)",
    ["provider"],
)


# ---------------------------------------------------------------------------
# Helpers: build a minimal ProviderMergerAgent bypassing __init__
# ---------------------------------------------------------------------------

_SOURCE_IBKR_GENERIC = "ibkr"


def _make_bar(
    symbol: str = "ESM6",
    tf: str = "1m",
    ts: datetime | None = None,
) -> BarMessage:
    """Build a BarMessage with a UTC-aware timestamp."""
    if ts is None:
        ts = datetime(2026, 3, 28, 14, 30, tzinfo=UTC)
    return BarMessage(
        ts=ts,
        symbol=symbol,
        tf=tf,
        open=5000.0,
        high=5010.0,
        low=4990.0,
        close=5005.0,
        volume=100,
        source=_SOURCE_IBKR_GENERIC,
        session_type=SessionType.RTH,
    )


def _make_agent(
    provider_raw_topics: list[str] | None = None,
    provider_routing_config: dict[str, str] | None = None,
    provider_silence_bars_threshold: int = 5,
):
    """Build ProviderMergerAgent using __new__ (service test pattern)."""
    from services.provider_merger_agent import ProviderMergerAgent

    agent = ProviderMergerAgent.__new__(ProviderMergerAgent)
    agent.name = "provider_merger_agent"
    agent._stop_event = asyncio.Event()
    agent.logger = MagicMock()
    agent.tracer = MagicMock()
    agent._env_name = "dev"
    agent._kafka_producer = AsyncMock()
    agent._kafka_consumer = AsyncMock()
    # Failover state
    agent._promoted: dict[str, str] = {}
    agent._last_bar_ts: defaultdict[str, dict[str, datetime]] = defaultdict(dict)
    # Settings config
    agent._provider_raw_topics = provider_raw_topics or ["ibkr"]
    agent._provider_routing_config = provider_routing_config or {
        "futures": "ibkr",
        "equity": "ibkr",
        "crypto": "ibkr",
        "fx": "ibkr",
    }
    agent._provider_silence_bars_threshold = provider_silence_bars_threshold
    # Topic -> provider cache (mirrors __init__ pattern)
    from src.core.stream_keys import topic_market_bars_raw
    agent._topic_to_provider = {
        topic_market_bars_raw("dev", p): p for p in (provider_raw_topics or ["ibkr"])
    }
    # Instrument lookup: symbol -> asset_class string
    agent._symbol_to_asset_class: dict[str, str] = {
        "ESM6": "futures",
        "NQM6": "futures",
    }
    # Pre-cache labeled metric children (mirrors __init__ pattern)
    all_providers = provider_raw_topics or ["ibkr"]
    agent._routed_lbl = {
        p: _TEST_MERGER_ROUTED.labels(provider=p) for p in all_providers
    }
    agent._dropped_lbl = {
        p: _TEST_MERGER_DROPPED.labels(provider=p) for p in all_providers
    }
    agent._latency_lbl = {
        p: _TEST_MERGER_LATENCY.labels(provider=p) for p in all_providers
    }
    return agent


# ---------------------------------------------------------------------------
# Structural contract
# ---------------------------------------------------------------------------


def test_inherits_base_agent() -> None:
    """ProviderMergerAgent must be a BaseAgent subclass."""
    from services.provider_merger_agent import ProviderMergerAgent
    from src.core.agent.base import BaseAgent

    assert issubclass(ProviderMergerAgent, BaseAgent)


# ---------------------------------------------------------------------------
# Routing: authoritative bar -> market.bars
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_routes_authoritative_bar_to_market_bars() -> None:
    """Bar from authoritative provider must be published to topic_market_bars."""
    from src.core.stream_keys import topic_market_bars, topic_market_bars_raw

    agent = _make_agent()
    bar = _make_bar()
    topic = topic_market_bars_raw("dev", "ibkr")

    await agent._handle_bar(topic, bar)

    # Producer must have published to market.bars
    calls = agent._kafka_producer.publish.call_args_list
    published_topics = [c.args[0] for c in calls if c.args]
    assert topic_market_bars("dev") in published_topics


# ---------------------------------------------------------------------------
# Routing: non-authoritative bar -> dropped
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_drops_non_authoritative_bar() -> None:
    """Bar from non-authoritative provider must NOT be published to market.bars."""
    from src.core.stream_keys import topic_market_bars, topic_market_bars_raw

    # Configure routing: futures authoritative is ibkr, but bar comes from alpaca
    agent = _make_agent(
        provider_raw_topics=["ibkr", "alpaca"],
        provider_routing_config={
            "futures": "ibkr",
            "equity": "ibkr",
            "crypto": "ibkr",
            "fx": "ibkr",
        },
    )
    bar = _make_bar()
    alpaca_topic = topic_market_bars_raw("dev", "alpaca")

    # Track dropped counter via agent method
    await agent._handle_bar(alpaca_topic, bar)

    # Producer must NOT have published to market.bars
    calls = agent._kafka_producer.publish.call_args_list
    published_topics = [c.args[0] for c in calls if c.args]
    assert topic_market_bars("dev") not in published_topics


# ---------------------------------------------------------------------------
# Source field preserved
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_preserves_bar_message_source() -> None:
    """Bar forwarded to market.bars must have source field unchanged."""
    from src.core.stream_keys import topic_market_bars, topic_market_bars_raw

    agent = _make_agent()
    bar = _make_bar()
    topic = topic_market_bars_raw("dev", "ibkr")

    await agent._handle_bar(topic, bar)

    # Find the market.bars publish call
    calls = agent._kafka_producer.publish.call_args_list
    market_bars_calls = [
        c for c in calls if c.args and c.args[0] == topic_market_bars("dev")
    ]
    assert len(market_bars_calls) == 1
    published_payload = market_bars_calls[0].args[1]
    assert published_payload["source"] == _SOURCE_IBKR_GENERIC


# ---------------------------------------------------------------------------
# Quality event published on routed bar
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publishes_quality_event_on_routed_bar() -> None:
    """After routing a bar, a ProviderQualityEvent with event_type='bar_received' must be published."""
    from src.core.stream_keys import topic_market_bars_raw, topic_market_data_quality

    agent = _make_agent()
    bar = _make_bar()
    topic = topic_market_bars_raw("dev", "ibkr")

    await agent._handle_bar(topic, bar)

    # Find the quality event publish call
    calls = agent._kafka_producer.publish.call_args_list
    quality_calls = [
        c for c in calls if c.args and c.args[0] == topic_market_data_quality("dev")
    ]
    assert len(quality_calls) >= 1
    quality_payload = quality_calls[0].args[1]
    assert quality_payload["event_type"] == "bar_received"


# ---------------------------------------------------------------------------
# Latency is positive
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_latency_ms_positive() -> None:
    """Quality event latency_ms must be >= 0."""
    from src.core.stream_keys import topic_market_bars_raw, topic_market_data_quality

    agent = _make_agent()
    bar = _make_bar()
    topic = topic_market_bars_raw("dev", "ibkr")

    await agent._handle_bar(topic, bar)

    calls = agent._kafka_producer.publish.call_args_list
    quality_calls = [
        c for c in calls if c.args and c.args[0] == topic_market_data_quality("dev")
    ]
    assert len(quality_calls) >= 1
    quality_payload = quality_calls[0].args[1]
    assert quality_payload["latency_ms"] >= 0


# ---------------------------------------------------------------------------
# Failover: primary silence -> promote secondary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detects_primary_silence_promotes_secondary() -> None:
    """Primary silent for N bars while secondary has data -> _promoted[symbol]=secondary; failover quality event."""
    from src.core.stream_keys import topic_market_bars_raw, topic_market_data_quality

    agent = _make_agent(
        provider_raw_topics=["ibkr", "alpaca"],
        provider_routing_config={"futures": "ibkr", "equity": "ibkr", "crypto": "ibkr", "fx": "ibkr"},
        provider_silence_bars_threshold=2,
    )

    # Simulate primary (ibkr) was last seen 3 bar-intervals ago (silence > threshold=2)
    stale_ts = datetime.now(UTC) - timedelta(seconds=3 * 60)  # 3 minutes ago for 1m bars
    agent._last_bar_ts = defaultdict(dict, {"ibkr": {"ESM6": stale_ts}})

    # Secondary (alpaca) sends a bar
    bar = _make_bar()
    alpaca_topic = topic_market_bars_raw("dev", "alpaca")

    await agent._handle_bar(alpaca_topic, bar)

    # _promoted must now be set for the symbol
    assert agent._promoted.get("ESM6") == "alpaca"

    # A failover quality event must have been published
    calls = agent._kafka_producer.publish.call_args_list
    quality_calls = [
        c for c in calls if c.args and c.args[0] == topic_market_data_quality("dev")
    ]
    failover_events = [
        c for c in quality_calls if c.args[1].get("event_type") == "failover"
    ]
    assert len(failover_events) >= 1
    assert failover_events[0].args[1]["promoted_provider"] == "alpaca"


# ---------------------------------------------------------------------------
# Recovery: primary resumes after failover
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recovery_after_failover() -> None:
    """After failover, primary resumes -> recovery quality event; _promoted cleared."""
    from src.core.stream_keys import topic_market_bars_raw, topic_market_data_quality

    agent = _make_agent(
        provider_raw_topics=["ibkr", "alpaca"],
        provider_routing_config={"futures": "ibkr", "equity": "ibkr", "crypto": "ibkr", "fx": "ibkr"},
    )
    # Pre-set failover state: ESM6 is promoted to alpaca
    agent._promoted = {"ESM6": "alpaca"}

    # Primary (ibkr) resumes
    bar = _make_bar()
    ibkr_topic = topic_market_bars_raw("dev", "ibkr")

    await agent._handle_bar(ibkr_topic, bar)

    # _promoted must be cleared
    assert "ESM6" not in agent._promoted

    # A recovery quality event must have been published
    calls = agent._kafka_producer.publish.call_args_list
    quality_calls = [
        c for c in calls if c.args and c.args[0] == topic_market_data_quality("dev")
    ]
    recovery_events = [
        c for c in quality_calls if c.args[1].get("event_type") == "recovery"
    ]
    assert len(recovery_events) >= 1


# ---------------------------------------------------------------------------
# Topic subscription
# ---------------------------------------------------------------------------


def test_subscribes_to_all_configured_raw_topics() -> None:
    """With provider_raw_topics=['ibkr'], topics_consumed includes topic_market_bars_raw(env, 'ibkr')."""
    from src.core.stream_keys import topic_market_bars_raw

    agent = _make_agent(provider_raw_topics=["ibkr"])

    assert topic_market_bars_raw("dev", "ibkr") in agent.topics_consumed


# ---------------------------------------------------------------------------
# Consumer group name
# ---------------------------------------------------------------------------


def test_consumer_group_name() -> None:
    """Consumer group must be 'provider_merger_consumer'."""

    agent = _make_agent()
    assert agent.consumer_group == "provider_merger_consumer"


# ---------------------------------------------------------------------------
# Provider extraction from topic name
# ---------------------------------------------------------------------------


def test_routing_extracts_provider_from_topic() -> None:
    """Topic 'dev.market.bars.raw.ibkr' -> extracted provider is 'ibkr'."""

    agent = _make_agent()
    provider = agent._extract_provider_from_topic("dev.market.bars.raw.ibkr")
    assert provider == "ibkr"
