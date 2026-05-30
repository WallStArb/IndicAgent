"""Tests for BaseAIWorker ABC and IAIAgent Protocol."""

import asyncio
from datetime import datetime

import pytest

from src.core.ai.base_agent import BaseAIWorker, IAIAgent
from src.core.ai.context import SignalContext
from src.core.ai.output import AgentOutput


class ConcreteAgent(BaseAIWorker):
    """Concrete implementation for testing — provides _run() no-op."""

    agent_id = "concrete"
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
        """No-op for test agents."""
        pass


class TestBaseAIAgent:
    """Test suite for BaseAIWorker ABC."""

    def test_base_ai_agent_is_abstract(self):
        """Verify cannot instantiate directly without _compute()."""
        with pytest.raises(TypeError):
            # BaseAIWorker is abstract — _compute() not implemented
            BaseAIWorker()

    def test_compute_captures_timing(self):
        """Verify latency_ms on returned AgentOutput equals wall-clock within 10ms."""

        class TimedAgent(ConcreteAgent):
            agent_id = "timed"

            async def _compute(self, context: SignalContext) -> AgentOutput:
                # Simulate 50ms computation
                await asyncio.sleep(0.05)
                return AgentOutput(
                    agent_id=self.agent_id,
                    group=self.group,
                    output_type="neutral",
                    payload={"test": True},
                )

        agent = TimedAgent()
        ctx = SignalContext(
            symbol="ES",
            timeframe="5m",
            ts=datetime.now(),
        )

        async def run_test():
            result = await agent.compute(ctx)
            # latency_ms should be ~50ms (within 10ms tolerance)
            assert 40 <= result.latency_ms <= 60

        asyncio.run(run_test())

    def test_compute_returns_neutral_on_exception(self):
        """Verify _compute() raises, compute() returns neutral AgentOutput."""

        class FailingAgent(ConcreteAgent):
            agent_id = "failing"

            async def _compute(self, context: SignalContext) -> AgentOutput:
                raise ValueError("test error")

        agent = FailingAgent()
        ctx = SignalContext(
            symbol="ES",
            timeframe="5m",
            ts=datetime.now(),
        )

        async def run_test():
            result = await agent.compute(ctx)
            assert result.output_type == "neutral"
            assert result.payload == {}
            assert result.error == "test error"

        asyncio.run(run_test())

    def test_compute_returns_neutral_on_timeout(self):
        """Verify _compute() sleeps beyond budget, compute() returns neutral."""

        class SlowAgent(ConcreteAgent):
            agent_id = "slow"
            latency_budget_ms = 100.0  # 100ms budget

            async def _compute(self, context: SignalContext) -> AgentOutput:
                # Sleep for 200ms — exceeds 100ms budget
                await asyncio.sleep(0.2)
                return AgentOutput(
                    agent_id=self.agent_id,
                    group=self.group,
                    output_type="signal",
                )

        agent = SlowAgent()
        ctx = SignalContext(
            symbol="ES",
            timeframe="5m",
            ts=datetime.now(),
        )

        async def run_test():
            result = await agent.compute(ctx)
            assert result.output_type == "neutral"
            assert "timeout" in result.error

        asyncio.run(run_test())

    def test_on_error_hook_called_on_exception(self):
        """Verify _on_error() receives the Exception."""

        class HookAgent(ConcreteAgent):
            agent_id = "hook"
            error_received = None

            async def _compute(self, context: SignalContext) -> AgentOutput:
                raise ValueError("hook test")

            async def _on_error(self, error: Exception) -> None:
                # Capture error for verification
                HookAgent.error_received = error

        agent = HookAgent()
        ctx = SignalContext(
            symbol="ES",
            timeframe="5m",
            ts=datetime.now(),
        )

        async def run_test():
            await agent.compute(ctx)
            assert HookAgent.error_received is not None
            assert isinstance(HookAgent.error_received, ValueError)
            assert str(HookAgent.error_received) == "hook test"

        asyncio.run(run_test())

    def test_audit_payload_property_returns_empty_dict(self):
        """Verify default hook returns {}."""

        class AuditAgent(ConcreteAgent):
            agent_id = "audit"

            async def _compute(self, context: SignalContext) -> AgentOutput:
                return AgentOutput(
                    agent_id=self.agent_id,
                    group=self.group,
                    output_type="neutral",
                )

        agent = AuditAgent()
        assert agent._audit_payload == {}


class TestIAIAgentProtocol:
    """Test suite for IAIAgent Protocol."""

    def test_protocol_compliance(self):
        """Verify BaseAIWorker subclass satisfies IAIAgent Protocol."""

        class CompliantAgent(ConcreteAgent):
            agent_id = "compliant"

        agent = CompliantAgent()

        # isinstance check via Protocol
        assert isinstance(agent, IAIAgent)
        assert agent.agent_id == "compliant"
        assert agent.group == "alpha"
        assert agent.shadow_only is True
        assert agent.latency_budget_ms == 5000.0
