"""Interim acceptance tests for IntelligencePipelineComputeAgent._assemble_checkpoint_extra.

These tests document the cross-plan ordering hazard introduced in Plan 02:
- After Plan 02 the orchestrator reads cross-owned fields from its own attributes.
- Plan 03 will migrate tod_priors source -> self._cache_mgr.tod_priors
- Plan 05 will migrate kalman_state / setup_last_fire -> self._sig_proc.get_*()

The no-plugin_states assertion is the permanent contract (HIGH finding 5 regression guard).
"""

from __future__ import annotations

from tests.unit.pipeline_helpers import make_agent


def test_assemble_checkpoint_extra_keys_are_exactly_cross_owned():
    """_assemble_checkpoint_extra must return exactly the four cross-owned fields.

    Plan 02 interim form: reads orchestrator-owned attributes directly.
    Plans 03/05 will change the SOURCE of values (not the keys).

    Asserts HIGH finding 5: 'plugin_states' must NOT appear in the returned dict.
    """
    agent = make_agent()
    # Seed cross-owned attrs with recognisable values
    agent._kalman_state = {"k1": 1.0}
    agent._tod_priors = {"t1": 0.5}
    agent._last_bar_offset = {"p:0": 42}
    agent._setup_last_fire = {"s1": {"bars_since": 3}}

    result = agent._assemble_checkpoint_extra()

    # Exact key set — no plugin_states, no extra keys
    assert set(result.keys()) == {
        "kalman_state",
        "tod_priors",
        "last_bar_offset",
        "setup_last_fire",
    }

    # HIGH finding 5 regression guard: plugin_states MUST NOT be in extra_state
    assert "plugin_states" not in result

    # Values reflect what was seeded
    assert result["kalman_state"] == {"k1": 1.0}
    assert result["tod_priors"] == {"t1": 0.5}
    assert result["last_bar_offset"] == {"p:0": 42}
    assert result["setup_last_fire"] == {"s1": {"bars_since": 3}}


def test_assemble_checkpoint_extra_plugin_states_not_present_when_state_mgr_has_data():
    """plugin_states must not leak into extra_state even when PluginStateManager has data.

    Regression guard: if someone adds plugin_states to _assemble_checkpoint_extra by
    mistake, write_checkpoint will raise ValueError — this test catches it earlier.
    """
    agent = make_agent()
    # Populate plugin state in the manager
    agent._state_mgr.update(("plugA", "ES", "1m"), {"x": 1})
    agent._kalman_state = {}
    agent._tod_priors = {}
    agent._last_bar_offset = {}
    agent._setup_last_fire = {}

    result = agent._assemble_checkpoint_extra()

    assert "plugin_states" not in result
    # The extra state must be passable directly to write_checkpoint without raising
    # (write_checkpoint raises if plugin_states is in extra_state)
    agent._state_mgr.write_checkpoint(result)  # must not raise
