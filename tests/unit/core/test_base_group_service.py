"""Unit tests for INFRA-04 and INFRA-06 in BaseGroupCoordinator / BaseAIWorker.

INFRA-04: _on_error emits AI_AGENT_ERRORS_TOTAL + publishes lineage when set.
INFRA-06: graduation stub deleted; LineageRecorder lifecycle in BaseGroupCoordinator;
          dispatch via override detection.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

from src.core.ai.base_agent import BaseAIWorker
from src.core.ai.output import AgentOutput
from src.intelligence.ai.context import SignalContext
from src.intelligence.ai.group_coordinator import BaseGroupCoordinator

# ---------------------------------------------------------------------------
# Minimal test doubles
# ---------------------------------------------------------------------------


class ConcreteAIAgent(BaseAIWorker):
    """Minimal concrete BaseAIWorker for testing _on_error hooks."""

    agent_id = "test_agent"
    group = "alpha"
    tiers_needed = frozenset()

    async def _compute(self, context: SignalContext) -> AgentOutput:
        return AgentOutput(
            agent_id=self.agent_id,
            group=self.group,
            output_type="neutral",
            payload={},
        )

    async def _run(self) -> None:
        """No-op — test double is compute-only."""
        pass


# ---------------------------------------------------------------------------
# INFRA-06: Graduation stub removal and class attribute checks
# ---------------------------------------------------------------------------


def test_group_coordinator_has_no_graduation_attr():
    """INFRA-06: has_graduation and _graduation_loop stub must be deleted from base."""
    assert not hasattr(
        BaseGroupCoordinator, "has_graduation"
    ), "has_graduation class attribute must be deleted from BaseGroupCoordinator"
    assert not hasattr(
        BaseGroupCoordinator, "_graduation_loop"
    ), "_graduation_loop stub must be deleted from BaseGroupCoordinator"


# ---------------------------------------------------------------------------
# INFRA-04: _on_error counter + lineage
# ---------------------------------------------------------------------------


def test_on_error_increments_ai_agent_errors_total():
    """INFRA-04: _on_error increments AI_AGENT_ERRORS_TOTAL with agent_id and error_type."""
    agent = ConcreteAIAgent()

    async def run():
        with patch("src.core.ai.base_agent.AI_AGENT_ERRORS_TOTAL") as mock_counter:
            await agent._on_error(RuntimeError("boom"))
            mock_counter.add.assert_called_once()
            call_args = mock_counter.add.call_args
            # First positional arg must be 1
            assert call_args[0][0] == 1
            labels = call_args[0][1]
            assert labels["agent_id"] == agent.agent_id
            assert labels["error_type"] == "RuntimeError"

    asyncio.run(run())


def test_on_error_publishes_to_lineage_when_set():
    """INFRA-04: _on_error calls lineage.record() with correct event_type and metadata."""
    agent = ConcreteAIAgent()
    mock_lineage = MagicMock()
    mock_lineage.record = MagicMock()
    agent._lineage = mock_lineage

    async def run():
        with patch("src.core.ai.base_agent.AI_AGENT_ERRORS_TOTAL"):
            await agent._on_error(ValueError("x"))
        assert mock_lineage.record.call_count == 1
        call_kwargs = mock_lineage.record.call_args[1]
        assert call_kwargs["event_type"] == "agent_prediction"
        assert call_kwargs["source"] == agent.agent_id
        metadata = call_kwargs["metadata"]
        assert metadata["error_type"] == "ValueError"

    asyncio.run(run())


def test_on_error_skips_lineage_when_none():
    """INFRA-04: _on_error does not raise when _lineage is None; counter still fires."""
    agent = ConcreteAIAgent()
    assert agent._lineage is None

    async def run():
        with patch("src.core.ai.base_agent.AI_AGENT_ERRORS_TOTAL") as mock_counter:
            # Must not raise AttributeError
            await agent._on_error(RuntimeError("y"))
            mock_counter.add.assert_called_once()

    asyncio.run(run())


# ---------------------------------------------------------------------------
# INFRA-06: Override-detection dispatch for graduation
# ---------------------------------------------------------------------------


def test_graduation_dispatch_via_override_detection():
    """INFRA-06: hasattr detects _graduation_loop only on subclasses that define it."""

    class WithGraduation(BaseGroupCoordinator):
        """Subclass that defines its own _graduation_loop."""

        group_id = "test_graduation"

        @property
        def agents(self):
            return []

        @property
        def trigger_topics(self):
            return []

        @property
        def output_topic(self):
            return "test.output"

        def _bar_topics(self):
            return []

        async def _handle_trigger(self, event: dict) -> None:
            pass

        async def _graduation_loop(self) -> None:
            pass

    class WithoutGraduation(BaseGroupCoordinator):
        """Subclass that does NOT define _graduation_loop."""

        group_id = "test_no_graduation"

        @property
        def agents(self):
            return []

        @property
        def trigger_topics(self):
            return []

        @property
        def output_topic(self):
            return "test.output2"

        def _bar_topics(self):
            return []

        async def _handle_trigger(self, event: dict) -> None:
            pass

    # Subclass with override: hasattr returns True
    assert hasattr(
        WithGraduation, "_graduation_loop"
    ), "WithGraduation defines _graduation_loop; hasattr should be True"
    # Base class: graduation loop deleted; hasattr returns False
    assert not hasattr(
        BaseGroupCoordinator, "_graduation_loop"
    ), "BaseGroupCoordinator stub was deleted; hasattr should be False"
    # Subclass without override: hasattr returns False
    assert not hasattr(
        WithoutGraduation, "_graduation_loop"
    ), "WithoutGraduation does not define _graduation_loop; hasattr should be False"
