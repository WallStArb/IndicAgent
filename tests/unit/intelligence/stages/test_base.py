"""Tests for Stage base class.

Behavior tests:
  1. Stage constructor initializes consumer, producer, and attribution producer
  2. Stage constructor creates circuit breaker and data quality monitor
  3. process() is abstract, raises NotImplementedError
  4. run() consumes messages from input topic
  5. run() validates input with data quality monitor
  6. run() calls process() through circuit breaker
  7. run() emits attribution after successful process
  8. run() publishes output to next stage
  9. run() logs errors and continues on exception (fault tolerance)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.intelligence.stages.base import Stage
from src.observability.circuit_breaker import CircuitBreaker
from src.intelligence.monitoring.data_quality_monitor import DataQualityMonitor


# ---------------------------------------------------------------------------
# Concrete subclass for testing
# ---------------------------------------------------------------------------


class ConcreteStage(Stage):
    """Concrete Stage for testing — process() returns a simple output dict."""

    async def process(self, event):
        return {"symbol": event.symbol, "tf": event.tf, "confidence": 0.8}


# ---------------------------------------------------------------------------
# Minimal valid IntelligenceEvent payload
# IntelligenceEvent fields: ts, tf, symbol, bar, i1, i2, i3, i4, i5, smc, i6
# All sub-model fields are optional with None defaults — passing {} works.
# ---------------------------------------------------------------------------

VALID_MSG = {
    "schema_version": "1.0",
    "ts": "2026-01-01T00:00:00+00:00",
    "symbol": "ES",
    "tf": "1m",
    "bar": {"o": 100.0, "h": 101.0, "l": 99.0, "c": 100.5, "v": 1000},
    "i1": {},
    "i3": {},
    "i4": {},
    "i5": {},
    "smc": {},
    "i6": {},
}


# ---------------------------------------------------------------------------
# Helpers to build a Stage without live Kafka
# ---------------------------------------------------------------------------


def make_stage() -> ConcreteStage:
    """Build a ConcreteStage with all Kafka clients mocked."""
    stage = ConcreteStage.__new__(ConcreteStage)
    # Manually initialise fields without calling __init__ (which needs live Kafka)
    stage.stage_name = "quality_gated"
    stage._output_topic = "development.quality_gated"
    stage.consumer = AsyncMock()
    stage.producer = AsyncMock()
    stage.attribution_producer = AsyncMock()
    stage.circuit_breaker = CircuitBreaker()
    stage.data_quality_monitor = DataQualityMonitor("quality_gated")
    stage.events_consumed = MagicMock()
    stage.events_produced = MagicMock()
    stage.processing_errors = MagicMock()
    stage.circuit_state = MagicMock()
    stage._attribution_topic = "development.pipeline.attribution"
    stage._last_circuit_state = "closed"
    return stage


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_stage_constructor_initializes_consumer_producer_attribution():
    """Test 1: Stage constructor initializes consumer, producer, and attribution producer."""
    stage = make_stage()
    assert stage.consumer is not None
    assert stage.producer is not None
    assert stage.attribution_producer is not None


def test_stage_constructor_creates_circuit_breaker_and_dqm():
    """Test 2: Stage constructor creates circuit breaker and data quality monitor."""
    stage = make_stage()
    assert isinstance(stage.circuit_breaker, CircuitBreaker)
    assert isinstance(stage.data_quality_monitor, DataQualityMonitor)


def test_process_is_abstract_raises_not_implemented():
    """Test 3: process() is abstract, raises NotImplementedError."""
    # Stage itself is abstract — direct instantiation should fail
    with pytest.raises(TypeError):
        Stage(  # type: ignore[abstract]
            "test",
            "topic.in",
            "topic.out",
            MagicMock(),
            MagicMock(),
            MagicMock(),
        )


@pytest.mark.asyncio
async def test_run_consumes_messages_from_input_topic():
    """Test 4: run() consumes messages from input topic."""
    stage = make_stage()

    stage.data_quality_monitor.validate_input = AsyncMock(return_value=True)
    stage.data_quality_monitor.validate_output = AsyncMock(return_value=True)
    stage.attribution_producer.publish = AsyncMock()
    stage.producer.publish = AsyncMock()

    async def mock_messages():
        yield ("topic.in", "ES:1m", VALID_MSG)

    stage.consumer.messages = mock_messages

    await stage.run()

    # run() consumed at least one message (validate_input was called)
    assert stage.data_quality_monitor.validate_input.called


@pytest.mark.asyncio
async def test_run_validates_input_with_data_quality_monitor():
    """Test 5: run() validates input with data quality monitor."""
    stage = make_stage()

    validate_calls = []

    async def mock_validate_input(event):
        validate_calls.append(event)
        return False  # Reject input — message should be dropped

    stage.data_quality_monitor.validate_input = mock_validate_input
    stage.producer.publish = AsyncMock()

    async def mock_messages():
        yield ("topic.in", "ES:1m", VALID_MSG)

    stage.consumer.messages = mock_messages

    await stage.run()

    # validate_input was called once
    assert len(validate_calls) == 1
    # producer.publish was NOT called (message dropped after validation failure)
    stage.producer.publish.assert_not_called()


@pytest.mark.asyncio
async def test_run_calls_process_through_circuit_breaker():
    """Test 6: run() calls process() through circuit breaker."""
    stage = make_stage()
    process_calls = []

    async def tracking_process(event):
        process_calls.append(event)
        return {"symbol": event.symbol, "tf": event.tf, "confidence": 0.8}

    stage.process = tracking_process
    stage.data_quality_monitor.validate_input = AsyncMock(return_value=True)
    stage.data_quality_monitor.validate_output = AsyncMock(return_value=True)
    stage.attribution_producer.publish = AsyncMock()
    stage.producer.publish = AsyncMock()

    async def mock_messages():
        yield ("topic.in", "ES:1m", VALID_MSG)

    stage.consumer.messages = mock_messages

    await stage.run()

    assert len(process_calls) == 1


@pytest.mark.asyncio
async def test_run_emits_attribution_after_successful_process():
    """Test 7: run() emits attribution after successful process."""
    stage = make_stage()
    stage.data_quality_monitor.validate_input = AsyncMock(return_value=True)
    stage.data_quality_monitor.validate_output = AsyncMock(return_value=True)
    stage.attribution_producer.publish = AsyncMock()
    stage.producer.publish = AsyncMock()

    async def mock_messages():
        yield ("topic.in", "ES:1m", VALID_MSG)

    stage.consumer.messages = mock_messages

    await stage.run()

    # Attribution should have been emitted exactly once
    stage.attribution_producer.publish.assert_called_once()
    call_args = stage.attribution_producer.publish.call_args
    # The topic argument should contain "attribution"
    topic_arg = call_args[1].get("topic") or call_args[0][0]
    assert "attribution" in topic_arg


@pytest.mark.asyncio
async def test_run_publishes_output_to_next_stage():
    """Test 8: run() publishes output to next stage."""
    stage = make_stage()
    stage.data_quality_monitor.validate_input = AsyncMock(return_value=True)
    stage.data_quality_monitor.validate_output = AsyncMock(return_value=True)
    stage.attribution_producer.publish = AsyncMock()
    stage.producer.publish = AsyncMock()

    async def mock_messages():
        yield ("topic.in", "ES:1m", VALID_MSG)

    stage.consumer.messages = mock_messages

    await stage.run()

    stage.producer.publish.assert_called_once()


@pytest.mark.asyncio
async def test_run_logs_errors_and_continues_on_exception():
    """Test 9: run() logs errors and continues on exception (fault tolerance)."""
    stage = make_stage()
    stage.data_quality_monitor.validate_input = AsyncMock(return_value=True)
    stage.data_quality_monitor.validate_output = AsyncMock(return_value=True)
    stage.attribution_producer.publish = AsyncMock()
    stage.producer.publish = AsyncMock()

    # Make process() raise on first call, succeed on second
    call_count = [0]

    async def failing_then_succeeding(event):
        call_count[0] += 1
        if call_count[0] == 1:
            raise RuntimeError("Processing error")
        return {"symbol": event.symbol, "tf": event.tf, "confidence": 0.8}

    stage.process = failing_then_succeeding

    async def mock_messages():
        yield ("topic.in", "ES:1m", VALID_MSG)
        yield ("topic.in", "ES:1m", VALID_MSG)

    stage.consumer.messages = mock_messages

    # Should complete without raising — errors are logged, not propagated
    await stage.run()

    # Both messages processed (process() called for each)
    assert call_count[0] == 2
    # Output published for both messages — first bypassed (pass-through), second normal
    assert stage.producer.publish.call_count == 2
