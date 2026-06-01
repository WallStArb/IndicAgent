"""Tests for BaseAIWorker ABC and IAIAgent Protocol."""

import asyncio
from datetime import datetime
from typing import ClassVar
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from src.core.ai.base_agent import BaseAIWorker, IAIAgent
from src.core.ai.output import AgentOutput
from src.intelligence.ai.context import SignalContext


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


# ---------------------------------------------------------------------------
# Shared fixtures and helpers for _run_typed tests
# ---------------------------------------------------------------------------


class _Result(BaseModel):
    """Minimal result model for _run_typed tests."""

    value: float


def _make_typed_agent() -> BaseAIWorker:
    """Build a concrete BaseAIWorker subclass with result_type = _Result."""

    class TypedWorker(ConcreteAgent):
        agent_id = "typed_worker"
        result_type: ClassVar[type[BaseModel]] = _Result

    return TypedWorker()


def _make_ctx() -> SignalContext:
    """Build a minimal SignalContext for tests."""
    return SignalContext(
        symbol="ES",
        timeframe="5m",
        ts=datetime.now(),
        signal_id=None,
        smc=None,
    )


def _patch_run_typed(monkeypatch) -> dict:
    """Install fake make_llm_adapter + pydantic_ai.Agent; return the captured kwargs dict."""
    captured: dict = {}

    def fake_make_llm_adapter(**kwargs):
        captured.update(kwargs)
        return object()

    class FakeAgent:
        def __init__(self, model, **kwargs):
            pass

        async def run(self, prompt):
            obj = MagicMock()
            obj.output = _Result(value=1.0)
            return obj

    monkeypatch.setattr("src.core.ai.llm_adapter.make_llm_adapter", fake_make_llm_adapter)
    import pydantic_ai

    monkeypatch.setattr(pydantic_ai, "Agent", FakeAgent)
    return captured


class TestRunTyped:
    """Tests for BaseAIWorker._run_typed() and __init_subclass__ guard."""

    def test_happy_path_returns_result_type_instance(self, monkeypatch):
        """_run_typed() returns validated result_type instance; Agent got correct kwargs."""
        agent = _make_typed_agent()
        ctx = _make_ctx()

        captured_adapter_kwargs: dict = {}
        sentinel_adapter = object()
        captured_agent_kwargs: dict = {}

        def fake_make_llm_adapter(**kwargs):
            captured_adapter_kwargs.update(kwargs)
            return sentinel_adapter

        expected_result = _Result(value=0.5)

        class FakeAgent:
            def __init__(self, model, **kwargs):
                captured_agent_kwargs.update(kwargs)
                captured_agent_kwargs["model"] = model

            async def run(self, prompt):
                obj = MagicMock()
                obj.output = expected_result
                return obj

        monkeypatch.setattr("src.core.ai.llm_adapter.make_llm_adapter", fake_make_llm_adapter)
        # Monkeypatch pydantic_ai.Agent used inside the lazy import in _run_typed.
        import pydantic_ai

        monkeypatch.setattr(pydantic_ai, "Agent", FakeAgent)

        async def run():
            return await agent._run_typed(ctx, prompt="p", system="s")

        result = asyncio.run(run())

        assert result == expected_result
        assert captured_agent_kwargs.get("output_type") is _Result
        assert captured_agent_kwargs.get("retries") == 1
        assert captured_agent_kwargs.get("model") is sentinel_adapter

    def test_runtime_error_when_result_type_is_none(self):
        """_run_typed() raises RuntimeError immediately if result_type is None."""

        class NoTypedWorker(ConcreteAgent):
            agent_id = "no_typed"
            # result_type stays None (base class default)

        agent = NoTypedWorker()
        ctx = _make_ctx()

        async def run():
            await agent._run_typed(ctx, prompt="p", system="s")

        with pytest.raises(RuntimeError, match="result_type is None"):
            asyncio.run(run())

    def test_timeout_derived_from_timeout_s(self, monkeypatch):
        """make_llm_adapter is called with timeout == worker._timeout_s."""
        agent = _make_typed_agent()
        ctx = _make_ctx()
        captured = _patch_run_typed(monkeypatch)

        asyncio.run(agent._run_typed(ctx, prompt="p", system="s"))

        assert captured["timeout"] == agent._timeout_s

    def test_max_tokens_none_resolves_to_default(self, monkeypatch):
        """max_tokens=None is resolved to _default_max_tokens (an int, never None)."""
        agent = _make_typed_agent()
        ctx = _make_ctx()
        captured = _patch_run_typed(monkeypatch)

        asyncio.run(agent._run_typed(ctx, prompt="p", system="s"))
        assert captured["max_tokens"] == 2048
        assert isinstance(captured["max_tokens"], int)

        captured.clear()
        asyncio.run(agent._run_typed(ctx, prompt="p", system="s", max_tokens=500))
        assert captured["max_tokens"] == 500

    def test_audit_context_carries_agent_id_and_placeholder_call_id(self, monkeypatch):
        """audit_context passed to make_llm_adapter has correct agent_id and call_id=""."""
        agent = _make_typed_agent()
        ctx = _make_ctx()
        captured = _patch_run_typed(monkeypatch)

        asyncio.run(agent._run_typed(ctx, prompt="p", system="s"))

        audit = captured["audit_context"]
        assert audit["agent_id"] == agent.agent_id
        assert audit["call_id"] == "", "adapter must mint the real call_id, not _run_typed"

    def test_init_subclass_guard_raises_type_error_on_non_basemodel(self):
        """Defining a subclass with a non-BaseModel result_type raises TypeError at class-definition time."""
        with pytest.raises(TypeError, match="result_type must be a pydantic BaseModel subclass"):
            type(
                "_BadWorker",
                (ConcreteAgent,),
                {"result_type": int, "agent_id": "bad", "group": "alpha"},
            )
