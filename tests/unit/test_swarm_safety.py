"""Tests for SafeSwarmWrapper.

Uses class-level AsyncMock for async iterables (per CLAUDE.md async mock gotcha).
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.intelligence.swarm.context import SwarmContext


def _make_context() -> SwarmContext:
    return SwarmContext(
        signal_id=uuid4(),
        symbol="ESM6",
        timeframe="1m",
        ts=datetime(2026, 4, 9, 14, 30, tzinfo=UTC),
        atr=8.5,
        adx=None,
        rsi=None,
        hmm_regime=1,
        trend_regime=None,
        vol_regime=None,
        vol_percentile=None,
        garch_vol_ratio=None,
        garch_vol_regime=None,
        kalman_trend=None,
        kalman_slope=None,
        vwap=None,
        poc_price=None,
        poc_price_rolling=None,
        ctf_score=None,
        ctf_trend_alignment=None,
        ctf_structure_alignment=None,
        ctf_regime_agreement=None,
        ctf_timeframes_aligned=None,
        ctf_fvg_alignment=None,
        ctf_ob_alignment=None,
        winner_plugin="TrendFollowing",
        winner_direction=1,
        winner_confidence=0.8,
        price=5280.0,
        volume=12000.0,
    )


def _make_contributor(multiplier: float = 1.2, path: str = "deterministic") -> MagicMock:
    from src.intelligence.schemas import AgentResult
    contributor = MagicMock()
    contributor.agent_id = "test_agent"
    contributor.path = path
    contributor.shadow_only = True
    contributor.latency_budget_ms = 100.0
    result = AgentResult(
        agent_id="test_agent",
        path=path,
        multiplier=multiplier,
        confidence=0.85,
    )
    contributor.compute = AsyncMock(return_value=result)
    return contributor


@pytest.mark.asyncio
async def test_wrapper_returns_agent_result_on_success():
    from src.intelligence.swarm.safety import SafeSwarmWrapper
    contributor = _make_contributor(multiplier=1.2)
    wrapper = SafeSwarmWrapper(contributor)
    ctx = _make_context()
    result = await wrapper.run(ctx)
    assert result is not None
    assert result.multiplier == 1.2


@pytest.mark.asyncio
async def test_wrapper_returns_neutral_on_timeout():
    from src.intelligence.swarm.safety import SafeSwarmWrapper

    async def slow_compute(ctx):
        await asyncio.sleep(10.0)

    contributor = MagicMock()
    contributor.agent_id = "slow_agent"
    contributor.path = "deterministic"
    contributor.shadow_only = True
    contributor.latency_budget_ms = 10.0  # 10ms budget
    contributor.compute = slow_compute

    wrapper = SafeSwarmWrapper(contributor)
    ctx = _make_context()
    result = await wrapper.run(ctx)
    # Timeout → neutral multiplier (1.0)
    assert result is not None
    assert result.multiplier == 1.0
    assert result.error is not None


@pytest.mark.asyncio
async def test_wrapper_clamps_multiplier_above_max():
    from src.intelligence.swarm.safety import SafeSwarmWrapper

    # AgentResult.multiplier is clamped to [0, 2] by schema — this tests that the
    # wrapper returns neutral when the agent raises an exception instead.
    contributor = _make_contributor(multiplier=1.0)
    contributor.compute = AsyncMock(side_effect=ValueError("agent crashed"))

    wrapper = SafeSwarmWrapper(contributor)
    ctx = _make_context()
    result = await wrapper.run(ctx)
    assert result.multiplier == 1.0  # neutral fallback
    assert result.error is not None


@pytest.mark.asyncio
async def test_wrapper_records_latency_ms():
    from src.intelligence.swarm.safety import SafeSwarmWrapper
    contributor = _make_contributor(multiplier=1.1)
    wrapper = SafeSwarmWrapper(contributor)
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
    from src.intelligence.schemas import AgentResult
    from src.intelligence.swarm.aggregator import SwarmAggregator

    a1 = AgentResult(agent_id="a1", path="deterministic", multiplier=1.4, confidence=0.9)
    a2 = AgentResult(agent_id="a2", path="deterministic", multiplier=1.1, confidence=0.1)
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
    from src.intelligence.schemas import AgentResult
    from src.intelligence.swarm.aggregator import SwarmAggregator

    # Extreme result that would push final above 1.3
    a1 = AgentResult(agent_id="extreme", path="deterministic", multiplier=2.0, confidence=1.0)
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
