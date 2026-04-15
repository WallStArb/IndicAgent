"""Unit tests for AINarrativeComputeAgent.

Uses __new__ pattern to bypass __init__ (per CLAUDE.md service test pattern).
"""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest


def _make_agent():
    """Create agent via __new__ to bypass __init__."""
    from services.ai_narrative_agent import AINarrativeComputeAgent
    agent = AINarrativeComputeAgent.__new__(AINarrativeComputeAgent)
    agent._orchestrator = MagicMock()
    agent._producer = MagicMock()
    agent.settings = MagicMock(env_name="test")
    agent.logger = MagicMock()
    return agent


def _make_record(direction: int = 1, symbol: str = "ESM6"):
    from src.intelligence.schemas import BarIntelligenceRecord, IntelligenceEvent
    intel = MagicMock(spec=IntelligenceEvent)
    intel.symbol = symbol
    intel.tf = "1m"
    intel.ts = datetime.now(UTC)

    record = MagicMock(spec=BarIntelligenceRecord)
    record.intelligence = intel
    record.winner_direction = direction
    record.winner_confidence = 0.80
    record.winner_plugin = "TrendFollowing"
    record.record_id = str(uuid4())
    return record


@pytest.mark.asyncio
async def test_process_bar_publishes_narrative_on_success():
    agent = _make_agent()
    record = _make_record()
    agent._orchestrator.generate = AsyncMock(return_value="Bullish breakout above 5280.")
    agent._producer.publish = AsyncMock()

    await agent._process_bar(record)

    agent._producer.publish.assert_awaited_once()
    call_args = agent._producer.publish.call_args
    payload = call_args[0][1]
    assert payload["narrative"] == "Bullish breakout above 5280."
    assert payload["symbol"] == "ESM6"


@pytest.mark.asyncio
async def test_process_bar_skips_when_orchestrator_returns_none():
    agent = _make_agent()
    record = _make_record(direction=0)
    agent._orchestrator.generate = AsyncMock(return_value=None)
    agent._producer.publish = AsyncMock()

    await agent._process_bar(record)

    agent._producer.publish.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_bar_does_not_raise_on_exception():
    agent = _make_agent()
    record = _make_record()
    agent._orchestrator.generate = AsyncMock(side_effect=RuntimeError("LLM exploded"))
    agent._producer.publish = AsyncMock()

    # Should not raise — graceful handling
    await agent._process_bar(record)
    agent._producer.publish.assert_not_awaited()
