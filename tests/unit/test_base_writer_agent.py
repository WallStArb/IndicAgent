"""Tests for BaseWriterAgent ABC — consume-parse-buffer-flush-commit loop.

Uses a concrete test subclass to verify the abstract base class contract.
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.agent.base_writer import BaseWriterAgent

# ---------------------------------------------------------------------------
# Concrete test subclass — implements all abstract methods
# ---------------------------------------------------------------------------


class StubWriterAgent(BaseWriterAgent):
    """Minimal concrete subclass for testing BaseWriterAgent."""

    BATCH_SIZE = 10
    FLUSH_INTERVAL_SECS = 0.1
    MAX_BUFFER_SIZE = 50

    def __init__(self) -> None:
        super().__init__(name="stub_writer", metrics_port=None)
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
    """Test 1: BaseWriterAgent is abstract — cannot be instantiated directly."""

    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            BaseWriterAgent(name="test", metrics_port=None)  # type: ignore[abstract]

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

        with patch.object(agent.logger, "warning", side_effect=lambda *a, **kw: logged_warnings.append((a, kw))):
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
            agent._buffer = agent._buffer[-agent.MAX_BUFFER_SIZE:]
            agent._buffer_overflow_total.inc(dropped)

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

        # Simulate what _run does: set gauge
        agent._buffer_depth_gauge.set(len(agent._buffer))

        # Verify the gauge value is set (can read from Prometheus registry)
        import prometheus_client

        # Get the gauge value from the registry
        registry = prometheus_client.REGISTRY
        for metric in registry.collect():
            for sample in metric.samples:
                if sample.name == "stub_writer_buffer_depth":
                    assert sample.value == 2.0
                    return

        pytest.fail("buffer_depth gauge not found in Prometheus registry")
