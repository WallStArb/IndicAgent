"""Tests for src/core/ai/multiplier_agent — BaseMultiplierAgent."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import ClassVar

UTC = UTC


def _make_dummy_agent():
    """Construct a minimal concrete subclass of BaseMultiplierAgent for testing."""
    from src.core.ai.context import AIContext
    from src.core.ai.multiplier_agent import BaseMultiplierAgent

    class _DummyAgent(BaseMultiplierAgent):
        output_schema: ClassVar[dict] = {"score": float, "confidence": float}
        agent_id = "dummy_v1"
        group = "test"
        tiers_needed = frozenset()
        latency_budget_ms = 1000.0
        shadow_only = True

        async def _compute(self, context: AIContext):
            return self._neutral(error="not used in tests", latency_ms=0.0)

    return _DummyAgent.__new__(_DummyAgent)


def _make_context():
    """Build a minimal AIContext for testing."""
    from src.core.ai.context import AIContext

    return AIContext(
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
    assert output.agent_id == "dummy_v1"
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


def test_base_multiplier_agent_class_hierarchy():
    """BaseMultiplierAgent is a subclass of BaseAIWorker and ABC."""
    from src.core.ai.base_agent import BaseAIWorker
    from src.core.ai.multiplier_agent import BaseMultiplierAgent

    assert issubclass(BaseMultiplierAgent, BaseAIWorker)


def test_output_schema_class_var():
    """Concrete subclass defines output_schema as a ClassVar dict."""
    agent = _make_dummy_agent()
    assert hasattr(type(agent), "output_schema")
    assert isinstance(type(agent).output_schema, dict)
