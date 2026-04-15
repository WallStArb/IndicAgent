"""Unit tests for SwarmOrchestratorComputeAgent. Uses __new__ pattern."""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest


def _make_agent():
    from services.swarm_orchestrator_agent import SwarmOrchestratorComputeAgent
    from src.intelligence.swarm.aggregator import SwarmAggregator
    from src.intelligence.swarm.context import SwarmContextCache

    agent = SwarmOrchestratorComputeAgent.__new__(SwarmOrchestratorComputeAgent)
    agent._context_cache = SwarmContextCache()
    agent._contributors = []
    agent._aggregator = SwarmAggregator()
    agent._producer = MagicMock()
    agent._producer.publish = AsyncMock()
    agent.settings = MagicMock(env_name="test")
    agent.logger = MagicMock()
    return agent


@pytest.mark.asyncio
async def test_bar_loop_updates_context_cache():
    agent = _make_agent()
    from src.intelligence.schemas import IntelligenceEvent

    event = MagicMock(spec=IntelligenceEvent)
    event.symbol = "ESM6"
    event.tf = "1m"
    event.ts = datetime.now(UTC)
    event.bar = MagicMock()
    event.i1 = MagicMock()
    event.i4 = MagicMock()
    event.i6 = MagicMock()

    await agent._handle_bar(event)

    # Cache should now have an entry for (ESM6, 1m)
    # Pass a signal mock with a real plugin string — SwarmContext.winner_plugin is str | None
    from src.intelligence.schemas import RankedSignal

    sig = MagicMock(spec=RankedSignal)
    sig.plugin = "TrendFollowing"
    sig.direction = 1
    sig.calibrated_confidence = 0.8
    ctx = agent._context_cache.build("ESM6", "1m", sig, uuid4())
    assert ctx is not None


@pytest.mark.asyncio
async def test_signal_loop_publishes_to_dlq_when_no_context():
    agent = _make_agent()
    from src.intelligence.schemas import RankedSignal

    signal = MagicMock(spec=RankedSignal)
    signal.signal_id = str(uuid4())
    signal.plugin = "TrendFollowing"
    signal.calibrated_confidence = 0.8
    signal.is_winner = True

    # No context cached → DLQ
    await agent._handle_signal(signal, symbol="UNKNOWN", tf="1m")

    agent._producer.publish.assert_awaited_once()
    dlq_topic = agent._producer.publish.call_args[0][0]
    assert "dlq" in dlq_topic


@pytest.mark.asyncio
async def test_signal_loop_runs_zero_contributors_returns_neutral():
    agent = _make_agent()
    from src.intelligence.schemas import IntelligenceEvent, RankedSignal

    event = MagicMock(spec=IntelligenceEvent)
    event.symbol = "ESM6"
    event.tf = "1m"
    event.ts = datetime.now(UTC)
    event.bar = MagicMock()
    event.bar.close = 5280.0
    event.bar.volume = 10000.0
    event.i1 = MagicMock()
    event.i4 = MagicMock()
    event.i4.hmm_regime = 1
    event.i6 = MagicMock()

    await agent._handle_bar(event)

    signal = MagicMock(spec=RankedSignal)
    signal.signal_id = str(uuid4())
    signal.plugin = "TrendFollowing"
    signal.calibrated_confidence = 0.8
    signal.is_winner = True
    signal.direction = 1

    await agent._handle_signal(signal, symbol="ESM6", tf="1m")

    # With 0 contributors, should publish neutral AlphaMultiplier (not DLQ)
    agent._producer.publish.assert_awaited()
    published_topic = agent._producer.publish.call_args[0][0]
    assert "dlq" not in published_topic
