"""Acceptance tests for IntelligencePipeline._assemble_checkpoint_extra.

Post-plan-06 form (D-09 cutover):
- SignalProcessor and PluginStateManager removed in P6 pipeline rewrite
- Checkpoint is now minimal: only last_bar_offset

The no-plugin_states assertion is the permanent contract (HIGH finding 5 regression guard).
"""

from __future__ import annotations

from tests.unit.pipeline.pipeline_helpers import make_agent


def test_assemble_checkpoint_extra_keys_are_exactly_cross_owned():
    """_assemble_checkpoint_extra must return exactly last_bar_offset.

    P6 form: kalman_state and setup_last_fire removed (SignalProcessor retired).
    Only last_bar_offset remains as the checkpoint field.

    Asserts HIGH finding 5: 'plugin_states' must NOT appear in the returned dict.
    """
    agent = make_agent()
    agent._last_bar_offset = {"p:0": 42}

    result = agent._assemble_checkpoint_extra()

    # Exact key set — no plugin_states, no extra keys
    assert set(result.keys()) == {
        "last_bar_offset",
    }

    # HIGH finding 5 regression guard: plugin_states MUST NOT be in extra_state
    assert "plugin_states" not in result

    # Values reflect what was seeded
    assert result["last_bar_offset"] == {"p:0": 42}


def test_assemble_checkpoint_extra_plugin_states_not_present():
    """plugin_states must not appear in extra_state after D-09 cutover.

    Regression guard: if someone adds plugin_states to _assemble_checkpoint_extra by
    mistake, this test catches it.
    """
    agent = make_agent()
    agent._last_bar_offset = {}

    result = agent._assemble_checkpoint_extra()

    assert "plugin_states" not in result
    assert "kalman_state" not in result
    assert "setup_last_fire" not in result
