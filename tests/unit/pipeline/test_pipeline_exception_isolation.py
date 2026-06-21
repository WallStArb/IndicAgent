"""Test pipeline exception isolation — plugin failure graceful degradation.

Proves PIPE-05: a single plugin exception never crashes the pipeline;
remaining plugins complete and PLUGIN_ERRORS_TOTAL / PLUGIN_DURATION_MS fire correctly.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.intelligence.register_plugins import TIER_I1
from src.intelligence.register_plugins import TIER_I7 as I7_PLUGINS
from tests.unit.pipeline.pipeline_helpers import deterministic_plugin, make_agent, signal_plugin


def _failing_plugin(error_cls=RuntimeError, msg="injected failure"):
    """Plugin whose compute_full always raises error_cls(msg)."""

    class FailingPlugin:
        supports_incremental = False

        def compute_full(self, frames, *, state=None):
            raise error_cls(msg)

    return FailingPlugin()


# Helper: run executor.run_i1 with minimal state plumbing
async def _run_i1_via_executor(agent, frames, symbol="ES", tf="1m"):
    """Run I1 tier via PluginExecutor with empty state (mirrors orchestrator flow)."""
    plugin_states = agent._state_mgr.get_all_states_for(symbol, tf)
    lock = agent._state_mgr.get_lock((symbol, tf))
    result, _state_updates = await agent._executor.run_i1(
        plugin_states, lock, frames, symbol, tf, shadow_cache={}
    )
    return result


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestExceptionIsolation:
    """Prove plugin exceptions never crash the pipeline — graceful degradation."""

    @pytest.mark.asyncio
    async def test_single_i1_plugin_raises_does_not_crash(self):
        """One failing I1 plugin — remaining 4 succeed, pipeline returns their output."""
        agent = make_agent()

        plugin_names = TIER_I1[:5]
        agent._executor._plugin_cache[plugin_names[0]] = _failing_plugin()
        for i, name in enumerate(plugin_names[1:], start=1):
            agent._executor._plugin_cache[name] = deterministic_plugin({f"{name}_val": float(i)})

        frames = {"main": MagicMock()}
        result = await _run_i1_via_executor(agent, frames)

        assert isinstance(result, dict), f"Expected dict, got {type(result)}"
        for name in plugin_names[1:]:
            key = f"{name}_val"
            assert key in result, f"Missing key '{key}' from successful plugin"
        assert f"{plugin_names[0]}_val" not in result

    @pytest.mark.asyncio
    async def test_all_i1_plugins_raise_returns_empty(self):
        """All I1 plugins fail — run_i1 returns empty dict without crashing."""
        agent = make_agent()

        for name in TIER_I1[:5]:
            agent._executor._plugin_cache[name] = _failing_plugin()

        frames = {"main": MagicMock()}
        result = await _run_i1_via_executor(agent, frames)

        assert isinstance(result, dict), f"Expected dict, got {type(result)}"
        assert result == {}, f"Expected empty dict, got keys: {list(result.keys())}"

    @pytest.mark.asyncio
    async def test_single_i7_plugin_raises_does_not_crash(self):
        """One failing I7 plugin — remaining succeed, signal ranking proceeds."""
        agent = make_agent()

        plugin_names = I7_PLUGINS[:3]
        agent._executor._plugin_cache[plugin_names[0]] = _failing_plugin()
        agent._executor._plugin_cache[plugin_names[1]] = signal_plugin(plugin_names[1], direction=1)
        agent._executor._plugin_cache[plugin_names[2]] = signal_plugin(
            plugin_names[2], direction=-1
        )

        bar = MagicMock()
        bar.symbol = "ES"
        bar.tf = "1m"

        event = MagicMock()
        event.i1 = MagicMock()
        event.i1.model_dump.return_value = {}
        event.i2 = None
        event.i3 = None
        event.i4 = None
        event.i5 = None
        event.smc = None
        event.i6 = None

        from src.intelligence.pipeline.signal_processor import CacheSnapshot

        snapshot = CacheSnapshot(
            perf_weights={},
            calibration_curves={},
            drift_penalties={},
            cis_weights={},
            cis_weights_version=0,
        )

        with (
            patch(
                "src.intelligence.pipeline.signal_processor.build_flat_features",
                return_value={},
            ),
            patch(
                "src.intelligence.pipeline.signal_processor.apply_quality_gate",
                side_effect=lambda sigs, *a, **kw: sigs,
            ),
            patch(
                "src.intelligence.pipeline.signal_processor.apply_regime_gate",
                side_effect=lambda sigs, *a, **kw: sigs,
            ),
            # Phase 112 D-04: apply_calibration removed from signal_processor
            patch(
                "src.intelligence.pipeline.signal_processor.rank_signals",
                side_effect=lambda sigs, *a, **kw: sigs,
            ),
            patch(
                "src.intelligence.pipeline.signal_processor.select_winner",
                return_value=(None, [], "no_signal"),
            ),
        ):
            result = await agent._sig_proc.process(
                event, {}, bar, "ES", "1m", raw_signals=[], cache_snapshot=snapshot
            )

        assert result.i7_result is not None, "Expected i7_result in SignalProcessorResult"
        assert isinstance(result.i7_result["ranked"], list)
        assert len(result.i7_result["ranked"]) == 0  # raw_signals=[] so no signals to process

    @pytest.mark.asyncio
    async def test_error_counter_increments_on_exception(self):
        """PLUGIN_ERRORS_TOTAL.add(1, {plugin_name, tier}) called when plugin raises."""
        agent = make_agent()

        failing_name = TIER_I1[0]
        agent._executor._plugin_cache[failing_name] = _failing_plugin()

        frames = {"main": MagicMock()}

        mock_observer = MagicMock()
        agent._executor._observer = mock_observer

        await _run_i1_via_executor(agent, frames)

        mock_observer.record_error.assert_called()
        call = mock_observer.record_error.call_args_list[0]
        assert (
            call.args[0] == failing_name
        ), f"Expected plugin_name={failing_name!r}, got {call.args[0]!r}"

    @pytest.mark.asyncio
    async def test_plugin_duration_recorded_on_success(self):
        """PLUGIN_DURATION_MS.record(value, {plugin_name, tier}) called with positive value."""
        agent = make_agent()

        plugin_name = TIER_I1[0]
        agent._executor._plugin_cache[plugin_name] = deterministic_plugin({"some_key": 1.0})

        frames = {"main": MagicMock()}

        mock_observer = MagicMock()
        agent._executor._observer = mock_observer

        await _run_i1_via_executor(agent, frames)

        mock_observer.record_result.assert_called()
        call = mock_observer.record_result.call_args_list[0]
        duration_ms = call.args[2]
        assert isinstance(
            duration_ms, (int, float)
        ), f"Expected numeric duration, got {type(duration_ms)}"
        assert duration_ms >= 0, f"Duration must be non-negative, got {duration_ms}"

    @pytest.mark.asyncio
    async def test_partial_output_propagates_to_downstream(self):
        """Failing plugins produce no keys; succeeding plugins' keys all appear in output."""
        agent = make_agent()

        plugin_names = TIER_I1[:5]
        agent._executor._plugin_cache[plugin_names[0]] = _failing_plugin()
        agent._executor._plugin_cache[plugin_names[2]] = _failing_plugin()
        agent._executor._plugin_cache[plugin_names[1]] = deterministic_plugin({"p1_key": 1})
        agent._executor._plugin_cache[plugin_names[3]] = deterministic_plugin({"p3_key": 3})
        agent._executor._plugin_cache[plugin_names[4]] = deterministic_plugin({"p4_key": 4})

        frames = {"main": MagicMock()}
        result = await _run_i1_via_executor(agent, frames)

        assert "p1_key" in result, "Key p1_key missing from successful plugin 1"
        assert "p3_key" in result, "Key p3_key missing from successful plugin 3"
        assert "p4_key" in result, "Key p4_key missing from successful plugin 4"
        assert result["p1_key"] == 1
        assert result["p3_key"] == 3
        assert result["p4_key"] == 4


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
