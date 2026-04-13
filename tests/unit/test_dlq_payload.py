"""Tests for DLQPayload schema."""

import pytest
from datetime import datetime, UTC
from src.core.schemas.dlq_payload import DLQPayload


def test_dlq_payload_serialization():
    """Verify DLQPayload serializes to JSON correctly."""
    payload = DLQPayload(
        agent="test_agent",
        source_topic="test.topic",
        error_type="ValidationError",
        error_message="Missing required field",
        payload={"symbol": "ES"},
        timestamp=datetime.now(UTC),
        retry_count=0,
    )

    json_str = payload.model_dump_json()
    assert "agent" in json_str
    assert "error_type" in json_str
    assert "payload" in json_str


def test_dlq_payload_all_fields():
    """Verify DLQPayload accepts all required fields."""
    payload = DLQPayload(
        agent="bar_auditor_agent",
        source_topic="dev.market.bars",
        error_type="KeyError",
        error_message="Missing 'symbol' field",
        payload={"timestamp": "2026-04-13T19:48:20Z"},
        timestamp=datetime.now(UTC),
        retry_count=0,
    )

    assert payload.agent == "bar_auditor_agent"
    assert payload.source_topic == "dev.market.bars"
    assert payload.error_type == "KeyError"
    assert payload.retry_count == 0


def test_dlq_payload_retry_count_default():
    """Verify DLQPayload retry_count defaults to 0."""
    payload = DLQPayload(
        agent="test_agent",
        source_topic="test.topic",
        error_type="ValidationError",
        error_message="Test error",
        payload={"test": "data"},
        timestamp=datetime.now(UTC),
    )

    assert payload.retry_count == 0
