"""Test pipeline exception isolation — plugin failure graceful degradation.

Proves PIPE-05: a single plugin exception never crashes the pipeline;
remaining plugins complete and PLUGIN_ERRORS_TOTAL / PLUGIN_DURATION_MS fire correctly.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from services.intelligence_pipeline_agent import I7_PLUGINS
from src.intelligence.register_plugins import TIER_I1
from tests.unit.pipeline_helpers import deterministic_plugin, make_agent, signal_plugin


def _failing_plugin(error_cls=RuntimeError, msg="injected failure"):
    """Plugin whose compute_full always raises error_cls(msg)."""

    class FailingPlugin:
        def compute_full(self, frames):
            raise error_cls(msg)

    return FailingPlugin()


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
        agent._plugin_cache[plugin_names[0]] = _failing_plugin()
        for i, name in enumerate(plugin_names[1:], start=1):
            agent._plugin_cache[name] = deterministic_plugin({f"{name}_val": float(i)})

        frames = {"main": MagicMock()}
        result = await agent._run_i1(frames, "ES", "1m")

        assert isinstance(result, dict), f"Expected dict, got {type(result)}"
        for name in plugin_names[1:]:
            key = f"{name}_val"
            assert key in result, f"Missing key '{key}' from successful plugin"
        assert f"{plugin_names[0]}_val" not in result

    @pytest.mark.asyncio
    async def test_all_i1_plugins_raise_returns_empty(self):
        """All I1 plugins fail — _run_i1 returns empty dict without crashing."""
        agent = make_agent()

        for name in TIER_I1[:5]:
            agent._plugin_cache[name] = _failing_plugin()

        frames = {"main": MagicMock()}
        result = await agent._run_i1(frames, "ES", "1m")

        assert isinstance(result, dict), f"Expected dict, got {type(result)}"
        assert result == {}, f"Expected empty dict, got keys: {list(result.keys())}"

    @pytest.mark.asyncio
    async def test_single_i7_plugin_raises_does_not_crash(self):
        """One failing I7 plugin — remaining succeed, signal ranking proceeds."""
        agent = make_agent()

        plugin_names = I7_PLUGINS[:3]
        agent._plugin_cache[plugin_names[0]] = _failing_plugin()
        agent._plugin_cache[plugin_names[1]] = signal_plugin(plugin_names[1], direction=1)
        agent._plugin_cache[plugin_names[2]] = signal_plugin(plugin_names[2], direction=-1)

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

        with (
            patch("services.intelligence_pipeline_agent._build_features_from_event", return_value={}),
            patch("services.intelligence_pipeline_agent.apply_quality_gate", side_effect=lambda sigs, *a, **kw: sigs),
            patch("services.intelligence_pipeline_agent.apply_regime_gate", side_effect=lambda sigs, *a, **kw: sigs),
            patch("services.intelligence_pipeline_agent.apply_tod_adjustment", side_effect=lambda sigs, *a, **kw: sigs),
            patch("services.intelligence_pipeline_agent.apply_calibration", side_effect=lambda sigs, *a, **kw: sigs),
            patch("services.intelligence_pipeline_agent.rank_signals", side_effect=lambda sigs, *a, **kw: sigs),
            patch("services.intelligence_pipeline_agent.select_winner", return_value=None),
            patch("services.intelligence_pipeline_agent._apply_alpha_decay"),
        ):
            result = await agent._run_i7(bar, event, {})

        assert "ranked" in result, "Expected 'ranked' key in result"
        assert isinstance(result["ranked"], list)
        assert len(result["ranked"]) == 2

    @pytest.mark.asyncio
    async def test_error_counter_increments_on_exception(self):
        """PLUGIN_ERRORS_TOTAL.labels(plugin_name, tier).inc() called when plugin raises."""
        agent = make_agent()

        failing_name = TIER_I1[0]
        agent._plugin_cache[failing_name] = _failing_plugin()

        frames = {"main": MagicMock()}

        with patch("services.intelligence_pipeline_agent.PLUGIN_ERRORS_TOTAL") as mock_errors:
            await agent._run_i1(frames, "ES", "1m")

        mock_errors.labels.assert_called_with(plugin_name=failing_name, tier="I1")
        mock_errors.labels.return_value.inc.assert_called()

    @pytest.mark.asyncio
    async def test_plugin_duration_recorded_on_success(self):
        """PLUGIN_DURATION_MS.labels(plugin_name, tier).observe() called with positive value."""
        agent = make_agent()

        plugin_name = TIER_I1[0]
        agent._plugin_cache[plugin_name] = deterministic_plugin({"some_key": 1.0})

        frames = {"main": MagicMock()}

        with patch("services.intelligence_pipeline_agent.PLUGIN_DURATION_MS") as mock_duration:
            await agent._run_i1(frames, "ES", "1m")

        mock_duration.labels.assert_called_with(plugin_name=plugin_name, tier="I1")
        observe_mock = mock_duration.labels.return_value.observe
        observe_mock.assert_called()

        call_args = observe_mock.call_args_list
        assert len(call_args) >= 1, "observe() was never called"
        duration_value = call_args[0][0][0]
        assert isinstance(duration_value, (int, float)), (
            f"Expected numeric duration, got {type(duration_value)}"
        )
        assert duration_value >= 0, f"Duration must be non-negative, got {duration_value}"

    @pytest.mark.asyncio
    async def test_partial_output_propagates_to_downstream(self):
        """Failing plugins produce no keys; succeeding plugins' keys all appear in output."""
        agent = make_agent()

        plugin_names = TIER_I1[:5]
        agent._plugin_cache[plugin_names[0]] = _failing_plugin()
        agent._plugin_cache[plugin_names[2]] = _failing_plugin()
        agent._plugin_cache[plugin_names[1]] = deterministic_plugin({"p1_key": 1})
        agent._plugin_cache[plugin_names[3]] = deterministic_plugin({"p3_key": 3})
        agent._plugin_cache[plugin_names[4]] = deterministic_plugin({"p4_key": 4})

        frames = {"main": MagicMock()}
        result = await agent._run_i1(frames, "ES", "1m")

        assert "p1_key" in result, "Key p1_key missing from successful plugin 1"
        assert "p3_key" in result, "Key p3_key missing from successful plugin 3"
        assert "p4_key" in result, "Key p4_key missing from successful plugin 4"
        assert result["p1_key"] == 1
        assert result["p3_key"] == 3
        assert result["p4_key"] == 4


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
