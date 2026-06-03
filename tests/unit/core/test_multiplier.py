"""Tests for src/core/ai/evaluator — Evaluator."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import ClassVar

UTC = UTC


def _make_dummy_agent():
    """Construct a minimal concrete subclass of Evaluator for testing."""
    from src.core.ai.evaluator import Evaluator
    from src.intelligence.ai.context import SignalContext

    # Use a function-call counter to generate unique agent_ids for test isolation
    if not hasattr(_make_dummy_agent, "_counter"):
        _make_dummy_agent._counter = 0
    _make_dummy_agent._counter += 1
    unique_id = f"dummy_v1_{_make_dummy_agent._counter}"

    class _DummyAgent(Evaluator):
        output_schema: ClassVar[dict] = {"score": float, "confidence": float}
        agent_id = unique_id
        group = "test"
        tiers_needed = frozenset()
        latency_budget_ms = 1000.0
        shadow_only = True

        async def _compute(self, context: SignalContext):
            return self._neutral(error="not used in tests", latency_ms=0.0)

    return _DummyAgent.__new__(_DummyAgent)


def _make_context():
    """Build a minimal SignalContext for testing."""
    from src.intelligence.ai.context import SignalContext

    return SignalContext(
        signal_id=None,
        symbol="ES",
        timeframe="5m",
        ts=datetime.now(UTC),
        i1=None,
        i4=None,
        i6=None,
        i7=None,
        smc=None,
    )


def test_parse_multiplier_response_clean_json():
    """_parse_multiplier_response returns parsed dict for valid JSON."""
    agent = _make_dummy_agent()
    result = agent._parse_multiplier_response('{"a": 1}', lambda d: d)
    assert result == {"a": 1}


def test_parse_multiplier_response_garbage_returns_none():
    """_parse_multiplier_response returns None for unparseable input."""
    agent = _make_dummy_agent()
    result = agent._parse_multiplier_response("garbage no json here", lambda d: d)
    assert result is None


def test_build_multiplier_output_clamps_upper():
    """_build_multiplier_output clamps multiplier to 2.0 when above."""
    agent = _make_dummy_agent()
    ctx = _make_context()
    output = agent._build_multiplier_output(
        ctx, multiplier=2.5, confidence=0.8, payload={"reasoning": "x"}, prompt_version="v1"
    )
    assert output.payload["multiplier"] == 2.0


def test_build_multiplier_output_clamps_lower():
    """_build_multiplier_output clamps multiplier to 0.0 when below."""
    agent = _make_dummy_agent()
    ctx = _make_context()
    output = agent._build_multiplier_output(
        ctx, multiplier=-0.5, confidence=0.8, payload={"reasoning": "x"}, prompt_version="v1"
    )
    assert output.payload["multiplier"] == 0.0


def test_build_multiplier_output_output_type():
    """_build_multiplier_output returns AgentOutput with output_type 'multiplier'."""
    agent = _make_dummy_agent()
    ctx = _make_context()
    output = agent._build_multiplier_output(
        ctx, multiplier=0.8, confidence=0.7, payload={}, prompt_version="v1"
    )
    assert output.output_type == "multiplier"


def test_build_multiplier_output_fields_from_context():
    """AgentOutput agent_id, group, symbol, timeframe, shadow_only match agent/context."""
    agent = _make_dummy_agent()
    ctx = _make_context()
    output = agent._build_multiplier_output(
        ctx, multiplier=0.9, confidence=0.6, payload={}, prompt_version="v2"
    )
    assert output.agent_id == agent.agent_id
    assert output.group == "test"
    assert output.symbol == "ES"
    assert output.timeframe == "5m"
    assert output.shadow_only is True


def test_build_multiplier_output_prompt_version_in_payload():
    """prompt_version is stored in the AgentOutput payload."""
    agent = _make_dummy_agent()
    ctx = _make_context()
    output = agent._build_multiplier_output(
        ctx, multiplier=1.0, confidence=0.5, payload={}, prompt_version="v1"
    )
    assert output.payload["prompt_version"] == "v1"


def test_evaluator_class_hierarchy():
    """Evaluator is a subclass of BaseAIWorker and ABC."""
    from src.core.ai.base_agent import BaseAIWorker
    from src.core.ai.evaluator import Evaluator

    assert issubclass(Evaluator, BaseAIWorker)


def test_output_schema_class_var():
    """Concrete subclass defines output_schema as a ClassVar dict."""
    agent = _make_dummy_agent()
    assert hasattr(type(agent), "output_schema")
    assert isinstance(type(agent).output_schema, dict)
