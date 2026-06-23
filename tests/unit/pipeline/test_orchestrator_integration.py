"""Orchestrator integration tests — checkpoint write delegation.

v3.0 pipeline: IntelligencePipeline is a FeatureFactory compute + publish daemon.
The old v2.x signal processing routing tests (i7/DLQ topics, SignalProcessor,
PluginExecutor state threading) were deleted when that architecture was replaced.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.unit.pipeline.pipeline_helpers import make_agent


@pytest.mark.asyncio
async def test_orchestrator_writes_checkpoint_via_state_manager_only():
    """Checkpoint write goes through PluginStateManager; extra_state must NOT contain plugin_states."""
    agent = make_agent()
    agent._assemble_checkpoint_extra = MagicMock(
        return_value={
            "kalman_state": {},
            "setup_last_fire": {},
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
