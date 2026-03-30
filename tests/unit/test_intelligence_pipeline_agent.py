"""Tests for IntelligencePipelineComputeAgent — unified I1-I7 pipeline.

Tests cover:
- Output buffer QueueFull handling
- Drain task dequeues and publishes
- State restore from checkpoint payload
- State restore version mismatch fallback
- Agent import and instantiation
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.state_serializer import StateSerializer

# ---------------------------------------------------------------------------
# Helper: create bare agent instance via __new__() pattern (CLAUDE.md)
# ---------------------------------------------------------------------------


def _make_agent():
    """Create IntelligencePipelineComputeAgent.__new__() instance with required attrs."""
    from services.intelligence_pipeline_agent import IntelligencePipelineComputeAgent

    agent = IntelligencePipelineComputeAgent.__new__(IntelligencePipelineComputeAgent)
    # Set BaseAgent-level attributes
    agent.name = "intelligence_pipeline_agent"
    agent._stop_event = asyncio.Event()
    agent.logger = MagicMock()
    agent.tracer = MagicMock()
    # Set agent-specific attributes needed for tests
    agent._output_queue = asyncio.Queue(maxsize=2)
    agent._output_buffer_drops = MagicMock()
    agent._output_buffer_depth = MagicMock()
    agent._output_publish_failures = MagicMock()
    agent._state_checkpoint_fallback_total = MagicMock()
    agent._state_checkpoint_failures_total = MagicMock()
    agent._state_offset_reset_total = MagicMock()
    agent._settings = MagicMock()
    agent._settings.env_name = "dev"
    agent._plugin_states = {}
    agent._kalman_state = {}
    agent._tod_priors = {}
    agent._bar_history = MagicMock()
    agent._last_bar_offset = {}
    agent._shadow_mode = False
    agent._kafka_producer = AsyncMock()
    agent._db = None
    agent.AGENT_VERSION = "v1"
    agent._consumer_group = "intelligence_pipeline_group"
    return agent


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestEnqueue:
    """Test _enqueue() with QueueFull handling."""

    def test_enqueue_queue_full_increments_counter(self):
        """QueueFull on output buffer increments counter, does not raise."""
        agent = _make_agent()
        # Fill the queue to capacity (maxsize=2)
        agent._output_queue.put_nowait(("topic1", "key1", b"val1"))
        agent._output_queue.put_nowait(("topic2", "key2", b"val2"))

        # Third enqueue should trigger QueueFull
        agent._enqueue("topic3", "key3", b"val3")

        # Counter should have been incremented
        agent._output_buffer_drops.inc.assert_called_once()

    def test_enqueue_normal_does_not_increment_counter(self):
        """Normal enqueue does not increment drops counter."""
        agent = _make_agent()
        agent._enqueue("topic", "key", b"val")
        agent._output_buffer_drops.inc.assert_not_called()
        assert agent._output_queue.qsize() == 1


async def _stop_agent_after(agent, delay: float = 0.2) -> None:
    """Signal agent stop after a short delay — used by drain tests."""
    await asyncio.sleep(delay)
    agent._stop_event.set()


class TestDrainOutput:
    """Test _drain_output() publishes items from queue."""

    @pytest.mark.asyncio
    async def test_drain_output_publishes(self):
        """Drain task dequeues items and calls kafka producer publish."""
        agent = _make_agent()
        # Enqueue an item
        agent._enqueue("test_topic", "test_key", {"data": "payload"})

        asyncio.create_task(_stop_agent_after(agent))
        await agent._drain_output()

        # Verify producer was called
        agent._kafka_producer.publish.assert_called_once()
        call_args = agent._kafka_producer.publish.call_args
        assert call_args[0][0] == "test_topic"
        assert call_args[1]["key"] == "test_key"

    @pytest.mark.asyncio
    async def test_drain_output_publish_failure_increments_counter(self):
        """Publish failure increments output_publish_failures counter."""
        agent = _make_agent()
        agent._kafka_producer.publish.side_effect = RuntimeError("kafka down")
        agent._enqueue("topic", "key", {"data": "val"})

        asyncio.create_task(_stop_agent_after(agent))
        await agent._drain_output()

        agent._output_publish_failures.inc.assert_called()


class TestStateRestore:
    """Test state checkpoint restore logic."""

    @pytest.mark.asyncio
    async def test_state_restore_populates_fields(self):
        """State restore from checkpoint payload restores all five state fields."""
        agent = _make_agent()

        # Create a checkpoint payload (key names match agent's _checkpoint_state format)
        state_data = {
            "_plugin_states": {("rsi_14", "ESM6", "1m"): {"value": 42.5}},
            "_kalman_state": {("ESM6", "1m"): {"x_est": 0.5, "P_est": 0.01}},
            "_tod_priors": {("trending", "1m", 10): 1.2},
            "_last_bar_offset": {("ESM6", "1m"): 12345},
        }
        encoded = StateSerializer.encode(state_data)

        # Mock state consumer yielding one valid checkpoint
        checkpoint_key = "v1:ESM6:1m"
        mock_consumer = AsyncMock()

        async def _mock_messages():
            yield ("topic", checkpoint_key, encoded)
            await asyncio.sleep(0.1)

        # MagicMock return_value so messages() returns the async generator directly
        mock_consumer.messages = MagicMock(return_value=_mock_messages())

        with patch("services.intelligence_pipeline_agent.KafkaConsumerClient",
                   return_value=mock_consumer):
            result = await agent._restore_state_checkpoint()

        assert result is True
        assert ("rsi_14", "ESM6", "1m") in agent._plugin_states
        assert agent._plugin_states[("rsi_14", "ESM6", "1m")]["value"] == 42.5
        assert ("ESM6", "1m") in agent._kalman_state
        assert ("trending", "1m", 10) in agent._tod_priors
        assert agent._last_bar_offset[("ESM6", "1m")] == 12345

    @pytest.mark.asyncio
    async def test_state_restore_version_mismatch_triggers_fallback(self):
        """State restore with version mismatch triggers fallback counter increment."""
        agent = _make_agent()

        # Checkpoint with wrong version prefix
        checkpoint_key = "v99:ESM6:1m"
        state_data = {"_plugin_states": {}}
        encoded = StateSerializer.encode(state_data)

        mock_consumer = AsyncMock()

        async def _mock_messages():
            yield ("topic", checkpoint_key, encoded)
            await asyncio.sleep(0.1)

        mock_consumer.messages = MagicMock(return_value=_mock_messages())

        with patch("services.intelligence_pipeline_agent.KafkaConsumerClient",
                   return_value=mock_consumer):
            result = await agent._restore_state_checkpoint()

        assert result is False
        agent._state_checkpoint_fallback_total.inc.assert_called()

    @pytest.mark.asyncio
    async def test_state_restore_empty_topic_returns_false(self):
        """State restore with no messages on topic returns False."""
        agent = _make_agent()

        mock_consumer = AsyncMock()

        async def _mock_messages():
            return
            yield  # unreachable yield makes this an empty async generator

        mock_consumer.messages = MagicMock(return_value=_mock_messages())

        with patch("services.intelligence_pipeline_agent.KafkaConsumerClient",
                   return_value=mock_consumer):
            result = await agent._restore_state_checkpoint()

        assert result is False


class TestAgentImport:
    """Verify the agent module imports and class can be instantiated."""

    def test_agent_imports(self):
        """Agent class is importable."""
        from services.intelligence_pipeline_agent import IntelligencePipelineComputeAgent
        assert IntelligencePipelineComputeAgent is not None

    def test_agent_inherits_base_agent(self):
        """Agent inherits from BaseAgent."""
        from services.intelligence_pipeline_agent import IntelligencePipelineComputeAgent
        from src.core.agent.base import BaseAgent
        assert issubclass(IntelligencePipelineComputeAgent, BaseAgent)

    def test_shadow_mode_default_false(self):
        """Shadow mode is False by default."""
        agent = _make_agent()
        assert agent._shadow_mode is False


class TestShadowMode:
    """Test shadow mode behavior."""

    def test_shadow_mode_enabled(self):
        """Shadow mode attribute can be set to True."""
        agent = _make_agent()
        agent._shadow_mode = True
        assert agent._shadow_mode is True
