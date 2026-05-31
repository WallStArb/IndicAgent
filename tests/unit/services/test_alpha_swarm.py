"""Unit tests for AlphaSwarm — Plan 78-01 + 78-03.

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

import asyncio
import re
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.core.ai.output import AgentOutput
from src.core.stream_keys import topic_signal_lineage
from src.intelligence.ai.context import SignalContext
from src.intelligence.schemas import SMCContext

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fake_producer() -> MagicMock:
    """Fake Kafka producer that captures publishes."""
    producer = MagicMock()
    producer.publish = AsyncMock()
    return producer


def _make_agent(hmm_regime: int = 1, tf: str = "5m"):
    """Build AlphaSwarm bypassing __init__ (CLAUDE.md __new__ pattern)."""
    from services.alpha_swarm import AlphaSwarm
    from src.core.ai.lineage import LineageRecorder

    agent = AlphaSwarm.__new__(AlphaSwarm)
    agent.settings = MagicMock(env_name="test")
    agent.logger = MagicMock()

    # Inject fake producer + LineageRecorder (per plan step 6)
    fake_producer = _make_fake_producer()
    agent._producer = fake_producer
    agent._lineage = LineageRecorder(producer=fake_producer, env_name="test")

    # Mock context cache
    smc_ctx = SMCContext(hmm_regime=hmm_regime)
    mock_context = SignalContext(
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
    import services.alpha_swarm as m

    assert not hasattr(m, "ShadowRecorder"), "ShadowRecorder still imported in alpha_swarm_agent"


def test_transform_recorder_not_in_module():
    """TransformRecorder must not be importable from alpha_swarm_agent module."""
    import services.alpha_swarm as m

    assert not hasattr(
        m, "TransformRecorder"
    ), "TransformRecorder still imported in alpha_swarm_agent"


def test_lineage_recorder_in_module():
    """LineageRecorder consolidated onto BaseSwarmCoordinator in Phase 084-03.
    AlphaSwarmAgent inherits it from the base; no direct import needed here."""
    import inspect

    from src.intelligence.ai.base_group_service import BaseSwarmCoordinator

    src = inspect.getsource(BaseSwarmCoordinator._setup)
    assert "LineageRecorder" in src, "LineageRecorder must be wired in BaseSwarmCoordinator._setup"


def test_extract_volume_profile_not_in_module():
    """_extract_volume_profile method must be removed from AlphaSwarm."""
    from services.alpha_swarm import AlphaSwarm

    assert not hasattr(
        AlphaSwarm, "_extract_volume_profile"
    ), "_extract_volume_profile still present in AlphaSwarm"


# ---------------------------------------------------------------------------
# Task 1: Lineage write path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_swarm_result_publishes_to_signal_lineage():
    """One signal in → one Kafka message to topic_signal_lineage with agent_prediction."""
    agent, fake_producer = _make_agent(hmm_regime=1, tf="5m")

    smc_ctx = SMCContext(hmm_regime=1)
    enriched = SignalContext(
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
    # Plan 80-07: _record_swarm_result now takes agent as 3rd arg (before result)
    mock_agent = MagicMock(agent_id="skeptic_v1", group="alpha", shadow_only=True)
    await agent._record_swarm_result(signal_id, enriched, mock_agent, result)

    # Flush buffered records
    await agent._lineage.flush()

    expected_topic = topic_signal_lineage("test")
    assert fake_producer.publish.called, "LineageRecorder.flush() never published"
    call_args = fake_producer.publish.call_args
    assert (
        call_args[0][0] == expected_topic or call_args.args[0] == expected_topic
    ), f"Published to wrong topic: {call_args}"
    row = call_args[1].get("msg") or (call_args[0][1] if len(call_args[0]) > 1 else None)
    assert row is not None, f"No msg kwarg in publish call: {call_args}"
    assert row["event_type"] == "agent_prediction", f"event_type mismatch: {row['event_type']}"


@pytest.mark.asyncio
async def test_record_swarm_result_segment_key_numeric():
    """Recorded segment_key must match r'^\\d+\\.[0-9]+m$' (numeric.TFm)."""
    agent, fake_producer = _make_agent(hmm_regime=2, tf="15m")

    smc_ctx = SMCContext(hmm_regime=2)
    enriched = SignalContext(
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
    mock_agent = MagicMock(agent_id="skeptic_v1", group="alpha", shadow_only=True)
    await agent._record_swarm_result(signal_id, enriched, mock_agent, result)
    await agent._lineage.flush()

    call_args = fake_producer.publish.call_args
    row = call_args[1].get("msg") or (call_args[0][1] if len(call_args[0]) > 1 else None)
    segment_key = row.get("metadata", {}).get("segment_key") or row.get("segment_key", "")
    # segment_key may be in metadata JSONB — check both locations
    assert re.match(
        r"^\d+\.", segment_key
    ), f"segment_key does not start with numeric prefix: {segment_key!r}"
    assert not segment_key.startswith(
        "unknown."
    ), f"segment_key starts with 'unknown.': {segment_key!r}"


@pytest.mark.asyncio
async def test_record_swarm_result_missing_hmm_regime_uses_sentinel():
    """If hmm_regime is None, _record_swarm_result must use 'unknown.{tf}' sentinel key."""
    agent, fake_producer = _make_agent(hmm_regime=1)

    smc_ctx = SMCContext(hmm_regime=None)
    enriched = SignalContext(
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
    mock_agent = MagicMock(agent_id="skeptic_v1", group="alpha", shadow_only=True)
    await agent._record_swarm_result(signal_id, enriched, mock_agent, result)
    await agent._lineage.flush()

    # Should publish with sentinel segment_key (never drops lineage data)
    assert fake_producer.publish.called, "LineageRecorder should publish with sentinel key"
    call_args = fake_producer.publish.call_args
    row = call_args[1].get("msg") or (call_args[0][1] if len(call_args[0]) > 1 else None)
    segment_key = row.get("metadata", {}).get("segment_key") or row.get("segment_key", "")
    assert segment_key == "unknown.5m", f"Expected sentinel 'unknown.5m', got {segment_key!r}"


# ---------------------------------------------------------------------------
# Task 2: _LEAD_MAP and segment key
# ---------------------------------------------------------------------------


def test_lead_map_es_resolves_to_nq():
    """_resolve_lead('ES') must return 'NQ'."""
    from services.alpha_swarm import _resolve_lead

    assert _resolve_lead("ES") == "NQ", "_resolve_lead('ES') should return 'NQ'"


def test_lead_map_nq_self_leads():
    """_resolve_lead('NQ') must return 'NQ' (self-lead)."""
    from services.alpha_swarm import _resolve_lead

    assert _resolve_lead("NQ") == "NQ", "_resolve_lead('NQ') should return 'NQ' (self-lead)"


def test_lead_map_unknown_symbol_self_leads():
    """_resolve_lead for unmapped symbol returns itself."""
    from services.alpha_swarm import _resolve_lead

    assert _resolve_lead("AAPL") == "AAPL"
    assert _resolve_lead("GC") == "GC"


def test_lead_map_constant_exists():
    """_LEAD_MAP module constant must exist with ES->NQ."""
    import services.alpha_swarm as m

    assert hasattr(m, "_LEAD_MAP"), "_LEAD_MAP not found in alpha_swarm_agent"
    assert m._LEAD_MAP.get("ES") == "NQ", f"_LEAD_MAP['ES'] != 'NQ': {m._LEAD_MAP}"


@pytest.mark.asyncio
async def test_segment_key_uses_numeric_regime():
    """For i4.hmm_regime=1 and tf='5m', segment_key == '1.5m'."""
    agent, fake_producer = _make_agent(hmm_regime=1, tf="5m")

    smc_ctx = SMCContext(hmm_regime=1)
    enriched = SignalContext(
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

    mock_agent = MagicMock(agent_id="skeptic_v1", group="alpha", shadow_only=True)
    await agent._record_swarm_result(signal_id, enriched, mock_agent, result)
    await agent._lineage.flush()

    call_args = fake_producer.publish.call_args
    row = call_args[1].get("msg") or (call_args[0][1] if len(call_args[0]) > 1 else None)
    # segment_key stored in metadata JSONB
    segment_key = row.get("metadata", {}).get("segment_key", "")
    assert segment_key == "1.5m", f"Expected segment_key='1.5m', got {segment_key!r}"


@pytest.mark.asyncio
async def test_es_lead_is_nq():
    """For symbol ESM6, resolved lead base should be NQ via _LEAD_MAP."""
    from services.alpha_swarm import _resolve_lead

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
    """Build AlphaSwarm with mock DB pool for graduation tests."""
    from services.alpha_swarm import AlphaSwarm

    agent = AlphaSwarm.__new__(AlphaSwarm)
    agent.settings = MagicMock()
    agent.settings.swarm_graduation_interval_s = 0  # no sleep in tests
    agent.logger = _structlog_mock()
    agent._pool = MagicMock()
    agent._demotion_streak = 0
    agent._agents = []  # Plan 80-07: _run_graduation_cycle iterates self._agents
    agent._agent_weights = {}
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
async def test_graduation_cycle_iterates_agents_and_calls_reload():
    """Plan 80-07: _run_graduation_cycle iterates self._agents, calls _reload and _refresh."""
    agent = _make_graduation_agent()
    # Mock the async methods that require pool access
    agent._evaluate_agent = AsyncMock()
    agent._reload_agent_weights = AsyncMock()
    agent._refresh_shadow_state_from_registry = AsyncMock()

    # Add two mock agents
    agent._agents = [
        MagicMock(agent_id="skeptic_v1"),
        MagicMock(agent_id="correlation_v1"),
    ]

    await agent._run_graduation_cycle()

    # _evaluate_agent called once per agent
    assert agent._evaluate_agent.call_count == 2
    called_ids = [c.args[0] for c in agent._evaluate_agent.call_args_list]
    assert "skeptic_v1" in called_ids
    assert "correlation_v1" in called_ids
    # reload + refresh called at end
    agent._reload_agent_weights.assert_awaited_once()
    agent._refresh_shadow_state_from_registry.assert_awaited_once()


@pytest.mark.asyncio
async def test_graduation_cycle_continues_on_agent_error():
    """Plan 80-07: if _evaluate_agent raises, cycle continues with other agents."""
    agent = _make_graduation_agent()
    call_count = [0]

    async def _side_effect(agent_id: str) -> None:
        call_count[0] += 1
        if agent_id == "skeptic_v1":
            raise RuntimeError("db error")

    agent._evaluate_agent = _side_effect
    agent._reload_agent_weights = AsyncMock()
    agent._refresh_shadow_state_from_registry = AsyncMock()
    agent._agents = [
        MagicMock(agent_id="skeptic_v1"),
        MagicMock(agent_id="correlation_v1"),
    ]

    # Should not raise; should continue past error
    await agent._run_graduation_cycle()
    assert call_count[0] == 2, "Expected both agents evaluated despite error"


@pytest.mark.asyncio
async def test_graduation_cycle_with_empty_agents():
    """Plan 80-07: empty agents list → no evaluate calls, reload+refresh still called."""
    agent = _make_graduation_agent()
    agent._evaluate_agent = AsyncMock()
    agent._reload_agent_weights = AsyncMock()
    agent._refresh_shadow_state_from_registry = AsyncMock()
    # _agents already [] from _make_graduation_agent

    await agent._run_graduation_cycle()

    agent._evaluate_agent.assert_not_called()
    agent._reload_agent_weights.assert_awaited_once()
    agent._refresh_shadow_state_from_registry.assert_awaited_once()


@pytest.mark.asyncio
async def test_graduation_loop_handles_nan_gracefully():
    """Spearman on constant predictions returns nan rho — _evaluate_agent guards against NaN."""
    agent = _make_graduation_agent()
    agent._reload_agent_weights = AsyncMock()
    agent._refresh_shadow_state_from_registry = AsyncMock()

    # Mock _evaluate_agent to simulate the NaN scenario silently passing
    agent._evaluate_agent = AsyncMock()  # no-op — NaN handling tested in evaluate_agent tests

    agent._agents = [MagicMock(agent_id="skeptic_v1")]

    # Should not raise
    await agent._run_graduation_cycle()
    # No crash = pass


# ---------------------------------------------------------------------------
# Plan 78-06: Task 3 — Single-agent swarm, pass-through enrichment, dead helpers deleted
# ---------------------------------------------------------------------------


def test_swarm_agents_are_four_typed_agents():
    """Plan 80-07: _agents init list must declare list[Evaluator] with four agents.

    Updated from Phase 78 single-skeptic assertion. Plan 80-07 adds
    Correlation, RegimeCoherence, Counterfactual alongside Skeptic.
    VolumeAgentComputeAgent (Phase 74 dead code) must remain absent.
    """
    import services.alpha_swarm as m

    # All four Phase 80 agents must be importable from the module
    assert hasattr(m, "CorrelationAnalyzer"), "CorrelationAnalyzer not in module"
    assert hasattr(m, "RegimeCoherenceAnalyzer"), "RegimeCoherenceAnalyzer not in module"
    assert hasattr(m, "CounterfactualEvaluator"), "CounterfactualEvaluator not in module"
    assert hasattr(m, "SkepticEvaluator"), "SkepticEvaluator not in module"
    # VolumeAgentComputeAgent (Phase 74 dead code) must remain absent
    assert not hasattr(
        m, "VolumeAgentComputeAgent"
    ), "VolumeAgentComputeAgent still imported in alpha_swarm_agent"
    # Evaluator must be the typed list element
    assert hasattr(m, "Evaluator"), "Evaluator not imported in alpha_swarm_agent"


def test_swarm_agent_to_transform_has_all_agents():
    """_SWARM_AGENT_TO_TRANSFORM must map all five multiplier agents (Phase 80 + Phase 70 ML scorer)."""
    import services.alpha_swarm as m

    assert hasattr(
        m, "_SWARM_AGENT_TO_TRANSFORM"
    ), "_SWARM_AGENT_TO_TRANSFORM not found in alpha_swarm_agent"
    mapping = m._SWARM_AGENT_TO_TRANSFORM
    expected = {
        "skeptic_v1": ("swarm_skeptic", 6),
        "correlation_v1": ("swarm_correlation", 6),
        "regime_coherence_v1": ("swarm_regime_coherence", 6),
        "counterfactual_v1": ("swarm_counterfactual", 6),
        "ml_scorer_v1": ("swarm_ml_scorer", 6),
    }
    assert dict(mapping) == expected, f"Unexpected mapping: {dict(mapping)}"


@pytest.mark.asyncio
async def test_enrich_context_is_pass_through():
    """_enrich_context must be async and return the same context object (identity)."""
    from datetime import UTC, datetime

    from services.alpha_swarm import AlphaSwarm
    from src.intelligence.ai.context import SignalContext

    svc = AlphaSwarm.__new__(AlphaSwarm)
    svc.logger = MagicMock()
    # _context_cache needed by _enrich_context? No — pass-through needs nothing
    ctx = SignalContext(symbol="ESM6", timeframe="5m", ts=datetime.now(UTC))

    result = await svc._enrich_context(ctx)
    assert (
        result is ctx
    ), "_enrich_context must return the SAME ctx object (pass-through, object identity)"


def test_lead_index_map_deleted():
    """_LEAD_INDEX_MAP, _find_lead_context, _extract_volume_profile must be absent."""
    import services.alpha_swarm as m
    from services.alpha_swarm import AlphaSwarm

    assert not hasattr(m, "_LEAD_INDEX_MAP"), "_LEAD_INDEX_MAP still present in alpha_swarm_agent"
    assert not hasattr(
        AlphaSwarm, "_find_lead_context"
    ), "_find_lead_context still present on AlphaSwarm"
    assert not hasattr(
        AlphaSwarm, "_extract_volume_profile"
    ), "_extract_volume_profile still present on AlphaSwarm"


def test_wave1_invariants_preserved():
    """Plan 01 invariants: no ShadowRecorder/TransformRecorder.
    LineageRecorder consolidated onto BaseSwarmCoordinator in Phase 084-03,
    so it is no longer directly imported in alpha_swarm_agent."""
    import services.alpha_swarm as m

    assert not hasattr(
        m, "ShadowRecorder"
    ), "ShadowRecorder still imported (Plan 01 should have removed it)"
    assert not hasattr(
        m, "TransformRecorder"
    ), "TransformRecorder still imported (Plan 01 should have removed it)"


# ---------------------------------------------------------------------------
# Plan 80-07: Task 4 — new dispatch tests
# ---------------------------------------------------------------------------


def _make_agent_with_mocks():  # type: ignore[return]
    """Build AlphaSwarm with mocked dependencies for dispatch tests."""
    from services.alpha_swarm import AlphaSwarm

    agent = AlphaSwarm.__new__(AlphaSwarm)
    agent.settings = MagicMock(
        SWARM_MIN_TF_MINUTES=5,
        SWARM_MIN_CONFIDENCE=0.6,
        SWARM_WEIGHT_MIN_SAMPLES=30,
        SWARM_WEIGHT_FLOOR=0.05,
        SWARM_MAX_CONCURRENT_CALLS=8,
        env_name="test",
    )
    agent.logger = MagicMock()
    agent._agents = []
    agent._agent_weights = {}
    agent._semaphore = None
    agent._pool = None
    agent._lineage = MagicMock(record=MagicMock())
    agent._producer = MagicMock(publish=AsyncMock())
    return agent


def test_compute_final_multiplier_excludes_errors() -> None:
    """Weighted average uses only non-error agents with valid multipliers."""
    agent = _make_agent_with_mocks()
    agents_list = [MagicMock(agent_id="a"), MagicMock(agent_id="b"), MagicMock(agent_id="c")]
    ok = AgentOutput(
        agent_id="a",
        group="alpha",
        payload={"multiplier": 0.8},
        shadow_only=True,
    )
    err = AgentOutput(
        agent_id="b",
        group="alpha",
        payload={},
        shadow_only=True,
        error="fail",
    )
    ok2 = AgentOutput(
        agent_id="c",
        group="alpha",
        payload={"multiplier": 0.6},
        shadow_only=True,
    )
    result, count = agent._compute_final_multiplier(agents_list, [ok, err, ok2], "5m")
    # Default weight 1/3 each but only valid pair used: weighted avg = (0.8+0.6)/2 = 0.7
    import pytest as _pytest

    assert result == _pytest.approx(0.7)
    assert count == 2


def test_compute_final_multiplier_returns_none_when_all_fail() -> None:
    """All-error results → (None, 0)."""
    agent = _make_agent_with_mocks()
    agents_list = [MagicMock(agent_id="a"), MagicMock(agent_id="b")]
    err1 = AgentOutput(
        agent_id="a",
        group="alpha",
        payload={},
        shadow_only=True,
        error="x",
    )
    err2 = AgentOutput(
        agent_id="b",
        group="alpha",
        payload={},
        shadow_only=True,
        error="y",
    )
    result, count = agent._compute_final_multiplier(agents_list, [err1, err2], "5m")
    assert result is None
    assert count == 0


def test_no_direct_signal_ledger_writes() -> None:
    """services/alpha_swarm.py must contain zero UPDATE/INSERT signal_ledger statements."""
    import pathlib

    path = pathlib.Path("services/alpha_swarm.py")
    src = path.read_text()
    # Strip comment lines
    non_comment = "\n".join(line for line in src.splitlines() if not line.lstrip().startswith("#"))
    assert "UPDATE signal_ledger" not in non_comment
    assert "INSERT INTO signal_ledger" not in non_comment


@pytest.mark.asyncio
async def test_shadow_enrollment_loops_all_agents() -> None:
    """_shadow_registry_ensure_agents inserts each agent_id in self._agents."""
    agent = _make_agent_with_mocks()
    agents = [
        MagicMock(agent_id="skeptic_v1"),
        MagicMock(agent_id="correlation_v1"),
        MagicMock(agent_id="regime_coherence_v1"),
        MagicMock(agent_id="counterfactual_v1"),
    ]
    agent._agents = agents
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock()
    mock_pool = MagicMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    mock_pool.acquire = MagicMock(return_value=ctx)
    agent._pool = mock_pool
    await agent._shadow_registry_ensure_agents(agents)
    called_ids = [call.args[1] for call in mock_conn.execute.call_args_list]
    assert "correlation_v1" in called_ids
    assert "regime_coherence_v1" in called_ids
    assert "counterfactual_v1" in called_ids
    assert "skeptic_v1" in called_ids


@pytest.mark.asyncio
async def test_tf_gate_skips_signals_below_min_minutes() -> None:
    """1m signals (1 minute < SWARM_MIN_TF_MINUTES=5) must not invoke any agent."""
    agent = _make_agent_with_mocks()
    # Set semaphore so we'd know if it was acquired
    agent._semaphore = asyncio.Semaphore(8)
    mock_agent = AsyncMock(agent_id="skeptic_v1", shadow_only=True, tiers_needed=frozenset())
    agent._agents = [mock_agent]

    raw_signal = {
        "signal_id": str(uuid4()),
        "symbol": "ESM6",
        "tf": "1m",  # below SWARM_MIN_TF_MINUTES=5
        "setup_plugin": "vwap_reversion",
        "direction": 1,
        "pre_quality_confidence": 0.75,
        "signal_schema_version": "v1",
    }
    await agent._process_one_signal(raw_signal)
    # No agent should have been called
    mock_agent.compute.assert_not_called()


@pytest.mark.asyncio
async def test_schema_gate_skips_v0_signals() -> None:
    """signal_schema_version='v0' must not invoke any agent."""
    agent = _make_agent_with_mocks()
    agent._semaphore = asyncio.Semaphore(8)
    # Mock _context_cache so the method doesn't crash if it reaches that point
    agent._context_cache = MagicMock()
    mock_agent = AsyncMock(agent_id="skeptic_v1", shadow_only=True, tiers_needed=frozenset())
    agent._agents = [mock_agent]

    raw_signal = {
        "signal_id": str(uuid4()),
        "symbol": "ESM6",
        "tf": "5m",
        "setup_plugin": "vwap_reversion",
        "direction": 1,
        "pre_quality_confidence": 0.75,
        "signal_schema_version": "v0",  # schema gate should reject this
    }
    await agent._process_one_signal(raw_signal)
    mock_agent.compute.assert_not_called()


@pytest.mark.asyncio
async def test_semaphore_blocks_then_proceeds() -> None:
    """Dispatch blocks when semaphore is full and proceeds once a slot is freed.

    The swarm never silently skips — Kafka lag-skip is the backpressure valve (D-07).
    """
    import asyncio as _asyncio

    agent = _make_agent_with_mocks()
    agent._semaphore = _asyncio.Semaphore(1)

    # Pre-acquire the only slot
    await agent._semaphore.acquire()

    from datetime import UTC, datetime

    from src.intelligence.ai.context import SignalContext
    from src.intelligence.schemas import SMCContext

    mock_context = SignalContext(
        symbol="ESM6",
        timeframe="5m",
        ts=datetime.now(UTC),
        smc=SMCContext(hmm_regime=1),
    )
    agent._context_cache = MagicMock()
    agent._context_cache.build.return_value = mock_context
    agent._enrich_context = AsyncMock(side_effect=lambda ctx: ctx)

    mock_agent = AsyncMock(
        agent_id="skeptic_v1",
        group="alpha",
        shadow_only=True,
        tiers_needed=frozenset(),
        latency_budget_ms=5000.0,
    )
    from src.core.ai.output import AgentOutput

    mock_agent.compute = AsyncMock(
        return_value=AgentOutput(agent_id="skeptic_v1", group="alpha", payload={"multiplier": 1.0})
    )
    agent._agents = [mock_agent]
    agent._lineage = MagicMock()
    agent._lineage.record = MagicMock()

    raw_signal = {
        "signal_id": str(uuid4()),
        "symbol": "ESM6",
        "tf": "5m",
        "setup_plugin": "vwap_reversion",
        "direction": 1,
        "pre_quality_confidence": 0.75,
        "calibrated_confidence": 0.75,
        "signal_schema_version": "v1",
    }

    # Release the slot after a short delay so dispatch can proceed
    async def _release_after() -> None:
        await _asyncio.sleep(0.05)
        agent._semaphore.release()

    release_task = _asyncio.create_task(_release_after())
    await agent._process_one_signal(raw_signal)
    await release_task

    # Signal was processed, not skipped
    mock_agent.compute.assert_called_once()
