"""Tests for AgentOutput universal envelope."""

import pytest
from datetime import datetime
from uuid import UUID

from src.core.ai.output import AgentOutput


class TestAgentOutput:
    """Test suite for AgentOutput frozen model."""

    def test_agent_output_is_frozen(self):
        """Verify ConfigDict(frozen=True) prevents mutation."""
        output = AgentOutput(
            agent_id="test_agent",
            group="alpha",
            symbol="ES",
            timeframe="5m",
        )
        with pytest.raises(Exception):  # ValidationError on frozen model
            output.symbol = "NQ"

    def test_agent_output_default_payload_empty(self):
        """Verify default factory produces {}."""
        output = AgentOutput(
            agent_id="test_agent",
            group="alpha",
        )
        assert output.payload == {}

    def test_agent_output_construction(self):
        """Verify all fields set correctly."""
        signal_id = UUID("00000000-0000-0000-0000-000000000001")
        ts = datetime.now()
        output = AgentOutput(
            agent_id="test_agent",
            group="alpha",
            signal_id=signal_id,
            symbol="ES",
            timeframe="5m",
            ts=ts,
            output_type="signal",
            payload={"multiplier": 1.5, "confidence": 0.8},
            shadow_only=False,
            latency_ms=123.45,
            error=None,
        )
        assert output.agent_id == "test_agent"
        assert output.group == "alpha"
        assert output.signal_id == signal_id
        assert output.symbol == "ES"
        assert output.timeframe == "5m"
        assert output.ts == ts
        assert output.output_type == "signal"
        assert output.payload == {"multiplier": 1.5, "confidence": 0.8}
        assert output.shadow_only is False
        assert output.latency_ms == 123.45
        assert output.error is None

    def test_agent_output_model_copy_update(self):
        """Verify frozen model enrichment works via model_copy."""
        output = AgentOutput(
            agent_id="test_agent",
            group="alpha",
            latency_ms=100.0,
        )
        enriched = output.model_copy(update={"latency_ms": 250.0})
        assert enriched.latency_ms == 250.0
        assert output.latency_ms == 100.0  # Original unchanged
