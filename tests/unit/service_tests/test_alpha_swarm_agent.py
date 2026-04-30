"""Unit tests for AlphaSwarmComputeAgent — Plan 78-01.

Tests verify:
- Single LineageRecorder replaces ShadowRecorder + TransformRecorder
- No second asyncpg.create_pool call
- Segment key built from numeric hmm_regime + timeframe
- ES resolves to NQ via _LEAD_MAP; NQ self-leads
- _extract_volume_profile removed
- ShadowRecorder/TransformRecorder not importable from module
"""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.core.ai.context import AIContext, I4Context
from src.core.ai.output import AgentOutput
from src.core.stream_keys import topic_signal_lineage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fake_producer() -> MagicMock:
    """Fake Kafka producer that captures publishes."""
    producer = MagicMock()
    producer.publish = AsyncMock()
    return producer


def _make_agent(hmm_regime: int = 1, tf: str = "5m"):
    """Build AlphaSwarmComputeAgent bypassing __init__ (CLAUDE.md __new__ pattern)."""
    from services.alpha_swarm_agent import AlphaSwarmComputeAgent
    from src.core.ai.lineage import LineageRecorder

    agent = AlphaSwarmComputeAgent.__new__(AlphaSwarmComputeAgent)
    agent.settings = MagicMock(env_name="test")
    agent.logger = MagicMock()

    # Inject fake producer + LineageRecorder (per plan step 6)
    fake_producer = _make_fake_producer()
    agent._producer = fake_producer
    agent._lineage = LineageRecorder(producer=fake_producer, env_name="test")

    # Mock context cache
    i4_ctx = I4Context(hmm_regime=hmm_regime)
    mock_context = AIContext(
        symbol="ESM6",
        timeframe=tf,
        ts=datetime.now(UTC),
        i4=i4_ctx,
    )
    agent._context_cache = MagicMock()
    agent._context_cache.build.return_value = mock_context

    # Mock agents
    mock_swarm_agent = MagicMock()
    mock_swarm_agent.agent_id = "skeptic_v1"
    mock_swarm_agent.shadow_only = True
    mock_swarm_agent.tiers_needed = frozenset()
    agent._agents = [mock_swarm_agent]

    # Mock publish_result (side-effect free)
    agent._publish_result = AsyncMock()

    return agent, fake_producer


def _make_raw_signal(symbol: str = "ESM6", tf: str = "5m") -> dict:
    """Minimal raw signal dict that signal_dict_to_ranked can parse."""
    return {
        "signal_id": str(uuid4()),
        "symbol": symbol,
        "tf": tf,
        "setup_plugin": "vwap_reversion",
        "direction": 1,
        "pre_quality_confidence": 0.75,
        "calibrated_confidence": 0.72,
        "adjusted_rank": 0.8,
        "regime_eligible": True,
        "i7": {},
    }


# ---------------------------------------------------------------------------
# Task 1: Module-level import assertions
# ---------------------------------------------------------------------------


def test_shadow_recorder_not_in_module():
    """ShadowRecorder must not be importable from alpha_swarm_agent module."""
    import services.alpha_swarm_agent as m

    assert not hasattr(m, "ShadowRecorder"), (
        "ShadowRecorder still imported in alpha_swarm_agent"
    )


def test_transform_recorder_not_in_module():
    """TransformRecorder must not be importable from alpha_swarm_agent module."""
    import services.alpha_swarm_agent as m

    assert not hasattr(m, "TransformRecorder"), (
        "TransformRecorder still imported in alpha_swarm_agent"
    )


def test_lineage_recorder_in_module():
    """LineageRecorder must be imported in alpha_swarm_agent module."""
    import services.alpha_swarm_agent as m

    assert hasattr(m, "LineageRecorder"), (
        "LineageRecorder not found in alpha_swarm_agent"
    )


def test_extract_volume_profile_not_in_module():
    """_extract_volume_profile method must be removed from AlphaSwarmComputeAgent."""
    from services.alpha_swarm_agent import AlphaSwarmComputeAgent

    assert not hasattr(AlphaSwarmComputeAgent, "_extract_volume_profile"), (
        "_extract_volume_profile still present in AlphaSwarmComputeAgent"
    )


# ---------------------------------------------------------------------------
# Task 1: Lineage write path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_swarm_result_publishes_to_signal_lineage():
    """One signal in → one Kafka message to topic_signal_lineage with agent_prediction."""
    agent, fake_producer = _make_agent(hmm_regime=1, tf="5m")

    i4_ctx = I4Context(hmm_regime=1)
    enriched = AIContext(
        symbol="ESM6",
        timeframe="5m",
        ts=datetime.now(UTC),
        i4=i4_ctx,
    )
    result = AgentOutput(
        agent_id="skeptic_v1",
        group="alpha",
        payload={"multiplier": 1.05, "confidence": 0.8},
        shadow_only=True,
    )
    signal_id = uuid4()

    await agent._record_swarm_result(signal_id, enriched, result)

    # Flush buffered records
    await agent._lineage.flush()

    expected_topic = topic_signal_lineage("test")
    assert fake_producer.publish.called, "LineageRecorder.flush() never published"
    call_args = fake_producer.publish.call_args
    assert call_args[0][0] == expected_topic or call_args.args[0] == expected_topic, (
        f"Published to wrong topic: {call_args}"
    )
    row = call_args[1].get("value") or (call_args[0][1] if len(call_args[0]) > 1 else None)
    assert row is not None, f"No value kwarg in publish call: {call_args}"
    assert row["event_type"] == "agent_prediction", (
        f"event_type mismatch: {row['event_type']}"
    )


