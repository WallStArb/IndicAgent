"""Unit tests for GraduationWriterAgent.

Tests are DB-agnostic and Kafka-agnostic — all external dependencies mocked.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from services.graduation_writer_agent import CONSUMER_GROUP, GraduationWriterAgent


def test_consumer_group_locked():
    assert CONSUMER_GROUP == "graduation_writer_group"


def test_class_constants_locked():
    assert GraduationWriterAgent.BATCH_SIZE == 50
    assert GraduationWriterAgent.FLUSH_INTERVAL_SECS == 5.0


def _make_agent() -> GraduationWriterAgent:
    """Construct agent instance bypassing __init__ for unit isolation."""
    a = GraduationWriterAgent.__new__(GraduationWriterAgent)
    a.logger = MagicMock()
    a._repo = MagicMock()
    a._repo.batch_upsert = AsyncMock()
    a._rows_written = MagicMock()
    a._write_errors = MagicMock()
    a._batch_latency = MagicMock()
    return a


def test_parse_payload_valid():
    a = _make_agent()
    payload = {
        "transform_id": "t",
        "transform_version": "v1",
        "segment_key": "g",
        "n": 30,
        "is_graduated": True,
        "evaluated_at": "2026-04-24T00:00:00Z",
        "expires_at": "2026-07-23T00:00:00Z",
    }
    assert a._parse_payload(payload) == [payload]


def test_parse_payload_missing_key_returns_none():
    a = _make_agent()
    bad = {"transform_id": "t"}  # missing required keys
    assert a._parse_payload(bad) is None


def test_parse_payload_non_dict_returns_none():
    a = _make_agent()
    assert a._parse_payload("not a dict") is None  # type: ignore[arg-type]
    assert a._parse_payload(None) is None  # type: ignore[arg-type]


def test_parse_payload_empty_dict_returns_none():
    a = _make_agent()
    assert a._parse_payload({}) is None


def test_parse_payload_partial_keys_returns_none():
    a = _make_agent()
    partial = {
        "transform_id": "t",
        "transform_version": "v1",
        # missing segment_key, n, is_graduated, evaluated_at, expires_at
    }
    assert a._parse_payload(partial) is None


@pytest.mark.asyncio
async def test_flush_batch_calls_upsert():
    a = _make_agent()
    batch = [{"transform_id": "t", "n": 30}]
    await a._flush_batch(batch)
    a._repo.batch_upsert.assert_awaited_once_with(batch)


@pytest.mark.asyncio
async def test_flush_batch_increments_rows_written():
    a = _make_agent()
    batch = [{"transform_id": "t"}, {"transform_id": "u"}]
    await a._flush_batch(batch)
    a._rows_written.inc.assert_called_once_with(2)


@pytest.mark.asyncio
async def test_flush_batch_increments_error_counter_on_exception():
    a = _make_agent()
    a._repo.batch_upsert = AsyncMock(side_effect=RuntimeError("DB down"))
    with pytest.raises(RuntimeError):
        await a._flush_batch([{"transform_id": "t"}])
    a._write_errors.inc.assert_called_once()


@pytest.mark.asyncio
async def test_flush_batch_observes_latency():
    a = _make_agent()
    batch = [{"transform_id": "t"}]
    await a._flush_batch(batch)
    a._batch_latency.observe.assert_called_once()
