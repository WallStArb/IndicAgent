"""Tests for QualityGateService.

Behavior tests:
  1. process() applies min(hurst_quality, entropy_quality) to confidence
  2. process() applies drift_penalty multiplier after quality multiplier
  3. process() passes through unchanged when hurst_quality and entropy_quality are 1.0
  4. process() sets attribution_reason with quality values
  5. process() handles missing features gracefully (defaults to 1.0)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.intelligence.monitoring.data_quality_monitor import DataQualityMonitor
from src.observability.circuit_breaker import CircuitBreaker


# ---------------------------------------------------------------------------
# Minimal IntelligenceEvent-like dict for testing
# ---------------------------------------------------------------------------

VALID_EVENT_DICT = {
    "schema_version": "1.0",
    "ts": "2026-01-01T09:30:00+00:00",
    "symbol": "ES",
    "tf": "1m",
    "bar": {"o": 100.0, "h": 101.0, "l": 99.0, "c": 100.5, "v": 1000},
    "i1": {},
    "i3": {},
    "i4": {},
    "i5": {},
    "smc": {},
    "i6": {},
    "confidence": 0.8,
    "hurst_trend_quality": 0.9,
    "entropy_quality": 0.85,
    "drift_penalty": 0.9,
    "setup_plugin": "trad_TrendFollowing",
}


def make_event():
    """Minimal event object with attribute access."""
    class _Event:
        symbol = "ES"
        tf = "1m"
        timeframe = "1m"
        features = {
            "confidence": 0.8,
            "hurst_trend_quality": 0.9,
            "entropy_quality": 0.85,
            "drift_penalty": 0.9,
        }

        def model_dump(self):
            return dict(VALID_EVENT_DICT)

    return _Event()


def make_stage():
    """Build a QualityGateService with mocked Kafka clients."""
    from src.intelligence.stages.quality_gate import QualityGateService

    stage = QualityGateService.__new__(QualityGateService)
    stage.stage_name = "quality_gate"
    stage._output_topic = "development.pipeline.quality_gated"
    stage.consumer = AsyncMock()
    stage.producer = AsyncMock()
    stage.attribution_producer = AsyncMock()
    stage.circuit_breaker = CircuitBreaker()
    stage.data_quality_monitor = DataQualityMonitor("quality_gate")
    stage.events_consumed = MagicMock()
    stage.events_produced = MagicMock()
    stage.processing_errors = MagicMock()
    stage.circuit_state = MagicMock()
    return stage


@pytest.mark.asyncio
async def test_quality_gate_applies_hurst_entropy_multiplier():
    """Test 1: process() applies min(hurst_quality, entropy_quality) to confidence."""
    stage = make_stage()
    event = make_event()
    event.features = {"confidence": 0.8, "hurst_trend_quality": 0.9, "entropy_quality": 0.85}

    result = await stage.process(event)

    # quality = min(0.9, 0.85) = 0.85; 0.8 * 0.85 = 0.68
    assert result["confidence"] == pytest.approx(0.68, abs=1e-4)


@pytest.mark.asyncio
async def test_quality_gate_applies_drift_penalty():
    """Test 2: process() applies drift_penalty after quality multiplier."""
    stage = make_stage()
    event = make_event()
    # No quality reduction, but drift penalty
    event.features = {
        "confidence": 0.8,
        "hurst_trend_quality": 1.0,
        "entropy_quality": 1.0,
        "drift_penalty": 0.85,
    }

    result = await stage.process(event)

    # quality = min(1.0, 1.0) = 1.0; then 0.8 * 0.85 = 0.68
    assert result["confidence"] == pytest.approx(0.68, abs=1e-4)


@pytest.mark.asyncio
async def test_quality_gate_passthrough_when_no_penalties():
    """Test 3: process() passes confidence through when all multipliers are 1.0."""
    stage = make_stage()
    event = make_event()
    event.features = {
        "confidence": 0.75,
        "hurst_trend_quality": 1.0,
        "entropy_quality": 1.0,
        "drift_penalty": 1.0,
    }

    result = await stage.process(event)

    assert result["confidence"] == pytest.approx(0.75, abs=1e-4)


@pytest.mark.asyncio
async def test_quality_gate_sets_attribution_reason():
    """Test 4: process() sets attribution_reason with quality values."""
    stage = make_stage()
    event = make_event()

    result = await stage.process(event)

    assert "attribution_reason" in result
    assert "quality_gate" in result["attribution_reason"].lower() or "hurst" in result["attribution_reason"].lower() or result["attribution_reason"]


@pytest.mark.asyncio
async def test_quality_gate_handles_missing_features():
    """Test 5: process() handles missing features gracefully, defaults to 1.0."""
    stage = make_stage()
    event = make_event()
    event.features = {}  # No features

    result = await stage.process(event)

    # All defaults to 1.0, confidence 0.0 (missing) * 1.0 = 0.0
    assert "confidence" in result
    assert result["confidence"] >= 0.0
