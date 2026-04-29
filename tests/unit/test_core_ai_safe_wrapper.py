"""Tests for SafeAgentWrapper timeout and exception isolation."""

import asyncio
from datetime import datetime

from src.core.ai.base_agent import BaseAIAgent
from src.core.ai.context import AIContext
from src.core.ai.output import AgentOutput
from src.core.ai.safe_wrapper import SafeAgentWrapper


class DummyAgent(BaseAIAgent):
    """Dummy agent for testing."""
    agent_id = "dummy"
    group = "alpha"
    tiers_needed = frozenset()

    async def _compute(self, context: AIContext) -> AgentOutput:
        return AgentOutput(
            agent_id=self.agent_id,
            group=self.group,
            output_type="signal",
            payload={"test": True},
        )

    async def _run(self) -> None:
        """No-op for test agents."""
        pass


class TestSafeAgentWrapper:
    """Test suite for SafeAgentWrapper."""

    def test_wrapper_returns_result_on_success(self):
        """Verify passes through AgentOutput from agent.compute()."""

        agent = DummyAgent()
        wrapper = SafeAgentWrapper(agent)

        ctx = AIContext(
            symbol="ES",
            timeframe="5m",
            ts=datetime.now(),
        )

        async def run_test():
            result = await wrapper.compute(ctx)
            assert result.agent_id == "dummy"
            assert result.group == "alpha"
            assert result.output_type == "signal"
            assert result.payload == {"test": True}

        asyncio.run(run_test())

    def test_wrapper_returns_neutral_on_timeout(self):
        """Verify agent exceeds budget, wrapper returns neutral."""

        class SlowAgent(DummyAgent):
            agent_id = "slow"
            latency_budget_ms = 100.0  # 100ms budget

            async def _compute(self, context: AIContext) -> AgentOutput:
                await asyncio.sleep(0.2)  # Exceeds budget
                return AgentOutput(
                    agent_id=self.agent_id,
                    group=self.group,
                    output_type="signal",
                )

        agent = SlowAgent()
        wrapper = SafeAgentWrapper(agent)

        ctx = AIContext(
            symbol="ES",
            timeframe="5m",
            ts=datetime.now(),
        )

        async def run_test():
            result = await wrapper.compute(ctx)
            assert result.output_type == "neutral"
            assert "timeout" in result.error

        asyncio.run(run_test())

    def test_wrapper_returns_neutral_on_exception(self):
        """Verify agent raises, wrapper returns neutral."""

        class FailingAgent(DummyAgent):
            agent_id = "failing"

            async def _compute(self, context: AIContext) -> AgentOutput:
                raise ValueError("agent error")

        agent = FailingAgent()
        wrapper = SafeAgentWrapper(agent)

        ctx = AIContext(
            symbol="ES",
            timeframe="5m",
            ts=datetime.now(),
        )

        async def run_test():
            result = await wrapper.compute(ctx)
            assert result.output_type == "neutral"
            assert result.error == "agent error"

        asyncio.run(run_test())

    def test_wrapper_latency_budget_from_agent(self):
        """Verify timeout derived from agent.latency_budget_ms (D-51)."""

        class CustomBudgetAgent(DummyAgent):
            agent_id = "custom"
            latency_budget_ms = 250.0  # Custom 250ms budget

            async def _compute(self, context: AIContext) -> AgentOutput:
                await asyncio.sleep(0.3)  # Exceeds 250ms
                return AgentOutput(
                    agent_id=self.agent_id,
                    group=self.group,
                    output_type="signal",
                )

        agent = CustomBudgetAgent()
        wrapper = SafeAgentWrapper(agent)

        # Verify wrapper reads agent's latency_budget_ms
        assert wrapper._timeout_s == 0.25  # 250ms / 1000

        ctx = AIContext(
            symbol="ES",
            timeframe="5m",
            ts=datetime.now(),
        )

        async def run_test():
            result = await wrapper.compute(ctx)
            assert result.output_type == "neutral"
            assert "timeout" in result.error

        asyncio.run(run_test())

    def test_wrapper_does_not_block_gather(self):
        """Verify two wrappers, one slow, both complete independently."""

        class FastAgent(DummyAgent):
            agent_id = "fast"

            async def _compute(self, context: AIContext) -> AgentOutput:
                await asyncio.sleep(0.01)  # 10ms
                return AgentOutput(
                    agent_id=self.agent_id,
                    group=self.group,
                    output_type="signal",
                )

        class SlowAgent(DummyAgent):
            agent_id = "slow"
            latency_budget_ms = 50.0

            async def _compute(self, context: AIContext) -> AgentOutput:
                await asyncio.sleep(0.1)  # 100ms — exceeds budget
                return AgentOutput(
                    agent_id=self.agent_id,
                    group=self.group,
                    output_type="signal",
                )

        fast_agent = FastAgent()
        slow_agent = SlowAgent()

        fast_wrapper = SafeAgentWrapper(fast_agent)
        slow_wrapper = SafeAgentWrapper(slow_agent)

        ctx = AIContext(
            symbol="ES",
            timeframe="5m",
            ts=datetime.now(),
        )

        async def run_test():
            # Both wrappers run in parallel
            results = await asyncio.gather(
                fast_wrapper.compute(ctx),
                slow_wrapper.compute(ctx),
            )
            # Fast agent should succeed
            assert results[0].agent_id == "fast"
            assert results[0].output_type == "signal"
            # Slow agent should timeout (neutral)
            assert results[1].agent_id == "slow"
            assert results[1].output_type == "neutral"

        asyncio.run(run_test())