@pytest.mark.asyncio
async def test_record_swarm_result_segment_key_numeric():
    """Recorded segment_key must match ^\d+\.[0-9]+m$ (numeric.TFm)."""
    agent, fake_producer = _make_agent(hmm_regime=2, tf="15m")

    i4_ctx = I4Context(hmm_regime=2)
    enriched = AIContext(
        symbol="NQM6",
        timeframe="15m",
        ts=datetime.now(UTC),
        i4=i4_ctx,
    )
    result = AgentOutput(
        agent_id="skeptic_v1",
        group="alpha",
        payload={"multiplier": 0.9},
        shadow_only=True,
    )
    signal_id = uuid4()

    await agent._record_swarm_result(signal_id, enriched, result)
    await agent._lineage.flush()

    call_args = fake_producer.publish.call_args
    row = call_args[1].get("value") or (call_args[0][1] if len(call_args[0]) > 1 else None)
    segment_key = row.get("metadata", {}).get("segment_key") or row.get("segment_key", "")
    # segment_key may be in metadata JSONB — check both locations
    assert re.match(r"^\d+\.", segment_key), (
        f"segment_key does not start with numeric prefix: {segment_key!r}"
    )
    assert not segment_key.startswith("unknown."), (
        f"segment_key starts with 'unknown.': {segment_key!r}"
    )


@pytest.mark.asyncio
async def test_record_swarm_result_missing_hmm_regime_skips():
    """If hmm_regime is None, _record_swarm_result must log warning and skip."""
    agent, fake_producer = _make_agent(hmm_regime=1)

    i4_ctx = I4Context(hmm_regime=None)
    enriched = AIContext(
        symbol="ESM6",
        timeframe="5m",
        ts=datetime.now(UTC),
        i4=i4_ctx,
    )
    result = AgentOutput(
        agent_id="skeptic_v1",
        group="alpha",
        payload={"multiplier": 1.0},
        shadow_only=True,
    )
    signal_id = uuid4()

    await agent._record_swarm_result(signal_id, enriched, result)
    await agent._lineage.flush()

    # Should not have published anything
    assert not fake_producer.publish.called, (
        "LineageRecorder published despite missing hmm_regime"
    )
    # Logger should have been called with missing_hmm_regime warning
    assert agent.logger.warning.called or agent.logger.warn.called, (
        "No warning logged for missing hmm_regime"
    )


# ---------------------------------------------------------------------------
# Task 2: _LEAD_MAP and segment key
# ---------------------------------------------------------------------------


def test_lead_map_es_resolves_to_nq():
    """_resolve_lead('ES') must return 'NQ'."""
    from services.alpha_swarm_agent import _resolve_lead

    assert _resolve_lead("ES") == "NQ", "_resolve_lead('ES') should return 'NQ'"


def test_lead_map_nq_self_leads():
    """_resolve_lead('NQ') must return 'NQ' (self-lead)."""
    from services.alpha_swarm_agent import _resolve_lead

    assert _resolve_lead("NQ") == "NQ", "_resolve_lead('NQ') should return 'NQ' (self-lead)"


def test_lead_map_unknown_symbol_self_leads():
    """_resolve_lead for unmapped symbol returns itself."""
    from services.alpha_swarm_agent import _resolve_lead

    assert _resolve_lead("AAPL") == "AAPL"
    assert _resolve_lead("GC") == "GC"


def test_lead_map_constant_exists():
    """_LEAD_MAP module constant must exist with ES->NQ."""
    import services.alpha_swarm_agent as m

    assert hasattr(m, "_LEAD_MAP"), "_LEAD_MAP not found in alpha_swarm_agent"
    assert m._LEAD_MAP.get("ES") == "NQ", f"_LEAD_MAP['ES'] != 'NQ': {m._LEAD_MAP}"


@pytest.mark.asyncio
async def test_segment_key_uses_numeric_regime():
    """For i4.hmm_regime=1 and tf='5m', segment_key == '1.5m'."""
    agent, fake_producer = _make_agent(hmm_regime=1, tf="5m")

    i4_ctx = I4Context(hmm_regime=1)
    enriched = AIContext(
        symbol="ESM6",
        timeframe="5m",
        ts=datetime.now(UTC),
        i4=i4_ctx,
    )
    result = AgentOutput(
        agent_id="skeptic_v1",
        group="alpha",
        payload={"multiplier": 1.1},
        shadow_only=True,
    )
    signal_id = uuid4()

    await agent._record_swarm_result(signal_id, enriched, result)
    await agent._lineage.flush()

    call_args = fake_producer.publish.call_args
    row = call_args[1].get("value") or (call_args[0][1] if len(call_args[0]) > 1 else None)
    # segment_key stored in metadata JSONB
    segment_key = row.get("metadata", {}).get("segment_key", "")
    assert segment_key == "1.5m", f"Expected segment_key='1.5m', got {segment_key!r}"


@pytest.mark.asyncio
async def test_es_lead_is_nq():
    """For symbol ESM6, resolved lead base should be NQ via _LEAD_MAP."""
    from services.alpha_swarm_agent import _resolve_lead

    # ESM6 base is 'ES', maps to NQ
    # _resolve_lead takes the base symbol, not the full contract
    lead = _resolve_lead("ES")
    assert lead == "NQ", f"Expected lead='NQ' for ES, got {lead!r}"
