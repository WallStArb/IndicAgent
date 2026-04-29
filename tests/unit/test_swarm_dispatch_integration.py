"""Integration tests for multi-agent dispatch in AlphaSwarmComputeAgent.

Tests: concurrent agent execution, shared cache, context enrichment,
TF filtering, independent result recording, neutral fallback.
"""
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.core.ai.output import AgentOutput
from src.intelligence.swarm.context import SwarmContext


def _make_context(**overrides):
    """Create a minimal SwarmContext for testing."""
    defaults = dict(
        signal_id=uuid4(), symbol="ESM6", timeframe="5m",
        ts=datetime.now(UTC),
        atr=None, adx=None, rsi=None,
        hmm_regime=None, trend_regime=None, vol_regime=None,
        vol_percentile=None, garch_vol_ratio=None, garch_vol_regime=None,
        kalman_trend=None, kalman_slope=None,
        vwap=None, poc_price=None, poc_price_rolling=None,
        ctf_score=None, ctf_trend_alignment=None, ctf_structure_alignment=None,
        ctf_regime_agreement=None, ctf_timeframes_aligned=None,
        ctf_fvg_alignment=None, ctf_ob_alignment=None,
        winner_plugin=None, winner_direction=None, winner_confidence=None,
        price=None, volume=None,
    )
    defaults.update(overrides)
    return SwarmContext(**defaults)


def _make_signal_event(**overrides):
    """Create a minimal RankedSignal-compatible event dict."""
    defaults = dict(
        signal_id=str(uuid4()),
        plugin="TrendFollowing",
        direction=1,
        raw_confidence=0.7,
        calibrated_confidence=0.7,
        regime_eligible=True,
        quality_score=0.8,
        tod_multiplier=1.0,
        adjusted_rank=0.75,
        is_winner=True,
        symbol="ESM6",
        tf="5m",
    )
    defaults.update(overrides)
    return defaults


def _make_mock_context(**overrides):
    """Create a mock AIContext-like object with .i4 attribute."""
    ctx = MagicMock()
    ctx.symbol = overrides.get("symbol", "ESM6")
    ctx.timeframe = overrides.get("timeframe", "5m")
    ctx.i4 = MagicMock()
    ctx.i4.hmm_regime = overrides.get("hmm_regime", None)
    return ctx


def _make_service_with_mock_agents(n_agents: int = 3):
    """Create AlphaSwarmComputeAgent with mock agents."""
    from services.alpha_swarm_agent import AlphaSwarmComputeAgent

    svc = AlphaSwarmComputeAgent.__new__(AlphaSwarmComputeAgent)
    svc.settings = MagicMock(env_name="test")
    svc._context_cache = MagicMock()
    svc._recorder = MagicMock()
    svc._recorder.record = AsyncMock()
    svc._recorder.flush = AsyncMock()
    svc._transform_recorder = MagicMock()
    svc._transform_recorder.record = AsyncMock()
    svc._transform_recorder.flush = AsyncMock()
    svc._producer = MagicMock()
    svc._producer.publish = AsyncMock()
    svc.logger = MagicMock()

    # Create mock agents that return AgentOutput
    mock_agents = []
    for i in range(n_agents):
        agent = MagicMock()
        agent.agent_id = f"test_agent_{i}"
        agent.path = "llm_swarm"
        agent.shadow_only = True
        agent.latency_budget_ms = 5000.0
        agent.tiers_needed = frozenset()
        agent.compute = AsyncMock(return_value=AgentOutput(
            agent_id=f"test_agent_{i}",
            group="alpha",
            output_type="prediction",
            payload={"multiplier": 0.8, "confidence": 0.6, "failure_probability": 0.5, "prompt_version": "test_v1"},
            shadow_only=True,
        ))
        mock_agents.append(agent)

    svc._agents = mock_agents
    return svc, mock_agents


@pytest.mark.asyncio
async def test_handle_trigger_runs_all_agents():
    """Per D-15: all agents run concurrently via asyncio.gather."""
    svc, agents = _make_service_with_mock_agents(3)
    ctx = _make_mock_context(symbol="ESM6", timeframe="5m", hmm_regime=1)
    svc._context_cache.build = MagicMock(return_value=ctx)
    svc._enrich_context = MagicMock(return_value=ctx)

    event = _make_signal_event(symbol="ESM6", tf="5m")
    await svc._handle_trigger(event)

    # All 3 agents called
    for agent in agents:
        agent.compute.assert_called_once()

    # 3 publish calls (one per agent result)
    assert svc._producer.publish.call_count == 3


@pytest.mark.asyncio
async def test_handle_trigger_filters_1m():
    """Per D-09: 1m signals are skipped."""
    svc, agents = _make_service_with_mock_agents(3)

    event = _make_signal_event(symbol="ESM6", tf="1m")
    await svc._handle_trigger(event)

    # No agents called
    for agent in agents:
        agent.compute.assert_not_called()


