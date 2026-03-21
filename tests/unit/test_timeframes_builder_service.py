# tests/unit/test_timeframes_builder_service.py
"""Unit tests for TimeframeBuilderService completeness metadata and topic routing."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
import structlog

from src.core.timeframe_builder import _TARGET_TIMEFRAMES, _update_accumulator


def _make_accumulator(bar_count: int) -> dict:
    """Build a completed accumulator with the given bar_count."""
    bar = {"open": 100.0, "high": 105.0, "low": 99.0, "close": 103.0, "volume": 500}
    acc = None
    for _ in range(bar_count):
        acc = _update_accumulator(acc, bar, period_ts=1000)
    return acc


def test_is_complete_true_when_bar_count_equals_tf_minutes():
    """A 5m bar built from exactly 5 × 1m bars is complete."""
    tf = "5m"
    tf_minutes = _TARGET_TIMEFRAMES[tf]
    acc = _make_accumulator(bar_count=tf_minutes)
    is_complete = acc["bar_count"] == tf_minutes
    assert is_complete is True


def test_is_complete_false_when_bar_count_less_than_tf_minutes():
    """A 5m bar built from 3 × 1m bars (service restarted mid-period) is incomplete."""
    tf = "5m"
    tf_minutes = _TARGET_TIMEFRAMES[tf]
    acc = _make_accumulator(bar_count=3)
    is_complete = acc["bar_count"] == tf_minutes
    assert is_complete is False


def test_bar_count_correct_for_15m():
    acc = _make_accumulator(bar_count=15)
    assert acc["bar_count"] == 15
    assert acc["bar_count"] == _TARGET_TIMEFRAMES["15m"]


def test_bar_count_correct_for_1h():
    acc = _make_accumulator(bar_count=60)
    assert acc["bar_count"] == 60
    assert acc["bar_count"] == _TARGET_TIMEFRAMES["1h"]


@pytest.mark.asyncio
async def test_emit_bar_includes_completeness_fields():
    """_emit_bar must include bar_count and is_complete in the published payload."""
    from services.timeframes_builder_service import TimeframeBuilderService

    svc = TimeframeBuilderService.__new__(TimeframeBuilderService)
    svc._env_name = "development"
    svc._htf_topic = "development.market.bars.htf"
    svc._last_emitted = {}
    svc._bars_built = {tf: 0 for tf in _TARGET_TIMEFRAMES}
    svc.logger = structlog.get_logger("test")

    published_payload = {}

    async def _capture_publish(topic, payload, key=None):
        published_payload.update(payload)

    mock_producer = MagicMock()
    mock_producer.publish = AsyncMock(side_effect=_capture_publish)
    svc._producer = mock_producer

    tf = "5m"
    tf_minutes = _TARGET_TIMEFRAMES[tf]
    acc = _make_accumulator(bar_count=3)  # incomplete — only 3 of 5 bars

    await svc._emit_bar("ES", tf, acc, tf_minutes)

    assert "bar_count" in published_payload
    assert published_payload["bar_count"] == 3
    assert "is_complete" in published_payload
    assert published_payload["is_complete"] is False


@pytest.mark.asyncio
async def test_emit_bar_complete_flag_true_when_full():
    """is_complete=True when bar_count equals tf_minutes."""
    from services.timeframes_builder_service import TimeframeBuilderService

    svc = TimeframeBuilderService.__new__(TimeframeBuilderService)
    svc._env_name = "development"
    svc._htf_topic = "development.market.bars.htf"
    svc._last_emitted = {}
    svc._bars_built = {tf: 0 for tf in _TARGET_TIMEFRAMES}
    svc.logger = structlog.get_logger("test")

    published_payload = {}

    async def _capture_publish(topic, payload, key=None):
        published_payload.update(payload)

    mock_producer = MagicMock()
    mock_producer.publish = AsyncMock(side_effect=_capture_publish)
    svc._producer = mock_producer

    tf = "5m"
    tf_minutes = _TARGET_TIMEFRAMES[tf]
    acc = _make_accumulator(bar_count=5)  # complete

    await svc._emit_bar("ES", tf, acc, tf_minutes)

    assert published_payload["is_complete"] is True
    assert published_payload["bar_count"] == 5
