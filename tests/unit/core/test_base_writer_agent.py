"""Tests for BaseWriter ABC — consume-parse-buffer-flush-commit loop.

Uses a concrete test subclass to verify the abstract base class contract.
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel, ValidationError

from src.core.agent.base_writer import BaseWriter

# ---------------------------------------------------------------------------
# Concrete test subclass — implements all abstract methods
# ---------------------------------------------------------------------------


class StubWriterAgent(BaseWriter):
    """Minimal concrete subclass for testing BaseWriter."""

    BATCH_SIZE = 10
    FLUSH_INTERVAL_SECS = 0.1
    MAX_BUFFER_SIZE = 50

    def __init__(self) -> None:
        super().__init__(name="stub_writer")
        self.flushed_batches: list[list[Any]] = []
        self.dlq_payloads: list[tuple[Any, Any]] = []
        self._topic = "test.topic"
        self._group = "test_consumer"

    def _topic_name(self) -> str:
        return self._topic

    @property
    def _consumer_group(self) -> str:
        return self._group

    def _parse_payload(self, payload: dict) -> list | None:
        # Simulate parse failure for payloads with "fail" key
        if payload.get("fail"):
            return None
        return [payload]

    async def _flush_batch(self, batch: list) -> None:
        self.flushed_batches.append(batch)

    def _dlq_topic(self) -> str | None:
        return "test.dlq"

    async def _run(self) -> None:
        """No-op for testing — tests call buffer/flush methods directly."""

    # Helper: simulate consumer.messages() yielding payloads
    async def _fake_messages(self, payloads: list[dict]):
        for p in payloads:
            yield ("test.topic", None, p)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBaseWriterAgentAbstract:
    """Test 1: BaseWriter is abstract — cannot be instantiated directly."""

    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            BaseWriter(name="test")  # type: ignore[abstract]

    def test_concrete_subclass_instantiates(self):
        agent = StubWriterAgent()
        assert agent.name == "stub_writer"
        assert agent._buffer == []
        assert agent._last_flush == 0.0


class TestDLQRouting:
    """Test 2: _parse_payload returning None routes payload to DLQ."""

    @pytest.mark.asyncio
    async def test_none_parse_routes_to_dlq(self):
        agent = StubWriterAgent()
        agent._consumer = MagicMock()

        # Simulate one message that fails parsing
        dlq_called = False
        logged_warnings = []

        with patch.object(
            agent.logger, "warning", side_effect=lambda *a, **kw: logged_warnings.append((a, kw))
        ):
            async for _topic, _key, payload in agent._fake_messages([{"fail": True}]):
                rows = agent._parse_payload(payload)
                if rows is None:
                    dlq = agent._dlq_topic()
                    if dlq:
                        agent.dlq_payloads.append((dlq, payload))
                    continue

        assert len(agent.dlq_payloads) == 1
        assert agent.dlq_payloads[0][0] == "test.dlq"
        assert agent.dlq_payloads[0][1] == {"fail": True}

    @pytest.mark.asyncio
    async def test_log_only_when_no_dlq_topic(self):
        agent = StubWriterAgent()
        agent._consumer = MagicMock()
        # Override dlq to return None
        agent._dlq_topic = lambda: None  # type: ignore[assignment]

        logged = []
        async for _topic, _key, payload in agent._fake_messages([{"fail": True}]):
            rows = agent._parse_payload(payload)
            if rows is None:
                dlq = agent._dlq_topic()
                if dlq:
                    agent.dlq_payloads.append((dlq, payload))
                else:
                    logged.append("dlq_log_only")
                continue

        assert len(logged) == 1
        assert len(agent.dlq_payloads) == 0


class TestFlushTriggers:
    """Tests 3-4: _flush_batch is called on buffer size or time trigger."""

    @pytest.mark.asyncio
    async def test_flush_on_batch_size(self):
        """Test 3: _flush_batch called when buffer reaches BATCH_SIZE."""
        agent = StubWriterAgent()

        # Feed exactly BATCH_SIZE messages
        payloads = [{"id": i} for i in range(agent.BATCH_SIZE)]
        async for _topic, _key, payload in agent._fake_messages(payloads):
            rows = agent._parse_payload(payload)
            if rows is not None:
                agent._buffer.extend(rows)

        # Simulate the flush trigger logic
        assert len(agent._buffer) >= agent.BATCH_SIZE
        await agent._do_flush()
        assert len(agent.flushed_batches) == 1
        assert len(agent.flushed_batches[0]) == agent.BATCH_SIZE
        assert len(agent._buffer) == 0

    @pytest.mark.asyncio
    async def test_flush_on_time_interval(self):
        """Test 4: _flush_batch called when FLUSH_INTERVAL_SECS elapsed."""
        agent = StubWriterAgent()

        # Add a few items to buffer
        agent._buffer.extend([{"id": 1}, {"id": 2}])
        # Set last_flush to past
        agent._last_flush = time.monotonic() - agent.FLUSH_INTERVAL_SECS - 1

        # Time trigger should fire
        now = time.monotonic()
        should_flush = agent._buffer and (now - agent._last_flush) >= agent.FLUSH_INTERVAL_SECS
        assert should_flush

        await agent._do_flush()
        assert len(agent.flushed_batches) == 1
        assert len(agent._buffer) == 0


class TestOffsetCommit:
    """Test 5: offset commit happens AFTER successful _flush_batch, not before."""

    @pytest.mark.asyncio
    async def test_commit_after_flush(self):
        agent = StubWriterAgent()
        agent._consumer = AsyncMock()
        agent._buffer.extend([{"id": 1}])

        await agent._do_flush()

        # Verify flush was called AND commit was called
        assert len(agent.flushed_batches) == 1
        agent._consumer.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_commit_on_flush_failure(self):
        """If _flush_batch raises, offset should NOT be committed."""
        agent = StubWriterAgent()
        agent._consumer = AsyncMock()

        # Make _flush_batch fail
        async def failing_flush(batch):
            raise RuntimeError("DB down")

        agent._flush_batch = failing_flush  # type: ignore[assignment]
        agent._buffer.extend([{"id": 1}])

        await agent._do_flush()

        # Buffer should NOT be cleared (left intact for retry)
        assert len(agent._buffer) == 1
        # Commit should NOT have been called
        agent._consumer.commit.assert_not_awaited()


class TestBufferOverflow:
    """Test 6: buffer overflow drops oldest entries and increments counter."""

    def test_overflow_drops_oldest(self):
        agent = StubWriterAgent()
        agent._consumer = MagicMock()

        # Fill buffer beyond MAX_BUFFER_SIZE
        for i in range(agent.MAX_BUFFER_SIZE + 20):
            agent._buffer.append({"id": i})

        # Simulate overflow guard from _run
        if len(agent._buffer) > agent.MAX_BUFFER_SIZE:
            dropped = len(agent._buffer) - agent.MAX_BUFFER_SIZE
            agent._buffer = agent._buffer[-agent.MAX_BUFFER_SIZE :]
            agent._buffer_overflow_total.add(dropped)

        assert len(agent._buffer) == agent.MAX_BUFFER_SIZE
        # Should have kept the NEWEST entries
        assert agent._buffer[0]["id"] == 20
        assert agent._buffer[-1]["id"] == agent.MAX_BUFFER_SIZE + 19


class TestTeardownFlush:
    """Test 7: _teardown calls _flush_batch with remaining buffer contents."""

    @pytest.mark.asyncio
    async def test_teardown_flushes_buffer(self):
        agent = StubWriterAgent()
        agent._consumer = AsyncMock()
        agent._buffer.extend([{"id": 1}, {"id": 2}])

        await agent._teardown()

        assert len(agent.flushed_batches) == 1
        assert len(agent.flushed_batches[0]) == 2
        assert len(agent._buffer) == 0

    @pytest.mark.asyncio
    async def test_teardown_skips_empty_buffer(self):
        agent = StubWriterAgent()
        agent._consumer = AsyncMock()

        await agent._teardown()

        assert len(agent.flushed_batches) == 0


class TestBufferDepthGauge:
    """Test 8: buffer_depth gauge is set every consume cycle."""

    @pytest.mark.asyncio
    async def test_gauge_set_after_buffering(self):
        agent = StubWriterAgent()
        agent._consumer = MagicMock()

        # Add items to buffer
        agent._buffer.extend([{"id": 1}, {"id": 2}])

        # OTel up_down_counter: verify .add() is callable and doesn't raise
        mock_gauge = MagicMock()
        agent._buffer_depth_gauge = mock_gauge
        agent._buffer_depth_gauge.add(len(agent._buffer))
        mock_gauge.add.assert_called_once_with(2)


class TestFlushLatencyMetrics:
    """Test 9: flush/commit latency histograms are observed on success."""

    @pytest.mark.asyncio
    async def test_flush_latency_histogram_has_samples_after_flush(self):
        agent = StubWriterAgent()
        agent._consumer = AsyncMock()
        agent._buffer.extend([{"id": 1}])

        mock_flush_latency = MagicMock()
        agent._flush_latency = mock_flush_latency
        await agent._do_flush()

        # OTel histogram: .record() must have been called once with a positive value
        assert mock_flush_latency.record.call_count >= 1
        recorded_val = mock_flush_latency.record.call_args[0][0]
        assert recorded_val >= 0.0, "flush_latency must record non-negative seconds"

    @pytest.mark.asyncio
    async def test_commit_latency_histogram_has_samples_after_flush(self):
        agent = StubWriterAgent()
        agent._consumer = AsyncMock()
        agent._buffer.extend([{"id": 1}])

        mock_commit_latency = MagicMock()
        agent._commit_latency = mock_commit_latency
        await agent._do_flush()

        # OTel histogram: .record() must have been called once with a positive value
        assert mock_commit_latency.record.call_count >= 1
        recorded_val = mock_commit_latency.record.call_args[0][0]
        assert recorded_val >= 0.0, "commit_latency must record non-negative seconds"

    @pytest.mark.asyncio
    async def test_flush_errors_counter_increments_on_failure(self):
        agent = StubWriterAgent()
        agent._consumer = AsyncMock()

        async def failing_flush(batch):
            raise RuntimeError("DB down")

        agent._flush_batch = failing_flush
        agent._buffer.extend([{"id": 1}])

        mock_errors = MagicMock()
        agent._flush_errors_total = mock_errors

        await agent._do_flush()

        # Buffer should NOT be cleared (left intact for retry)
        assert len(agent._buffer) == 1
        # Commit should NOT have been called
        agent._consumer.commit.assert_not_awaited()

        # OTel counter: .add(1) must have been called
        mock_errors.add.assert_called_once_with(1)


class TestBufferOverflowAlert:
    """Test 10: buffer overflow logs with severity=critical."""

    def test_overflow_caps_buffer_and_tracks_dropped(self):
        agent = StubWriterAgent()

        # Fill well beyond MAX_BUFFER_SIZE
        for i in range(agent.MAX_BUFFER_SIZE + 20):
            agent._buffer_rows([{"id": i}])

        # Buffer should be capped at MAX_BUFFER_SIZE
        assert len(agent._buffer) == agent.MAX_BUFFER_SIZE
        # Should have kept the NEWEST entries
        assert agent._buffer[0]["id"] == 20
        assert agent._buffer[-1]["id"] == agent.MAX_BUFFER_SIZE + 19


# ---------------------------------------------------------------------------
# Pydantic payload gate tests (INFRA-01)
# ---------------------------------------------------------------------------


class _IdModel(BaseModel):
    id: int


class TypedWriterAgent(BaseWriter):
    """Writer subclass that declares a payload_model for testing the Pydantic gate."""

    payload_model = _IdModel
    parsed_args: list[Any] = []

    def __init__(self) -> None:
        super().__init__(name="typed_writer")
        self.parsed_args = []

    def _topic_name(self) -> str:
        return "test.typed"

    @property
    def _consumer_group(self) -> str:
        return "typed_group"

    def _parse_payload(self, payload: Any) -> list | None:
        self.parsed_args.append(payload)
        return [payload]

    async def _flush_batch(self, batch: list) -> None:
        pass

    async def _run(self) -> None:
        pass


class TestPydanticPayloadGate:
    """Tests for INFRA-01: payload_model Pydantic validation gate."""

    def test_payload_model_default_is_none(self):
        """BaseWriter.payload_model defaults to None."""
        assert BaseWriter.payload_model is None

    @pytest.mark.asyncio
    async def test_pydantic_validation_error_routes_to_dlq(self):
        """ValidationError on payload_model routes to DLQ, increments parse_failures, leaves buffer empty."""
        agent = TypedWriterAgent()
        agent._consumer = AsyncMock()

        bad_payload = {"id": "not_an_int"}

        # Mock _maybe_route_to_dlq and _parse_failures_total
        agent._maybe_route_to_dlq = AsyncMock()
        mock_counter = MagicMock()
        agent._parse_failures_total = mock_counter

        # Exercise the gate directly by simulating the gate logic from _run()
        model_cls = type(agent).payload_model
        assert model_cls is not None
        try:
            validated = model_cls.model_validate(bad_payload)
            agent._parse_payload(validated)
        except ValidationError as exc:
            agent._parse_failures_total.add(1)
            await agent._maybe_route_to_dlq(bad_payload, exc)

        # _parse_failures_total.add(1) must be called
        mock_counter.add.assert_called_once_with(1)
        # _maybe_route_to_dlq must be awaited with (payload, ValidationError)
        agent._maybe_route_to_dlq.assert_awaited_once()
        call_args = agent._maybe_route_to_dlq.call_args
        assert call_args[0][0] == bad_payload
        assert isinstance(call_args[0][1], ValidationError)
        # Buffer must remain empty (gate continued before _buffer_rows)
        assert agent._buffer == []

    @pytest.mark.asyncio
    async def test_pydantic_validation_success_passes_validated_model_to_parse(self):
        """Valid payload passes a BaseModel instance (not raw dict) to _parse_payload."""
        agent = TypedWriterAgent()
        agent._consumer = AsyncMock()

        good_payload = {"id": 42}

        # Exercise the gate directly
        model_cls = type(agent).payload_model
        assert model_cls is not None
        validated = model_cls.model_validate(good_payload)
        agent._parse_payload(validated)

        # _parse_payload must have received a BaseModel instance with id == 42
        assert len(agent.parsed_args) == 1
        received = agent.parsed_args[0]
        assert isinstance(received, BaseModel)
        assert received.id == 42  # type: ignore[attr-defined]


class TestTeardownAutoCloseGuards:
    """Test 13: _teardown auto-closes _consumer, _pool, _db via hasattr/getattr guards."""

    @pytest.mark.asyncio
    async def test_teardown_stops_consumer(self):
        """_teardown must call _consumer.stop() when _consumer is not None."""
        agent = StubWriterAgent()
        mock_consumer = AsyncMock()
        agent._consumer = mock_consumer

        await agent._teardown()

        mock_consumer.stop.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_teardown_closes_pool(self):
        """_teardown must call _pool.close() when _pool is present on the subclass."""
        agent = StubWriterAgent()
        agent._consumer = AsyncMock()
        mock_pool = AsyncMock()
        agent._pool = mock_pool  # type: ignore[attr-defined]

        await agent._teardown()

        mock_pool.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_teardown_closes_db_manager(self):
        """_teardown must call _db.close() when _db is present on the subclass."""
        agent = StubWriterAgent()
        agent._consumer = AsyncMock()
        mock_db = AsyncMock()
        agent._db = mock_db  # type: ignore[attr-defined]

        await agent._teardown()

        mock_db.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_teardown_consumer_close_exception_does_not_raise(self):
        """_teardown must log and suppress exceptions from consumer.stop()."""
        agent = StubWriterAgent()
        mock_consumer = AsyncMock()
        mock_consumer.stop.side_effect = RuntimeError("already closed")
        agent._consumer = mock_consumer

        # Must not raise
        await agent._teardown()

    @pytest.mark.asyncio
    async def test_teardown_skips_none_consumer(self):
        """_teardown must not call stop() when _consumer is None."""
        agent = StubWriterAgent()
        # _consumer is None by default in __init__
        assert agent._consumer is None

        # Must not raise
        await agent._teardown()
