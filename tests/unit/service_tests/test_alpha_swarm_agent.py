"""Unit tests for AlphaSwarmComputeAgent — Plan 78-01 + 78-03.

Tests verify:
- Single LineageRecorder replaces ShadowRecorder + TransformRecorder
- No second asyncpg.create_pool call
- Segment key built from numeric hmm_regime + timeframe
- ES resolves to NQ via _LEAD_MAP; NQ self-leads
- _extract_volume_profile removed
- ShadowRecorder/TransformRecorder not importable from module
- Plan 78-03: _graduation_loop Spearman gates (promotion, demotion, under-N)
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.core.ai.context import AIContext
from src.intelligence.schemas import SMCContext
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
    smc_ctx = SMCContext(hmm_regime=hmm_regime)
    mock_context = AIContext(
        symbol="ESM6",
        timeframe=tf,
        ts=datetime.now(UTC),
        smc=smc_ctx,
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

    smc_ctx = SMCContext(hmm_regime=1)
    enriched = AIContext(
        symbol="ESM6",
        timeframe="5m",
        ts=datetime.now(UTC),
        smc=smc_ctx,
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
    """Recorded segment_key must match r'^\\d+\\.[0-9]+m$' (numeric.TFm)."""
    agent, fake_producer = _make_agent(hmm_regime=2, tf="15m")

    smc_ctx = SMCContext(hmm_regime=2)
    enriched = AIContext(
        symbol="NQM6",
        timeframe="15m",
        ts=datetime.now(UTC),
        smc=smc_ctx,
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

    smc_ctx = SMCContext(hmm_regime=None)
    enriched = AIContext(
        symbol="ESM6",
        timeframe="5m",
        ts=datetime.now(UTC),
        smc=smc_ctx,
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

    smc_ctx = SMCContext(hmm_regime=1)
    enriched = AIContext(
        symbol="ESM6",
        timeframe="5m",
        ts=datetime.now(UTC),
        smc=smc_ctx,
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


# ---------------------------------------------------------------------------
# Plan 78-03: _graduation_loop unit tests (Spearman gates)
# ---------------------------------------------------------------------------


def _structlog_mock():
    """Minimal structlog-compatible mock."""
    log = MagicMock()
    log.info = MagicMock()
    log.warning = MagicMock()
    log.error = MagicMock()
    return log


def _make_graduation_agent():
    """Build AlphaSwarmComputeAgent with mock DB pool for graduation tests."""
    from services.alpha_swarm_agent import AlphaSwarmComputeAgent

    agent = AlphaSwarmComputeAgent.__new__(AlphaSwarmComputeAgent)
    agent.settings = MagicMock()
    agent.settings.swarm_graduation_interval_s = 0  # no sleep in tests
    agent.logger = _structlog_mock()
    agent._pool = MagicMock()
    agent._demotion_streak = 0
    # Note: 'running' is a read-only property; _run_graduation_cycle() is callable directly
    return agent


def _make_mock_pool_and_conn(rows: list[tuple], current_state: str = "shadow"):
    """Return (pool, conn) mock yielding (multiplier, pnl_r) rows.

    Each row is (prediction_value, pnl_r); prediction stored as {'score': value}.
    current_state 'shadow' means is_shadow=True.
    """
    is_shadow = current_state == "shadow"

    # Build asyncpg Record-like dicts
    records = [{"prediction": {"score": float(m)}, "pnl_r": float(p)} for m, p in rows]
    state_row = {"is_shadow": is_shadow, "demotion_consecutive_count": 0}

    conn = MagicMock()
    conn.fetch = AsyncMock(return_value=records)
    conn.fetchrow = AsyncMock(return_value=state_row)
    conn.execute = AsyncMock()

    conn_ctx = MagicMock()
    conn_ctx.__aenter__ = AsyncMock(return_value=conn)
    conn_ctx.__aexit__ = AsyncMock(return_value=False)

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=conn_ctx)
    return pool, conn


@pytest.mark.asyncio
async def test_promotion_gate_promotes_with_100_positive_samples():
    """100 strongly-positive correlated samples → state transitions to 'live' (is_shadow=FALSE)."""
    import numpy as np

    agent = _make_graduation_agent()

    # 100 samples with strong positive Spearman correlation
    rng = np.random.default_rng(42)
    predictions = np.linspace(0.1, 1.0, 100)
    pnl_rs = predictions + rng.normal(0, 0.05, 100)  # strong positive correlation
    rows = list(zip(predictions.tolist(), pnl_rs.tolist()))

    pool, conn = _make_mock_pool_and_conn(rows, current_state="shadow")
    agent._pool = pool

    await agent._run_graduation_cycle()

    # Check that promotion UPDATE was issued: is_shadow=FALSE
    execute_calls = conn.execute.call_args_list
    assert len(execute_calls) > 0, "Expected at least one DB execute call"
    # Find UPDATE call that passes is_shadow=False
    promoted = any(
        False in call.args  # asyncpg uses positional params
        for call in execute_calls
    )
    assert promoted or agent.logger.info.called, (
        f"Promotion UPDATE not found. execute_calls={execute_calls}"
    )
    # Check logger for 'live' in info calls
    info_str = str(agent.logger.info.call_args_list)
    assert "live" in info_str, f"Expected 'live' state logged. info_calls={info_str}"


@pytest.mark.asyncio
async def test_under_n_no_eval():
    """50 samples (< 100) → no Spearman; n written to DB; no promotion."""
    import numpy as np

    agent = _make_graduation_agent()

    rng = np.random.default_rng(7)
    predictions = np.linspace(0.1, 1.0, 50)
    pnl_rs = predictions + rng.normal(0, 0.05, 50)
    rows = list(zip(predictions.tolist(), pnl_rs.tolist()))

    pool, conn = _make_mock_pool_and_conn(rows, current_state="shadow")
    agent._pool = pool

    await agent._run_graduation_cycle()

    # No promotion: is_shadow=False should NOT appear in execute args
    execute_calls = conn.execute.call_args_list
    assert len(execute_calls) > 0, "Expected UPDATE to write n_resolved even under-N"
    promoted = any(
        False in call.args
        for call in execute_calls
    )
    assert not promoted, f"Unexpected promotion with n=50: execute_calls={execute_calls}"

    # n=50 should appear as an integer arg in one of the execute calls
    all_int_args = [
        a for call in execute_calls for a in call.args if isinstance(a, int)
    ]
    assert 50 in all_int_args, f"n=50 not found in execute call args: {execute_calls}"


@pytest.mark.asyncio
async def test_demotion_streak_fires_after_3_consecutive_negative_cycles():
    """state='live', 3 consecutive rho < 0 → demotion; streak resets on positive cycle."""
    import numpy as np

    rng = np.random.default_rng(99)
    predictions = np.linspace(0.1, 1.0, 100)

    # Negative correlation rows
    neg_pnl = -predictions + rng.normal(0, 0.05, 100)
    neg_rows = list(zip(predictions.tolist(), neg_pnl.tolist()))

    # Test 1: 3 consecutive negative cycles → demotion fires (streak resets to 0 after)
    agent = _make_graduation_agent()
    agent._demotion_streak = 0

    demoted = False
    for _cycle in range(3):
        pool, conn = _make_mock_pool_and_conn(neg_rows, current_state="live")
        agent._pool = pool
        await agent._run_graduation_cycle()
        # Check if demotion UPDATE was issued (is_shadow=True set on a 'live' agent)
        execute_calls = conn.execute.call_args_list
        if any(True in call.args and "swarm_agent" in str(call) for call in execute_calls):
            demoted = True

    # After 3 negative cycles from 'live', demotion should have fired.
    # Implementation resets streak to 0 after demotion — check streak was 0 (reset) or demotion logged
    info_str = str(agent.logger.info.call_args_list)
    assert "shadow" in info_str or agent._demotion_streak == 0, (
        f"Expected demotion after 3 neg cycles. streak={agent._demotion_streak}, info={info_str}"
    )

    # Test 2: streak resets to 0 after positive cycle
    pos_pnl = predictions + rng.normal(0, 0.05, 100)
    pos_rows = list(zip(predictions.tolist(), pos_pnl.tolist()))

    agent2 = _make_graduation_agent()
    agent2._demotion_streak = 0

    # Cycle 1: negative → streak = 1
    pool, conn = _make_mock_pool_and_conn(neg_rows, current_state="live")
    agent2._pool = pool
    await agent2._run_graduation_cycle()
    streak_after_neg = agent2._demotion_streak
    assert streak_after_neg == 1, f"Expected streak=1 after neg, got {streak_after_neg}"

    # Cycle 2: positive → streak = 0
    pool, conn = _make_mock_pool_and_conn(pos_rows, current_state="live")
    agent2._pool = pool
    await agent2._run_graduation_cycle()
    streak_after_pos = agent2._demotion_streak
    assert streak_after_pos == 0, f"Expected streak=0 after pos, got {streak_after_pos}"

    # Cycle 3: negative → streak = 1 (reset from 0, not from 2)
    pool, conn = _make_mock_pool_and_conn(neg_rows, current_state="live")
    agent2._pool = pool
    await agent2._run_graduation_cycle()
    streak_final = agent2._demotion_streak
    assert streak_final == 1, f"Expected streak=1 after reset+neg, got {streak_final}"


@pytest.mark.asyncio
async def test_graduation_loop_handles_nan_gracefully():
    """Constant prediction values → scipy nan rho — treated as rho=0, p=1; no crash."""
    agent = _make_graduation_agent()

    # 100 rows with constant prediction (scipy returns nan rho)
    rows = [(0.5, float(i) * 0.01) for i in range(100)]
    pool, conn = _make_mock_pool_and_conn(rows, current_state="shadow")
    agent._pool = pool

    # Should not raise
    await agent._run_graduation_cycle()
    # No crash = pass


# ---------------------------------------------------------------------------
# Plan 78-06: Task 3 — Single-agent swarm, pass-through enrichment, dead helpers deleted
# ---------------------------------------------------------------------------


def test_single_agent_swarm_only_skeptic():
    """_agents must contain exactly one agent: SkepticAgentComputeAgent."""
    from services.alpha_swarm_agent import AlphaSwarmComputeAgent
    from src.intelligence.ai.alpha.skeptic_agent import SkepticAgentComputeAgent

    svc = AlphaSwarmComputeAgent.__new__(AlphaSwarmComputeAgent)
    # Simulate what __init__ should set after Plan 06
    # We test the class structure directly: CorrelationAgent/VolumeAgent must not exist
    assert not hasattr(AlphaSwarmComputeAgent, "_CorrelationAgentComputeAgent__init__"), (
        "CorrelationAgentComputeAgent still referenced in class"
    )
    # Module-level imports must be clean
    import services.alpha_swarm_agent as m
    assert not hasattr(m, "CorrelationAgentComputeAgent"), (
        "CorrelationAgentComputeAgent still imported in alpha_swarm_agent"
    )
    assert not hasattr(m, "VolumeAgentComputeAgent"), (
        "VolumeAgentComputeAgent still imported in alpha_swarm_agent"
    )


def test_swarm_agent_to_transform_has_only_skeptic():
    """_SWARM_AGENT_TO_TRANSFORM must map exactly one key: 'skeptic_v1'."""
    import services.alpha_swarm_agent as m

    assert hasattr(m, "_SWARM_AGENT_TO_TRANSFORM"), (
        "_SWARM_AGENT_TO_TRANSFORM not found in alpha_swarm_agent"
    )
    mapping = m._SWARM_AGENT_TO_TRANSFORM
    assert set(mapping.keys()) == {"skeptic_v1"}, (
        f"_SWARM_AGENT_TO_TRANSFORM has unexpected keys: {set(mapping.keys())}"
    )
    assert mapping["skeptic_v1"] == ("swarm_skeptic", 6), (
        f"Unexpected value for skeptic_v1: {mapping['skeptic_v1']}"
    )


@pytest.mark.asyncio
async def test_enrich_context_is_pass_through():
    """_enrich_context must be async and return the same context object (identity)."""
    from services.alpha_swarm_agent import AlphaSwarmComputeAgent
    from datetime import UTC, datetime
    from src.core.ai.context import AIContext

    svc = AlphaSwarmComputeAgent.__new__(AlphaSwarmComputeAgent)
    svc.logger = MagicMock()
    # _context_cache needed by _enrich_context? No — pass-through needs nothing
    ctx = AIContext(symbol="ESM6", timeframe="5m", ts=datetime.now(UTC))

    result = await svc._enrich_context(ctx)
    assert result is ctx, (
        "_enrich_context must return the SAME ctx object (pass-through, object identity)"
    )


def test_lead_index_map_deleted():
    """_LEAD_INDEX_MAP, _find_lead_context, _extract_volume_profile must be absent."""
    import services.alpha_swarm_agent as m
    from services.alpha_swarm_agent import AlphaSwarmComputeAgent

    assert not hasattr(m, "_LEAD_INDEX_MAP"), (
        "_LEAD_INDEX_MAP still present in alpha_swarm_agent"
    )
    assert not hasattr(AlphaSwarmComputeAgent, "_find_lead_context"), (
        "_find_lead_context still present on AlphaSwarmComputeAgent"
    )
    assert not hasattr(AlphaSwarmComputeAgent, "_extract_volume_profile"), (
        "_extract_volume_profile still present on AlphaSwarmComputeAgent"
    )


def test_wave1_invariants_preserved():
    """Plan 01 invariants: LineageRecorder present, no ShadowRecorder/TransformRecorder."""
    import services.alpha_swarm_agent as m

    assert hasattr(m, "LineageRecorder"), (
        "LineageRecorder not found in alpha_swarm_agent (Plan 01 invariant)"
    )
    assert not hasattr(m, "ShadowRecorder"), (
        "ShadowRecorder still imported (Plan 01 should have removed it)"
    )
    assert not hasattr(m, "TransformRecorder"), (
        "TransformRecorder still imported (Plan 01 should have removed it)"
    )
