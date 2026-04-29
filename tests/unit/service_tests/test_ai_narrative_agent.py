"""Unit tests for NarrativeGroupComputeAgent._handle_trigger."""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.core.ai.output import AgentOutput


def _make_agent():
    from services.ai_narrative_agent import NarrativeGroupComputeAgent

    agent = NarrativeGroupComputeAgent.__new__(NarrativeGroupComputeAgent)
    mock_narrative_agent = MagicMock()
    mock_narrative_agent.agent_id = "narrative_v1"
    mock_narrative_agent.shadow_only = True
    mock_narrative_agent.latency_budget_ms = 5000
    mock_narrative_agent.tiers_needed = frozenset()
    agent._agents = [mock_narrative_agent]
    agent._context_cache = MagicMock()
    agent._producer = MagicMock()
    agent._publish_result = AsyncMock()
    agent.settings = MagicMock(env_name="test")
    agent.logger = MagicMock()
    return agent


def _make_event(symbol: str = "ESM6", tf: str = "1m") -> dict:
    return {
        "intelligence": {
            "symbol": symbol,
            "tf": tf,
            "ts": datetime.now(UTC).isoformat(),
        },
        "winner_direction": 1,
        "record_id": str(uuid4()),
    }


def _make_output(text: str = "", error: str | None = None) -> AgentOutput:
    return AgentOutput(
        agent_id="narrative_v1",
        group="narrative",
        payload={"text": text},
        error=error,
        shadow_only=True,
    )


@pytest.mark.asyncio
async def test_handle_trigger_publishes_on_success():
    agent = _make_agent()
    event = _make_event()
    mock_context = MagicMock()
    agent._context_cache.build.return_value = mock_context
    output = _make_output(text="Bullish breakout above 5280.")
    agent._agents[0].compute = AsyncMock(return_value=output)

    await agent._handle_trigger(event)

    agent._publish_result.assert_awaited_once()
    published: AgentOutput = agent._publish_result.await_args[0][0]
    assert published.payload["text"] == "Bullish breakout above 5280."
    assert published.agent_id == "narrative_v1"


@pytest.mark.asyncio
async def test_handle_trigger_skips_when_no_narrative_text():
    agent = _make_agent()
    event = _make_event()
    agent._context_cache.build.return_value = MagicMock()
    agent._agents[0].compute = AsyncMock(return_value=_make_output(text=""))

    await agent._handle_trigger(event)

    agent._publish_result.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_trigger_skips_when_agent_returns_error():
    agent = _make_agent()
    event = _make_event()
    agent._context_cache.build.return_value = MagicMock()
    agent._agents[0].compute = AsyncMock(
        return_value=_make_output(text="some text", error="LLM timeout")
    )

    await agent._handle_trigger(event)

    agent._publish_result.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_trigger_skips_when_no_context():
    agent = _make_agent()
    event = _make_event()
    agent._context_cache.build.return_value = None

    await agent._handle_trigger(event)

    agent._publish_result.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_trigger_skips_stale_bar():
    agent = _make_agent()
    event = _make_event()
    # Years in the past — clearly exceeds _STALENESS_LIMIT of 10m
    old_ts = datetime(2020, 1, 1, 12, 0, 0, tzinfo=UTC)
    event["intelligence"]["ts"] = old_ts.isoformat()
    agent._context_cache.build.return_value = MagicMock()

    await agent._handle_trigger(event)

    agent._context_cache.build.assert_not_called()
    agent._publish_result.assert_not_awaited()
