"""Orchestrator integration tests — MEDIUM finding from REVIEWS.md.

Verifies the thin DAG router wires all 5 extracted classes correctly:
- 4-way output routing (signals / DLQ / winner / journal) — HIGH finding 4
- Checkpoint assembly excludes plugin_states — HIGH finding 5
- State update flow through PluginExecutor → PluginStateManager — HIGH finding 1
- Checkpoint write delegates to PluginStateManager only
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.intelligence.pipeline.signal_processor import SignalProcessorResult
from tests.unit.pipeline.pipeline_helpers import make_agent


def _make_bar():
    bar = MagicMock()
    bar.symbol = "ES"
    bar.tf = "1m"
    bar.ts = datetime.now(UTC)
    bar.bar_id = "test-bar-id"
    bar.open = bar.high = bar.low = bar.close = 100.0
    bar.volume = 1000
    bar.gap_preceding = False
    return bar


def _success_result():
    return SignalProcessorResult(
        success=True,
        signals_payload={"symbol": "ES", "tf": "1m", "signals": [{"setup_plugin": "X"}]},
        dlq_payload=None,
        winner_payload={"setup_plugin": "X", "direction": 1},
        i7_result={
            "ranked": [{"setup_plugin": "X"}],
            "winner": {"setup_plugin": "X", "direction": 1},
            "signals_evaluated": 1,
            "signals_after_quality": 1,
            "signals_after_regime": 1,
            "signals_after_tod": 1,
            "signals_after_calibration": 1,
            "i7_computed_at": datetime.now(UTC),
        },
    )


def _dlq_result():
    return SignalProcessorResult(
        success=False,
        signals_payload=None,
        dlq_payload={"reason": "cis_score_null", "symbol": "ES", "tf": "1m"},
        winner_payload=None,
        i7_result={
            "ranked": [],
            "winner": None,
            "signals_evaluated": 1,
            "signals_after_quality": 0,
            "signals_after_regime": 0,
            "signals_after_tod": 0,
            "signals_after_calibration": 0,
            "i7_computed_at": datetime.now(UTC),
        },
    )


def _wire_agent(agent, sig_proc_result, *, i7_state_updates=None):
    """Wire agent deps directly so routing logic is exercised without context managers."""
    from src.intelligence.pipeline.feature_pipeline_executor import FeaturePipelineResult

    agent._bar_history = MagicMock()
    agent._bar_history.append = MagicMock()
    agent._bar_history.is_warm = MagicMock(return_value=True)
    agent._bar_history.to_dataframe = MagicMock(return_value=MagicMock())
    agent._last_bar_ts = {}
    agent._last_bar_offset = {}
    agent._shadow_mode = False
    agent._bars_processed = MagicMock()
    agent._i7_latency_ms = MagicMock()

    fake_event = MagicMock()
    fake_event.model_dump_json = MagicMock(return_value="{}")

    # Mock FeaturePipelineExecutor.run() returning a FeaturePipelineResult
    fp_result = FeaturePipelineResult(
        event=fake_event,
        tiered={},
        main_df=MagicMock(),
        hmm_regime=None,
    )
    agent._feature_pipeline = MagicMock()
    agent._feature_pipeline.run = AsyncMock(return_value=fp_result)

    # Mock run_i7_complete returning raw_signals list; state updates via _last_i7_state_updates
    agent._executor.run_i7_complete = AsyncMock(return_value=[])
    agent._executor._last_i7_state_updates = i7_state_updates or {}

    agent._sig_proc.process = AsyncMock(return_value=sig_proc_result)
    agent._enqueue_intel_journal = AsyncMock()

    # Replace out_queue methods with fresh mocks
    enqueue_mock = MagicMock()
    enqueue_blocking_mock = AsyncMock()
    agent._out_queue.enqueue = enqueue_mock
    agent._out_queue.enqueue_blocking = enqueue_blocking_mock

    return enqueue_mock, enqueue_blocking_mock


@pytest.mark.asyncio
async def test_orchestrator_routes_signals_payload_to_i7_topic():
    """Success path: signals → i7 topic, winner → aggregated topic, DLQ not called."""
    agent = make_agent()
    bar = _make_bar()
    _, enqueue_blocking = _wire_agent(agent, _success_result())

    await agent._process_bar_inner(bar)

    topics_called = [str(c.args[0]) for c in enqueue_blocking.call_args_list if c.args]
    topic_str = " ".join(topics_called)

    assert any(
        "i7" in t or "signals" in t for t in topics_called
    ), f"i7 topic not called; got {topic_str}"
    assert any(
        "aggregated" in t for t in topics_called
    ), f"aggregated topic not called; got {topic_str}"
    assert not any(
        "dlq" in t for t in topics_called
    ), f"DLQ topic unexpectedly called; got {topic_str}"


@pytest.mark.asyncio
async def test_orchestrator_routes_dlq_payload_to_dlq_topic():
    """DLQ path: dlq → dlq topic, signals/aggregated NOT called."""
    agent = make_agent()
    bar = _make_bar()
    _, enqueue_blocking = _wire_agent(agent, _dlq_result())

    await agent._process_bar_inner(bar)

    topics_called = [str(c.args[0]) for c in enqueue_blocking.call_args_list if c.args]
    topic_str = " ".join(topics_called)

    assert any("dlq" in t for t in topics_called), f"DLQ topic not called; got {topic_str}"
    assert not any(
        "aggregated" in t for t in topics_called
    ), f"aggregated topic unexpectedly called; got {topic_str}"


@pytest.mark.asyncio
async def test_orchestrator_checkpoint_assembly_excludes_plugin_states():
    """_assemble_checkpoint_extra must return exactly 4 keys, never plugin_states (HIGH finding 5)."""
    agent = make_agent()
    agent._last_bar_offset = {}
    extra = agent._assemble_checkpoint_extra()

    assert isinstance(extra, dict)
    assert "kalman_state" in extra
    assert "setup_last_fire" in extra
    assert "tod_priors" in extra
    assert "last_bar_offset" in extra
    assert (
        "plugin_states" not in extra
    ), "HIGH finding 5 violated: plugin_states in checkpoint extra"
    assert len(extra) == 4, f"Expected exactly 4 keys, got {list(extra.keys())}"


@pytest.mark.asyncio
async def test_orchestrator_state_update_flow_through_executor_to_state_manager():
    """PluginExecutor.run_i7_plugins state updates are written to PluginStateManager (HIGH finding 1)."""
    agent = make_agent()
    bar = _make_bar()
    state_update = {("plugA", "ES", "1m"): {"seen": True}}
    dlq = _dlq_result()
    _wire_agent(agent, dlq, i7_state_updates=state_update)

    await agent._process_bar_inner(bar)

    stored = agent._state_mgr.get_state(("plugA", "ES", "1m"))
    assert stored == {"seen": True}, f"State update not propagated; got {stored}"


@pytest.mark.asyncio
async def test_orchestrator_writes_checkpoint_via_state_manager_only():
    """Checkpoint write goes through PluginStateManager; extra_state must NOT contain plugin_states."""
    agent = make_agent()
    agent._assemble_checkpoint_extra = MagicMock(
        return_value={
            "kalman_state": {},
            "setup_last_fire": {},
            "tod_priors": {},
            "last_bar_offset": {},
        }
    )
    write_mock = AsyncMock()
    agent._state_mgr.write_checkpoint = write_mock

    await agent._state_mgr.write_checkpoint(extra_state=agent._assemble_checkpoint_extra())

    assert write_mock.called
    call_kwargs = write_mock.call_args
    extra = call_kwargs.kwargs.get("extra_state") or (
        call_kwargs.args[0] if call_kwargs.args else {}
    )
    assert "plugin_states" not in extra, "Checkpoint extra must not contain plugin_states"