@pytest.mark.asyncio
async def test_handle_trigger_accepts_all_eligible_tfs():
    """Per D-09: 5m, 15m, 1h, 4h, 1d all processed."""
    from services.alpha_swarm_agent import _ELIGIBLE_TFS

    for tf in _ELIGIBLE_TFS:
        svc, agents = _make_service_with_mock_agents(1)
        ctx = _make_mock_context(timeframe=tf)
        svc._context_cache.build = MagicMock(return_value=ctx)
        svc._enrich_context = MagicMock(return_value=ctx)

        event = _make_signal_event(tf=tf)
        await svc._handle_trigger(event)

        agents[0].compute.assert_called_once()


@pytest.mark.asyncio
async def test_handle_trigger_skips_on_no_context():
    """Signal is skipped when context_cache.build returns None."""
    svc, agents = _make_service_with_mock_agents(3)
    svc._context_cache.build = MagicMock(return_value=None)

    event = _make_signal_event(symbol="ESM6", tf="5m")
    await svc._handle_trigger(event)

    for agent in agents:
        agent.compute.assert_not_called()


@pytest.mark.asyncio
async def test_enrichment_adds_volume_profile():
    """Per D-16: volume_profile dict added to enriched context."""
    svc, _ = _make_service_with_mock_agents(0)

    svc._extract_volume_profile = MagicMock(return_value={
        "vah": 4505.0, "val": 4495.0,
        "price_in_value_area": 0.7,
    })
    svc._find_lead_context = MagicMock(return_value=None)

    ctx = _make_context(symbol="ESM6", timeframe="5m")
    enriched = svc._enrich_context(ctx)

    assert enriched.volume_profile is not None
    assert enriched.volume_profile["vah"] == 4505.0
    assert enriched.volume_profile["val"] == 4495.0
    # Original context unchanged
    assert ctx.volume_profile is None


@pytest.mark.asyncio
async def test_enrichment_adds_lead_context():
    """Per D-16: lead_context SwarmContext added for CorrelationAgent."""
    svc, _ = _make_service_with_mock_agents(0)

    lead = _make_context(symbol="ESM6", timeframe="5m", trend_regime=0.8)
    svc._find_lead_context = MagicMock(return_value=lead)
    svc._extract_volume_profile = MagicMock(return_value=None)

    ctx = _make_context(symbol="NQM6", timeframe="5m")
    enriched = svc._enrich_context(ctx)

    assert enriched.lead_context is not None
    assert enriched.lead_context.symbol == "ESM6"
    # Original context unchanged
    assert ctx.lead_context is None


@pytest.mark.asyncio
async def test_neutral_result_on_error():
    """Per D-11: errors are logged but don't crash the service."""
    svc, agents = _make_service_with_mock_agents(1)

    # Agent raises exception — SafeAgentWrapper catches and returns error output
    agents[0].compute = AsyncMock(side_effect=Exception("LLM timeout"))

    ctx = _make_mock_context(symbol="ESM6", timeframe="5m")
    svc._context_cache.build = MagicMock(return_value=ctx)
    svc._enrich_context = MagicMock(return_value=ctx)

    event = _make_signal_event(symbol="ESM6", tf="5m")

    # Should NOT raise — error is caught by SafeAgentWrapper
    await svc._handle_trigger(event)


@pytest.mark.asyncio
async def test_each_agent_recorded_independently():
    """Per D-15: each agent's result published independently."""
    svc, agents = _make_service_with_mock_agents(3)

    # Give each agent a distinct result
    for i, agent in enumerate(agents):
        agent.compute = AsyncMock(return_value=AgentOutput(
            agent_id=f"test_agent_{i}",
            group="alpha",
            output_type="prediction",
            payload={"multiplier": 0.5 + i * 0.3, "confidence": 0.4 + i * 0.2, "failure_probability": 0.3 + i * 0.1},
            shadow_only=True,
        ))

    ctx = _make_mock_context(symbol="ESM6", timeframe="5m", hmm_regime=1)
    svc._context_cache.build = MagicMock(return_value=ctx)
    svc._enrich_context = MagicMock(return_value=ctx)

    event = _make_signal_event(symbol="ESM6", tf="5m")
    await svc._handle_trigger(event)

    # 3 independent publish calls
    assert svc._producer.publish.call_count == 3


def test_enrichment_preserves_all_context_fields():
    """Enriched context preserves all original SwarmContext fields."""
    svc, _ = _make_service_with_mock_agents(0)
    svc._find_lead_context = MagicMock(return_value=None)
    svc._extract_volume_profile = MagicMock(return_value=None)

    ctx = _make_context(
        symbol="ESM6", timeframe="5m",
        atr=12.5, adx=25.0, rsi=55.0,
        hmm_regime=1, price=4500.0,
        winner_plugin="TrendFollowing",
        winner_direction=1,
        winner_confidence=0.75,
    )
    enriched = svc._enrich_context(ctx)

    assert enriched.symbol == "ESM6"
    assert enriched.atr == 12.5
    assert enriched.adx == 25.0
    assert enriched.rsi == 55.0
    assert enriched.hmm_regime == 1
    assert enriched.price == 4500.0
    assert enriched.winner_plugin == "TrendFollowing"
    assert enriched.winner_direction == 1
    assert enriched.winner_confidence == 0.75
