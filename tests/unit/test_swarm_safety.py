"""Tests for SafeSwarmWrapper.

Uses class-level AsyncMock for async iterables (per CLAUDE.md async mock gotcha).
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.core.ai.context import AIContext


def _make_context() -> AIContext:
    return AIContext(
        signal_id=uuid4(),
        symbol="ESM6",
        timeframe="1m",
        ts=datetime(2026, 4, 9, 14, 30, tzinfo=UTC),
    )


def _make_agent_output(multiplier: float = 1.2) -> MagicMock:
    from src.core.ai.output import AgentOutput
    output = AgentOutput(
        agent_id="test_agent",
        group="alpha",
        signal_id=uuid4(),
        symbol="ESM6",
        timeframe="1m",
        ts=datetime(2026, 4, 9, 14, 30, tzinfo=UTC),
        output_type="multiplier",
        payload={"multiplier": multiplier, "confidence": 0.85},
        shadow_only=True,
        latency_ms=100.0,
    )
    return output


@pytest.mark.asyncio
async def test_wrapper_returns_agent_output_on_success():
    from src.core.ai.safe_wrapper import SafeAgentWrapper
    from src.intelligence.ai.alpha.skeptic_agent import SkepticAgentComputeAgent

    # Create a mock LLM chain
    mock_llm = MagicMock()
    mock_llm.generate = AsyncMock(return_value='{"failure_probability": 0.2, "confidence": 0.9, "risk_factors": [], "reasoning": "test"}')

    agent = SkepticAgentComputeAgent(llm_chain=mock_llm)
    wrapper = SafeAgentWrapper(agent)
    ctx = _make_context()
    result = await wrapper.run(ctx)
    assert result is not None
    assert result.payload["multiplier"] == (1.0 - 0.2) * 0.9


@pytest.mark.asyncio
async def test_wrapper_returns_neutral_on_timeout():
    from src.core.ai.safe_wrapper import SafeAgentWrapper

    async def slow_compute(ctx):
        await asyncio.sleep(10.0)

    agent = MagicMock()
    agent.agent_id = "slow_agent"
    agent.latency_budget_ms = 10.0  # 10ms budget
    agent.compute = slow_compute

    wrapper = SafeAgentWrapper(agent)
    ctx = _make_context()
    result = await wrapper.run(ctx)
    # Timeout → neutral output
    assert result is not None
    assert result.payload.get("multiplier", 1.0) == 1.0
    assert result.error is not None


@pytest.mark.asyncio
async def test_wrapper_returns_neutral_on_exception():
    from src.core.ai.safe_wrapper import SafeAgentWrapper

    agent = MagicMock()
    agent.agent_id = "crashing_agent"
    agent.latency_budget_ms = 1000.0
    agent.compute = AsyncMock(side_effect=ValueError("agent crashed"))

    wrapper = SafeAgentWrapper(agent)
    ctx = _make_context()
    result = await wrapper.run(ctx)
    assert result.payload.get("multiplier", 1.0) == 1.0  # neutral fallback
    assert result.error is not None


@pytest.mark.asyncio
async def test_wrapper_records_latency_ms():
    from src.core.ai.safe_wrapper import SafeAgentWrapper
    from src.intelligence.ai.alpha.skeptic_agent import SkepticAgentComputeAgent

    mock_llm = MagicMock()
    mock_llm.generate = AsyncMock(return_value='{"failure_probability": 0.1, "confidence": 0.95, "risk_factors": [], "reasoning": "test"}')

    agent = SkepticAgentComputeAgent(llm_chain=mock_llm)
    wrapper = SafeAgentWrapper(agent)
    ctx = _make_context()
    result = await wrapper.run(ctx)
    assert result.latency_ms >= 0.0


# ---------------------------------------------------------------------------
# SwarmAggregator
# ---------------------------------------------------------------------------

def test_aggregator_returns_neutral_for_empty_contributors():
    from src.intelligence.schemas import AlphaMultiplier
    from src.intelligence.swarm.aggregator import SwarmAggregator

    agg = SwarmAggregator()
    result = agg.aggregate(
        signal_id=uuid4(),
        symbol="ESM6",
        timeframe="1m",
        ts=datetime.now(UTC),
        path_a_results=[],
        path_b_results=[],
    )
    assert isinstance(result, AlphaMultiplier)
    assert result.final_alpha_multiplier == 1.0
    assert result.shadow_only is True


def test_aggregator_confidence_weighted_path_a():
    from src.core.ai.output import AgentOutput
    from src.intelligence.swarm.aggregator import SwarmAggregator

    a1 = AgentOutput(agent_id="a1", group="alpha", payload={"multiplier": 1.4, "confidence": 0.9})
    a2 = AgentOutput(agent_id="a2", group="alpha", payload={"multiplier": 1.1, "confidence": 0.1})
    # Weighted: (1.4*0.9 + 1.1*0.1) / (0.9+0.1) = (1.26 + 0.11) / 1.0 = 1.37

    agg = SwarmAggregator()
    result = agg.aggregate(
        signal_id=uuid4(),
        symbol="ESM6",
        timeframe="1m",
        ts=datetime.now(UTC),
        path_a_results=[a1, a2],
        path_b_results=[],
    )
    assert abs(result.path_a_multiplier - 1.37) < 0.01


def test_aggregator_production_multiplier_is_clamped():
    """production_multiplier must stay in [0.7, 1.3] regardless of computed value."""
    from src.core.ai.output import AgentOutput
    from src.intelligence.swarm.aggregator import SwarmAggregator

    a1 = AgentOutput(agent_id="extreme", group="alpha", payload={"multiplier": 2.0, "confidence": 1.0})
    agg = SwarmAggregator()
    result = agg.aggregate(
        signal_id=uuid4(),
        symbol="ESM6",
        timeframe="1m",
        ts=datetime.now(UTC),
        path_a_results=[a1],
        path_b_results=[],
    )
    assert result.production_multiplier <= 1.3
    assert result.production_multiplier >= 0.7
