"""Acceptance tests for IntelligencePipelineComputeAgent._assemble_checkpoint_extra.

Post-plan-05 form (final):
- tod_priors reads from self._cache_mgr.tod_priors (migrated in Plan 03)
- kalman_state reads from self._sig_proc.get_kalman_state() (migrated in Plan 05)
- setup_last_fire reads from self._sig_proc.get_setup_last_fire() (migrated in Plan 05)

The no-plugin_states assertion is the permanent contract (HIGH finding 5 regression guard).
"""

from __future__ import annotations

from tests.unit.pipeline.pipeline_helpers import make_agent


def test_assemble_checkpoint_extra_keys_are_exactly_cross_owned():
    """_assemble_checkpoint_extra must return exactly the four cross-owned fields.

    Final form (plan 05): kalman_state and setup_last_fire read from SignalProcessor.

    Asserts HIGH finding 5: 'plugin_states' must NOT appear in the returned dict.
    """
    agent = make_agent()
    # Seed cross-owned attrs via their new owners
    agent._sig_proc.restore_kalman_state({"k1": 1.0})
    # tod_priors lives in CacheManager — seed via public API
    agent._cache_mgr.seed_tod_priors({"t1": 0.5})
    agent._last_bar_offset = {"p:0": 42}
    agent._sig_proc.restore_setup_last_fire({"s1": {"bars_since": 3}})

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
    # tod_priors flows from CacheManager (plan 03 migration)
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
    agent._last_bar_offset = {}
    # kalman_state and setup_last_fire are empty by default in SignalProcessor

    result = agent._assemble_checkpoint_extra()

    assert "plugin_states" not in result
    # The extra state must be passable directly to write_checkpoint without raising
    # (write_checkpoint raises if plugin_states is in extra_state)
    agent._state_mgr.write_checkpoint(result)  # must not raise
